# sinan/：司南（调度，外壳）

规格：v1.3 §4.1；D11 做最小循环。目录由异议报告 001 第 1 项新增（2026-11-17 裁决采纳）。

## 实现的契约接口

- 读 `GET /v1/problems/{pid}/work`（图服务派生的可做事项），决定先做什么；申请租约并同时预留预算（`POST /v1/problems/{pid}/leases`）。
- 按租约启动会话：调用 Adapter 的契约接口，不读 Adapter 内部状态。
- 只读估值类字段（`expected_gain`、knot、unlocks）排序；不写任何等级相关的东西（I8）。

## 已落地（M0 最小循环）

`paoding_sinan.contract`：`Sinan(cfg, graph, reader, blobs, sessions)`、`SinanConfig`。

- `pick(pid)`：只读。从 `/work` 里挑下一项，返回 `{"do": 项}`、`{"wait": 原因}` 或 `{"stop": 原因}`。任务种类的先后是 bootstrap → reason → explore；explore 之间按 `expected_gain` 从高到低。
- `step(pid)`：对挑中的项申请租约（同时预留预算），调用 `SessionPort.run`，返回会话的结局。租约被拒时停机并带回拒绝码。
- `run(pid, max_steps, between)`：循环到关题、需要人或没有可做的事。`between` 在每一步之前被调用，单进程部署里用来驱动判官运行器；多进程部署里判官自己轮询，不传。
- 预留：bootstrap 与 reason 取配置值（bootstrap 不超过 `bootstrap_share × cap`）；explore 取 Intent 的预算，不超过 `explore_cap`。
- 题面从 Origin 的 `statement_ref` 读出，交给会话。

司南提交的只有 `lease`（I8）；judge 项不归它领。M0 的循环在进程内经 `GraphPort`、`GraphReader` 读写，与 HTTP 的 `/work`、`/leases` 是同一个投影与同一条提议通道。

部署形态：`scripts/run.py`（组装根 `scripts/stack.py`）在一个进程里起图服务、判官运行器、司南、哮天犬，各自一个循环并行；司南每道未关的题一个循环，`pick` → `step`，等待与停机原因只在变化时记一行日志。判官与司南并行，所以 `wait_for_judges` 也看在途的判官租约。

T-1 开关（`SinanConfig`）：`order_by_gain`（关掉后按 `/work` 的顺序）、`wait_for_judges`（判定未决时不开新任务；“未决”= `/work` 里还有 judge 项，或判官已领走请求而裁决未落盘）、`thin_bootstrap`（Bootstrap 的预留封顶）。

端到端纵切在 `tests/integration/test_e2e.py`：开题（HTTP）→ Bootstrap → 判定 → Reason → Explore → 判定 → 图服务自动关题，替身执行层与真 Docker 各一条。

## 官的声明

| 结构 | 官 | 标签 | 启用条件 | 退役信号 / 说明 |
| --- | --- | --- | --- | --- |
| 排序循环本身 | 守门官以外的纯代码 | — | 常开 | 读 `/work`、申请租约，是确定性代码，不调用模型 |
| 规则表（按画像选外壳规则、认领规则） | 感知官 | T-1 | 常开 | 模型自选策略不劣于推导出的规则 → 三轴只作报告字段 |
| Bootstrap 先瘦后厚 | 感知官 | T-1 | 常开；开关 `bootstrap_share` | 见附录 B |

## 依赖

`paoding_graph.contract`、`paoding_adapter.contract`。不被任何组件依赖。
