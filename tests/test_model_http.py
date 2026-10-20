import json
import urllib.error
import pytest
from insightops.config import probe_configuration
from insightops.workflow import call_model, ModelAPIError
from insightops.challenges import evaluate_live
from insightops.data import ROOT


def test_probe_reports_only_http_status_not_response_body(monkeypatch):
    monkeypatch.setenv("INSIGHTOPS_API_KEY","dummy-secret-never-display")
    monkeypatch.setenv("INSIGHTOPS_MODEL","test-model")
    def fail(*args,**kwargs):
        raise urllib.error.HTTPError("https://example.com/models",401,"dummy-secret-never-display",None,None)
    monkeypatch.setattr("urllib.request.urlopen",fail)
    result=probe_configuration()
    assert result["http_status"]==401
    assert "dummy-secret-never-display" not in json.dumps(result)


def test_model_error_has_safe_status_only(monkeypatch):
    monkeypatch.setenv("INSIGHTOPS_API_KEY","dummy-secret-never-display")
    monkeypatch.setenv("INSIGHTOPS_MODEL","test-model")
    def fail(*args,**kwargs):
        raise urllib.error.HTTPError("https://example.com",401,"dummy-secret-never-display",None,None)
    monkeypatch.setattr("urllib.request.urlopen",fail)
    with pytest.raises(ModelAPIError) as caught:
        call_model([])
    assert caught.value.http_status==401
    assert "dummy-secret-never-display" not in str(caught.value)


def test_auth_failure_stops_after_first_request(tmp_path,monkeypatch):
    attempts=[]
    monkeypatch.setattr("insightops.challenges.configuration_status",lambda:{"ready":True,"model":"fake"})
    def fail(messages):
        attempts.append(messages)
        raise ModelAPIError(401)
    monkeypatch.setattr("insightops.challenges.call_model",fail)
    result=evaluate_live(ROOT/"evals/challenges.json",tmp_path,live=True,limit=4)
    assert len(attempts)==1
    assert result["status"]=="stopped_provider_error"
    record=json.loads(next(tmp_path.glob("*/responses.jsonl")).read_text())
    assert record["http_status"]==401
