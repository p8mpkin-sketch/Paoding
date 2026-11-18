# sinan/：司南（调度，外壳）

规格：v1.4 §4.1；D11 做最小循环。目录由异议报告 001 第 1 项新增（2026-11-17 裁决采纳）。

## 实现的契约接口

- 读 `GET /v1/problems/{pid}/work`（图服务派生的可做事项），决定先做什么；申请租约并同时预留预算（`POST /v1/problems/{pid}/leases`）。
- 按租约启动会话：调用 Adapter 的契约接口，不读 Adapter 内部状态。
- 只读估值类字段（`expected_gain`、knot、unlocks）排序；不写任何等级相关的东西（I8）。

## 已落地（M0 最小循环）

`paoding_sinan.contract`：`Sinan(cfg, graph, reader, blobs, sessions)`、`SinanConfig`。

- `pick(pid)`：只读。从 `/work` 里挑下一项，返回 `{"do": 项}`、`{"wait": 原因}` 或 `{"stop": 原因}`。任务种类的先后是 bootstrap → reason → explore；explore 之间按 `expected_gain` 从高到低。
- `dispatch(pid)`：对挑中的项申请租约（同时预留预算），把会话交给线程池就返回 `{"started": 项, "lease": id}`；开不了时返回与 `pick` 同形的等待或停机原因。
- `collect(timeout, pid)`：收回跑完的会话。会话线程里的异常变成一条 `status="crashed"` 的记录，不带倒调度线程。
- `step(pid)`：`dispatch` 后等这一个会话跑完，返回它的结局（串行用法）。租约被拒时停机并带回拒绝码。
- `run(pid, max_steps, between)`：循环到关题、需要人或没有可做的事。每一轮把能开的会话都开出去，再等至少一个跑完。`between` 在每一轮之前被调用，单进程部署里用来驱动判官运行器；多进程部署里判官自己轮询，不传。

### 并发（审计 P1-3）

会话在线程池里跑，`SinanConfig.max_sessions` 是本实例同时在途的会话上限，默认 3，取 1 即串行。调度本身仍是单线程、确定性代码。

- 同一 Intent 同时只有一个会话：内核的租约互斥（同一目标上已有在途租约则 `conflict_leased`，在途的 Intent 也不在 `/work` 里）；司南另记一张在途表，上一个会话的线程没收回之前不再开同一项。
- Reason 每题互斥：内核同样只给一个在途的 reason 租约。Reason 该跑或正在跑时不开新的 Explore，已在途的 Explore 不打断。
- 租约的幂等键带着项本身（`sinan-lease:<题>:<seq>:<种类>:<目标>`）：同一 seq 上接连领两个租约，后一个不会被当成前一个的重放。
- 别的会话还占着预留时，`over_budget` 是等待，不是停机。
- 取值上的缝隙记在 `docs/m0/dissent-p1-3-sinan-concurrency.md`。
- 预留：bootstrap 与 reason 取配置值（bootstrap 不超过 `bootstrap_share × cap`）；explore 取 Intent 的预算，不超过 `explore_cap`。
- 题面从 Origin 的 `statement_ref` 读出，交给会话。

司南提交的只有 `lease`（I8）；judge 项不归它领。M0 的循环在进程内经 `GraphPort`、`GraphReader` 读写，与 HTTP 的 `/work`、`/leases` 是同一个投影与同一条提议通道。

部署形态：`scripts/run.py`（组装根 `scripts/stack.py`）在一个进程里起图服务、判官运行器、司南、哮天犬，各自一个循环并行；司南每道未关的题一个实例与一个调度循环，`collect` → `pick` → `dispatch`，会话在该实例的线程池里并行（配置 `max_sessions`，默认 3）；会话的开始与结束各记一行日志，等待与停机原因只在变化时记一行。关题时还在途的会话由该循环叫停。判官与司南并行，所以 `wait_for_judges` 也看在途的判官租约。

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
