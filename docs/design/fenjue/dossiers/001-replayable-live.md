# 炼档 001：可回放的实时性

> 焚决首炼。协议见 [02 炼化](../02-lianhua.md)；前三节的设计稿是 [05 §1](../05-cases.md#1-案例一可回放的实时性)，随 #116 经 cz 2026-11-20 裁决通过（FJ13、FJ15）。机器可读的部分在同名的 [001-replayable-live.json](./001-replayable-live.json)。
>
> 状态：第五节读数已出，**结局提议：火莲**；待 cz 第六节裁决。

## 一、识火

| 栏 | 内容 |
| --- | --- |
| 出处 | 常见编码智能体的终端与网页界面：执行时滚动显示工具调用、命令输出与模型的自述（2026 年 11 月所见） |
| 现象 | 人能实时看到智能体在干什么 |
| 我们缺什么 | 开放道执行中图台空白，cz 2026-11-20 实测“什么进度也看不到”。#115 补上了实时面板 |
| 是否异火 | 是。“执行过程的实时表面”是一类做法，不绑定某一家 |

## 二、萃意

- **火意**：执行的每一步在发生时就对人可见。
- **前提**：原系统的流直接来自工具进程，没有独立的记录者。
- **代价**：流是易失的，事后看不到“当时看到了什么”；流里可能带出凭据；叙述与工具输出混排，人容易把叙述读成证据。
- **与本火的重叠**：T4 的 `as_of` 回放能还原任一时刻的图，但只到事件粒度，看不到会话内部；四语域要求每段内容只属于一个语域。
- **冲突**：T2（凭据）、T5（叙述与证据混排）。
- **融合假设**：实时所见的每一行，事后能逐字节回放出来；凡是一次执行的那一行，能点进对应的执行留档。
- **守门性质拆分**：无。不新增出站、不新增证据类别、不新增席位。活动段登记为 authored 类，永不作依据。
- **遮住出处还成立吗**：成立。设计里没有任何一处依赖原系统的实现；用到的只是我们自己的 `register_artifact`、authored 类与 `as_of`。

## 三、入位

| 栏 | 内容 |
| --- | --- |
| 火位 | H6 观察面（主）；H4 上下文（入账段作为事件账里的 Artifact） |
| 席位 | 不涉及（不是 H1） |
| 经脉 | M1 提议（适配层用已有令牌 `register_artifact` 登记 authored 类）；M4 读（`as_of` 回放、读执行留档） |
| 清单草稿 | `h6.activity-ledger`，`lineage.from = h6.activity`（#115）；见 JSON 的 `fire` |
| 入库四问 | 感知官；退役信号：面板打开率低于 5%（〔占位〕）；启用条件：开放道常开，严格道按开关、缺省关；对照臂：A′ |
| 替换谁 | 替换 `h6.activity`；`h6.activity` 留作对照臂（`ledger_roles=()` 即 A′ 原样） |
| 预登记读数 | [05 §1.4](../05-cases.md#14-预登记读数草稿)，两个占位值由 cz 2026-11-20 定为：入账间隔 30 秒、每题入账事件上限 200 条（超出改为只在每轮结束与收尾时入账） |

### 合火 F 的三处改动（实现）

| # | 改动 | 代码 |
| --- | --- | --- |
| 1 | **条目成链**：每条条目带序号 `n` 与哈希 `h`，`h_n = sha256(h_{n-1} ‖ JCS(条目去掉 h))`，起点是 64 个 0。凭据遮盖在成链之前做 | `adapter/…/activity.py` 的 `item_hash`、`ActivityLog.feed` |
| 2 | **分段入账**：锚点是每次 exec 返回、每轮结束、距上次入账满 30 秒、会话收尾（赶在释放租约之前）。每段是一份 JCS 文档 `{v, kind, lease, first, last, prev, head, items}`，用已有的 `register_artifact` 登记为 authored 类，媒体类型 `application/vnd.paoding.activity-segment+json`，`parents` 指上一段。回放时逐段校验 `prev`、序号连续、每条哈希、`last` 与 `head`，任一处不对整体报 `ChainBroken`，不给部分结果 | `ActivityLog.segment`、`replay_segments`；`session.py` 的 `_maybe_anchor`、`_anchor`、`ledger_items` |
| 3 | **执行行可点**：exec 的结果条目带执行层返回的 ArtifactId（只认 exec 调用，其他工具返回里的 `artifact` 字样不算）；界面上这一行有“看执行记录”，打开证据抽屉；自述行不可点。在途时尚未入账的条目标“未入账” | `activity.py` 的 `_artifact_of`；`web/src/ui/SessionActivity.tsx` |

读端：`GET /v1/leases/{id}/activity?after=N&as_of=<seq>`。给 `as_of` 时只从事件账里该 seq 及之前登记的段重建，`status` 为 `replay`、不轮询；链校验不过回 409 `chain_broken`。不给时照 #115 读实时流水，另给 `anchored_through`（已入账到第几条；`null` 表示这个会话不入账）。会话目录被清掉后，结束了的会话从事件账读回。工作台的时间轴拨到某个 seq，会话活动面板就是那一刻已入账的内容。

## 四、验体

### 4.1 体质改动行数：0

本次改动的文件只在适配层的活动流水与会话编排（`adapter/…/activity.py`、`session.py`、`contract.py` 的一行再导出）、组装根 `scripts/stack.py` 与前端。[01 §3](../01-boundary.md#3-体质五项) 列出的强制点（`judgebox/`、`qicao/vet.py`、`graph/`、`executor/`、`watchdog/`、`adapter/…/proxy.py`、`keyring.py`、`creds.py`）一行未动：

```
git diff --numstat origin/main -- judgebox qicao/src graph executor watchdog \
  adapter/src/paoding_adapter/proxy.py adapter/src/paoding_adapter/keyring.py \
  adapter/src/paoding_adapter/creds.py     # 空
```

不新增事件种类，不加事件字段，不新增席位，不动 reducer。`register_artifact` 的事件体仍是今天的形状。

### 4.2 静态验体

| 检 | 结果 |
| --- | --- |
| 清单形状 | 清单见 JSON。火位立名（F2）之前没有清单校验器，本档的清单按 [01 §8](../01-boundary.md#8-一团火的数据形状) 手写 |
| 经脉越界 | 只用 M1（适配层席位本来就能登记 authored 类）与 M4 |
| 依赖方向 | `ci/check_deps.py` 过：适配层只 import `paoding_graph.contract` |
| 体质内部不可达 | 不 import 事件日志、钥匙环、闸门内部；不开网络套接字 |
| 领域词 | `ci/check_domain_words.py` 过 |
| 入库四问 | 四栏非空；感知官，不是守门官 |
| 资产寻址 | 这团火没有资产文件 |

### 4.3 动态验体（体质试炼，F1 的 `tests/fenjue/trials.py`）

| 体质 | 结果与依据 |
| --- | --- |
| T1 判 | 试炼 T1 组全过。活动段是 authored 类，不进交付引用，不碰判官路径 |
| T2 闸 | 试炼 T2 组全过；新增 `test_what_was_seen_live_replays_byte_for_byte` 断言原话里的令牌不出现在任何入账段里 |
| T3 顶 | 试炼 T3 组全过。入账不调模型，不经端点代理 |
| T4 账 | 八份按道冻结的黄金日志逐字节回放（`tests/fenjue/test_t4_zhang.py`）全过；严格道席位不在 `ledger_roles` 里，严格道的事件日志与 main 相同 |
| T5 证 | 试炼 T5 组全过；新增断言：入账段只用 authored 类、`producer.session` 是这个会话 |

全量 `pytest`：1317 过、72 跳过；前端 `vitest` 196 过、lint 与类型检查过（本 PR 的 CI 复跑）。

## 五、融火

### 5.1 五臂

| 臂 | 是什么 | 怎么得到 |
| --- | --- | --- |
| B | 本火：#115 之前，无实时性 | 构造 |
| A′ | 异火单炼：#115 原样 | 同一测试台 `ledger_roles=()`（`test_without_the_ledger_nothing_is_registered`） |
| F | 合火：本 PR | 缺省配置 |
| B′ | 同火对照：main 重跑 | 结构读数是确定性的，同一剧本跑两遍逐字节相同，噪声底为 0 |

### 5.2 读数

剧本：假 CLI 走真的端点代理、真的工具端点、真的图服务，两次 exec 加一次交付（`adapter/tests/test_activity_ledger.py` 的 `SCRIPT`）。

| 维 | 类 | 方向 | B | A′ | F | 门槛 | 依据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 实时所见可回放率 | 新生 | ↑ | 0 | 0 | **100%**（3/3 个锚点） | 100% | `test_what_was_seen_live_replays_byte_for_byte` |
| 活动链校验 | 新生 | ↑ | 0 | 0 | **100%**（改一个字、换次序、丢一段、塞坏段，4/4 报错） | 100% | `test_tampering_is_always_caught` |
| 执行行可追率 | 新生 | ↑ | 0 | 0 | **100%**（2/2 个 exec 行点到 exec 类留档） | 100% | 同上；`test_only_exec_results_carry_an_artifact` |
| 执行到可见的延迟 | 异火 | ↓ | 会话结束 | 约 3 秒（轮询） | 约 3 秒（轮询不变） | ≤ A′ + 噪声底 | 前端轮询间隔未改 |
| 凭据泄漏数（活动、入账段） | 本火 | ↓ | 0 | 0 | 0 | 0 | 同上 |
| 旧日志逐字节回放 | 本火 | — | 过 | 过 | 过 | 过 | `tests/fenjue/test_t4_zhang.py` |
| 严格道事件日志不变 | 本火 | — | — | — | 相同 | 相同 | 严格道席位不入账；全量测试里严格道的事件断言不变 |
| 每次交付花费、墙钟 | 共有 | ↓ | x | x | 同 A′（入账不调模型） | ≤ max(B, A′) + 噪声底 | 假 CLI；真模型的运行读数待 cz 跑 |
| 每题新增事件数 | 共有 | ↓ | 0 | 0 | 本剧本 +3 条（14 对 11） | ≤ 200 条 | 测试台实测 |
| 入账段 Blob 字节数 | 共有 | ↓ | 0 | 0 | 本剧本 2543 字节（3 段） | 〔占位〕 | 测试台实测 |

另有两条构造性质，各有一条测试：会话目录按期清掉之后，活动仍能从事件账读回（`test_the_ledger_outlives_the_session_directory`）；每题上限设为 0 时，只剩每轮结束与收尾那一两段，收尾后全部入账（`test_cap_leaves_only_round_ends_and_the_closing_anchor`）。

### 5.3 结局提议：火莲

三条新生维从 B 与 A′ 的 0（构造）到 F 的 100%，是两源都没有的性质；本火维无一退步；异火维与 A′ 持平；共有维里花费不变，事件数与字节数在上限之内。按 [03 §3](../03-huolian.md#3-四种结局) 判火莲。

品阶提议：第 2 阶，即 [04 §2](../04-evolution.md#2-品阶) 品阶表里预留给本档的那一行。首炼先于 F2（FJ14），所以本档裁决后先记在本档与 JSON 里；F2 合入时第 1 阶（立名）与第 2 阶依次入表，F3 之后品阶随功法摘要进开题事件。

### 5.4 炼档度量

| 量 | 值 |
| --- | --- |
| 炼化周期 | 0 天（识火 2026-11-20，读数 2026-11-20） |
| 体质改动行数 | **0** |
| 火位改动面 | 2 个火位（H6、H4）；适配层 3 个文件、组装根 1 个、前端 5 个（含假后端），测试 2 个 |
| 试火花费 | 0（全部是假 CLI 上的结构读数） |
| 结局 | 火莲（提议） |
| 散火次数 | 0 |

### 5.5 散火

`AdapterConfig.ledger_roles = ()` 即指回 `h6.activity`（A′）：不再登记任何段，面板照旧能读，只是不标已入账；已经登记的段留在账上，回放照旧可读。F2 之后这个开关挂到 H6 火位的设置上。

## 六、裁决

待 cz。

## 七、散火记录

无。
