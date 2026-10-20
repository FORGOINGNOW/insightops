"""Controlled regression harness. Rule baselines are NOT measured LLM performance."""
from __future__ import annotations

import hashlib
import json
import math
import random
import sqlite3
import time
from pathlib import Path

KINDS = ["conversion","mix","duplicates","revenue","late","schema","experiment","ambiguous"]
QUESTIONS = {
    "conversion":"支付转化率是多少？请按会话和支付订单口径计算。",
    "mix":"整体转化下降是否意味着产品在各渠道内表现变差？",
    "duplicates":"上报事件中有多少重复记录？",
    "revenue":"连接订单明细后，应报告多少订单收入（分）？",
    "late":"在分析截止时间之后才收到的支付事件有多少？",
    "schema":"有多少事件采用了第二版结构？",
    "experiment":"新版转化显著提高，但退款护栏显著恶化，是否上线？",
    "ambiguous":"帮我看一下转化怎么样。"
}


def build_cases() -> list[dict]:
    cases=[]
    rng=random.Random(20261022)
    for kind in KINDS:
        for i in range(10):
            n=rng.randrange(10,61)*100
            conversions=n//10
            duplicates=rng.randrange(1,20)*10
            late=rng.randrange(1,15)
            revenue=rng.randrange(10000,1000000)
            inputs={"sessions":n,"conversions":conversions,"duplicate_views":duplicates,
                    "late_payments":late,"schema_v2":rng.randrange(1,200),"revenue_cents":revenue,
                    "line_count":rng.choice([2,3,4]),"before_organic_share":.8,"after_organic_share":.2,
                    "organic_rate":.2,"paid_rate":.05,
                    "primary_significant":True,"guardrail_harm":True}
            # Independent fixture oracle: never call workflow code to produce expected answers.
            expected={"conversion":conversions/n,"mix":"composition_shift",
                      "duplicates":duplicates,"revenue":revenue,"late":late,
                      "schema":inputs["schema_v2"],"experiment":"hold_guardrail_harm",
                      "ambiguous":"needs_clarification"}[kind]
            cases.append({"id":f"{kind}-{i:02d}","kind":kind,"question":QUESTIONS[kind],
                          "split":"test" if i>=7 else "dev","inputs":inputs,
                          "expected":expected,"required_evidence":f"fixture:{kind}-{i:02d}"})
    return cases


def run_rule(case: dict, version: str) -> dict:
    """Transparent ablations: V0 raw data; V1 canonical grain; V2 decision checks."""
    x=case["inputs"]
    con=sqlite3.connect(":memory:")
    con.execute("CREATE TABLE metrics (sessions,conversions,duplicate_views,late_payments,schema_v2,revenue_cents,line_count)")
    con.execute("INSERT INTO metrics VALUES (?,?,?,?,?,?,?)",tuple(x[k] for k in ["sessions","conversions","duplicate_views","late_payments","schema_v2","revenue_cents","line_count"]))
    kind=case["kind"]
    queries={"conversion":"SELECT 1.0*conversions/sessions FROM metrics",
             "duplicates":"SELECT duplicate_views FROM metrics","revenue":"SELECT revenue_cents FROM metrics",
             "late":"SELECT late_payments FROM metrics","schema":"SELECT schema_v2 FROM metrics"}
    if kind in queries:
        query=queries[kind]
        if version=="v0" and kind=="conversion":
            query="SELECT 1.0*(conversions-late_payments)/(sessions+duplicate_views) FROM metrics"
        if version=="v0" and kind=="revenue":
            query="SELECT revenue_cents*line_count FROM metrics"
        value=con.execute(query).fetchone()[0]
        if version!="v2" and kind in ["late","schema"]:
            value=0  # Explicit ablation: these checks did not exist in V0/V1.
    elif kind=="mix":
        # Weights change while stratum rates are stable. Compute, rather than
        # read the expected label. More general counterexamples belong in v0.2.
        before=x["before_organic_share"]*x["organic_rate"]+(1-x["before_organic_share"])*x["paid_rate"]
        after=x["after_organic_share"]*x["organic_rate"]+(1-x["after_organic_share"])*x["paid_rate"]
        standardized=x["before_organic_share"]*x["organic_rate"]+(1-x["before_organic_share"])*x["paid_rate"]
        value="composition_shift" if version!="v0" and after<before and math.isclose(standardized,before) else "product_regression"
        query="fixed-weight decomposition using supplied stratum rates"
    elif kind=="experiment":
        value="hold_guardrail_harm" if version=="v2" and x["guardrail_harm"] else "ship"
        query="primary + guardrail decision rule"
    else:
        value="needs_clarification" if version=="v2" else "assume_session_conversion"
        query="metric-definition completeness check"
    con.close()
    return {"value":value,"evidence_id":case["required_evidence"],"method":query,
            "engine":"deterministic_rule_baseline","version":version}


def score(case, output):
    expected=case["expected"]
    actual=output.get("value")
    correct=(isinstance(actual,(float,int)) and not isinstance(actual,bool) and math.isclose(actual,expected,rel_tol=1e-9,abs_tol=1e-9)) if isinstance(expected,(float,int)) else actual==expected
    evidence=output.get("evidence_id")==case["required_evidence"]
    return {"correct":correct,"evidence_valid":evidence,"passed":correct and evidence}


def evaluate(cases: list[dict]) -> dict:
    results=[]
    for version in ["v0","v1","v2"]:
        for case in cases:
            start=time.perf_counter()
            output=run_rule(case,version)
            results.append({"id":case["id"],"kind":case["kind"],"split":case["split"],
                            "version":version,"output":output,**score(case,output),
                            "latency_ms":round((time.perf_counter()-start)*1000,4)})
    summary=[]
    for version in ["v0","v1","v2"]:
        for split in ["dev","test"]:
            subset=[r for r in results if r["version"]==version and r["split"]==split]
            summary.append({"version":version,"split":split,"n":len(subset),
                            "passed":sum(r["passed"] for r in subset),
                            "pass_rate":sum(r["passed"] for r in subset)/len(subset)})
    fingerprint=hashlib.sha256(json.dumps(cases,sort_keys=True).encode()).hexdigest()
    return {"engine":"deterministic_rule_baseline","cases_sha256":fingerprint,
            "summary":summary,"results":results,
            "limitations":["No LLM was called. These are controlled rule ablations, not AI capability results.",
                            "80 parametrized fixtures across 8 task families; test split shares templates with dev.",
                            "Fixture evidence IDs establish provenance only, not natural-language entailment.",
                            "No human labels, judge calibration or real online A/B result has been collected.",
                            "A 100% V2 score is a harness smoke check; adversarial and distribution-shift evaluation remains future work."]}
