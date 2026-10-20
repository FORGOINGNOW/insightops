"""Select aggregate/public run evidence for Git review; never include .env/raw data.

Run only after live evaluation completes. Actual Git staging remains explicit.
"""
import hashlib
import json
import shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    runs=[]
    for path in (ROOT/"artifacts/live-evals").glob("*/summary.json"):
        summary=json.loads(path.read_text(encoding="utf-8"))
        if summary.get("status")=="completed" and summary.get("cases")==24 and summary.get("versions")==["v1","v2"]:
            runs.append((path.parent,summary))
    if not runs:
        raise ValueError("No completed 24-case live evaluation; cannot create result claims")
    folder,result=sorted(runs,key=lambda item:item[0].name)[-1]
    out=ROOT/"reports/live";out.mkdir(exist_ok=True)
    for name in ("plan.json","responses.jsonl","summary.json","human-review-template.json"):
        shutil.copy2(folder/name,out/name)
    for source,target in [("workflow-live-before-context.json","workflow-before-context.json"),("workflow-live.json","workflow-after-context.json")]:
        shutil.copy2(ROOT/"artifacts"/source,out/target)
    rows=[json.loads(line) for line in (out/"responses.jsonl").read_text(encoding="utf-8").splitlines()]
    cases=json.loads((ROOT/"evals/challenges.json").read_text(encoding="utf-8"))
    index={c["id"]:c for c in cases}
    failures=[{"id":r["id"],"version":r["version"],"expected_decision":index[r["id"]]["expected"]["decision"],
               "actual_decision":r["answer"].get("decision"),"score":r["score"],"gate":r["gate"]}
              for r in rows if r["status"]=="returned" and not r["score"]["passed"]]
    (out/"failures.json").write_text(json.dumps(failures,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    hashes={name:hashlib.sha256((ROOT/"src/insightops"/name).read_bytes()).hexdigest() for name in ("challenges.py","workflow.py","review.py")}
    if not (out/"snapshot-metadata.json").exists():
        (out/"snapshot-metadata.json").write_text(json.dumps({"run_id":result["run_id"],"source_files_at_snapshot":hashes,
            "note":"Source hashes at evidence snapshot time; baseline workflow predates the added data contract. Raw response/prompt hashes remain in run records."},indent=2)+"\n",encoding="utf-8")
    report=f"""# v0.2：真实数据、真实模型与失败驱动的迭代

输出契约修复与同集开发复测见 [V3 报告](v3-contract-retest.md)。首轮原始结果保持不变。

## 实测范围

2026-10-20，模型 `{result['configuration']['model']}`。24 个作者独立编写的合成挑战、两个配置、各运行一次，共 {sum(r['requests_attempted'] for r in result['summary'])} 次请求。运行 ID `{result['run_id']}`。本次评估固定证据上的报告与决策组件，未评估模型自行查库、RAG、多 Agent 或生产任务分布。

V1 使用基础提示与结构/数值验证；V2 同时增加约束提示和确定性决策门禁。参考答案不进入请求。V2 的约束来自证据合同，模型会看到这些约束，这属于被评估系统的一部分。

| 配置 | 请求 | 原始答案参考评分通过 | 门禁拦截 | 未通过参考评分但被接受 | 总 token | 延迟中位数 |
|---|---:|---:|---:|---:|---:|---:|
"""
    for row in result["summary"]:
        report+=f"| {row['version']} | {row['requests_attempted']} | {row['raw_reference_passes']}/{row['requests_attempted']} | {row['blocked']} | {row['reference_failures_accepted']} | {row['reported_total_tokens']:,} | {row['median_latency_ms']:.0f} ms |\n"
    report+="""
原始评分检查 schema、精确决策标签、要求的数字引用和局限说明。拦截不算回答成功；“未通过参考评分”也不自动意味着危险，可能是标签与语义相近的拒答不一致，须逐条复核。

## 失败案例（保留全部，不更改答案键追分）

| 案例 | 配置 | 预期标签 | 实际标签 | 被拦截 |
|---|---|---|---|---|
"""
    for failure in failures:
        report+=f"| {failure['id']} | {failure['version']} | {failure['expected_decision']} | {failure['actual_decision']} | {failure['gate']['blocked']} |\n"
    report+="""
细项见 [失败记录](live/failures.json)、[完整响应](live/responses.jsonl) 与 [汇总](live/summary.json)。这些是自动参考评分，尚无独立人工标注或裁判校准。单次小样本不能证明稳定提升；没有报告统计显著性。

## 一次实际工作流修复

原端到端工作流在用户指定样例 before/after 会话支付转化率时仍要求澄清。原因是模型在选工具前看不到可用数据的周期别名、总体和指标定义。

修复：在路由前提供由只读查询构建的数据合同，明确 before/after 的时间范围、会话总体、订单支付口径与允许工具。复跑同一问题后选择 analysis，并完成报告数值引用核验。前后输出见 [修复前](live/workflow-before-context.json) 和 [修复后](live/workflow-after-context.json)。这是单任务诊断性验证，不宣称端到端总体成功率提高。

## 真实数据证据

[UCI 案例](real-data/report.md) 读取 541,909 行发票明细。保留未知客户的金额、以敏感性分析处理候选重复、保留亚便士单价、将未完整观察的次月复购留空，原始读取账本与 SQL 聚合对账通过。

## 尚未完成

- 独立人工复核、至少两位评审的重叠样本与分歧复盘。
- LLM 裁判与人工评分的校准。
- 新分布任务、重复采样、提示与门禁的独立消融。
- 经确认的模型价格表与金额成本核算。
- 实际业务接入与上线效果追踪。

人工评分模板为空白，不能当作已收集标签。原始业务文件和 API 凭证不进入仓库。
"""
    (ROOT/"reports/v0.2-iteration.md").write_text(report,encoding="utf-8")
    snapshot_v3()
    print(json.dumps({"run_id":result["run_id"],"summary":result["summary"],"failure_records":len(failures)},indent=2))


def snapshot_v3():
    candidates=[]
    for file in (ROOT/"artifacts/live-evals").glob("*/summary.json"):
        data=json.loads(file.read_text(encoding="utf-8"))
        if data.get("status")=="completed" and data.get("versions")==["v3"] and data.get("cases")==24:
            candidates.append((file.parent,data))
    if not candidates:
        return
    folder,result=sorted(candidates,key=lambda item:item[0].name)[-1]
    target=ROOT/"reports/live-v3";target.mkdir(exist_ok=True)
    for name in ("plan.json","summary.json","responses.jsonl","human-review-template.json"):
        shutil.copy2(folder/name,target/name)
    r=result["summary"][0]
    report=f"""# V3 输出契约修复：开发集复测

这是查看 V1/V2 错误后，在**相同 24 个场景**上的开发复测；不是独立测试集成绩，不能作为泛化准确率或稳定收益。

模型 `{result['configuration']['model']}`，运行 `{result['run_id']}`，24 次请求、每场景一次。

## 改动

1. 明确 claims 仅允许有限数值标量，禁止布尔、空值、数组和对象。
2. 给出置信区间引用的点分索引示例，禁止方括号路径。
3. 定义接近的拒答标签，并要求选择第一项数据合同约束。
4. 增加缺失置信区间的确定性检查。没有修改案例或参考答案，案例 SHA-256 与首轮相同。

## 实测

严格参考评分通过 **{r['raw_reference_passes']}/{r['requests_attempted']}**，门禁拦截 {r['blocked']} 条；仍有 {r['reference_failures_accepted']} 条未通过参考评分但被门禁接受。token 总量 {r['reported_total_tokens']:,}，延迟中位数 {r['median_latency_ms']:.0f} ms。

V1/V2 首轮分别为 13/24、14/24。该前后对比同时改变提示与部分门禁，没有重复采样，也没有将任务随机分配到版本，不能据此宣称统计显著提升或提示词独立贡献。

## 保留的失败

`within-segment-regression` 的参考标签是 `investigate_within_segment`，V3 返回 `descriptive_only`。输出仍列出了各渠道下降并建议排查，但结构化决策过于笼统。这也说明精确标签评分与摘要语义并非同一件事，需要独立人工复核；本项目不把它直接归为危险错误。

完整 [原始响应](live-v3/responses.jsonl)、[摘要](live-v3/summary.json) 及空白人工评分模板保留。评分回放命令 `python scripts/replay_scores.py` 检查 72 条真实响应的案例哈希、请求哈希、原始评分和决策门禁，无需模型请求。

下一步应冻结本轮开发结果，新增未用于修改提示的任务与分布，并开展重复采样及独立人工复核。不能继续在这 24 个案例上调优后把分数称为测试成绩。
"""
    (ROOT/"reports/v3-contract-retest.md").write_text(report,encoding="utf-8")


if __name__=="__main__":
    main()
