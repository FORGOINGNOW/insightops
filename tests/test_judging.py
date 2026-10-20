import json
import pytest
from insightops.judging import packet,judge_pairs,calibration_status,valid_judgment
from insightops.review import DIMENSIONS


def fixture(tmp_path):
    case={"id":"case","question":"q","evidence":{"sales":5},"expected":{"decision":"secret_answer_key"}}
    cases=tmp_path/"cases.json";cases.write_text(json.dumps([case]),encoding="utf-8")
    rows=[{"id":"case","status":"returned","version":"v3","repeat":i,"answer":{"summary":"x","decision":"x","claims":[],"limitations":[]},"score":{"passed":True}} for i in (0,1)]
    (tmp_path/"responses.jsonl").write_text("\n".join(json.dumps(r) for r in rows),encoding="utf-8")
    return cases


def test_blinded_packet_has_no_gold_version_or_auto_score(tmp_path):
    cases=fixture(tmp_path);out=tmp_path/"packet"
    result=packet(tmp_path,cases,out)
    data=(out/"review-packet.json").read_text(encoding="utf-8")
    assert result["human_reviews_collected"]==0
    assert "secret_answer_key" not in data and '"version"' not in data and '"score"' not in data
    with pytest.raises(ValueError,match="Completed"):
        calibration_status(out,out/"review-packet.json")
    with pytest.raises(ValueError,match="existing review"):
        packet(tmp_path,cases,out)


def test_swapped_preference_is_mapped_to_original_candidate(tmp_path,monkeypatch):
    cases=fixture(tmp_path)
    rating={d:2 for d in DIMENSIONS}
    answers=iter([{"A":rating,"B":rating,"preference":"A","rationale":"x"},
                  {"A":rating,"B":rating,"preference":"B","rationale":"x"}])
    monkeypatch.setattr("insightops.judging.configuration_status",lambda:{"ready":True,"model":"fake"})
    monkeypatch.setattr("insightops.judging.call_model",lambda _:(next(answers),{"total_tokens":1}))
    result=judge_pairs(tmp_path,cases,tmp_path/"judge",live=True,limit=1,max_requests=2)
    assert result["preference_consistency"]==1
    assert result["human_calibration"]=="not_collected"


def test_calibration_is_not_fabricated_from_empty_labels(tmp_path):
    assert calibration_status(tmp_path)["calibrated"] is False
    labels=tmp_path/"labels.json";labels.write_text("[]",encoding="utf-8")
    with pytest.raises(ValueError):
        calibration_status(tmp_path,labels)


def test_judge_rejects_boolean_score():
    scores={d:2 for d in DIMENSIONS};scores["numeric_score"]=True
    assert not valid_judgment({"A":scores,"B":scores,"preference":"tie","rationale":"x"})


def test_completed_human_ratings_match_canonical_judge_scores(tmp_path):
    cases=fixture(tmp_path);out=tmp_path/"packet";packet(tmp_path,cases,out)
    mapping=json.loads((out/"coordinator-map.json").read_text(encoding="utf-8"))
    labels=[{"item_id":mapping[0]["item_id"],"reviewer_id":"test-reviewer",**{d:2 for d in DIMENSIONS}}]
    path=tmp_path/"labels.json";path.write_text(json.dumps(labels),encoding="utf-8")
    score={d:2 for d in DIMENSIONS}
    record={"case_id":"case","valid":True,"swapped":False,"source_versions":["v3","v3"],"source_repeats":[0,1],"judgment":{"A":score,"B":score}}
    judge=tmp_path/"judge";judge.mkdir();(judge/"judgments.jsonl").write_text(json.dumps(record),encoding="utf-8")
    result=calibration_status(out,path,judge)
    assert result["status"]=="comparison_computed"
    assert result["calibrated"] is False
    assert all(r["n"]==1 and r["exact_agreement"]==1 for r in result["comparisons"])
