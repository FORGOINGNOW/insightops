"""Re-score committed provider outputs without network access or credentials."""
import hashlib
import json
from pathlib import Path
from insightops.challenges import score_challenge, guard, make_messages

ROOT=Path(__file__).resolve().parents[1]


def main():
    checked=0
    for name,suite in (("live","challenges.json"),("live-v3","challenges.json"),("holdout","holdout.json")):
        folder=ROOT/"reports"/name
        source=ROOT/"evals"/suite
        cases={c["id"]:c for c in json.loads(source.read_text(encoding="utf-8"))}
        fingerprint=hashlib.sha256(source.read_bytes()).hexdigest()
        if not (folder/"summary.json").exists():
            continue
        summary=json.loads((folder/"summary.json").read_text(encoding="utf-8"))
        assert summary["cases_sha256"]==fingerprint,"Challenge set changed; original scores must remain versioned"
        for line in (folder/"responses.jsonl").read_text(encoding="utf-8").splitlines():
            record=json.loads(line)
            if record["status"]!="returned":
                continue
            case=cases[record["id"]]
            prompt_hash=hashlib.sha256(json.dumps(make_messages(case,record["version"]),sort_keys=True).encode()).hexdigest()
            assert prompt_hash==record["prompt_sha256"],"Prompt/contract drift: retain the historical evaluator"
            actual=score_challenge(case,record["answer"])
            assert actual==record["score"],f"Scoring drift: {record['id']} {record['version']}"
            if record["version"] in ("v2","v3"):
                assert guard(record["answer"],case["evidence"],record["version"])==record["gate"]
            checked+=1
    if checked==0:
        raise ValueError("No committed real responses to replay")
    from insightops.judging import valid_judgment
    judge_checked=0
    for name in ("judge-diagnostics","judge-controls"):
        path=ROOT/"reports"/name/"judgments.jsonl"
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                record=json.loads(line)
                if record["status"]=="returned":
                    assert valid_judgment(record["judgment"])==record["valid"]
                    judge_checked+=1
    print(json.dumps({"cached_real_responses_verified":checked,"judge_schemas_verified":judge_checked,"network_requests":0},indent=2))


if __name__=="__main__":
    main()
