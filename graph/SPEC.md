# graph/：契约 1 解牛图服务 + 契约 2 Artifact 仓库 + 契约 5 预算账本投影

规格：v1.3 §3.1、§3.2、§3.5；不变量 I1、I3、I4、I7、I8。

## 实现的契约接口

- 事件信封 `Event`（§3.1.2），JCS（RFC 8785）规范化，按题哈希链 `prev_hash → hash`。
- 内核函数 `validate(state, actor, op)` 与 `apply(state, event)`：纯函数，不读时钟、不做 IO、不调用模型（I1）。
- 等级函数、消费门、Intent 状态：**从参考模型搬运，不重写**（`src/paoding_graph/refmodel.py` 是 `docs/design/reference-model/kernel.py` 的逐字节副本，CI 比对）。参考模型与规格不一致时以规格为准，并写异议报告。
- 端点（M0 走本机 Unix socket）：§3.1.2 端点表与 §3.2.2 Blob/Artifact 端点。
- Blob 仓库：本地目录按 sha256 寻址，写入不可变，读取校验哈希（`corrupt`）。
- 对外契约（`paoding_graph.contract`）：事件信封、拒绝码、Artifact/Check/VaultRef 类型、客户端。

## 官的声明（附录 B 三类制）

| 结构 | 官 | 标签 | 启用条件 | 退役信号 / 长存依据 |
| --- | --- | --- | --- | --- |
| 事件日志 + 确定性裁决 | 守门官 | T-0 | 常开 | 会话必死，跨会话的持久是系统的定义 |
| 出处类别与可采信检查 | 守门官 | T-0 | 常开 | 达成与否必须独立于模型自述（红线 2） |
| 画像推导 | 守门官 | T-0 | 常开（人可覆盖） | 授权与不可逆性由人和环境决定 |
| 估值不进等级（I8） | 守门官 | T-0 | 常开 | 估计不是事实；性质测试常驻 CI |
| 三层视图（`view?layer=`） | 感知官 | T-1 | 常开；开关 `view=full_dump` | 满量导出与下钻版解题率差 ≤1 题且成本不升 |
| 账本投影、归因记录 | 量具 | T-0 | 常开 | 永不退役，也永不守门 |

## HTTP 绑定（HMI §11 方案 A；`httpapi.py`、`views.py`）

启动：`uv run python -m paoding_graph.httpapi --home .paoding --port 8787 [--static web/dist] [--allow-origin http://localhost:5173]`。只监听 `127.0.0.1`；人的令牌写在 `<home>/human.token`。

**约定。**

- 读是 GET，全部是状态的纯函数（`views.py`，进 I1 的 AST 纯度检查）。每个视图端点可带 `as_of=<seq>`，由唯一的 reducer 重放得到（`GraphService.state_at`，不另写解释器）。应答外壳：`{as_of, head, view_hash, …视图}`，`view_hash = sha256(JCS(视图))`；加 `state_hash=1` 另给该序号的状态哈希。
- 写是 POST，全部落到 `GraphService.submit`，与 `pd` 同一条提议通道。身份只来自 `Authorization: Bearer <令牌>`；没有令牌 401，未知令牌 403，都不进日志。写操作带 `idem_key`。
- 错误体：`{ok:false, code, detail}`。`unknown_ref` 404，`schema_error` 400，`forbidden_op` 401/403，后续里程碑的端点 404 `not_enabled`。一批提议被内核拒绝仍是 200，逐条结果在 `results` 里。
- 服务端自己的缺陷是 500 `{ok:false, code:"internal", detail:<异常类名>}`，栈打到标准错误；不再把 `KeyError`、`TypeError`、`ValueError` 一律说成 400 `schema_error`（审计 P1-4）。分发处只认 `HttpError`、`views.NotFound`、`views.NotEnabled` 与解析层的 `BadBody`。
- 四语域：凡文字内容都是 `{src, register, value}`，`register` 由 `src`（出处类别）查 `views.REGISTER` 得到，取值 `证据｜叙述｜人｜估`。结构字段（id、等级、状态、账目）恒属证据。`pd` 的行首标记读同一张表。
- 只对本机：`Host` 不是回环名拒绝；带 `Origin` 且非同源的请求一律 403，除非在 `--allow-origin` 白名单。读端点不要令牌（M1 本机单用户；`EventSource` 也带不了头）。
- 排序只用创建 seq；时间只取事件 `ts`。
- 访问日志缺省关（`HttpConfig.access_log`）。打开后每个请求向 `logging` 的 `http` 记一条：方法、路径、状态码、耗时、字节数、对端地址；不记查询串、请求头与请求体。

**端点。**

| 端点 | 说明 |
| --- | --- |
| `GET /v1/health` | `{ok, head, api}` |
| `GET /healthz` | 运维探针（不带版本前缀）：`{ok, status: ok｜degraded, api, components{名: {ok, …}}}`，全部正常 200，否则 503。`graph`（链头、题数）与 `blobs`（目录可写）由本组件给；其余组件的状态由组装根经 `HttpConfig.health` 给。不要令牌，不含题目内容；说明见 `docs/ops.md` |
| `GET /v1/problems` | `items[]`：`id、title、closed、terminal、terminal_badge、profile、opened_seq、opened_ts、closed_seq、spent_usd_milli、cap_usd_milli`；`totals`：题数、solved 数、总花费、每解成本 |
| `GET /v1/problems/{pid}/status` | `problem`（画像、推出值与覆盖、scope、env、终态）、`goal{statement, accept, predicate}`、`facts[]`、`intents[]`、`hints[]`、`leases[]`、`requests[]`、`review`、`closeout` |
| `GET /v1/problems/{pid}/view?layer=title｜summary&after_seq=&limit=` | 按创建顺序的节点清单，`next_after_seq` 为游标；`frontier`（活跃 Hint、待人处理、未结束 Intent 及其前提、未到终态的论断）。`layer=full` 需服务端开 `view_full_dump` |
| `GET /v1/problems/{pid}/budget` | 账本投影：`cap、spent、reserved、by_kind、verify_spent、marks、mark_seqs、mark_lines、percent、wall、review` |
| `GET /v1/problems/{pid}/work` | `items[]`：`bootstrap｜reason｜explore｜judge｜rejudge｜human` |
| `GET /v1/nodes/{id}?layer=title｜summary｜evidence` | 论断、Intent 或 Hint。`evidence` 层的论断带 `grounds[{id,class,register,hash,size}]`、`no_evidence_root`、`body_ref` |
| `GET /v1/problems/{pid}/invalidations?node=` | `invalidated[]`（参考模型的搬运函数） |
| `GET /v1/problems/{pid}/events?after=&limit=&wait=` | 审计日志。有新事件立刻返回，否则最多等 `wait` 秒（上限 30）；带 `as_of` 时只读到该序号、不等 |
| `GET /v1/problems/{pid}/stream` | SSE。每帧 `id: <seq>`、`data: <事件>`（无 `event` 名，`onmessage` 直接收）；游标取 `Last-Event-ID` 或 `?after=`，都没有则从链头之后；落后超过 5000 条先发一帧 `event: snapshot`（`{as_of, status, budget}`）再续流；空闲时发注释心跳 |
| `GET /v1/problems/{pid}/cards/{kind}/{id}` | `{card, card_hash, display}`。人的决策操作带的 `seen.card_hash` 取自这里（不带 `as_of`）。`approval`（id 为 Intent）与 `closeout`（id 为题目 id）；`extension`、`dispute` 随 M1。`card` 与 `card_hash` 出自参考模型，估值不在卡面里 |
| `GET /v1/hints/{hid}/trace` | `temporal{added, abandoned}` 与 `exposure{sessions, added, abandoned}` 两列 |
| `GET /v1/artifacts/{id}`、`GET /v1/blobs/{hash}[?range=起-止]` | 登记记录（带 `register`）；字节一律 `attachment` + `nosniff`，读取时校验哈希，坏了返回 500 `corrupt` |
| `GET /v1/judges`、`/v1/templates`、`/v1/renderers` | 判官注册表；配置目录里的条目（带内容哈希，纯数据） |
| `POST /v1/profile/preview` | `{scope, goal.check.judge_id}` → `{profile, basis}`，与开题同一个推导函数，不写日志 |
| `PUT /v1/blobs` | 字节 → `{hash, size}` |
| `POST /v1/problems` | `{id, idem_key, ops}`：若干条 input 类 `register_artifact` 加最后一条 `open_problem`，Origin 用 `"$<下标>"` 指向前面的材料 |
| `POST /v1/problems/{pid}/proposals` | `{idem_key, ops[]}` → `{ok, results[]}`，整批原子 |
| `POST /v1/problems/{pid}/leases`、`/v1/leases/{id}/renew｜release`、`POST /v1/artifacts` | 组件用：201 / 409。与其它写操作一样必须带 `idem_key`（或 `Idempotency-Key` 头），缺了返回 400 `schema_error`，服务端不代为生成 |

节点形状（`status`、`view`、`nodes` 共用）：

- 论断：`id、type:"fact"、seq、claim_type、level、level_word、unstable、disputed、stale、title、summary、premises、yielded_by、session、predicate、grounds`。
- Intent：`id、type:"intent"、seq、status、risk、level、title、summary、premises、budget、needs_scope、gate、approvals、attempts、predicate、decision、expected_gain`（估值单独成字段，语域为“估”）。
- 判据卡 `predicate`（Goal、带判据的 Intent、观察类论断同形）：`target、judge_id、version、grade、label（judge@version）、spec_ref、spec_hash、expect、max_attempts、attempts_used、level、level_word、fail_means（refuted｜not_yet）、verdicts[]`。

**官类。** 只读投影是感知官的数据面（T-1；`view_full_dump` 开关），卡片投影与 `card_hash` 属守门官，账本投影是量具。

## 依赖

不依赖任何其它组件。其它组件经 `paoding_graph.contract` 与本机 socket 访问它。

## 类型与异常的去向（审计 P1-4）

- `state.py`：reducer 状态与事件的类型（`Problem`、`Fact`、`Intent`、`Lease`、`Verdict`＝M0 的 `Support` 等），全部是 `TypedDict`。运行时仍是普通 dict，状态哈希、重放、序列化不变。
- `parse.py`：未经校验的提议体只经 `Obj` 读；字段缺失、类型不对抛 `BadBody`。`reducer.validate` 只接 `BadBody` 与 `JCSError`（提议体里不能规范化的值）并转成 `schema_error`。校验函数其余部分抛出的异常是内核缺陷，原样暴露。
- CI：`ruff check`（含 BLE，不许宽接 `Exception`）、`ruff format --check`、`mypy --strict`（`graph/src/paoding_graph` 全部；`refmodel.py` 是参考模型的逐字节副本，不检查、不改）。
- 性质测试：`tests/test_malformed.py`（随机坏提议体，`validate` 不抛错、通过的事件体能落盘）、`tests/test_http_errors.py`（随机坏请求不出 500；注入的缺陷是 500 不是 400）。

## 实现取值（规格未定、在此钉死）

- 哈希链创世值：每题第一条事件的 `prev_hash` 为 64 个 `0`。
- 日志表只追加：SQLite 触发器拒绝 UPDATE 与 DELETE；`(problem_id, idem_key)` 唯一，重放返回首次事件。
- 状态哈希：`sha256(JCS(state))`，reducer 的状态必须是 JSON 值。
- Blob 写入后文件权限置只读；range 读取也先校验全文哈希。
- 新对象 id 由事件 seq 派生：`a_<seq>`、`f_<seq>`、`i_<seq>`、`j_<seq>`。
- `validate` 返回规范化事件体，含派生字段（画像、判官快照 `judge_snapshot`、`producer`、内容键）；cfg（判官注册表等）只在 validate 时读，重放不依赖它。
- 判官裁决的 `grade` 取开题时的判官快照，不取裁决方自报。
- `request_judge` 的判官必须是登记判据时的那一个（I4 判据先行的字面推论）；推断类论断在 M0 没有判据，不能请求判定。
- `input` 类 Artifact 可以在 `open_problem` 之前登记（Origin 要引用它们）；其它类别要求题目已开。
- M0 拒绝 `accept=human`、`check.control`、`done.tests` 与 `follows`/`executor`/`rollback`/`delegate`，返回 `schema_error`，待对应里程碑启用。
- Blob 是否存在由服务层在 validate 之前检查（IO 不进内核）。
- `validate` 多一个参数 `ts`：这条事件将被赋予的时间戳，由服务层的时钟给出；过期判断（`expire_lease`、`renew`）用它，reducer 仍不读时钟。租约的 `expires_at = ts + ttl_s × 1000` 在 apply 里由事件 ts 算出。
- Intent 的完整状态 = 参考模型的资格状态（achieved/abandoned/needs_human/blocked/open）叠加租约生命周期（leased、done）。失败（failed、nothing、budget_exhausted、过期；带判据的 Intent 释放后判据未过且无未决判定）累计 2 次即 abandoned（§3.4.4“两次后放弃”）。r2 失败或过期后转 needs_human。
- 被拒的批次也记下结果：同一 idem_key 重放返回首次结果，无论首次是否被拒。批内用 `"$<下标>"` 引用前一条产生的 id。
- **调用方惯例：改正后重交必须换新的 idem_key。** 被拒结果同样被缓存，拿原 idem_key 重交改正过的内容，只会原样拿回首次的拒绝，改正不会生效。idem_key 只用于"同一请求的重试"（网络超时、进程重启后重发同一批）。Adapter 的做法：每次工具调用生成新键（`submit:<租约>:<宿主实例号>:<调用序号>:<条目序号>`），会话内改正自然换键；重试同一调用才复用。
- 图服务自己追加的事件（`budget_mark`、Goal 到 E3 时的自动 `close_problem`）由 `work.followups` 纯函数算出，与触发它的批次在同一事务里落盘。
- 关题后只接受在途任务的交回：`cost`、`release`，以及会话令牌对自己留档的登记（`register_artifact`，限 authored 类，且令牌的会话是本题一条仍在途的租约）。题目常常是被会话自己提交的候选关掉的，判官一通过图服务立刻关题，此时会话还没交回留档；不放行这一步，会话收尾失败，租约就一直不释放。关题后的 `release` 带的 `transcript_ref` 照样挂到租约上。关题即视所有租约结束。
- 跨题隔离（I7 的推广）：凡是带引用的操作，引用指向别题的对象一律 `scope_mismatch`（引用不存在才是 `unknown_ref`）。这包括 `renew`/`release` 的租约（关题前后都查归属、持有者与在途）、`hint.about`、任务令牌的会话（会话即租约 id，只在租约所属的题内有效）。Goal 的候选次数按题计数。`graph/tests/test_isolation.py` 的性质测试常驻 CI：两题事件随机交错，每题的切片与派生视图等于只重放本题事件的结果。
- 判官运行器的令牌按身份种类放行续租与释放，但只限 judge 租约；任务租约只认持有者或该租约的会话令牌。
- 服务层（`service.py`）用一把可重入锁串行化提交与日志读取；新事件落盘后唤醒长轮询与事件流。`state_at(seq)` 的回放缓存永不失效（日志只追加、apply 纯函数）。
- 人的决定绑定所见（§3.1.9、HMI H2）：`approve`（批准与拒绝）必须带 `seen {seq, card_hash}`。内核 `validate` 在提交那一刻的状态上重算审批卡（`cards.card_object`，与 `/cards` 端点同一个函数），哈希不等返回 `stale_view`，服务层在该条结果的 `card` 里附上链头的最新卡片（形状同 `/cards` 端点，另带 `as_of`）。`seen.seq` 只留作审计，随事件体落盘。校验先于状态检查。人提交的 `close_problem` 带了 `seen` 就按四顾清单卡校验，校验过的哈希记进事件的 `card_hash`；不再接受不经校验的裸 `card_hash`。`accept`、`rule`、`extend` 三个操作内核还没有，见异议报告 `docs/m0/dissent-p0-5-seen-binding.md`。
- 目标陈述（`goal.statement`）的语域取“人”（开题人写下的文字）；规格的四语域表没有列这一项，见异议报告 004。
- 四顾清单：r0 且 `accept=judge` 的题恒为空（M0 形态）；r1/r2 题先给一条占位项，阻止自动关题，完整清单随 M4。

## 进度

| 日 | 内容 | 验收 |
| --- | --- | --- |
| D1（预备） | `jcs.py`、`envelope.py`、`eventlog.py`、`replay.py`、`blobs.py` | 3.1.5 的 1；3.2.5 的 1、4；RFC 8785 附录 B 向量 |
| D2（预备） | `reducer.py`（六种操作）、`levels.py`、`refmodel.py`（逐字节副本）、`tokens.py` | 迟滞（一败回 E0、两败为 X）；3.1.5 的 4（M0 形态）、6、8、9；3.2.5 的 2 前四种 |
| D8/D9 reducer 侧（预备） | 租约四操作、`/work`、Intent 完整状态、审批、Hint、放弃、用量、关题与终态、`budget_mark`；`work.py`；`service.py`（整批原子、幂等、自动追加、崩溃恢复） | 3.1.5 的 2、3（M0 形态）、5、7、9、15；3.3.5 的 7；3.4.5 的 3、6；3.5.5 的 1、2、5 |
| HTTP 绑定 | `httpapi.py`、`views.py`、`service.state_at`；`pd` 与网页共用四语域表 | 3.1.5 的 18（回放）、5（HTTP 形态）；3.2.5 的 2、4（HTTP 形态）；HT-2、3、5、6、10、16、17；§13.1 第 5 条、§13.3 |
