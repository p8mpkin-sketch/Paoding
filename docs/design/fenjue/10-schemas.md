# 10 数据形状：引擎与算法的 Schema

> 焚决设计 v0.2 的第十篇（待裁决）。机器可读的定义在 [`engine/schemas/`](./engine/schemas/)（JSON Schema 2020-12），本篇逐栏说明含义、谁写、怎么来。符合这些 Schema 的样例在 [`engine/examples/`](./engine/examples/)（三个验收用例的预期输出、组合夹具的候选清单、试算报告、交接包、异火榜首批条目），全部已按 Schema 校验通过。
>
> 实现线把这些 Schema 原样搬进 `paoding_fenjue`（校验器 V1 用它们），不另起一套。

## 1. 一览

| # | 形状 | 文件 | 谁产出 | 谁消费 | 在哪 |
| --- | --- | --- | --- | --- | --- |
| 2 | 公共定义 | `common.schema.json` | — | 全部 | — |
| 3 | 观察记录 | `observation.schema.json` | 读丹（经 `read_excerpt`） | 主丹、萃意、校验器 | 分析题工作区 `obs.jsonl` |
| 4 | 候选火清单 | `candidates.schema.json` | 识火 | cz（闸点 1）、萃意、异火榜 | authored 类 Artifact，交付 #1 |
| 5 | **火意** | `essence.schema.json` | 萃意 | cz（闸点 2）、入位、`lianhua.py import` | authored 类 Artifact，交付 #2 |
| 6 | 入位方案 | `placement.schema.json` | 入位 | cz（闸点 3）、实现线、`lianhua.py import` | authored 类 Artifact，交付 #3 |
| 7 | 立项单 | `intake.schema.json` | 界面（cz 新建分析） | 引擎 `intake` 工具 | input 类材料 |
| 8 | 试算报告 | `dry-run.schema.json` | 试算模式 | cz、异火榜 | authored 类 Artifact |
| 9 | 交接包 | `handoff.schema.json` | 闸点 3 之后 | 实现线、`lianhua.py import` | authored 类 Artifact，交付 #3 定稿 |
| 10 | 运行状态 | `run.schema.json` | 引擎形态（确定性） | 接力会话、校验器 | 分析题工作区 `run.json` |
| 11 | 异火榜 | `bang.schema.json` | `lianhua.py bang`（实现线） | 引擎（只读）、cz | 仓库 `docs/design/fenjue/yihuobang.json` |
| 12 | 闸点决定 | `decision.schema.json` | 决定块解析器 | 引擎形态 | 原文在 cz 的追问正文里 |

## 2. 公共定义

| 名 | 形状 | 说明 |
| --- | --- | --- |
| `slot` | `H1`…`H8` | 火位 |
| `kernelItem` | `T1`…`T5` | 体质项 |
| `port` | `M1`…`M7`，可带 `:操作` | 经脉，例 `M1:deliver` |
| `fireRef` / `fireId` | `h4.views-notes@1` / `h4.views-notes` | 火的 `id@ver` 与 id |
| `dimId` | `h4.compress` | 能力维（[08 附表 A](./08-algorithms.md#附表-a-能力剖面初值)） |
| `level` | 0–3 | 能力级 |
| `candId` / `obsId` / `bangId` / `dossierNo` | `C3` / `o` + 12 位十六进制 / `Y-007` / `001` | 编号；观察 id 是观察记录 JCS 的 sha256 前 12 位，所以同一条观察重跑得同一个 id |
| `mode` | `formal`、`dry_run`、`from_bang`、`replace` | 正式、试算、从异火榜取、重新入位 |
| `form` | `code`、`service`、`docs`、`description` | 外部系统的形态 |
| `tier` | `light`、`mid`、`heavy` | 丹的档位，由设置层的模型档案解析成具体模型 |
| `license` | `{status, spdx?, detected, reuse?}` | 许可证：`status` 取宽松、弱 copyleft、强 copyleft、专有、没找到（视为保留所有权利）、不明、服务条款、cz 的描述；`reuse` 是实现线的参考规则：只借思想或可参考原码（[12 §4](./12-handoff.md#4-许可证与出处)） |
| `snapshot` | `{id, form, identity, artifact?, size_tier?, license}` | 快照：`identity` 至少一项（归档 sha256、仓库加提交、探测计划 sha256、原话 sha256）；同一身份重跑勘察逐字节相同 |
| `evidenceRef` | `{snapshot, path?, lines?, probe_item?, sha256}` | 指向快照里一段原文；**原文不入产物**，只记位置与哈希，校验器 V3 按哈希核对 |
| `provenance` | `{snapshots, observations, source_label?}` | 出处：与遮蔽视图分开存；`source_label` 是给人看的来源说明，可以含外部专名，所以它不进遮蔽视图 |
| `checkResult` | `{id, ok, advisory?, detail?, override?}` | 一条检验的结果：`K1`–`K8`（萃意）或 `V1`–`V12`（校验器）；`override` 记 cz 在闸点坚持的修改 |
| `plainSummary` | ≤ 600 字 | 给人看的一段话，用常规技术词，不出现内部设计名词（V5） |

## 3. 观察记录 observation

读丹交回的结构化描述，原文的唯一替身。

| 栏 | 必填 | 含义 | 怎么来 |
| --- | --- | --- | --- |
| `id` | 是 | 观察 id | 记录 JCS 的 sha256 前 12 位 |
| `slot` | 是 | 火位 | 读计划给的问题模板所属火位 |
| `dims` | 否 | 涉及的剖面维 | 读丹从剖面维表里选 |
| `new_dims` | 否 | 剖面里没有的维 | 读丹写短名；主丹决定是否提“新维” |
| `kind` | 是 | 机制、外部行为、文档声称、配置、测试里写明的规格 | 读丹 |
| `statement` | 是 | ≤ 300 字，第三人称描述这段在做什么，用我们的词表 | 读丹；入库前过 K8 模式表 |
| `primitives` | 是 | 机制原语（[08 附表 B](./08-algorithms.md#附表-b-机制原语)） | 读丹 |
| `level_hint` | 否 | 外部在该维上的级的提示 | 读丹；最终级由主丹定 |
| `evidence` | 是 | 证据引用，≥ 1 | 工具面按读计划填，不由模型写 |
| `form` | 是 | 来自哪种形态 | 工具面 |
| `suspected_injection` | 是 | 疑似指令 | 确定性探测（[08 §4.4](./08-algorithms.md#44-对抗防护外部代码是数据不是指令) D6）或读丹，任一报即真 |
| `injection_note` | 否 | 疑似指令的类型 | 模式名或读丹的描述；**不复述指令原文** |
| `reader` | 否 | 读丹档位、定界 nonce 的 sha256、第几次读 | 工具面 |

## 4. 候选火清单 candidates

| 栏 | 必填 | 含义 |
| --- | --- | --- |
| `v`、`mode`、`run` | 是 | 版本、模式、分析实例里的题号 |
| `basis` | 是 | 对着哪套功法（品阶、摘要）、哪份剖面（sha256）、哪些快照算的；功法或剖面变了，这份清单的数字就要复算 |
| `candidates[]` | 是 | 见下表 |
| `already_have[]` | 是 | 已有不差：外部有、我们持平或更强的维，带我们的火与观察依据。证明扫过，也是诱饵检验（[11](./11-acceptance.md)） |
| `not_fire[]` | 是 | 普通需求：不是一种做法（只是一个按钮或配置项） |
| `unseen_slots[]` | 是 | 没见到相关机制的火位 |
| `coverage[]` | 是 | 逐火位覆盖报告：读了哪些模块、几段、多少 token、为什么停（预算、饱和、信号太弱、被立项的 `focus` 排除、预算截断）、最高分 |
| `checks[]` | 是 | 校验器结果 |
| `plain_summary` | 是 | 给人看的摘要 |

`candidates[]` 的每一项：

| 栏 | 必填 | 含义 | 怎么来 |
| --- | --- | --- | --- |
| `id`、`name`、`title` | 是 | 编号、短名（英文连字符，导入时作炼档短名）、标题（≤ 40 字） | 主丹 |
| `slot`、`also_slots` | 是、否 | 主火位与兼及火位（识火时的预判；入位后以入位方案为准） | 主丹 |
| `gaps[]` | 是 | 逐维差距：`dim`、`ours`（及 `ours_by`）、`theirs`、`gap`、`type`（缺维、更弱、新维）、`weight`、`pain` 与 `pain_basis`、`observations` | `ours`、`weight` 查剖面；`theirs` 主丹定；`gap`、`type` 按公式；`pain_basis` 必须是仓库文档锚点 |
| `value` | 是 | V = Σ w·gap·π | 公式 |
| `confidence`、`confidence_parts` | 是、否 | C = c₀ × cover × corro，按形态截断；拆项 | 公式 |
| `difficulty`、`difficulty_basis`、`difficulty_parts` | 是、否、否 | D（1–5）；识火时为预估，入位后重算；拆项 | 公式 |
| `risk` | 是 | R0–R3 | 按 [08 §3.7](./08-algorithms.md#37-差距价值置信难度) 的表 |
| `priority` | 是 | P = V·C ÷ (D·(1+R)) | 公式 |
| `dedupe` | 否 | 命中的异火榜条目或已有炼档 | 确定性比对 |
| `seed` | 是 | **炼档种子**：`name`、`title`、`identified`、`shihuo{source, phenomenon, gap, is_fire}`，与 `dossiers/TEMPLATE.json` 与 `lianhua.new()` 同形；`is_fire` 以“是”开头（`lianhua.new` 的要求） | 主丹写文字，形状由 Schema 定 |
| `provenance` | 是 | 出处 | 工具面 |
| `recommend` | 是 | 推荐、可选、不推荐，及一句理由 | 主丹；**推荐不是决定** |
| `flags` | 否 | 自指、来源有疑似指令、许可证受限、剖面过期、需要新火位、需要拆体质修炼 | 确定性 |

## 5. 火意 essence

萃意的产出，cz 要求字段级定义的那一份。分遮蔽视图 `masked` 与出处 `provenance` 两部分；K1–K8 只看 `masked`。

### 5.1 顶层

| 栏 | 必填 | 含义 |
| --- | --- | --- |
| `v` | 是 | 1 |
| `candidate` | 是 | 候选编号 |
| `masked` | 是 | 遮蔽视图，见 §5.2 |
| `provenance` | 是 | 出处（快照、观察 id、给人看的来源说明） |
| `field_refs` | 否 | 遮蔽视图的 JSON 指针 → 观察 id 列表。K5 要求前提、代价、冲突每一条至少挂一条 |
| `drafts` | 是 | 三稿互证：几稿（1–3）、选了哪稿、一致度（所选稿与另两稿的 Jaccard 之和，0–2）、分歧点 |
| `checks` | 是 | K1–K8 的结果（≥ 8 条；K6 带 `advisory: true`） |
| `human_edits` | 否 | cz 在闸点 2 的逐栏修改：JSON 指针、谁、哪天、追问事件的 seq |
| `plain_summary` | 是 | 给人看的摘要 |

### 5.2 遮蔽视图 `masked`

| 栏 | 必填 | 形状与限制 | 含义 | 渲染成 `lianhua` 的哪一栏 |
| --- | --- | --- | --- | --- |
| `statement` | 是 | 4–80 字 | 火意：一句话本质，不提实现 | `yi` |
| `mechanism[]` | 是 | 1–12 步；每步 `step`、`trigger`（≤120）、`input`（≤120）、`transform`（≤200）、`output`（≤120），可选 `invariant`（≤160）、`primitives`（≥1）、`features` | 机制骨架；名词只用机制原语、我们的词表与通用词；`features` 是冲突探针特征（[08 附表 C](./08-algorithms.md#附表-c-冲突探针)） | 不单独渲染（进 `engine.essence`） |
| `premises[]` | 是 | ≥ 1；每条 `id`（p1…）、`statement`、`holds_here`（成立、部分、不成立）、`why`，不成立或部分成立时 `replaced_by` 必填 | 原系统里它依赖什么才成立，在我们这里是否成立，不成立的用什么替代 | `premise` |
| `costs[]` | 是 | ≥ 1；每条 `id`（c1…）、`cost`、`kind`（时延、存储、安全、复杂度、可审计性、花费、人的注意力）、`here`（体质已付、会付、融合避免、不适用），可选 `kernel` | 原系统为它付了什么，在我们这里谁来付 | `cost` |
| `overlaps[]` | 是（可空） | 每条 `fire`（id@ver）、`dims`（≥1）、`relation`（重复、部分、互补），可选 `note` | 与本火的重叠，由能力维与剖面确定性算出 | `overlap` |
| `conflicts[]` | 是（可空） | 每条 `with`（T1–T5 或 id@ver）、`kind`（体质、语义、参数）、`statement`、`resolution`（融合化解、拆去体质修炼、替换、分区、参数化、不收），可选 `features`、`how` | 冲突与化解 | `conflict` |
| `fusion` | 是 | `statement`（4–300 字）、`emergent[]`、可选 `outcome_cap` | 融合假设与新生维 | `hypothesis` |
| `fusion.emergent[]` | 是（可空） | 每条 `dim`（≤40）、`why_zero_B`、`why_zero_A1`、`measure`（结构、运行）、`gate`，可选 `dir`、`how` | 新生维；两条“按构造为零”的理由必填；为空时 `outcome_cap` 只能是合炼 | 并入 `hypothesis` |
| `split[]` | 是（可空） | 每条 `part`、`kernel`、`to`（变更表草稿的去向） | 守门性质拆分；空表示无 | `split`（空时写“无”） |
| `implementations[]` | 是 | ≥ 2；每条 `sketch`、`primitives`（≥1）；两两的原语集合不全同 | 至少两种实现草图（K7） | 不单独渲染 |

`lianhua` 的第八栏 `masked`（“遮住出处还成立吗”）由检验结果生成：“机器检验 K1–K5、K7、K8 全过（K6 …）；闸点 2 由 cz 确认遮住出处成立”。渲染规则见 [12 §2.2](./12-handoff.md#22-萃意八栏的渲染规则)。

### 5.3 一份火意（节选自验收用例甲的预期）

```json
{
 "statement": "目标拆成有序阶段，每个阶段附上可核对的执行记录才算完成，后一阶段以前一阶段的确认为前提",
 "premises": [
  { "id": "p2", "statement": "阶段确认记录与检查输出放在同一处可改的存储里", "holds_here": "no",
    "why": "我们的执行留档按题哈希成链、活动条目成链入账，不可改",
    "replaced_by": "阶段完成点作为活动条目入链，引用执行留档的 ArtifactId" }
 ],
 "fusion": {
  "statement": "每个阶段的完成点在已入账的活动链上有确定位置，且紧前有它引用的执行留档；回放到任一完成点，看到的就是当时用来确认它的那条执行输出",
  "emergent": [
   { "dim": "阶段确认可回放率", "why_zero_B": "本火没有阶段，没有完成点可回放",
     "why_zero_A1": "照搬时阶段记录只在工作区文件里，不入事件账，回放不到", "measure": "structural", "gate": 1.0 }
  ],
  "outcome_cap": "huolian"
 }
}
```

全文见 [`engine/examples/case-a.expected.json`](./engine/examples/case-a.expected.json)。

## 6. 入位方案 placement

| 栏 | 必填 | 含义 | 对应 `lianhua.ruwei()` |
| --- | --- | --- | --- |
| `atoms[]` | 是 | 决策原子：`atom`（受控词表或 `other`）、`home`（H1–H8、T1–T5 或 none）、`mechanism_steps`、`params`、`owner_now`（今天拥有它的火）、`why_other` | 存进 `engine.placement` |
| `fire` | 是 | 清单草稿，[01 §8](./01-boundary.md#8-一团火的数据形状) 的 `Fire` 形状，`FIRE_KEYS` 齐全；可带 `seats`（H1）、`also_touches`；`lineage.dossier` 为空，导入时填档号 | `fire` |
| `group[]` | 是（可空） | 火组的其余成员，每个一份清单草稿 | 实现线扩展（[12 §2.3](./12-handoff.md#23-火组)） |
| `replaces` | 是（可空） | 被替换那团火的 id；必须也写在 `fire.lineage.from` 里（`lianhua.ruwei` 的要求） | `replaces` |
| `arms` | 是 | `B`、`A1`、`F`、`B1`，可选 `A0`；`A1` 做不出时写 `infeasible: 理由` | `arms` |
| `readings[]` | 是 | `dim`、`kind`（共有、本火、异火、新生）、`dir`，可选 `gate`、`test`、`run`、`mandatory`；新生维必有 `gate` | `readings` |
| `conflicts` | 是 | `fires[]`（火、原子、无冲突/参数/语义、化解、分区条件）、`kernel[]`、`candidates[]`（兼容、先后、依赖、互斥）、`slot_locks[]` | 存进 `engine.placement` |
| `steps[]` | 是 | 实现步骤：`n`、`do`、`slot`（或 `meter`）、`where`（组件与文件区，≥1）、`tests`、`kernel_lines`（恒为 0）、`accept` | 存进 `engine.placement`；设计 PR 里渲染成清单 |
| `kernel_forecast` | 是 | 体质影响预判，**必须为空数组** | — |
| `split[]` | 是（可空） | 拆去体质修炼的部分 | — |
| `new_slot` | 否 | 新火位提议（[08 §5.4](./08-algorithms.md#54-需要新火位)） | — |
| `difficulty` | 是 | 入位后重算的 D 与拆项 | — |
| `checks`、`plain_summary` | 是 | 校验器结果、给人看的摘要 | — |

## 7. 立项单 intake

| 栏 | 必填 | 含义 |
| --- | --- | --- |
| `mode` | 是 | 正式、试算、从异火榜取、重新入位 |
| `statement` | 是 | cz 的原话：想看这个系统的什么 |
| `sources[]` | 是 | 1–8 个来源：`no`、`form`、`via`（上传、资料库已有、仓库地址、服务地址、文档地址、就在原话里），按 `via` 带 `artifact`、`url`、`ref`（仓库必须给提交或标签，不抓漂移的默认分支）、`probe_plan`。**之后的扩权申请只能指向这里登记的来源** |
| `focus` | 否 | 只看这几个火位 |
| `max_candidates` | 否 | 候选上限 |
| `bang_entries` | 否 | 从哪几条榜上条目出发（`from_bang`、`replace`） |
| `requested_by`、`date` | 是 | — |
| `refused[]` | 否 | 拒收的来源与原因（拒收表命中：本机题库、校准目录等） |

## 8. 试算报告 dry-run

| 栏 | 必填 | 含义 |
| --- | --- | --- |
| `mode` | 是 | 恒为 `dry_run` |
| `candidates` | 是 | 完整的候选清单（同 §4） |
| `auto_picked` | 否 | 按 P 自动取的前 N 个 |
| `items[]` | 是 | 每个自动取的候选：火意单稿（遮蔽视图形状）、主火位、火组的火位、替换谁、冲突一句话、体质影响预判、难度、**可能的结局**（有望火莲、至多合炼、可能并火）及理由、K1–K5、K7、K8 的结果 |
| `not_placed[]` | 否 | 自动取了但**没有进入位**的候选：`candidate`、`kind`（`empty` 火意一栏都没有；`incomplete` 有内容但缺必填栏或类型不对）、`why`（缺什么、模型实际交回的顶层键）。只收结构这一类；九栏齐全而 K1 其余规则没过的照常在 `items[]` 里，由它的 `checks` 标着。没有就不写这一栏，旧产物照旧合法 |
| `estimate` | 是 | 正式走一遍的预估：按档位的 token、分钟，可选折算的预算 |
| `plain_summary` | 是 | 给人看的摘要 |

自洽：`auto_picked` 里的每个候选恰好出现在 `items[]` 或 `not_placed[]` 之一（引擎出报告时核对，问题记在 V11）。

与正式产出的区别：没有闸点决定、没有萃意三稿与盲审、没有实现步骤与预登记读数、不分配档号、不能导入炼档（[09 §3](./09-engine.md#3-试算模式)）。

## 9. 交接包 handoff

| 栏 | 必填 | 含义 |
| --- | --- | --- |
| `run`、`basis`、`decided_by`、`date` | 是 | 题号、对着哪套功法与剖面、谁裁决、哪天 |
| `g3_follow_up_seq` | 否 | 闸点 3 追问事件的 seq：cz 裁决的出处 |
| `order[]` | 是 | 火序：候选、位次、P、等谁、理由 |
| `held[]` | 否 | 挂起的：互斥待定、等结构修炼、等体质修炼、有环、火位占用 |
| `items[]` | 是 | G3 决定“交实现线”的候选，每个：`seed`（炼档种子）、`cuiyi`（渲染好的八栏）、`essence`（火意全文）、`placement`（入位方案全文）、`artifacts`（分析实例里各产物的 sha256） |
| `bang_updates[]` | 是 | 异火榜更新提议：新增、改状态、加一次运行记录、并入别条 |
| `profile_proposals[]` | 否 | 剖面修订提议（量具改动，cz 单独裁） |
| `library_import` | 否 | G3 勾了“报告存入资料库” |
| `validator` | 是 | 校验器 V1–V12 的结果 |

## 10. 运行状态 run

工作区里的 `run.json`，由引擎形态确定性地写，不由模型写。

| 栏 | 必填 | 含义 |
| --- | --- | --- |
| `run`、`mode` | 是 | 题号、模式 |
| `engine` | 是 | 引擎火 `id@ver`、功法摘要、这一题分在主臂还是留出臂 |
| `step` | 是 | 当前步：S0–S6、G1–G3、完成、预算暂停、叫停、失败 |
| `units[]` | 是 | 单元：`id`（例 `S3:H4:depth`、`S4:C2`）、`step`、`state`（待做、在做、完成、失败、预算截断、作废）、`output`（产物 sha256）、`depends_on`（上游产物；上游作废则本单元作废）、`summary`（带锚的单元摘要，≤ 1500 字）、`attempts`、`session` |
| `spent` | 是 | 已花（毫美元）、按步、按档位 token |
| `gates[]` | 是 | 每一闸：交付事件 seq、追问事件 seq、解析后的决定 |
| `artifacts` | 是 | 名字 → sha256（快照、勘察单、观察库、候选清单、各候选的火意与入位方案、交接包、报告） |
| `relays` | 否 | 已用的接力会话数（≤ 8） |

## 11. 异火榜条目 bang

文件 `{v, entries[]}`，条目：

| 栏 | 必填 | 含义 |
| --- | --- | --- |
| `id`、`title`、`essence`、`slot` | 是 | 编号、标题、火意一句（遮蔽视图的 `statement`）、主火位 |
| `fusion`、`also_slots`、`dims` | 否 | 融合假设一句、兼及火位、涉及的能力维 |
| `source_kind` | 否 | 出处类型（不写具体产品名） |
| `license` | 否 | 许可证状态 |
| `status` | 是 | 已识别、试算过、选中、已交实现线、已吞噬、不收、已排除、已并入、已散火（[09 §8.2](./09-engine.md#82-状态)） |
| `value`、`confidence`、`difficulty`、`risk`、`priority` | 否 | 上次算的 V、C、D、R、P |
| `basis_gongfa_digest` | 否 | 上次算 P 时的功法摘要；与当前不同即“需复算” |
| `kernel_lines_expected` | 否 | 预计体质改动行数（数，或“可能非 0”的说明） |
| `deps`、`exclusive_with` | 否 | 依赖、互斥 |
| `dossier`、`jie` | 否 | 炼档号、吞噬后的品阶 |
| `why`、`lessons` | 否 | 排除、不收、并入的理由；经验（不收时抄炼档的 `outcome_why`） |
| `runs[]` | 否 | 每次分析：题号、模式、走到哪步、产物 sha256、结局 |
| `history[]` | 是 | 状态史，只追加 |

## 12. 闸点决定 decision

决定块（[09 §2.4](./09-engine.md#24-闸点交付加追问)）解析后的形状：`gate`，以及按闸点不同的 `pick`、`exclude`（带理由）、`confirm`、`edit`（`候选编号.栏` → 新值）、`back`、`drop`、`to_implementation`、`hold`、`library_import`、`redo`、`note`；解析不了的行进 `unparsed`，引擎在下一次交付的 `needs` 里列出，不猜。
