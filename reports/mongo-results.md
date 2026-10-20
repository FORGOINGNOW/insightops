# MongoDB 实测：先保证结果，再比较执行计划

2026-10-20，本机 Docker MongoDB 7.0.45；16 个逻辑 CPU；Docker Engine 可用内存约 7.63 GiB，MongoDB 容器上限 1 GiB。运行完成时容器内存约 488 MiB。宿主为 Windows 11；磁盘介质未单独测量，因此不做跨硬件性能比较。

固定种子生成的 25,759 条基础事件复制 40 份，重写事件与会话逻辑键，共 **1,030,360 条文档**，平均每条 283 字节。复制数据用于扩大可复现扫描规模，不代表独立真实业务分布。

## 查询与索引

筛选 after 周期、payment 事件、received_at 不晚于截止点，按 logical_id 去重后计数。索引字段顺序为 period、event_type、received_at、logical_id。

每个条件先预热一次，再记录七次客户端耗时，中位数用于展示。先测无索引，再创建索引测优化版本。固定执行顺序与缓存状态存在混杂，没有声称是随机交叉的严格性能实验。

| 指标 | 无业务索引 | 复合索引 |
|---|---:|---:|
| 七次客户端耗时中位数 | 413.78 ms | 22.73 ms |
| explain 扫描文档 | 1,030,360 | 0 |
| explain 扫描索引键 | 0 | 22,480 |
| 去重支付事件数 | 22,480 | 22,480 |

索引覆盖本查询需要的字段，因此避免回表。约 18.2 倍的本地中位数差异仅适用于本次样例和环境，不意味着所有查询都有同样收益。

MongoDB 聚合结果与 SQLite 相同 cutoff、相同去重粒度结果乘以 40 一致。兼容两种嵌套字段结构的 page 归一化也返回全部 1,030,360 条 checkout 事件。

完整执行计划、每次延迟样本、来源哈希与参数见 [mongo-benchmark.json](mongo-benchmark.json)。

## 复现

```powershell
insightops demo
docker compose -p insightops-portfolio up -d --wait
python mongo/benchmark.py --copies 40 --repeats 7
docker compose -p insightops-portfolio stop
```

本次使用镜像 ID：`sha256:c53852c00c23ca9f23fc39690350ffa9a80e3642fe8f96879726d8da0abe80a7`。`mongo:7.0` 标签可能更新，复测应记录实际版本和镜像标识。
