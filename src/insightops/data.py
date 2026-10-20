"""Deterministic fixtures with an independently recorded generation ledger."""
from __future__ import annotations

import hashlib
import json
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = "synthetic-v1-seed-20261020"
CUTOFF = "2026-10-15T00:00:00"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate(out: Path, seed: int = 20261020, per_period: int = 10000) -> dict:
    if per_period < 100 or per_period % 10:
        raise ValueError("per_period must be >=100 and divisible by 10")
    out.mkdir(parents=True, exist_ok=True)
    db = out / "commerce.sqlite"
    # Only rebuild this generator's named output file.
    db.unlink(missing_ok=True)
    rng = random.Random(seed)
    con = sqlite3.connect(db)
    con.executescript((ROOT / "sql/schema.sql").read_text(encoding="utf-8"))
    ledger = {"snapshot": SNAPSHOT, "seed": seed, "synthetic": True, "periods": {},
              "orders": 0, "revenue_cents": 0, "duplicate_events": 0,
              "late_payments": 0, "missing_payments": 0, "schema_v2_events": 0}
    docs = []
    uid = 0
    for period, organic_share, base in [("before", .8, datetime(2026, 9, 1)),
                                          ("after", .2, datetime(2026, 10, 1))]:
        ledger["periods"][period] = {}
        for channel, n in [("organic", round(per_period * organic_share)),
                           ("paid", per_period - round(per_period * organic_share))]:
            # Exact per-stratum rates guarantee a known composition effect.
            k = round(n * (.2 if channel == "organic" else .05))
            outcomes = [1] * k + [0] * (n-k)
            rng.shuffle(outcomes)
            ledger["periods"][period][channel] = {"sessions": n, "conversions": k}
            for converted in outcomes:
                uid += 1
                sid = f"s{uid:07d}"
                at = (base + timedelta(days=rng.randrange(7), seconds=rng.randrange(86400))).isoformat()
                con.execute("INSERT INTO users VALUES (?,?,?,?)", (uid, channel, rng.choice(["web","mobile"]), rng.randrange(2)))
                con.execute("INSERT INTO assignments VALUES (?,?)", (uid, rng.choice(["A","B"])))
                con.execute("INSERT INTO sessions VALUES (?,?,?,?)", (sid, uid, period, at))
                kinds = ["view"]
                if converted:
                    amount = rng.randrange(1000,20001)
                    con.execute("INSERT INTO orders VALUES (?,?,?,?)", (f"o{uid}", sid, amount, int(rng.random()<.04)))
                    for line, cents in [(1,amount//2),(2,amount-amount//2)]:
                        con.execute("INSERT INTO order_items VALUES (?,?,?)", (f"o{uid}",line,cents))
                    ledger["orders"] += 1
                    ledger["revenue_cents"] += amount
                    if period == "after" and uid % 11 == 0:
                        ledger["missing_payments"] += 1
                    else:
                        kinds.append("payment")
                for kind in kinds:
                    logical = f"{sid}:{kind}"
                    received = at
                    if period == "after" and kind == "payment" and uid % 5 == 0:
                        received = "2026-10-20T00:00:00"
                        ledger["late_payments"] += 1
                    copies = 2 if period == "after" and kind == "view" and uid % 3 == 0 else 1
                    ledger["duplicate_events"] += copies-1
                    version = 2 if period == "after" and uid % 7 == 0 else 1
                    payload = {"page": "checkout"} if version == 1 else {"context": {"page": "checkout"}}
                    for copy in range(copies):
                        eid = f"{logical}:{copy}"
                        con.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?)", (eid,logical,sid,kind,at,received,version,json.dumps(payload)))
                        docs.append({"event_id":eid,"logical_id":logical,"session_id":sid,"event_type":kind,
                                     "occurred_at":at,"received_at":received,"schema_version":version,
                                     "period":period,"payload":payload})
                        ledger["schema_v2_events"] += int(version == 2)
    con.commit()
    con.close()
    (out/"events.jsonl").write_text("\n".join(json.dumps(d,ensure_ascii=False) for d in docs)+"\n",encoding="utf-8")
    (out/"ledger.json").write_text(json.dumps(ledger,indent=2),encoding="utf-8")
    manifest = {"snapshot":SNAPSHOT,"seed":seed,"per_period":per_period,
                "files":{name:digest(out/name) for name in ["commerce.sqlite","events.jsonl","ledger.json"]}}
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    return ledger
