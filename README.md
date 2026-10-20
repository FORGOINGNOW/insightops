# InsightOps

**从业务问题到可核验证据：电商数据诊断、实验评估与 AI 分析工作流。**

这个作品集围绕一个问题：支付转化率下降时，如何区分渠道结构变化、埋点异常和产品效果，并形成可信的决策建议？

默认演示使用固定种子生成的合成数据；独立的 [真实数据案例](reports/real-data/report.md) 分析 UCI 的 541,909 行历史发票明细。真实数据与合成实验分别报告，不拼接成真实产品增长故事。

新增 [24 个独立编写的挑战场景](evals/challenges.json)、真实模型报告组件评测、V2 决策约束与人工复核导入。运行状态和实测结果见 [版本记录](reports/v0.2-iteration.md)。

真实模型首轮 V1/V2 严格参考评分为 13/24、14/24；明确输出契约后，V3 在相同案例上的开发复测为 23/24。后者不是独立测试成绩，完整失败与局限见 [V3 复测报告](reports/v3-contract-retest.md)。

冻结 V3 后新增 12 个场景，每个运行两次，严格参考评分为 **18/24**；未据此修改系统。新场景结果、重复运行与裁判顺序诊断见 [新场景评测报告](reports/holdout-and-judge.md)。这是作者设计的合成评测，尚无独立真人标签。

## 30 秒看结果

默认数据包含 20,000 个会话。会话支付转化率由 **17% 降至 8%**，但 organic 和 paid 渠道内分别保持 **20% 和 5%**。按原渠道结构标准化后，后期仍为 **17%**。总体变化由渠道构成变化解释，不能直接据此推断产品改版的因果效果。

同时存在重复访问事件、延迟支付事件、缺失支付事件、嵌套字段版本变更，以及订单与明细连接造成的收入重复计数。模拟 A/B 实验则展示另一种情况：转化改善，但退款护栏恶化，因此暂停上线。

MongoDB 已在本地完成 **1,030,360 条合成事件**实测：同一聚合查询七次运行的耗时中位数由 **413.78 ms 降至 22.73 ms**，扫描文档数由 **1,030,360 降至 0**（覆盖索引），并通过 SQL 对账。这是固定顺序、热缓存的本机基准，不能外推到生产，详见 [实测报告](reports/mongo-results.md)。

| 能力 | 可检查的实现与交付 |
|---|---|
| SQL 和指标口径 | [表结构与会话事实视图](sql/schema.sql)、[分析 SQL](sql/analysis.sql)、[指标字典](docs/metrics.md) |
| 数据质量与根因诊断 | [分析实现](src/insightops/analytics.py)、[案例复盘](reports/business-case.md) |
| MongoDB 文档分析与性能 | [聚合、索引、执行计划、SQL 对账](mongo/benchmark.py) |
| 统计与实验 | [模拟实现](src/insightops/experiment.py)、[预先定义的实验方案](docs/experiment-plan.md) |
| AI 工作流 | [受限工具路由、数值核验与运行追踪](src/insightops/workflow.py) |
| 评测与回归 | [80 条冻结案例](evals/cases.json)、[评分说明与局限](evals/README.md) |
| 真实数据与清洗判断 | [公开数据报告](reports/real-data/report.md)、[来源与授权](data/sources/uci-online-retail.json)、[读取与 SQL 核对](src/insightops/real_data.py) |
| 真实模型与复核 | [组件评测实现](src/insightops/challenges.py)、[人工评分导入](src/insightops/review.py)、[配置说明](docs/model-configuration.md) |
| 工程验证 | [故障测试](tests/test_core.py)、[CI](.github/workflows/ci.yml)、[版本验收清单](docs/status.md) |

## 本地运行

Python 3.11+，建议使用独立虚拟环境。在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
insightops demo
python -m pytest -q
```

Linux/macOS 激活环境使用 `source .venv/bin/activate`，后续命令相同。

`insightops demo` 重建仓库内 `data/generated/` 下的命名样例文件，输出：

```text
artifacts/report.md          业务、实验与规则回归汇总
artifacts/report.html        可直接用浏览器打开的汇总
artifacts/analysis.json      指标、分层、质量及对账结果
artifacts/experiment.json    模拟实验、CI、SRM 与决策
artifacts/evaluation.json    逐案例评分与版本汇总
artifacts/workflow.json      演示路由、证据、数值核验及来源
```

快速运行可用 `insightops demo --per-period 1000`。默认参数每周期 10,000 个会话。生成目录和运行产物不入 Git；已运行的摘要存放于 [reports](reports/)。

## 工作流：演示与真实调用

默认 demo 使用确定性路由和报告模板，不调用模型、不产生模型费用。任意自然语言问题的路由能力需要真实模型模式验证。

真实模型模式使用兼容 Chat Completions 的接口。推荐先交互配置；输入密钥时隐藏显示，`.env` 被 Git 忽略，配置不会发起生成请求：

```powershell
python -m insightops.cli configure
python -m insightops.cli configure --check
# 可选：只读取服务商模型列表，确认认证和模型标识：
python -m insightops.cli configure --probe
```

也支持以下环境变量，优先级高于本地配置：

```powershell
# 使用自己的凭证管理方式设置这些变量，不把凭证写入文件或 Git。
# INSIGHTOPS_API_KEY   模型 API 凭证
# INSIGHTOPS_MODEL     明确的模型标识
# INSIGHTOPS_BASE_URL  可选，默认为 https://api.openai.com/v1
insightops workflow --live "比较样例中 before 和 after 周期的会话支付转化率，检查渠道结构与数据质量。"
```

一次正常调用包含两次请求：模型选择允许的分析工具，再基于工具证据输出报告。模型不能执行任意 SQL。数值声明验证失败会产生 `blocked_numeric_validation`；验证通过也保留 `requires_human_review`，因为摘要的语义和因果推断尚未自动验证。记录 token usage；未配置价格表时不虚构金额成本。接口需要支持 JSON 对象响应。

## 真实数据与模型挑战评测

```powershell
python -m pip install -e ".[real-data]"
insightops real-data --download
# 预览请求计划，不调用模型：
insightops challenge-eval
# 两个配置、四个场景，共八次真实请求：
insightops challenge-eval --live --limit 4 --max-requests 8
# 完整 24 场景的两个配置，共 48 次请求：
insightops challenge-eval --live --limit 24 --max-requests 48
# 修复配置 V3：相同案例上的开发复测，共 24 次请求：
insightops challenge-eval --live --versions v3 --limit 24 --max-requests 24
```

公开数据下载有来源哈希校验，原工作簿保持不变；金额使用百万分之一英镑整数保存。缺失客户 ID 的记录保留在金额统计中；相同字段行作为候选重复进行敏感性分析；未完整观察的次月复购指标保留为空。

挑战评测提供固定证据，测量报告与决策组件，不等同于端到端查库能力。V1 使用基础提示和数值检查，V2 额外加入分析约束提示及确定性决策门禁。评分同时保留模型原始答案是否通过、门禁是否拦截，拦截错误答案不算任务成功。逐条记录、请求计数、耗时、token 和空白人工复核模板保存在 `artifacts/live-evals/<run-id>/`。401/402/403/429 等不可继续的接口错误会停止后续请求。

复核者手工填写模板后运行：

```powershell
insightops human-review --run-dir artifacts/live-evals/<run-id> --labels <completed-labels.json>
```

模板不能当作已标注数据；单人评分不宣称评审间一致性。模型裁判校准仍待后续采集。

## 新场景、盲评与裁判诊断

```powershell
# 仅预览冻结协议，不发请求：
insightops holdout-eval
# 12 场景各运行两次，共 24 次请求：
insightops holdout-eval --live
# 从已提交结果重建本地盲评包与协调映射，无模型请求：
insightops review-pack --run-dir reports/holdout --cases evals/holdout.json --out artifacts/holdout-review
# 没有真人标签时返回 awaiting_human_labels：
insightops judge-calibrate --packet-dir artifacts/holdout-review
# 真人独立填写后，与裁判评分比较：
insightops judge-calibrate --packet-dir artifacts/holdout-review --labels <completed-review-packet.json> --judge-dir reports/judge-diagnostics
```

只把 review-packet.json 和评分说明发给真人评审，协调者保留映射。先独立评分再讨论。裁判顺序诊断使用配置中的同一模型，不是独立专家。比较指标包括混淆矩阵、精确一致率和二次加权 kappa；这些指标不会自动批准裁判用于发布。未收集到真人标签时，不输出伪造的一致率。

## MongoDB 可复现实验

需要已运行的 Docker Engine：

```powershell
python -m pip install -e ".[mongo]"
docker compose up -d --wait
python mongo/benchmark.py --copies 1 --repeats 7
# 扩大样例规模后复测，按实际运行结果报告性能：
python mongo/benchmark.py --copies 30 --repeats 7
docker compose stop
```

脚本仅重建 `insightops_portfolio.events_benchmark` 集合。不要指向需要保留同名集合的实例。结果包含优化前后延迟样本、执行计划、扫描量、文档数量、平均文档大小、服务端版本及 SQL 对账。数据复制扩大规模不能模拟真实生产分布。

## 结构与边界

```text
生成账本 → SQLite 用户/会话/订单/事件 → 指标与质量分析
                     └→ MongoDB 嵌套文档 → 索引/执行计划/核对
独立模拟随机实验 → 主指标/护栏/SRM → 决策
问题 → 工具选择 → 固定分析工具 → 结构化声明 → 数值核验 → 人工复核
冻结案例 → V0/V1/V2 规则消融 → 回归报告
```

这份作品集不声称已取得线上增长、真实客户应用或大规模生产运维经验。规则回归的 100% 分数只说明受控案例能通过预设检查。独立人工标注、模型裁判校准、多 Agent、RAG/MCP 是后续工作，见 [路线图](docs/roadmap.md)。
