import json
import pytest
from insightops.data import ROOT
from insightops.challenges import make_messages, policy_constraints, guard, score_challenge, evaluate_live


def cases():
    return json.loads((ROOT/"evals/challenges.json").read_text(encoding="utf-8"))


def test_answer_keys_do_not_leak_into_model_messages():
    case=cases()[0]
    case["expected"]["secret_canary"]="SECRET_ANSWER_KEY_MUST_NOT_REACH_MODEL"
    for version in ("v1","v2"):
        messages=json.dumps(make_messages(case,version))
        assert "SECRET_ANSWER_KEY_MUST_NOT_REACH_MODEL" not in messages
        assert '"expected"' not in messages


def test_srm_takes_precedence_over_guardrail_harm():
    evidence={"srm_p_value":.00001,"refund_effect_ci":[.004,.01],"refund_tolerance":.002}
    assert policy_constraints(evidence)[0]=="hold_invalid_assignment"
    answer={"decision":"ship","summary":"ship","claims":[],"limitations":["synthetic"]}
    assert guard(answer,evidence)["blocked"]


def test_reference_failure_is_distinct_from_policy_block():
    case=next(c for c in cases() if c["id"]=="srm-before-effects")
    answer={"decision":"ship","summary":"invalid rollout","claims":[],"limitations":["synthetic"]}
    assert not score_challenge(case,answer)["passed"]
    assert guard(answer,case["evidence"])["blocked"]


def test_hallucinated_claim_is_blocked_even_with_correct_decision():
    case=next(c for c in cases() if c["id"]=="embedded-instruction")
    answer={"decision":"report_numeric_value","summary":"claim","claims":[{"path":"sales_gbp","value":999999}],"limitations":["synthetic"]}
    assert not score_challenge(case,answer)["passed"]
    assert guard(answer,case["evidence"])["blocked"]


def test_budget_and_dry_run_never_call_provider(tmp_path,monkeypatch):
    monkeypatch.setattr("insightops.challenges.call_model",lambda _:pytest.fail("Unexpected API request"))
    result=evaluate_live(ROOT/"evals/challenges.json",tmp_path,live=False)
    assert not result["network_request_sent"]
    assert not list(tmp_path.iterdir())
    with pytest.raises(ValueError,match="exceeds"):
        evaluate_live(ROOT/"evals/challenges.json",tmp_path,limit=24,max_requests=12)


def test_missing_uncertainty_is_not_srm_zero():
    assert policy_constraints({"srm_p_value":None})==[]


def test_negative_index_and_duplicate_claim_paths_are_rejected():
    evidence={"a":[5]}
    negative={"decision":"report_numeric_value","summary":"x","claims":[{"path":"a.-1","value":5}],"limitations":["x"]}
    assert guard(negative,evidence)["blocked"]
    duplicated={**negative,"claims":[{"path":"a.0","value":5},{"path":"a.0","value":5}]}
    assert guard(duplicated,evidence)["blocked"]


def test_v3_makes_schema_and_decision_contract_explicit_without_gold():
    case=next(c for c in cases() if c["id"]=="point-estimate-only")
    assert policy_constraints(case["evidence"],"v2")==[]
    assert policy_constraints(case["evidence"],"v3")==["insufficient_uncertainty"]
    messages=make_messages(case,"v3")
    assert "numeric SCALAR" in messages[0]["content"]
    assert "expected" not in json.loads(messages[1]["content"])


def test_live_runner_persists_and_scores_without_fabricated_human_labels(tmp_path,monkeypatch):
    monkeypatch.setattr("insightops.challenges.configuration_status",lambda:{"ready":True,"model":"fake-endpoint"})
    monkeypatch.setattr("insightops.challenges.call_model",lambda _:(
        {"decision":"needs_clarification","summary":"Specify definition and window.","claims":[],"limitations":["No defined metric"]},
        {"total_tokens":10}))
    result=evaluate_live(ROOT/"evals/challenges.json",tmp_path,live=True,limit=1)
    assert result["status"]=="completed"
    assert all(r["raw_reference_pass_rate"]==1 for r in result["summary"])
    assert result["human_review"]=="not_collected"
    templates=list(tmp_path.glob("*/human-review-template.json"))
    assert len(templates)==1
    assert all(r["reviewer_id"] is None for r in json.loads(templates[0].read_text()))
