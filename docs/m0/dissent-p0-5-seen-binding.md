# 异议报告 P0-5：把 `seen` 校验落进内核时遇到的规格缝隙

> 日期：2026-11-18｜对象：规格 v1.3 §3.1.9、HMI v1.1 §3.5、§11.3；质量提升第一阶段 P0-5｜状态：待裁决
> 性质：操作集合与取值层面的缝隙，没有改架构。实现先按“现行取值”落地，裁决不同再改。本报告同时了结异议 004 第 4 条。

| # | 缝隙 | 现行取值 | 请裁决 |
| --- | --- | --- | --- |
| 1 | P0-5 要求在 `approve`、`deny`、`accept`、`rule` 上校验 `seen.card_hash`。内核里 `deny` 是 `approve` 的一个取值，已覆盖；`accept`（M4）、`rule`（M1）、`extend`（M1）三个操作内核还不存在，对应的 extension、dispute 卡也没有投影 | `approve`（两种取值）必须带 `seen`，不等即 `stale_view`。校验写成通用的 `_seen(state, pid, 卡种, 目标, body)`，后三个操作落地时各加一行调用即可。没有为了校验去提前实现这三个操作 | 确认；或要求本阶段就把 `rule`、`accept` 的操作本身提前 |
| 2 | M0 里人能做的终态决定只有 `close_problem`（带理由中止，或 r1/r2 题四顾清单非空时由人关题）。规格说验收走 `accept`、带收尾清单的 `seen`；`close_problem` 要不要带，没有写。现有事件体里有一个 `card_hash` 字段，人填什么就记什么，从不校验 | 人提交的 `close_problem`：带了 `seen` 就按 closeout 卡校验，校验过的哈希记进 `card_hash`；裸的 `card_hash` 改为拒收（`schema_error`）。不带 `seen` 仍然放行，因为网页与 `pd` 现在都没有四顾清单的确认流程，强制会让 r1/r2 题在 M0 关不了 | 四顾清单非空时是否强制 `seen`；强制的话网页的关题入口要先接上 closeout 卡 |
| 3 | 规格写“拒绝并附上最新的卡片”，没有写附在哪里、什么形状 | 被拒那一条结果多一个 `card` 字段，形状与 `GET /cards/{kind}/{id}` 相同（`card、card_hash、display`），另带 `as_of`。网页前端已按这个形状读（`ApiError.extra`）。卡片由服务层附上，内核的 `Reject` 只带卡的种类与目标，validate 不产出排版信息 | 确认形状 |
| 4 | 校验与其它检查的先后没有写。前提被证伪后 Intent 的状态也会变（不再是 `needs_human`），先查状态就会返回 `schema_error`，人看不到新卡 | `seen` 校验排在“Intent 存在、decision 取值合法”之后、状态检查之前。HT-7 的“注入反证后凭旧哈希批准被拒为 `stale_view`”因此成立 | 确认 |
| 5 | 被拒的批次按 idem_key 缓存（graph/SPEC.md 的调用方惯例）。`stale_view` 的结果连同当时的卡一起被缓存，拿原键重试会一直拿回旧卡 | 沿用惯例：看过新卡后重交必须换新键。网页每次提交生成新键；`pd` 的键含状态序号，卡片一变序号必变 | 确认 |
| 6 | 审批卡的范围取自参考模型的 `approval_card`：risk、预算、done、tests、needs_scope、rollback 与逐条前提的等级、disputed、unstable、stale、controlled、waived。规格 §3.1.9 的表另列“有效支持记录、判据来源、未决反证、与现有范围的差异及批准后的画像、r2 凭据名、所依赖封存的状态”，这些对象 M0 都还没有 | 不改参考模型，卡的范围随对应里程碑扩；题目范围在 M0 没有修订操作，所以现在不会出现“范围变了而卡不变” | 确认；范围修订操作落地时须同步把现有范围纳入卡片 |
