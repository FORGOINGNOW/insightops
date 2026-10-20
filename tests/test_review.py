import json
import pytest
from insightops.review import analyze_reviews,weighted_kappa,DIMENSIONS


def review_files(tmp_path,rows):
    (tmp_path/"responses.jsonl").write_text(json.dumps({"id":"case-a","version":"v1","repeat":0,"status":"returned"})+"\n",encoding="utf-8")
    path=tmp_path/"labels.json";path.write_text(json.dumps(rows),encoding="utf-8")
    return path


def row(reviewer):
    return {"case_id":"case-a","version":"v1","repeat":0,"reviewer_id":reviewer,**{d:2 for d in DIMENSIONS}}


def test_empty_templates_are_not_human_labels(tmp_path):
    path=review_files(tmp_path,[row(None)])
    with pytest.raises(ValueError,match="Unfilled"):
        analyze_reviews(tmp_path,path)


def test_single_reviewer_does_not_claim_agreement(tmp_path):
    path=review_files(tmp_path,[row("reviewer-a")])
    result=analyze_reviews(tmp_path,path)
    assert result["status"]=="single_reviewer_no_interrater_claim"
    assert result["agreement"]==[]


def test_duplicate_reviews_rejected(tmp_path):
    path=review_files(tmp_path,[row("reviewer-a"),row("reviewer-a")])
    with pytest.raises(ValueError,match="Duplicate"):
        analyze_reviews(tmp_path,path)


def test_kappa_handles_disagreement_and_constant_scores():
    assert weighted_kappa([(0,0),(1,1),(2,2)])==pytest.approx(1)
    assert weighted_kappa([(0,2),(2,0)])==pytest.approx(-1)
    assert weighted_kappa([(2,2),(2,2)]) is None
