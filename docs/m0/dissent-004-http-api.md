# 异议报告 004：HTTP 绑定落地时发现的规格缝隙

> 日期：2026-11-17｜对象：HMI v1.1 §2、§3.4、§3.6、§11、§13；规格 v1.3 §3.1.2、§3.2.2｜状态：待裁决
> 性质：都是端点形状与取值层面的缝隙，没有改架构。实现先按下面“现行取值”落地，裁决不同再改。

| # | 缝隙 | 现行取值 | 请裁决 |
| --- | --- | --- | --- |
| 1 | HMI §11.2 没有读判官注册表的端点，但 §3.2 的向导第 2 步要“从判官注册表里选 Goal 判官”，§3.2 的画像预览要能“指到具体的判官条目”。`/v1/templates` 说的是锦囊与配置目录，不是注册表本身 | 新增只读的 `GET /v1/judges`（`judge_id、version、grade、kind、max_cost` 与外部资源种类表） | 是否收进 §11.2；或并入 `/v1/templates` |
| 2 | `POST /v1/problems` 只写了“open_problem”，没有请求体。开题要先登记 input 类材料，Origin 才有东西可引 | `{id, idem_key, ops}`：若干条 input 类 `register_artifact` 加最后一条 `open_problem`，批内引用 `"$<下标>"`，整批原子。与 `pd problem open` 发出的批次逐字段相同 | 确认，或改成专门的开题请求体 |
| 3 | 读端点要不要令牌没有写。§13.3 说 M1“端口不对外；跨源请求一律拒绝”；SSE 的 `EventSource` 带不了 `Authorization` 头 | 读不要令牌；靠三条挡：只监听回环、`Host` 须为回环名（防 DNS 重绑定）、非同源的 `Origin` 一律 403（开发服务器走显式白名单）。写一律要令牌 | 确认 M1 形态；M4 多用户时读也要令牌，届时 SSE 的鉴权方式要另定 |
| 4 | H2 的 `seen {seq, card_hash}` 与 `stale_view` 属 M1，内核尚未实现；但 F2 的审批卡要绑定 `card_hash` | 只落投影：`/cards/approval｜closeout` 返回参考模型的卡片与 `card_hash`。写入侧 `approve` 暂不带 `seen`，内核不校验 | 是否把 `seen` 校验提前到 M0 末；不提前则网页审批与 `pd approve` 在 M0 的保护相同（都没有先查后用） |
| 5 | 四语域表（§3.4）没有列 `goal.statement` 与题名。前者是开题人写的文字，不是 Artifact | `goal.statement` 取“人”；题名沿用 `pd` 已有的做法取“叙述” | 确认，或都取“人” |
| 6 | H4 暴露关联的定义是“任务包含该 Hint 的 Reason 会话”。任务包留档在 authored 类 Artifact 里，要解析包内容才知道含哪些 Hint；投影层不读 Blob | 近似为：Hint 之后签发、且签发时 Hint 尚未关闭的 Reason 租约。M0 任务包对未关闭的 Hint 全量带入，所以两者等价 | 确认；任务包改成按节点筛 Hint（M1）时，要么把 `focus.hints` 记进租约事件，要么让投影读包 |
| 7 | §13.2 的补发阈值写“例如 5000 条”，快照帧的形状没写 | 阈值 5000，可配；快照帧 `event: snapshot`，`id` 为快照的 seq，`data` 为 `{as_of, skipped_after, status, budget}` | 确认形状 |
| 8 | H1“r2 缺回退时禁用批准”依赖 `rollback` 字段，内核 M0 拒收该字段（M4）。照字面做，M0 的 r2 Intent 在网页上永远批不了，而 `pd approve` 可以 | 卡面给 `rollback_declared`，M0 不禁用批准（与 `pd` 一致，pd/SPEC.md 已写明随 M4） | 确认 |
| 9 | `main` 重新初始化后只带到 #12 的内容，#13–#18 关闭而未合并；`status.md` 与 kickoff 都按“已评审通过”引用它们 | 把 #18 头部的组件代码原样搬回，另开一个恢复 PR 作为后续各 PR 的基底；措辞按 main 现行口径改过 | 确认恢复 PR 可直接合入，不需要逐个重审 |
