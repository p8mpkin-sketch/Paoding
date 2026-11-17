# watchdog/：哮天犬（纯脚本）

规格：v1.3 §2 数据流第 7 步、§3.5。只做四件事：过期租约（`expire_lease`）、超预算终止、清理孤儿容器、健康告警。

## 官的声明

| 结构 | 官 | 标签 | 启用条件 | 长存依据 |
| --- | --- | --- | --- | --- |
| 预算硬顶的执行者、过期回收 | 守门官 | T-0 | 常开 | 资源有涯 |

不调用模型。

## 依赖

`paoding_graph.contract`。

## 实现（离线预备）

`dog.py`，一个 `tick()` 一轮，`run_forever` 每 10 秒一轮。读的只有图服务的状态与 `/budget`。

| 件 | 做法 |
| --- | --- |
| 过期租约 | `expires_at` 已过的在途租约提交 `expire_lease`；会话若还活着，经 `TaskControl.kill(lid, "expired")` 收掉 |
| 超预算终止 | 按任务汇总 cost 事件：≥ 预留额 90% 通知一次 `soft_line`；≥ 预留额 `kill(lid, "budget")`。题花费 ≥ cap 或墙钟用尽：终止题内全部任务，提交 `close_problem`（终态由图服务按三值算，此时为 unsolved） |
| 清理孤儿容器 | 调注入的清扫函数（执行层 `sweep_orphans`） |
| 健康告警 | 每个后端最近 10 个已结束任务，失败（failed、expired）占比 > 50% 且样本 ≥ 4 时给出 `backend_unhealthy`，同一窗口只报一次。M0 只有一个后端；告警目前只在返回值里，交人的通道随 `pd` 落地 |

`TaskControl`（`contract.py`）是结构化接口：Adapter 的会话运行器有同名方法即可，哮天犬不 import adapter；组装根接线。
`soft_line` 在 Adapter 侧 = SIGINT 结束当前回合 + `--resume` 收尾轮；`kill` = SIGTERM 进程树 + 销毁执行容器，租约以 `budget_exhausted` 释放。

### 实现取值（待红队确认）

1. 软线、硬顶只看金额一轨；token 轨的上限由图服务在领租约时检查，哮天犬不重复。
2. 墙钟从开题事件的时间戳起算（reducer 状态新增 `opened_ts`）。
3. 判官租约不受任务软线约束（判官没有收尾轮），只受题 cap 与墙钟约束。

### 已知缺口

1. `scope_violation` 累计 3 次终止：执行层还不产生该事件（executor/SPEC.md 已知缺口 1），D3 补。
2. 告警不落日志：内核没有告警事件种类，M0 不加；`pd status` 读哮天犬的返回值显示。
