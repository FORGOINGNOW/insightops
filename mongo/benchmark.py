"""Run against a disposable database on an explicitly supplied MongoDB instance.

python mongo/benchmark.py --uri mongodb://localhost:27017 --copies 1 --repeats 7
Drops only the named benchmark collection inside insightops_portfolio.
"""
import argparse
import hashlib
import json
import platform
import statistics
import time
from pathlib import Path

from pymongo import MongoClient

ROOT=Path(__file__).resolve().parents[1]


def summary(plan):
    execution=plan.get("executionStats",{})
    # Aggregate explain output differs across MongoDB versions.
    for stage in plan.get("stages",[]):
        if "$cursor" in stage:
            execution=stage["$cursor"].get("executionStats",execution)
    return {k:execution.get(k) for k in ["nReturned","executionTimeMillis","totalKeysExamined","totalDocsExamined"]}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--uri",default="mongodb://localhost:27017")
    parser.add_argument("--copies",type=int,default=1)
    parser.add_argument("--repeats",type=int,default=7)
    args=parser.parse_args()
    if args.copies<1 or args.repeats<3:
        parser.error("copies >=1 and repeats >=3 required")
    client=MongoClient(args.uri,serverSelectionTimeoutMS=5000)
    db=client["insightops_portfolio"]
    name="events_benchmark"
    db[name].drop()
    col=db[name]
    source=ROOT/"data/generated/events.jsonl"
    originals=[json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    for copy in range(args.copies):
        batch=[]
        for doc in originals:
            row={**doc,"event_id":f"{copy}:{doc['event_id']}","logical_id":f"{copy}:{doc['logical_id']}","session_id":f"{copy}:{doc['session_id']}"}
            batch.append(row)
            if len(batch)==5000:
                col.insert_many(batch); batch=[]
        if batch:
            col.insert_many(batch)
    # Payment records are selective; dedup before counting business events.
    match={"period":"after","event_type":"payment","received_at":{"$lte":"2026-10-15T00:00:00"}}
    pipeline=[{"$match":match},{"$group":{"_id":"$logical_id"}},{"$count":"payments"}]
    def measure():
        list(col.aggregate(pipeline))  # Warmup; index creation occurs outside timed block.
        times=[]; result=None
        for _ in range(args.repeats):
            start=time.perf_counter(); result=list(col.aggregate(pipeline)); times.append((time.perf_counter()-start)*1000)
        explain=db.command("explain",{"aggregate":name,"pipeline":pipeline,"cursor":{}},verbosity="executionStats")
        return {"result":result,"latencies_ms":times,"median_ms":statistics.median(times),
                "explain_summary":summary(explain),"explain":explain}
    before=measure()
    col.create_index([("period",1),("event_type",1),("received_at",1),("logical_id",1)],name="period_type_received_logical")
    after=measure()
    if before["result"]!=after["result"]:
        raise RuntimeError("Index changed the query result")
    # Independent SQLite reconciliation against exactly the same cutoff and event grain.
    import sqlite3
    conn=sqlite3.connect(ROOT/"data/generated/commerce.sqlite")
    expected=conn.execute("SELECT COUNT(DISTINCT e.logical_id) FROM events e JOIN sessions s USING(session_id) WHERE s.period='after' AND e.event_type='payment' AND e.received_at<=?",("2026-10-15T00:00:00",)).fetchone()[0]*args.copies
    conn.close()
    observed=after["result"][0]["payments"] if after["result"] else 0
    if observed!=expected:
        raise RuntimeError(f"SQL/Mongo reconciliation failed: {observed} != {expected}")
    # Also exercise version-aware nested document access.
    pages=list(col.aggregate([{"$project":{"page":{"$ifNull":["$payload.page","$payload.context.page"]}}},
                              {"$group":{"_id":"$page","events":{"$sum":1}}}]))
    stats=db.command("collStats",name)
    report={"server_version":client.server_info()["version"],"host":platform.platform(),
            "logical_cpus":__import__('os').cpu_count(),"document_count":col.count_documents({}),
            "average_document_bytes":stats.get("avgObjSize"),"copies":args.copies,
            "source_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),"repeats":args.repeats,
            "cache_protocol":"one warmup per condition; before-index then after-index; ordering/cache confounds remain",
            "pipeline":pipeline,"before":before,"after":after,"results_equal":True,
            "sql_reconciled":True,"expected_distinct_payments":expected,"normalized_pages":pages,
            "limitations":["Local synthetic data benchmark, not a production scale claim.","Report actual machine RAM, MongoDB memory limits and storage medium separately before publishing performance claims."]}
    out=ROOT/"artifacts/mongo-benchmark.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
    print(json.dumps({"documents":report["document_count"],"before_ms":before["median_ms"],"after_ms":after["median_ms"],"sql_reconciled":True},indent=2))
    client.close()


if __name__=="__main__":
    main()
