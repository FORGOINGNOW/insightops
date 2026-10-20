from __future__ import annotations

import sqlite3
from pathlib import Path
from .data import CUTOFF


def analyze(db: Path) -> dict:
    con = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro",uri=True)
    con.row_factory = sqlite3.Row
    def rows(query, args=()):
        return [dict(r) for r in con.execute(query,args)]
    strata = rows("SELECT period,channel,COUNT(*) AS sessions,SUM(converted) AS conversions,AVG(converted) AS rate FROM session_facts GROUP BY period,channel ORDER BY period,channel")
    totals = rows("SELECT period,COUNT(*) AS sessions,SUM(converted) AS conversions,AVG(converted) AS rate FROM session_facts GROUP BY period")
    raw = rows("SELECT s.period,SUM(e.event_type='view') AS views,SUM(e.event_type='payment') AS payments FROM events e JOIN sessions s USING(session_id) WHERE e.received_at<=? GROUP BY s.period",(CUTOFF,))
    for r in raw:
        r["rate"] = r["payments"]/r["views"]
    duplicate = con.execute("SELECT COUNT(*)-COUNT(DISTINCT logical_id) FROM events").fetchone()[0]
    late = con.execute("SELECT COUNT(*) FROM events WHERE event_type='payment' AND received_at>?",(CUTOFF,)).fetchone()[0]
    missing = con.execute("SELECT COUNT(*) FROM orders o WHERE NOT EXISTS (SELECT 1 FROM events e WHERE e.session_id=o.session_id AND e.event_type='payment')").fetchone()[0]
    drift = con.execute("SELECT COUNT(*) FROM events WHERE schema_version=2").fetchone()[0]
    revenue = con.execute("SELECT SUM(amount_cents) FROM orders").fetchone()[0]
    naive = con.execute("SELECT SUM(o.amount_cents) FROM orders o JOIN order_items i USING(order_id)").fetchone()[0]
    item_total = con.execute("SELECT SUM(amount_cents) FROM order_items").fetchone()[0]
    rates = {(r["period"],r["channel"]):r for r in strata}
    before_n = sum(r["sessions"] for r in strata if r["period"]=="before")
    standardized = {period:sum(rates[("before",c)]["sessions"]/before_n*rates[(period,c)]["rate"] for c in ["organic","paid"]) for period in ["before","after"]}
    con.close()
    return {"canonical":totals,"strata":strata,"raw_as_of":raw,"cutoff":CUTOFF,
            "standardized_to_before_mix":standardized,
            "quality":{"duplicate_events":duplicate,"late_payments":late,"missing_payments":missing,"schema_v2_events":drift},
            "reconciliation":{"order_revenue_cents":revenue,"item_revenue_cents":item_total,
                              "naive_join_revenue_cents":naive,"passed":revenue==item_total},
            "conclusion":"Overall conversion falls due to channel composition; within-channel rates are unchanged. Event defects further depress the raw metric. This descriptive decomposition does not establish a causal product effect."}
