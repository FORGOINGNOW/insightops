"""New task families authored after freezing V3. Do not tune V3 on these results."""
import hashlib
import inspect
import json
import subprocess
from pathlib import Path
from insightops.challenges import V3,policy_constraints

ROOT=Path(__file__).resolve().parents[1]
CASES=[
 ("currency-mixing","英镑和美元的销售金额可以直接相加作为总收入吗？",{"amounts":{"GBP":100,"USD":200},"fx_rate":None},"separate_currency_totals",{"amounts.GBP":100,"amounts.USD":200}),
 ("ratio-aggregation","分组转化率直接平均得 26%，但按总分子分母得到 4%，应如何处理？",{"unweighted_rate":0.26,"weighted_rate":0.04,"metric_definition":"sum converters / sum eligible users"},"grain_reconciliation_required",{"weighted_rate":0.04}),
 ("temporal-leakage","用支付完成后生成的字段预测支付完成，离线准确率很高，能上线吗？",{"feature_available_at_prediction":False,"offline_accuracy":0.99},"investigate_temporal_leakage",{}),
 ("multiple-tests","同时测试了 100 个指标，最小 p 值 0.03，未经校正可以宣布显著吗？",{"tests":100,"minimum_p_value":0.03,"multiplicity_adjusted":False},"adjust_multiple_testing",{"tests":100}),
 ("repeated-peeking","每天看一次结果，第一次 p<0.05 就停，普通固定样本检验还可信吗？",{"looks":20,"sequential_design_prespecified":False,"stopping_p_value":0.04},"review_sequential_design",{"looks":20}),
 ("cluster-unit","按门店随机，却把每个订单当作独立样本做检验，可以据此上线吗？",{"randomization_unit":"store","analysis_unit":"order","cluster_adjusted":False,"stores":12},"review_cluster_dependence",{"stores":12}),
 ("cross-arm-users","同一批用户有 18% 同时进入实验两组，分流比例检验没报警，结论可靠吗？",{"srm_p_value":0.5,"cross_arm_fraction":0.18,"randomization_unit":"user"},"investigate_assignment_contamination",{"cross_arm_fraction":0.18}),
 ("time-unit","延迟日志一端是毫秒、另一端是秒，如何解读 1000 倍差异？",{"source_a_value":1000,"source_a_unit":"ms","source_b_value":1,"source_b_unit":"s"},"reconcile_units",{"source_a_value":1000,"source_b_value":1}),
 ("small-segment-harm","总体转化改善，但重要小客群退款恶化，应该直接全量吗？",{"overall_conversion_effect":0.02,"segment_refund_effect_ci":[0.01,0.03],"segment_share":0.05,"segment_prespecified":True},"investigate_segment_harm",{"segment_share":0.05}),
 ("impossible-funnel","定义为每用户最多一次支付，但支付用户数超过曝光用户数，先报大于100%的转化吗？",{"exposed_users":100,"paying_users":120,"max_conversions_per_user":1},"investigate_source_conflict",{"exposed_users":100,"paying_users":120}),
 ("right-censored-window","两组退款观察分别是 30 天和 7 天，B 更低，可以认为退款改善吗？",{"observation_complete":False,"a_followup_days":30,"b_followup_days":7,"refund_window_days":30},"incomplete_observation",{"b_followup_days":7}),
 ("aggregate-privacy","报告订单金额时是否需要把用户邮箱逐条公开？",{"sales_gbp":500,"email_example":"person@example.invalid","report_audience":"public portfolio","row_level_identifiers_needed":False},"aggregate_before_reporting",{"sales_gbp":500})
]

if __name__=="__main__":
    original=json.loads((ROOT/"evals/challenges.json").read_text(encoding="utf-8"))
    choices=sorted(set(original[0]["allowed_decisions"])|{r[3] for r in CASES})
    cases=[{"id":key,"question":question,"evidence":evidence,"severity":"major","allowed_decisions":choices,
            "expected":{"decision":decision,"required_claims":claims},"label_source":"author_reference_not_independent_review"}
           for key,question,evidence,decision,claims in CASES]
    path=ROOT/"evals/holdout.json"
    path.write_text(json.dumps(cases,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")
    manifest={"suite_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"frozen_v3_prompt_sha256":hashlib.sha256(V3.encode()).hexdigest(),
              "frozen_policy_sha256":hashlib.sha256(inspect.getsource(policy_constraints).encode()).hexdigest(),
              "frozen_code_commit":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
              "protocol":"12 new author-designed task families; V3 frozen before first call; two repeats; do not tune on results. Not an independent external benchmark."}
    (ROOT/"evals/holdout-manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8",newline="\n")
