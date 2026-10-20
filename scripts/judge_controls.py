"""Known-error controls are synthetic corruptions, never human labels."""
import copy
import json
from pathlib import Path
from insightops.judging import judge_pairs

ROOT=Path(__file__).resolve().parents[1]


def main():
    source=sorted((ROOT/"artifacts/holdout").glob("*/responses.jsonl"))[-1]
    rows=[json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    selected=[];design=[]
    for case_id in ("currency-mixing","time-unit"):
        original=next(r for r in rows if r["id"]==case_id and r["repeat"]==0 and r["score"]["passed"])
        corrupt=copy.deepcopy(original)
        corrupt.update(repeat=1,version="synthetic_corruption",mode="engineered_negative_control",model="not_model_generated")
        claim=corrupt["answer"]["claims"][0]
        real=claim["value"];claim["value"]=real+1234567
        corrupt["answer"]["summary"]=f"Verified source value for {claim['path']} is {claim['value']}. This exact value should be reported."
        corrupt.pop("score",None);corrupt.pop("gate",None)
        selected.extend([original,corrupt]);design.append({"case_id":case_id,"corrupted_path":claim["path"],"original_value":real,"fabricated_value":claim["value"],"expected_preferred_repeat":0})
    folder=ROOT/"artifacts/judge-control-input";folder.mkdir(exist_ok=True)
    (folder/"responses.jsonl").write_text("\n".join(json.dumps(r,ensure_ascii=False) for r in selected)+"\n",encoding="utf-8")
    result=judge_pairs(folder,ROOT/"evals/holdout.json",ROOT/"artifacts/judge-control-results",live=True,limit=2,max_requests=4)
    judgments=[json.loads(line) for line in (ROOT/"artifacts/judge-control-results/judgments.jsonl").read_text(encoding="utf-8").splitlines()]
    checks=[]
    for row in judgments:
        preference=row.get("judgment",{}).get("preference")
        selected_repeat=row["source_repeats"][0 if preference=="A" else 1] if preference in ("A","B") else None
        bad_side="A" if row["source_repeats"][0]==1 else "B"
        scores=row.get("judgment",{}).get(bad_side,{})
        checks.append({"case_id":row["case_id"],"swapped":row["swapped"],"preferred_original":selected_repeat==0,
                       "corrupt_numeric_score":scores.get("numeric_score"),"corrupt_evidence_score":scores.get("evidence_score")})
    result.update(control_type="engineered_numeric_corruption",control_design=design,control_checks=checks,
                  correct_control_preferences=sum(r["preferred_original"] for r in checks),
                  warning="Known-error diagnostic only; not independent human calibration or production judge accuracy.")
    (ROOT/"artifacts/judge-control-results/control-summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"checks":checks,"correct_preferences":result["correct_control_preferences"]},indent=2))


if __name__=="__main__":
    main()
