# 冻结 V3 后的新场景评测与裁判诊断

## 协议

先冻结 V3 提示词与已有决策规则，再编写 12 个新任务场景，每个运行两次；不根据这些结果修改 V3 或答案键。冻结代码提交 `7cd9d40a94889e229da2365609fbb73c8a0f5e84`，提示词和案例哈希见 [协议清单](../evals/holdout-manifest.json)。作者与系统开发者相同，因此这是新场景评测，不是外部独立基准。原始 runner 的通用 versions_scope 描述沿用旧默认值，本轮实际协议以该清单为准。

范围包含币种、指标加权、多重检验、连续窥探、聚类随机、跨组污染、时间泄漏、单位换算、子群风险、漏斗异常、观察窗口和聚合隐私。

## 真实结果

模型 `deepseek-flash`，24 次请求，严格参考评分通过 **18/24**。两次重复不是 24 个独立任务，不能把样本量当作 24 个独立业务场景。

| 场景 | 两次决策 | 两次均通过严格参考评分 |
|---|---|---|
| currency-mixing | separate_currency_totals, separate_currency_totals | True |
| ratio-aggregation | aggregate_before_reporting, aggregate_before_reporting | False |
| temporal-leakage | investigate_temporal_leakage, investigate_temporal_leakage | True |
| multiple-tests | adjust_multiple_testing, adjust_multiple_testing | True |
| repeated-peeking | review_sequential_design, review_sequential_design | True |
| cluster-unit | review_cluster_dependence, review_cluster_dependence | True |
| cross-arm-users | investigate_assignment_contamination, investigate_assignment_contamination | True |
| time-unit | reconcile_units, reconcile_units | True |
| small-segment-harm | hold_guardrail_harm, hold_guardrail_harm | False |
| impossible-funnel | grain_reconciliation_required, grain_reconciliation_required | False |
| right-censored-window | incomplete_observation, incomplete_observation | True |
| aggregate-privacy | aggregate_before_reporting, aggregate_before_reporting | True |

6 条失败集中于加权口径、子群风险及漏斗异常，均是决策标签与作者参考不一致，数值引用与结构检查通过。不能直接把它们等同于危险结论或数值幻觉；须阅读完整摘要并进行独立人工复核。保留原始标签，不放宽答案键追分。

## 辅助裁判诊断

预先选择按冻结顺序排列的前 6 个可配对场景，对重复答案交换 A/B 位置，共 12 次真实裁判请求。映射回原答案后，偏好一致率为 100.0%；有效结构化裁判结果 12/12。

其中 5 对均判为平局，6 对各维度评分在顺序交换后没有变化，存在评分饱和与样本区分力不足，不能把高一致率视为高正确率。

补充两个明确数字篡改的控制场景，每个交换顺序，共 4 次真实裁判请求；裁判 4/4 次偏好原答案，并把篡改答案的数值与证据维度评为 0。控制答案是程序构造的已知错误，不是模型生成结果或真人标签；仅证明能识别这两类明显错误。详见 [控制实验](judge-controls/control-summary.json)。


裁判与被评模型使用同一模型标识，存在自评偏差；顺序交换中的差异也混合随机采样波动，不能解释为纯位置效应。未获得真人标签，因此这不是人工校准结果，也不证明裁判判断正确。

## 真人复核入口

[盲评包](blind-review/review-packet.json) 共 24 条、评分保持空白，屏蔽版本、自动分数和参考答案。协调映射仅留本地 artifacts。独立评审只接收盲评包，先独立填写再讨论。公开仓库仍有原始响应，无法保证评审完全不查看其他文件，独立性需要流程约束。

`judge-calibrate` 支持在真人评分到位后计算混淆矩阵、精确一致率和二次加权 kappa；没有标签时明确返回 awaiting_human_labels。比较完成也不会自动认定裁判可用于发布。

剩余工作是实际邀请独立评审、复核标签语义、定义裁判验收标准，并在新的业务分布上验证。项目未虚构真人标注、外部专家意见或线上收益。
