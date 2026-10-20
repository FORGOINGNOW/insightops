import json
import sqlite3
import pytest
from insightops.data import generate
from insightops.analytics import analyze
from insightops.experiment import difference, run_experiment, sample_size
from insightops.evaluation import build_cases, evaluate, score
from insightops.workflow import validate_claims, run_workflow


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    folder=tmp_path_factory.mktemp("commerce")
    ledger=generate(folder,per_period=1000)
    return folder,ledger


def test_independent_ledger_reconciles(dataset):
    folder,ledger=dataset
    report=analyze(folder/"commerce.sqlite")
    for row in report["strata"]:
        expected=ledger["periods"][row["period"]][row["channel"]]
        assert row["sessions"]==expected["sessions"]
        assert row["conversions"]==expected["conversions"]
    assert report["reconciliation"]["order_revenue_cents"]==ledger["revenue_cents"]
    assert report["reconciliation"]["item_revenue_cents"]==ledger["revenue_cents"]
    assert report["reconciliation"]["naive_join_revenue_cents"]==2*ledger["revenue_cents"]
    for key in ["duplicate_events","late_payments","missing_payments","schema_v2_events"]:
        assert report["quality"][key]==ledger[key]


def test_mix_decomposition_and_raw_distortion(dataset):
    report=analyze(dataset[0]/"commerce.sqlite")
    totals={r["period"]:r for r in report["canonical"]}
    raw={r["period"]:r for r in report["raw_as_of"]}
    assert totals["before"]["rate"]==pytest.approx(.17)
    assert totals["after"]["rate"]==pytest.approx(.08)
    assert report["standardized_to_before_mix"]["after"]==pytest.approx(.17)
    assert raw["after"]["rate"]<totals["after"]["rate"]


def test_reference_ledger_detects_order_loss(dataset,tmp_path):
    folder,ledger=dataset
    target=tmp_path/"broken.sqlite"
    source=sqlite3.connect(folder/"commerce.sqlite")
    dest=sqlite3.connect(target); source.backup(dest); source.close()
    dest.execute("DELETE FROM orders WHERE order_id=(SELECT order_id FROM orders LIMIT 1)"); dest.commit();dest.close()
    report=analyze(target)
    assert report["reconciliation"]["order_revenue_cents"]!=ledger["revenue_cents"]
    assert not report["reconciliation"]["passed"]


def test_statistics_against_known_symmetric_case():
    result=difference(100,1000,100,1000)
    assert result["absolute_effect"]==0
    assert result["p_value"]==1
    assert result["ci95"][0]==pytest.approx(-result["ci95"][1])
    assert 6000<sample_size()<8000
    with pytest.raises(ValueError):
        difference(1,0,1,10)


def test_experiment_blocks_harm_and_invalid_assignment():
    assert run_experiment()["decision"]=="hold_guardrail_harm"
    assert run_experiment(skew=True)["decision"]=="hold_invalid_assignment"


def test_grader_rejects_wrong_value_and_forged_evidence():
    case=build_cases()[0]
    assert not score(case,{"value":-1,"evidence_id":case["required_evidence"]})["passed"]
    assert not score(case,{"value":case["expected"],"evidence_id":"invented"})["passed"]


def test_claim_validation_rejects_hallucinated_numbers_and_paths():
    evidence={"a":[{"n":5}],"text":"5"}
    valid={"claims":[{"path":"a.0.n","value":5}]}
    assert validate_claims(valid,evidence)["numeric_claims_passed"]
    for claim in [{"path":"a.0.n","value":6},{"path":"absent","value":5},{"path":"text","value":5},{"path":"a.0.n","value":True}]:
        assert not validate_claims({"claims":[claim]},evidence)["numeric_claims_passed"]
    assert not validate_claims({"claims":[]},evidence)["numeric_claims_passed"]


def test_tampered_snapshot_blocks_workflow(dataset,tmp_path):
    import shutil
    folder,_=dataset
    for name in ["commerce.sqlite","events.jsonl","ledger.json","manifest.json"]:
        shutil.copy2(folder/name,tmp_path/name)
    (tmp_path/"ledger.json").write_text("{}",encoding="utf-8")
    with pytest.raises(ValueError,match="Snapshot integrity"):
        run_workflow("diagnose",tmp_path)


def test_live_workflow_integration_with_fake_endpoint(dataset,monkeypatch):
    import insightops.workflow as workflow
    replies=iter([({"tool":"analysis","reason":"test"},{"total_tokens":10}),
                  ({"summary":"needs review","claims":[{"path":"quality.duplicate_events","value":-999}]},{"total_tokens":10})])
    monkeypatch.setattr(workflow,"call_model",lambda messages:next(replies))
    result=run_workflow("compare defined periods",dataset[0],live=True)
    assert result["status"]=="blocked_numeric_validation"
    assert len(result["usage"])==2


def test_live_rejects_unknown_tool(dataset,monkeypatch):
    import insightops.workflow as workflow
    monkeypatch.setattr(workflow,"call_model",lambda messages:({"tool":"delete_database"},{}))
    with pytest.raises(ValueError,match="allowlist"):
        run_workflow("test",dataset[0],live=True)


def test_malformed_model_claims_fail_closed():
    for claims in [None,"five",{},[None],[{"value":5}],[{"path":5,"value":5}]]:
        assert not validate_claims({"claims":claims},{"n":5})["numeric_claims_passed"]


def test_all_documented_sql_executes(dataset):
    from insightops.data import ROOT
    con=sqlite3.connect(dataset[0]/"commerce.sqlite")
    con.executescript((ROOT/"sql/analysis.sql").read_text(encoding="utf-8"))
    con.close()


def test_generator_is_reproducible(dataset,tmp_path):
    from insightops.data import digest
    generate(tmp_path,per_period=1000)
    for name in ["commerce.sqlite","events.jsonl","ledger.json"]:
        assert digest(tmp_path/name)==digest(dataset[0]/name)
