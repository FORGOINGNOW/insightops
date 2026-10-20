"""Import genuine completed human rubrics; never convert templates into labels."""
import itertools
import json
from collections import Counter
from pathlib import Path

DIMENSIONS=("numeric_score","evidence_score","uncertainty_score","actionability_score")


def weighted_kappa(pairs):
    """Quadratically weighted Cohen kappa for ordinal 0/1/2 scores."""
    if not pairs:
        return None
    n=len(pairs);left=Counter(a for a,b in pairs);right=Counter(b for a,b in pairs)
    observed=sum((a-b)**2/4 for a,b in pairs)/n
    expected=sum((a-b)**2/4*left[a]*right[b]/n**2 for a in range(3) for b in range(3))
    # A constant-rating table has no chance variation: kappa is undefined.
    return 1-observed/expected if expected else None


def analyze_reviews(run_dir: Path, labels_path: Path):
    responses=[json.loads(line) for line in (run_dir/"responses.jsonl").read_text(encoding="utf-8").splitlines() if line]
    valid={(r["id"],r["version"],r["repeat"]) for r in responses if r["status"]=="returned"}
    labels=json.loads(labels_path.read_text(encoding="utf-8"))
    if not isinstance(labels,list) or not labels:
        raise ValueError("No completed human review labels supplied")
    indexed={};reviewers=set()
    for row in labels:
        reviewer=row.get("reviewer_id")
        if not isinstance(reviewer,str) or not reviewer.strip():
            raise ValueError("Unfilled review template: reviewer_id is required")
        key=(row.get("case_id"),row.get("version"),row.get("repeat"))
        if key not in valid:
            raise ValueError("Review refers to a missing or failed model response")
        if (key,reviewer) in indexed:
            raise ValueError("Duplicate review for the same response and reviewer")
        if any(type(row.get(d)) is not int or row[d] not in (0,1,2) for d in DIMENSIONS):
            raise ValueError("Every rubric dimension requires an integer score in 0..2")
        indexed[key,reviewer]=row;reviewers.add(reviewer)
    agreement=[]
    for left,right in itertools.combinations(sorted(reviewers),2):
        shared=sorted(key for key in valid if (key,left) in indexed and (key,right) in indexed)
        for dimension in DIMENSIONS:
            pairs=[(indexed[key,left][dimension],indexed[key,right][dimension]) for key in shared]
            agreement.append({"reviewer_pair":[left,right],"dimension":dimension,"paired_responses":len(pairs),
                              "exact_agreement":sum(a==b for a,b in pairs)/len(pairs) if pairs else None,
                              "quadratic_weighted_kappa":weighted_kappa(pairs)})
    return {"completed_reviews":len(labels),"distinct_reviewers":len(reviewers),
            "responses_reviewed":len({key for key,reviewer in indexed}),"responses_available":len(valid),
            "status":"multiple_reviewers" if len(reviewers)>1 else "single_reviewer_no_interrater_claim",
            "agreement":agreement,
            "limitations":["Importer validates completeness and linkage, not reviewer identity or independence.",
                            "Kappa can be undefined for constant scores; small samples need cautious interpretation.",
                            "Disagreements should be adjudicated separately without overwriting initial ratings."]}
