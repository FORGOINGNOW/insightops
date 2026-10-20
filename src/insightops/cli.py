from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from .analytics import analyze
from .data import ROOT, generate
from .evaluation import build_cases, evaluate
from .experiment import run_experiment
from .workflow import run_workflow
from .config import configure, configuration_status, probe_configuration


def save(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


def demo(root: Path, n=10000):
    data=root/"data/generated"
    out=root/"artifacts"
    generate(data,per_period=n)
    analytics=analyze(data/"commerce.sqlite")
    experiment=run_experiment()
    cases_path=root/"evals/cases.json"
    cases=json.loads(cases_path.read_text(encoding="utf-8")) if cases_path.exists() else build_cases()
    evaluation=evaluate(cases)
    workflow=run_workflow("比较 2026 年 9 月和 10 月样例周期的会话支付转化率，并解释渠道结构及埋点质量的影响。",data)
    for name,value in [("analysis",analytics),("experiment",experiment),("evaluation",evaluation),("workflow",workflow)]:
        save(out/f"{name}.json",value)
    totals={r["period"]:r for r in analytics["canonical"]}
    report=f"""# InsightOps 本地运行报告

所有业务数据均为合成数据；工作流演示及评测使用确定性规则，没有调用大模型。

## 业务诊断

| 周期 | 会话数 | 支付数 | 会话支付转化率 |
|---|---:|---:|---:|
| before | {totals['before']['sessions']} | {totals['before']['conversions']} | {totals['before']['rate']:.2%} |
| after | {totals['after']['sessions']} | {totals['after']['conversions']} | {totals['after']['rate']:.2%} |

按 before 的渠道构成标准化后，after 的转化率为 {analytics['standardized_to_before_mix']['after']:.2%}。
各渠道内部转化率不变，整体下降由渠道构成变化解释；不能据此认定产品改版产生因果影响。

数据质量发现：重复事件 {analytics['quality']['duplicate_events']} 条；截止时点未到达的支付事件 {analytics['quality']['late_payments']} 条；缺失支付事件 {analytics['quality']['missing_payments']} 条。

收入对账通过：{analytics['reconciliation']['passed']}。未经聚合直接连接订单明细，会使订单收入重复计算。

## 模拟实验

主指标绝对差：{experiment['primary']['absolute_effect']:.2%}；95% CI：{experiment['primary']['ci95']}。
退款用户占分配用户比例的绝对差：{experiment['guardrail_refunded_users_per_assigned_user']['absolute_effect']:.2%}。
决策：`{experiment['decision']}`。模拟实验不代表真实线上收益。

## 回归评测

| 规则版本 | 集合 | 通过数 | 总数 | 通过率 |
|---|---|---:|---:|---:|
"""
    for r in evaluation["summary"]:
        report+=f"| {r['version']} | {r['split']} | {r['passed']} | {r['n']} | {r['pass_rate']:.1%} |\n"
    report+="\n这是规则消融与评测框架验证，不是 LLM 能力测量。测试集与开发集共享任务模板，不足以证明泛化能力。MongoDB 性能、真实模型质量、人工评审一致性均须独立运行或采集后报告。\n"
    (out/"report.md").write_text(report,encoding="utf-8")
    # Portable, dependency-free report viewer; raw HTML is escaped.
    (out/"report.html").write_text("<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>InsightOps</title><style>body{max-width:1000px;margin:40px auto;padding:0 24px;background:#f6f8fb;color:#18243b;font:16px/1.7 system-ui}pre{white-space:pre-wrap;background:white;padding:28px;border-radius:12px}</style><h1>InsightOps · 可复现分析报告</h1><pre>"+html.escape(report)+"</pre></html>",encoding="utf-8")
    print(report)
    return out


def main():
    parser=argparse.ArgumentParser(description="Synthetic evidence-first analytics portfolio")
    sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser("demo"); p.add_argument("--root",type=Path,default=ROOT); p.add_argument("--per-period",type=int,default=10000)
    p=sub.add_parser("workflow"); p.add_argument("question"); p.add_argument("--live",action="store_true"); p.add_argument("--root",type=Path,default=ROOT)
    p=sub.add_parser("eval"); p.add_argument("--root",type=Path,default=ROOT)
    p=sub.add_parser("configure"); group=p.add_mutually_exclusive_group(); group.add_argument("--check",action="store_true"); group.add_argument("--probe",action="store_true"); p.add_argument("--root",type=Path,default=ROOT)
    p=sub.add_parser("real-data"); p.add_argument("--download",action="store_true"); p.add_argument("--root",type=Path,default=ROOT)
    p=sub.add_parser("challenge-eval"); p.add_argument("--live",action="store_true"); p.add_argument("--limit",type=int,default=4); p.add_argument("--repeats",type=int,default=1); p.add_argument("--max-requests",type=int,default=12); p.add_argument("--versions",nargs="+",choices=["v1","v2","v3"],default=["v1","v2"]); p.add_argument("--root",type=Path,default=ROOT)
    p=sub.add_parser("human-review"); p.add_argument("--run-dir",type=Path,required=True); p.add_argument("--labels",type=Path,required=True)
    args=parser.parse_args()
    if args.command=="human-review":
        from .review import analyze_reviews
        result=analyze_reviews(args.run_dir,args.labels)
        save(args.run_dir/"human-review-summary.json",result)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    elif args.command=="real-data":
        from .real_data import run
        run(args.root,args.download)
    elif args.command=="challenge-eval":
        from .challenges import evaluate_live
        result=evaluate_live(args.root/"evals/challenges.json",args.root/"artifacts/live-evals",live=args.live,limit=args.limit,repeats=args.repeats,versions=tuple(args.versions),max_requests=args.max_requests)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    elif args.command=="configure":
        result=probe_configuration(args.root/".env") if args.probe else (configuration_status(args.root/".env") if args.check else configure(args.root/".env"))
        print(json.dumps(result,ensure_ascii=False,indent=2))
    elif args.command=="demo":
        demo(args.root,args.per_period)
    elif args.command=="workflow":
        result=run_workflow(args.question,args.root/"data/generated",args.live)
        save(args.root/"artifacts/workflow-live.json" if args.live else args.root/"artifacts/workflow-demo.json",result)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    else:
        cases=json.loads((args.root/"evals/cases.json").read_text(encoding="utf-8"))
        result=evaluate(cases)
        save(args.root/"artifacts/evaluation.json",result)
        print(json.dumps(result["summary"],indent=2))


if __name__=="__main__":
    main()
