"""Publish frozen holdout results and uncalibrated judge diagnostics."""
import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path
from insightops.challenges import V3

ROOT=Path(__file__).resolve().parents[1]


def main():
    manifest=json.loads((ROOT/"evals/holdout-manifest.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(V3.encode()).hexdigest()==manifest["frozen_v3_prompt_sha256"]
    assert hashlib.sha256((ROOT/"evals/holdout.json").read_bytes()).hexdigest()==manifest["suite_sha256"]
    candidates=sorted((ROOT/"artifacts/holdout").glob("*/summary.json"))
    if not candidates:
        raise ValueError("No real holdout evaluation")
    source=candidates[-1].parent;summary=json.loads((source/"summary.json").read_text(encoding="utf-8"))
    if summary.get("status")!="completed":
        raise ValueError("Holdout run is incomplete")
    out=ROOT/"reports/holdout";out.mkdir(exist_ok=True)
    for name in ("plan.json","summary.json","responses.jsonl","human-review-template.json"):
        shutil.copy2(source/name,out/name)
    rows=[json.loads(line) for line in (out/"responses.jsonl").read_text(encoding="utf-8").splitlines()]
    grouped=defaultdict(list)
    for row in rows:
        grouped[row["id"]].append(row)
    stability=[{"case_id":key,"repeats":len(values),"decisions":[r.get("answer",{}).get("decision") for r in values],
                "all_reference_passed":all(r.get("score",{}).get("passed",False) for r in values)} for key,values in grouped.items()]
    (out/"repeat-diagnostics.json").write_text(json.dumps(stability,indent=2)+"\n",encoding="utf-8")
    blind=ROOT/"reports/blind-review";blind.mkdir(exist_ok=True)
    for name in ("review-packet.json","instructions.md"):
        shutil.copy2(ROOT/"artifacts/holdout-review"/name,blind/name)
    judge=None
    if (ROOT/"artifacts/holdout-judge/summary.json").exists():
        target=ROOT/"reports/judge-diagnostics";target.mkdir(exist_ok=True)
        for name in ("summary.json","judgments.jsonl"):
            shutil.copy2(ROOT/"artifacts/holdout-judge"/name,target/name)
        judge=json.loads((target/"summary.json").read_text(encoding="utf-8"))
    controls=None
    if (ROOT/"artifacts/judge-control-results/control-summary.json").exists():
        target=ROOT/"reports/judge-controls";target.mkdir(exist_ok=True)
        for name in ("control-summary.json","judgments.jsonl"):
            shutil.copy2(ROOT/"artifacts/judge-control-results"/name,target/name)
        shutil.copy2(ROOT/"artifacts/judge-control-input/responses.jsonl",target/"source-responses.jsonl")
        controls=json.loads((target/"control-summary.json").read_text(encoding="utf-8"))
    result=summary["summary"][0]
    report=f"""# 冻结 V3 后的新场景评测与裁判诊断

## 协议

先冻结 V3 提示词与已有决策规则，再编写 12 个新任务场景，每个运行两次；不根据这些结果修改 V3 或答案键。冻结代码提交 `{manifest['frozen_code_commit']}`，提示词和案例哈希见 [协议清单](../evals/holdout-manifest.json)。作者与系统开发者相同，因此这是新场景评测，不是外部独立基准。原始 runner 的通用 versions_scope 描述沿用旧默认值，本轮实际协议以该清单为准。

范围包含币种、指标加权、多重检验、连续窥探、聚类随机、跨组污染、时间泄漏、单位换算、子群风险、漏斗异常、观察窗口和聚合隐私。

## 真实结果

模型 `{summary['configuration']['model']}`，{result['requests_attempted']} 次请求，严格参考评分通过 **{result['raw_reference_passes']}/{result['requests_attempted']}**。两次重复不是 24 个独立任务，不能把样本量当作 24 个独立业务场景。

| 场景 | 两次决策 | 两次均通过严格参考评分 |
|---|---|---|
"""
    for row in stability:
        report+=f"| {row['case_id']} | {', '.join(str(d) for d in row['decisions'])} | {row['all_reference_passed']} |\n"
    report+="""
6 条失败集中于加权口径、子群风险及漏斗异常，均是决策标签与作者参考不一致，数值引用与结构检查通过。不能直接把它们等同于危险结论或数值幻觉；须阅读完整摘要并进行独立人工复核。保留原始标签，不放宽答案键追分。

## 辅助裁判诊断

"""
    if judge:
        report+=f"预先选择按冻结顺序排列的前 {judge['pairs']} 个可配对场景，对重复答案交换 A/B 位置，共 {judge['requests_attempted']} 次真实裁判请求。映射回原答案后，偏好一致率为 {judge['preference_consistency']:.1%}；有效结构化裁判结果 {judge['valid_judgments']}/{judge['requests_attempted']}。\n\n"
        report+="其中 5 对均判为平局，6 对各维度评分在顺序交换后没有变化，存在评分饱和与样本区分力不足，不能把高一致率视为高正确率。\n\n"
    if controls:
        report+=f"补充两个明确数字篡改的控制场景，每个交换顺序，共 {controls['requests_attempted']} 次真实裁判请求；裁判 {controls['correct_control_preferences']}/{controls['requests_attempted']} 次偏好原答案，并把篡改答案的数值与证据维度评为 0。控制答案是程序构造的已知错误，不是模型生成结果或真人标签；仅证明能识别这两类明显错误。详见 [控制实验](judge-controls/control-summary.json)。\n\n"
    report+="""
裁判与被评模型使用同一模型标识，存在自评偏差；顺序交换中的差异也混合随机采样波动，不能解释为纯位置效应。未获得真人标签，因此这不是人工校准结果，也不证明裁判判断正确。

## 真人复核入口

[盲评包](blind-review/review-packet.json) 共 24 条、评分保持空白，屏蔽版本、自动分数和参考答案。协调映射仅留本地 artifacts。独立评审只接收盲评包，先独立填写再讨论。公开仓库仍有原始响应，无法保证评审完全不查看其他文件，独立性需要流程约束。

`judge-calibrate` 支持在真人评分到位后计算混淆矩阵、精确一致率和二次加权 kappa；没有标签时明确返回 awaiting_human_labels。比较完成也不会自动认定裁判可用于发布。

剩余工作是实际邀请独立评审、复核标签语义、定义裁判验收标准，并在新的业务分布上验证。项目未虚构真人标注、外部专家意见或线上收益。
"""
    (ROOT/"reports/holdout-and-judge.md").write_text(report,encoding="utf-8")
    print(json.dumps({"holdout_summary":summary["summary"],"judge_summary":judge,"human_labels":0},ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
