# 庖丁基座规格 v1.4

> 状态：v1.1 已裁决，A1 到 A10 全部采纳（[裁决书](./spec-v1.1-adjudication.md)）。v1.3 在它之上并入三批已定的内容：v1.2（裁决书的三项补充与[典故对账](./paoding-jieniu-principles.md)的 D1 到 D6）；[蓝图 v2](./architecture-blueprint-v2.md) 的采纳项与[评审](../reviews/blueprint-v2-review.md)附加条件（[蓝图裁决书](./blueprint-v2-adjudication.md)）；[HMI 设计 v1.1](./hmi-design-v1.md) 的裁决落地项。v1.2 没有单独发布，随 v1.3 一并交付。v1.4 只并入 M0 实施中经裁决的五条勘误（E1 到 E5，见文首第三张表），没有新增机制。v1.1 见提交 de33acf，它相对 v1.0 的变更表移到附录 C。
> 输入：[调研 v2](../research/agent-architecture-survey-v2.md)（[S#]/[Z#] 编号以其为准）、[官知止总纲 v1.2](./paoding-allegory-mapping.md)、[协调基质](./coordination-substrates.md)。架构 v0 与 v0.1 已归档，与本文不一致处以本文为准（裁决书 §五）。
> 论断标注：`[证据 S#/Z#]` 有调研来源；`[假设]` 待 M0/M1 验证，`[假设 M#]` 在该里程碑验证；`[观点]` 作者判断；`[待核]` 来源未能一手核对。
> 结构标注：`[T-0]` 当前必要，且模型再强也需要；`[T-1]` 下一代模型可能吃掉，必须放外壳并带开关。官类按总纲 v1.2 的三类制：感知官、守门官、量具，另带启用条件（2.3）。
> 瘦基线：按任务书红线 5，取单个 Claude Code 会话。文中"该 CLI"均指它，M0 的 Worker 后端也用它（3.4.2）。

下面三张表是本版相对 v1.1 的全部变更，人可以逐条否决；否决后该条按"位置"一列回退，其余不受影响。编号接 v1.1 的 1 到 8。已有章节的编号没有动，新内容都放在新增的小节与附录里，别处对本文的引用因此仍然有效。

**v1.2：裁决书补充与 D1 到 D6**

| # | 变更 | 位置 | 来源 | 里程碑与开关 |
| --- | --- | --- | --- | --- |
| 9 | 判官资产分两级：结构级以 input 类哈希固定；含密级以 `vault:` 引用登记，只在判官容器里解引用，Worker 的两个容器都看不到 | 3.1.2、3.2.2、3.3.2、3.3.5、5.2 | 规格裁决书 §三.1 | M0；无开关 |
| 10 | 终态三值 solved、accepted、unsolved；报告首行写终态与根结论的等级上限；accepted 不呈现为"已证明" | 3.1.2、3.1.8、6.1、6.2 | 规格裁决书 §三.2 | M0 |
| 11 | 基质接口九操作映射表 | 附录 A | 规格裁决书 §三.3 | 无代码 |
| 12 | Bn 与 B1b 同工具面、同判官、同提交次数上限；开放问题 10 关闭 | 8.3、§10 | 规格裁决书 §二 A2 的附带条件、§五 | M1 |
| 13 | 难点标记 `knot`：带 knot 的 Intent 不认领、不竞速，先由 Reason 决定看清、换缝还是升档 | 3.1.7、4.1 | 典故对账 D1；名片 §3 | M1；`knot=off` |
| 14 | 换缝优先于换刀：升档从默认动作改为显式选项；两次换缝未解必须升档 | 3.1.7、4.2 | 典故对账 D2 提案二 | M1；`escalate=first` 即 v1.1 的次序 |
| 15 | 折损账：花费分为"割"与七类"折" | 8.4 | 典故对账 D2 提案一 | M1；投影，无开关 |
| 16 | 切口命中率：带判据的 Intent 的达成率、在链率、因前提被证伪而放弃的比例 | 8.4 | 典故对账 D3 | M1；投影，无开关 |
| 17 | 关节度 `unlocks`：同等条件下先做能解开最多 blocked Intent 的那一个 | 3.1.7、4.1 | 典故对账 D4 | M2；`order=gain_only` |
| 18 | 关题固定三步：四顾、定终态、藏刀；清单有未确认项时由人验收 | 3.1.8 | 典故对账 D5；总纲提案 2 | M4；M0 的 r0 题以空清单走同一流程 |
| 19 | 由厚回薄：按结构签名分开统计薄、厚路径，厚路径无增量的题类建议只跑瘦路径，由人确认 | 4.3、8.4 | 典故对账 D6 | 统计 M1，建议 M4 |

**v1.3：蓝图采纳项、评审附加条件与 HMI 裁决落地**

| # | 变更 | 位置 | 来源 | 里程碑与开关 |
| --- | --- | --- | --- | --- |
| 20 | 六契约按三层表述（信任根、协调基质、会话边界），附与本文章节的映射表 | 2.1 | 蓝图 F1、§2.2；评审 P1-1 | 无代码 |
| 21 | 八条不变量及各自的强制点；新增 I7 等级不出题、I8 估值不进等级 | 2.2、3.1.5 | 蓝图 §1.3、§2.3 | I7 随 M3；I8 的性质测试已在参考模型 |
| 22 | 入库四问与官的三类制；结构清单加"官"与"启用条件"两列；退役条款并入附录 | 2.3、附录 B | 蓝图 F3；蓝图裁决书 #3；总纲 v1.2 | 无代码 |
| 23 | 题界与封存：`Seal`、`Excerpt`、`register_artifact` 的摘录规则、内建判官 `seal_check`、`seal_revoked` | 2.4、3.1.9、3.3.3 | 蓝图 §2.4、§2.5 | M3 |
| 24 | 对照判据 N1：`Check.control`，主运行通过且对照不通过才算通过 | 3.1.2、3.1.3、3.3.3、3.5.2 | 蓝图 §3.6 N1 | M1 搭车；审计无差别则删（8.5） |
| 25 | 预测账 N3：每个任务的首次 `submit` 带 `forecast`，投影出校准读数 | 3.4.2、3.5.3 | 蓝图 §3.6 N3 | M1 搭车，只记录；`early_stop` 默认关 |
| 26 | 常设留出 N2（互斥分配，附样本量说明）与评测预登记 | 8.6、8.3 规则 7 | 蓝图 §3.6 N2；评审 P2-2、P2-4 | 预登记 M1；留出 M2，`holdout=off` |
| 27 | 司南增补：零级估值排序、C2 并发规则、`race_k` 只用于不带 knot 的 Intent；knot 冻结先于名额公式，名额公式启用后取代 `race_k` | 4.1、4.4 | 蓝图 §1.2 立场⑥、§2.9 C2、§3.1；蓝图裁决书 #2 | M2 |
| 28 | 通鉴改写：判例、Playbook、读数三类效力；七步管线；退役改用随机留出的增益 | 4.3 | 蓝图 §3.2 | 判例自动封存 M3，管线 M4；`kits=off` |
| 29 | 榷场三级：零级并入司南规则，一级盲报行情（题组层，三读数闸门），二级席位资本 | 4.4 | 蓝图 F2、§3.1；蓝图裁决书 #2 | M2、M4、M5；`market=off\|quote\|capital` |
| 30 | 闲人协议：falsifier 与 free-form，事件触发，吸收率自限，与 knot 联动 | 4.5 | 蓝图 §3.3、C3 | M2；`idlers=off\|falsifier\|freeform\|both` |
| 31 | 子题与托管：`Delegate`、`escrow_out`、`escrow_in`；子题先由人开或批量开题 | 4.6 | 蓝图 §3.4、§6 第 1 条 | M5 |
| 32 | 内建 `workspace` 资源种类；第二领域（Lean）的判官配置与接入走查 | 3.6.2、3.3.3、6.4 | 蓝图 C1、§3.5 | M3 |
| 33 | 路线图 M1 到 M5 更新，M4 内部次序写明；内核增量台账 | §7 | 蓝图 §5.1、§5.2；蓝图裁决书 #2 | 见该表 |
| 34 | 未证明清单 20 条 | §11 | 蓝图 §5.3；评审 P1-2 | 见该表 |
| 35 | 榷场走查补每步资本列；复算脚本入库 | 6.3、`reference-model/market_walkthrough.py` | 评审 P1-3 | 无 |
| 36 | M1 审计清单，含"对照质量"抽样 | 8.5 | 评审 P2-3 | M1 |
| 37 | 等级按批重算；验证的三个触发源共用去重键与验证池 | 3.1.9 | 蓝图 §1.2 立场②、③ | M2 |
| 38 | `Intent.rollback`：r2 的 Intent 必须声明回退 | 3.1.2、3.1.9 | HMI H1 | M4 |
| 39 | 人的决策操作带 `seen {seq, card_hash}`，过期则拒绝 `stale_view`；卡片投影端点 | 3.1.9 | HMI H2、§11.2 | M1 |
| 40 | 全部只读端点支持 `as_of=<seq>`，由服务端从快照重放 | 3.1.9 | HMI H3 | M1 |
| 41 | 五个事件名落定：`budget_add`、`rule`、`accept`、`judge_revoke`、`intent_done` | 3.1.9 | HMI §11.3 | 随各操作的里程碑 |
| 42 | Adapter 把任务包登记为 authored 类 Artifact | 3.4.2 | HMI H4 | M0 的 D4 到 D6 |
| 43 | 端点代理到模型网关分三阶段；M1 是"端点代理接第二家厂商"，完整网关在 M5 | 3.5.3、4.2、§7 | HMI §12.3、§8 第 7 条；蓝图裁决书 #2 | M0、M1、M5 |
| 44 | M0 前端取方案 α：只做 `pd` 文本输出的四语域约定，没有网页 | 4.1、§7 | HMI §5、§8 第 1 条 | M0，计入 D10 与 D12 |

**v1.4：M0 实施勘误**

M0 实施中的异议报告 002 经评审方裁决（PR #15）产生四条勘误，另有一条（E5）由人在 2026-11-18 裁决，原清单在 [`docs/m0/errata-v1.4.md`](../m0/errata-v1.4.md)。只改措辞与归属，不动不变量。

| # | 变更 | 位置 | 来源 | 里程碑与开关 |
| --- | --- | --- | --- | --- |
| 45 | E1：`inputs` 属于 JudgeRequest（候选在 `claim_done` 时给出），不属于 Check；`add_fact.check` 去掉 `inputs` | 3.4.2 的 Op 定义；3.3.2 的 `JudgeRequest.inputs` 不变 | 异议 002 第 1 项 | M0；无开关 |
| 46 | E2：回合上限由 Adapter 从事件流计数执行；`--max-budget-usd` 保留为进程内第二道线；预算硬顶仍由端点代理兜底（I6 不变） | 3.4.2 后端绑定表 | 异议 002 第 2 项 | M0；无开关 |
| 47 | E3：前缀稳定性改为任务包①到④段 100% 字节前缀稳定；⑤到⑦可变段不参与断言；整包公共前缀比例降为遥测读数 | 3.4.5 第 5 条 | 异议 002 第 3 项 | M0；无开关 |
| 48 | E4：硬顶 = 请求前检查，越界的上界为单次请求的花费；M1 可选按 `max_tokens` 的预估价预扣 | 3.5.2 | 异议 002 第 4 项 | M0；预扣 M1 |
| 49 | E5：图服务的端点走 HTTP（本机回环），不是 Unix socket | 3.1.2 | HMI §11 方案 A；人的裁决（2026-11-18） | M0；无开关 |

落地时有九处取了读法，同样可以逐条否决：

1. D1 到 D6 没有单独的裁决书，按名片 §3 此前记录的裁决结果（同步前各行写的"已裁决"）与典故对账原文落地。
2. "先看清"要把观察 Intent 与原 Intent 连起来，升档要成为显式选项，典故对账没有给出字段。本版加一个可选字段 `Intent.follows` 与一个操作 `escalate_intent`，两者都不进等级函数与消费门（3.1.7）。
3. 护栏"两次换缝未解必须升档"按 `follows {as: reroute}` 的链长计数。
4. N1 的强制范围取蓝图正文：r2 的观察类前提与续期门的进展计数。是否扩到 r1 留在开放问题 14。
5. 常设留出按互斥分配实现：一道题至多留出一项（8.6）。
6. 评测预登记在 M1 的载体是评测台登记的一个分组；M5 起它与题组是同一种对象（8.3 规则 7）。
7. 榷场走查里第 2、3 轮的挂牌价按定价公式重算。蓝图原表的 0.2 与 0.15 低于两个家族报价时公式的下界 0.25；改用 0.30 与 0.27 之后名额归属与每一步的资本都不变（6.3）。蓝图原表已加勘误。
8. 卡片对象不含估值类字段，所以估值事件不会让 `card_hash` 变化（3.1.9）。
9. HMI 设计在另一个待合并的 PR 里。本版合并时它若还没有进 main，文中指向它的链接暂时不通。

3.1 节由日志派生的语义另有一份可运行的[参考模型](reference-model/README.md)：88 条测试，在 v1.1 的 47 条之上新增保密库、终态、knot 与换缝、关节度、对照判据、封存校验、预测账、留出分配、I8 的性质测试、审批卡的所见绑定与 r2 的回退声明，以及 6.3、6.4 两个走查的逐步核对；90 处变异全部被测试抓住。v1.1 建模时澄清的四处含糊仍然有效：人的裁决如何驳回反证、`tests` 以 Intent 是否达成为准、失效集合的定义、`grounds` 不收 authored 类。

## 目录

1. [约束审计](#1-约束审计)
2. [基座总览](#2-基座总览)
3. [契约](#3-契约)（3.1 解牛图 · 3.2 Artifact 仓库 · 3.3 判官 · 3.4 Worker Adapter · 3.5 预算账本 · 3.6 执行层）
4. [三个机制与前沿展开](#4-三个机制与前沿展开)（4.1 司南 · 4.2 模型经济 · 4.3 通鉴与锦囊 · 4.4 榷场 · 4.5 闲人协议 · 4.6 子题、托管与多节点）
5. [对抗性自检与其它自检](#5-对抗性自检与其它自检)
6. [走查](#6-走查)（6.1 CTF · 6.2 运维 · 6.3 榷场 · 6.4 Lean）
7. [路线图与 M0 实施清单](#7-路线图与-m0-实施清单)
8. [消耗预算与 M1 目标](#8-消耗预算与-m1-目标)
9. [术语表](#9-术语表)
10. [开放问题](#10-开放问题)
11. [未证明清单](#11-未证明清单)

附录：[A 基质接口映射](#附录-a-基质接口映射) · [B 官的声明与退役条款](#附录-b-官的声明与退役条款) · [C 版本记录](#附录-c-版本记录)

---

## 1. 约束审计

### 1.1 结论一览

| 约束 | 判定 | 处理 |
| --- | --- | --- |
| 红线 1 写入路径无模型 | 承重墙 | 维持，补两处澄清（A3） |
| 红线 2 反幻觉不变量 | 承重墙，但不充分 | 收紧（A1）；M0 起由部署强制（A10） |
| 红线 3 领域知识不进内核 | 承重墙 | 维持；授权范围对内核不透明，由执行层解释 |
| 红线 4 删简律 | 承重墙，但原文不可操作 | 补操作化：每个 T-1 结构必须有开关和一条消融臂，并逐题记入归因表（8.4） |
| 红线 5 诚实对照 | 承重墙，但基线定义偏松 | 收紧（A2） |
| 立场 1 证据梯六态 | 方向对；E1 与 E2 分两级没有直接证据 | 重构实现（A4）；E1/E2 标 T-1 |
| 立场 2 E1→E2 异构 | 方向对；"不同视角"不可机检 | 收紧（A5） |
| 立场 3 闲人写入面 | 维持 | 澄清复审的归属（A8） |
| 立场 4 消费时验证 | 承重墙 | 维持，补死锁出口（3.1.4） |
| 立场 5 三轴分立 | 三轴维持；由人填写会与授权范围矛盾 | 取值改为由结构推出，不补第四轴（A7） |
| 立场 6 复用成熟 CLI | 依据是单一数据点 [证据 Z3]，但路径最短 | 维持，工具面改为代理工具（A10） |
| 立场 7 证伪阻尼 | 目标对，机制可以更简单 | 重构（A6） |
| 立场 8 司南无权威状态 | 承重墙 | 维持 |
| 五契约的切分 | 部分是惯性 | 部署合并，补一条（A9） |

从众风险最大的不是某条立场，而是黑板路线本身。它的证据是比赛成绩，属作者自述且没有对照组 [证据 Z3][Z4]。A2 的 Bk 与 Bn 两条对照臂专门检验这一点。

### 1.2 异议清单

下列各条本文均按替代方案书写。人可以逐条否决，否决后按原立场改回。

| 编号 | 被挑战的约束 | 替代方案 | 论证 | 迁移成本 |
| --- | --- | --- | --- | --- |
| A1 | 红线 2："引用 Artifact"即可晋级 | ① Artifact 带出处类别 `exec/judge/input/authored`，只有前三类可作证据；② 观察类论断的内容就是可机检的谓词；③ E3 只来自判官在洁净环境中的独立重放，不来自 Worker 自己的执行记录 | 引用只保证出处，不保证相关；也挡不住"先写文件再读出来"。自造观察是常见失败 [证据 Z7]；AIxCC 只认可独立复现的 PoV [证据 S14][S15] | Artifact 加 2 个字段；Fact 加 `claim_type` 与 `check` |
| A2 | 红线 5：对照 = 单次瘦基线 | 四条对照臂：B1 单次瘦基线，工具面原样；B1b 瘦基线换用代理工具面，单独量出外壳税；Bk 等成本独立重试（任一次成功即算解出）；Bn 共享笔记（多 Worker 共用一个追加写的 Markdown，无图无等级） | 独立重试本身就能涨解题率，只对 B1 计算"增量/成本倍数"会虚高 [观点]。赢 Bk 才说明共享状态有价值；赢 Bn 才说明图和等级有价值 | 评测脚本多三条臂，约 1 天 |
| A3 | 红线 1 的边界 | 图服务只做内容键精确去重；语义合并是一种提议（`same_as`，完整版）；title 与 summary 由提议方撰写且不可变。图服务的任何路径都不调用模型 | 语义去重和摘要生成是最容易破线的两处 | 无 |
| A4 | 立场 1：等级是可晋级的状态 | 等级不存储，是"有效支持集"的纯函数；取消"晋级请求"操作。E3 与 E3d 的区别由判官注册表里的 `grade`（判定性/相符性）决定，不由提议方声明；"等待延迟判官"是标记，不是等级 | 可写的等级字段会带来晋级竞态和不可重放的状态 [观点] | v0.1 的晋级状态机改写为"支持记录 + 重算" |
| A5 | 立场 2："同模型不同视角"也算异构 | 异构 := 模型家族不同，或后一条支持引入了前一条没有的执行证据 | 只换提示词不能消除相关错误，且不可机检 [观点] | 无（收紧） |
| A6 | 立场 7：连坐豁免规则 + 传播深度上限 | ① X 只来自判定性判官失败或人的裁决，模型反证只产生"争议"；② 等级按最小不动点全量重算，有独立有效支持的节点自然保留；③ 单个事件导致 K 个以上节点降级时告警；④ 判官裁决的翻转需要连续两次一致，单次重跑失败只让等级回到 E0。不设深度上限 | 截断传播会留下"地基已塌、上层照旧"的节点。真正要防的是错误的证伪，所以门槛设在 X 的产生上。重算是经典真值维护（JTMS，Doyle 1979，不在调研编号内）[观点] | 新增派生标记 `disputed`、`unstable` |
| A7 | 立场 5：三轴作为人填的字段 | ① 三轴是派生的画像：判官轴由 Goal 判官的注册信息算出，可逆性取各条授权规则所标风险的最大值，信息完整度看授权范围里有没有外部资源。人只能事后覆盖并留痕。② 不补第四轴。时效性是判据的属性，由判官注册表里的 `ttl_s` 表达 | 人填的轴可能与授权范围矛盾，例如标了 r0 而范围允许不可逆动作。v1.0 曾补 `drift` 轴，走查时发现同一题里固定时间窗的观察与"当前状态"的观察并存，按题设轴太粗 [观点] | Problem 去掉 `axes`；授权规则加 `risk`；JudgeSpec 加 `ttl_s` |
| A8 | 立场 3 中复审者的归属 | 写支持记录的复审属于 Verify 角色；闲人只写猜想与反证，反证同样必须带可采信 Artifact | 与"闲人只写 E0 与反证"一致，消除 v0 中 reviewer 的歧义 | 无 |
| A9 | 五契约的切分 | ① 契约 1、2、5 的权威状态是同一条事件日志，图、Artifact 登记、预算是它的三个投影；接口分立，M0 部署为一个进程。② 新增契约 6 执行层 | 三套存储要做跨库一致性，没有收益 [观点]。授权范围、审批门、证据采集的强制点都在执行层，原五契约里没有落点 | 无（尚未实现） |
| A10 | 立场 6：解析 CLI 的输出 | 维持 CLI 复用。模型进程与命令执行分在两个容器：CLI 所在的模型容器里没有任何命令执行工具，命令经代理工具 `exec` 在执行容器里运行，输出由执行层登记；结论经代理工具 `submit` 提交，当场得到校验结果。代理工具由 Adapter 托管，经 CLI 的外部工具接口挂载 [证据：该 CLI 帮助文本，不在调研编号内]。模型密钥与计量都放在容器外的端点代理上 | 单容器里命令与 CLI 同权，可以改写事件流、读走密钥、另起不计量的会话，这是 v1.0 的三个部署缺口。任务书对契约 2 的要求本来就是 Artifact 由执行层直接写入。工具参数自带 Schema，校验结果在同一回合返回，不需要修复轮 | Bootstrap 与瘦基线的工具面不再相同，外壳税由 B1b 量出（A2） |

### 1.3 蓝图 v2 的审计结论

蓝图 v2 对上面两张表逐条复审，五条红线与各条立场全部维持，另提出三处修正、两条不变量和三处小修。它们已经评审与人的裁决采纳，落点如下：

| 编号 | 内容 | 落点 |
| --- | --- | --- |
| F1 | 六契约按变化速率分三层表述；另立跨日志的原语"题界与封存" | 2.1、2.4 |
| F2 | 规模靠题组、题、子题三层展开，不靠在一个决策域里加调度；榷场是记账的分配算法，先落在题组层 | 4.4、4.6；协调基质文档已加勘误 |
| F3 | 入库四问：官类、退役信号或长存依据、启用条件、对照臂 | 2.3、附录 B |
| I7 | 等级不出题 | 2.2、2.4 |
| I8 | 估值不进等级 | 2.2、3.1.5 |
| C1 | 资源插件集内建 `workspace` 种类 | 3.6.2 |
| C2 | 八仙的并发规则除画像外，再读"互不依赖的 open Intent 数" | 4.1 |
| C3 | 复审属于 Verify；闲人只有 falsifier 与 free-form 两种 | 4.5 |

蓝图同时指出一点，本文照录：名片所说的"三次独立推导收敛"，三次用的是同一份证据浓缩与同一族模型，它说明结论对这些前提稳定，不说明前提为真 [观点]。真正独立的检验仍然只有 M1 的四臂对照。

---

## 2. 基座总览

基座 = 一条事件日志 + 一个确定性裁决器 + 四个插拔接口（判官、Worker Adapter、执行层、Blob 存储）。

三条主线贯穿全文：

- **判据先行。** Goal、带判据的 Intent（r2 动作的预测是其中一种）、M1 的达标线，都在动手之前登记，之后不可改。证据梯只认登记过的判官；带判据的 Intent 把题目沿可判定的关节切开。
- **结构自识。** 画像、执行容器的能力、调度形态、任务包里列出的锦囊，都由题目的判官与授权范围确定性地推出，不由人逐项填写，也不由模型自报。这是任务书"先识别问题结构，再决定解法形态"的机械形式。难度同样是结构：难点标记 `knot` 与关节度 `unlocks` 都是图上的派生量（3.1.7）。
- **自我删简。** 每个 T-1 结构带开关、带消融臂，并在归因表里逐题记录它是否出现在解题链上（8.4）。

```
 人 ──(open / hint / approve / 裁决 / 验收)─────────────────┐
                                                          ▼
 ┌─────────┐  /work · 租约   ┌──────────────────────────────────────────┐
 │ 司南 ×N  │◀──────────────▶│ 契约1 解牛图服务：唯一写入者，确定性代码      │
 └────┬────┘                │ 事件日志 ─▶ 图与等级 │ Artifact 登记(契约2) │ 预算(契约5) │
      │ 启动                 └────▲──────────────▲──────────────▲───────┘
      ▼                          │ submit（提议） │ 登记 · 越界   │ 裁决 · 过期
 ┌─────────────────────────┐     │       ┌──────┴───────┐  ┌───┴─────────────┐
 │ 契约4 Adapter            │─────┘       │ 契约6 执行层   │  │ 契约3 判官运行器   │
 │  代理工具 exec/submit/show ── exec ───▶│  执行容器      │◀─│ （洁净重放）       │
 │  模型容器：CLI，只有文件工具 │             │  授权范围·采集  │  │ 哮天犬           │
 └─────────────────────────┘             └──────┬───────┘  └─────────────────┘
                                                ▼
                                    Blob 仓库（契约2，按 sha256 寻址）
 ═════════════ 题界：等级不出题，跨界只传封存摘录（2.4） ═════════════
   题组 ⇄ 题 ⇄ 子题（各有独立日志）        通鉴日志（判例、Playbook、读数）
```

数据流：

1. 人用 `pd problem open` 提交 Problem：授权范围（每条规则自带风险等级）、Goal 判据、预算。图服务据此算出画像。
2. 司南读 `/work`（图服务派生的可做事项），申请租约，同时预留预算。
3. 按租约起一对容器：模型容器归 Adapter，执行容器归执行层。CLI 在模型容器里运行，只有文件工具和三个代理工具，没有命令执行能力；它的模型请求经容器外的端点代理发出，密钥与计量都在那里。
4. 命令经 `exec` 在执行容器里运行。输出由执行层登记为 `exec` 类 Artifact，模型拿到的是截断后的输出和引用。
5. Worker 用 `submit` 提交结论。图服务当场确定性校验并追加事件；等级、预算、可做事项随之重算。
6. 需要判定时，判官运行器另起洁净的执行容器重放，提交裁决。
7. 哮天犬只做四件事：过期租约、超预算终止、清理孤儿容器、健康告警。

### 2.1 三层与六契约

六个契约的变化速率不同，按此分为三层 [蓝图 F1]。依赖是单向的：外壳依赖基质接口与代理工具，二者依赖信任根；信任根不读外壳的任何状态。

| 层 | 守的保证 | 什么时候才会变 |
| --- | --- | --- |
| 信任根 | 判据先行；出处类别与内容寻址；E3 与 X 的唯一来源；能力不超过 Intent 风险，风险不超过授权 | 发现新的独立画像轴，或威胁模型变化；新领域只加配置 |
| 协调基质 | 写入无模型；等级为派生；租约与预算原子 | 换基质时整体替换，九操作接口不动（附录 A） |
| 会话边界 | 模型对外只有三个代理工具；密钥与计量在容器外 | 换后端时重写绑定 |

本文按章节给契约编号，蓝图按层列契约。两种数法都得到六，指的是同一组东西，对照如下：

| 本文的契约 | 所在层 | 说明 |
| --- | --- | --- |
| 契约 1 解牛图（3.1） | 协调基质 | 其中的 `Problem` 记录属于信任根：判据、授权范围与预算由它登记，画像由它推出。蓝图把它单列为一个契约 |
| 契约 2 Artifact 仓库（3.2） | 信任根 | |
| 契约 3 判官（3.3） | 信任根 | |
| 契约 4 Worker Adapter（3.4） | 会话边界 | 端点代理在部署上属于这一层 |
| 契约 5 预算账本（3.5） | 协调基质上的投影 | 蓝图不把它算作契约；硬顶由会话边界的端点代理执行 |
| 契约 6 执行层（3.6） | 信任根 | |

第 4 节的机制（司南、模型经济、通鉴与锦囊、榷场、闲人、子题）都在这三层之外，属于外壳。

### 2.2 八条不变量

| # | 不变量 | 强制点 |
| --- | --- | --- |
| I1 | 写入路径无模型 | `validate` 与 `apply` 是纯函数（3.1.2）；3.1.5 的 1 |
| I2 | 证据只认执行层产出的可采信 Artifact；E3 与 X 只来自判定性判官的洁净重放或人的裁决 | 出处类别与可采信检查（3.2.4）；等级函数（3.1.2、3.1.3） |
| I3 | 等级不存储、不可写 | 没有写等级的操作；每次应用事件后重算 |
| I4 | 判据在动手前登记，之后不可改 | `Check` 随对象的创建事件写入；评测阈值预登记（8.3 规则 7） |
| I5 | 能力 ≤ Intent 风险 ≤ 授权范围；r2 的一次批准只管一次租约 | `add_intent` 的风险校验；执行层的 `compile`（3.6.2）；消费门 |
| I6 | 预算硬顶在容器之外执行 | 端点代理（3.4.2、3.5.2） |
| I7 | 等级不出题 | 跨题引用一律 `scope_mismatch`；摘录登记规则与 `seal_check`（2.4）；3.1.5 的 10 到 12 |
| I8 | 估值不进等级 | 等级函数与消费门的输入里没有估值类字段；参考模型的性质测试（3.1.5 的 13） |

I7 的依据是环境各不相同：等级对应的是那一道题的环境基线与判官，换一道题就不成立。I8 里的估值类指 `expected_gain`、预测账的 `forecast`、报价与行情、席位的权重与资本、Hint、闲人攻击的存活计数。它们只影响先做什么，不影响什么为真、什么可放行。两条都是守门官。

### 2.3 结构清单

每个结构入库时回答四问 [蓝图 F3]：它是哪一类官；感知官的退役信号或守门官的长存依据是什么；启用条件是什么；对照臂是什么，默认取它自己的退化形态。

官分三类，判别式是两问：它弥补的是模型的缺陷，还是世界的性质？它是要被相信，还是要被测量？弥补模型缺陷的是感知官，带退役条款；守世界性质的是守门官，长存；只产生读数的是量具，越换代越有用，永不退役，也永不守门（总纲 v1.2）。守门官与量具标 T-0，感知官标 T-1。只在规模上才需要的结构不另设一类，靠"启用条件"一列约束，免得它们在小规模上常开，成为纯成本。退役信号与长存依据逐条列在附录 B。

| 结构 | 标签 | 官 | 启用条件 | 成本影响 | 开关或对照臂 |
| --- | --- | --- | --- | --- | --- |
| 事件日志 + 确定性裁决 | T-0 | 守门官 | 常开 | 无模型成本，毫秒级 | 无 |
| 出处类别与可采信检查 | T-0 | 守门官 | 常开 | 无 | 无 |
| 模型容器与执行容器分离、代理工具 | T-0 | 守门官 | 常开 | 每条命令多一跳，毫秒级；外壳税待测（B1b） | 无 |
| Goal 判官、重放判官 | T-0 | 守门官 | 常开 | 每次一个洁净容器，秒到分钟，不耗 token | 自动重放的成本阈值 |
| 判官资产的保密库 | T-0 | 守门官 | 题目有含密级资产 | 无 | 无 |
| 预算预留、硬顶、哮天犬 | T-0 | 守门官 | 常开 | 无 | 无 |
| 授权范围、按风险注入能力、审批门 | T-0 | 守门官 | 常开；审批门在有 r2 或 `needs_scope` 时 | 人的等待时间 | 无 |
| 画像推导 | T-0 | 守门官 | 常开 | 无 | 人可覆盖 |
| 对照判据（N1） | T-0 | 守门官 | M1 起；r2 的观察类前提与续期门的进展计数 | 判官多跑一次，不耗 token | 审计无差别则删（8.5） |
| 题界与封存、`seal_check` | T-0 | 守门官 | M3 起；有跨题引用时 | 无模型成本 | 无 |
| 评测预登记 | T-0 | 守门官 | 评测题组 | 无 | 无 |
| 四顾与终局协议 | T-0 | 守门官 | 每次关题；r0 题以空清单通过 | 清单非空时是人的确认时间 | 无 |
| 判例（通鉴） | T-0 | 守门官 | M3 起，每题关闭时 | 无，纯投影 | 无 |
| 归因表、折损账、切口命中率 | T-0 | 量具 | 常开 | 无，是日志上的投影 | 无 |
| 预测账（N3） | T-0 | 量具 | M1 起 | 每任务约 20 token | 读数无开关；早停 `early_stop` 默认关 |
| 常设留出（N2）与通鉴读数 | T-0 | 量具 | M2 起；不含 r2 规则的题 | ε 乘以被留出官的真实增益 | `holdout=off` |
| 由厚回薄 | T-0 | 量具；调整由人确认 | 同一签名累计不少于 10 题 | 无；省下的是厚路径的花费 | 回归哨兵（4.3） |
| Bootstrap 先瘦后厚 | T-1 | 感知官 | 常开 | 易题上成本倍数约为 1 | `bootstrap_share` |
| 带判据的 Intent | T-1 | 感知官 | 常开 | 每次判定一个洁净容器，不耗 token | `checked_intents=off` |
| 80% 续期门 | T-1 | 感知官 | M1 起 | 没有进展的题最多少花题预算的 20% [假设] | `extension=always` |
| Reason 串行、只有它能加 Intent | T-1 | 感知官 | 常开 | 每轮约 0.45 美元（强档）[假设]；增加延迟 | 可改为 Explore 自行提 Intent |
| E1/E2 模型复核与异构要求 | T-1 | 感知官 | M1 起；有 r1 以上的消费者时 | 每条被消费的推断多 0.1–0.4 美元 [假设] | `ladder=binary`、`hetero=off` |
| 三层视图与缓存友好布局 | T-1 | 感知官 | 常开 | 任务包变小；同批并发会话可共享前缀缓存，跨轮命中取决于后端能否设断点 [假设] | `view=full_dump` |
| 八仙扇出控制器 | T-1 | 感知官 | M2 起 | 决定预算花得多快；成本倍数的上界由题预算硬顶给出 | 固定并发 |
| 难点标记 `knot` 与换缝优先 | T-1 | 感知官 | M1 起 | 难点上少开会话，多一个小的观察 Intent | `knot=off`、`escalate=first` |
| 关节度 `unlocks` | T-1 | 感知官 | M2 起；有 blocked 的 Intent 时 | 无 | `order=gain_only` |
| 闲人（falsifier、free-form） | T-1 | 感知官 | M2 起；事件触发；falsifier 要有可用的异家族 | 不超过题预算 10% | `idlers=off\|falsifier\|freeform\|both` |
| 模型分层 | T-1 | 感知官 | M2 起 | 同一题预算下 Explore 会话数约翻倍 [假设]，见 §8 | 全强档 |
| Playbook 与锦囊 | T-1 | 感知官 | M4 起；M1 只做人工复盘 | 复盘每题约 0.5 美元 [假设]；后续题降本 | `kits=off` 与留出组 |
| 榷场零级：估值排序 | T-1 | 感知官 | M2 起，默认形态 | 无 | 八仙规则表 |
| 榷场一级：盲报行情 | T-1 | 感知官 | M4，题组层；家族数 ≥ 2，可行组合数 ≥ 2 × 名额；三读数闸门（4.4） | 报价不超过预算 3% | `market=off\|quote` |
| 榷场二级：席位资本 | T-1 | 感知官 | M5；并发 ≥ 50 且一级的读数为正 | 无模型成本 | `market=quote\|capital` |
| 子题与托管 | T-1 | 感知官 | M5；单题 open 的 Intent 持续超过 Reason 一轮的处理量，或并发超过 10 | 每个子题多一次开题与一次封存，毫秒级 | 子题臂对"单题大图"臂 |

### 2.4 题界与封存

[T-0，守门官] 日志按题独立，等级不跨题。跨题只传可以校验的只读摘录。题组、子题、判例、通鉴都建在这一个原语上，不各造一套。M3 落地。

```ts
type Seal    = { problem_id: string, head_seq: number, head_hash: string,   // 该题哈希链的链头
                 state_hash: string, reducer: string,                       // 链头处的状态哈希与 reducer 版本
                 terminal?: "solved"|"accepted"|"unsolved" }                // 终态封存才有
type Excerpt = { seal: Seal, nodes: object[], supports: object[],           // 被摘录的节点与支持记录
                 blobs: string[] }                                          // 所引 Blob 的 sha256
```

1. **导出**是日志的确定性投影，不调用模型。校验方式是把来源日志重放到 `head_seq`，比对 `head_hash` 与 `state_hash`。
2. **摘录登记规则**，即 `register_artifact` 新增的一条：摘录在接收题里登记为 input 类 Artifact，登记方只能是接收题的图服务，先重放校验再追加。其它令牌登记摘录返回 `forbidden_op`；重放结果与封存不符返回 `bad_seal`。
3. **等级不随摘录过界**（I7）。摘录里的节点不是接收题的节点，不能作前提；以摘录为 `grounds` 的观察仍要由接收题的判官重放判定。
4. **内建判官 `seal_check`**（判定性，不含领域词）：核对一份终态封存可以重放、终态为 solved，并且子题 Goal 判据的哈希等于父题 Intent 登记的判据。它检验的是日志，不是内容，这是 I7 唯一的结构性例外。accepted 与 unsolved 的子题不能让父题的 Intent 达成。
5. **撤销。** 来源题的判官版本被撤销或人改判时，订阅它的题追加 `seal_revoked`，以这份封存为候选的 `seal_check` 裁决随之失效，等级重算，机制与判官版本撤销相同。r2 的 Intent 在申请租约时同步核对所依赖封存的最新状态；r0 与 r1 接受最终一致。

建在它上面的三种对象：

- **题组**是没有 Reason、Intent 全部是子题委托的父题。它的 Goal 判官只做计分（`advisory`），由期限或人关闭。
- **子题**是由带 `delegate` 的 Intent 开出的独立 Problem：独立日志、独立 Reason、独立预算，深度上限为 2（4.6）。
- **通鉴日志**与题日志是同一种基质实例，存判例、Playbook 与读数（4.3）。

一题之内的数据流就是上面的七步。跨题只有四条流：父题向子题划拨预算（`escrow_out`，子题的 `open_problem` 引用它）；子题关闭后给出终态封存，父题用 `seal_check` 判定，余额以 `escrow_in` 回拨，幂等键是封存的哈希；任意题关闭时判例写入通鉴日志；新题开题时 Adapter 按结构签名从通鉴取判例索引与锦囊，列进任务包第③段。

---

## 3. 契约

### 3.1 契约 1：解牛图（图状态服务）

#### 3.1.1 决策日志（备选与取舍）

| 议题 | 选定 | 被否方案 | 理由 |
| --- | --- | --- | --- |
| 权威状态 | 追加写事件日志 + 纯函数 reducer | 直接修改节点行的可变图 | 可重放、可审计、崩溃恢复只需重放 [证据 S5] |
| 存储 | M0 用 SQLite 单文件（WAL） | PostgreSQL（v0 方案）、专用图库、git 仓库 | 单写者与之天然契合，零运维；图规模在 10³–10⁴ 节点，内存邻接表足够 [观点]。多主机读写时再迁 PostgreSQL |
| 等级 | 支持集的派生函数 | 可写字段 + 晋级请求 | 见 A4 |
| 证伪传播 | 每个事件后全量重算（最小不动点） | 增量传播 + 深度上限 | 精确，百行内可写完。参考模型用未优化的 Python 全量重算，10³ 个节点约 6 毫秒，10⁴ 个约 70 毫秒 [证据：`reference-model/` 实测，不在调研编号内] |
| 批次语义 | 一批提议原子生效；Adapter 按"一个论断一批"切分 | 逐条独立 + 依赖传播 | reducer 更简单 |
| 计划写入 | Reason 租约每题互斥，只有它和人能加 Intent | Explore 自行加 Intent | 决策保持单线程 [证据 S44][Z5] |

#### 3.1.2 M0 最小版

```ts
type Event = {
  v: 1                        // 事件模式版本；reducer 按版本解释，旧日志可重放
  seq: number                 // 图服务分配，全局单调
  problem_id: string
  ts: number                  // 毫秒；追加时由图服务写入，是 reducer 唯一的时钟
  actor: { kind: "human"|"sinan"|"adapter"|"judge"|"executor"|"watchdog"|"graph", id: string,
           session?: string,  // 即租约 id
           role?: "bootstrap"|"reason"|"explore"|"verify"|"idler" }     // 角色，由租约决定，非模型自报
  kind: string                // 见操作表
  body: object
  idem_key: string            // 提议方生成；同键重放返回首次结果
  prev_hash: string           // 同题上一条事件的 hash；哈希链按题独立，可单独导出与校验
  hash: string                // sha256(JCS(除 hash 外的全部字段))，JCS 即 RFC 8785 规范化 JSON
}

type Profile = { info: "complete"|"partial",                 // 信息完整度 → 司南的生长规则
                 judge: "hard"|"costly"|"deferred"|"none",   // 判官类型 → Goal 的可达上限
                 reversibility: "r0"|"r1"|"r2" }             // 可逆性 → 审批门默认值
                 // 画像是派生量，不是输入，推导规则见下
type Budget = { usd_milli: number, tokens?: number, wall_s: number }
type VaultRef = { vault: string, digest: string }   // 含密级判官资产的引用：保密库里的键，加 sha256(盐 ‖ 内容)；盐也在库里
type Check  = { judge_id: string, spec_ref?: ArtifactId, expect?: object,    // expect 由判官解释
                sealed?: VaultRef[],                          // 判官要用的含密级资产，见 3.3.2
                control?: { inputs: ArtifactId[] | object } } // M1：对照判据，同规格、异输入，见 3.3.3

type Problem = {
  id: string; title: string
  origin: { statement_ref: ArtifactId, materials: ArtifactId[] }              // input 类
  goal:   { statement: string, check: Check, max_attempts: number,
            accept: "judge"|"human" }                                         // M0 只实现 judge
  scope: { resource: string, pattern: string, actions: string[],
           risk: "r0"|"r1"|"r2" }[]     // 必填。risk 由授权的人逐条标注，缺省 r2；其余字段内核不解释
  budget: Budget & { verify_share: number, bootstrap_share: number }
  env: { base: string, baseline_ref: string }      // base：执行容器的基础规格名（镜像与资源上限）
  judges: string[]                                                            // 本题启用的判官
  profile: Profile             // 派生字段：图服务在开题时算出并写入，提交时不接受
}
type Fact = {                  // 等级为 E0 时称 Conjecture；存储上是同一种记录
  id: string
  title: string                // 第一层，≤120 字符
  summary: string              // 第二层，≤600 字符
  body_ref?: ArtifactId        // 第三层正文，authored 类
  claim_type: "observation"|"inference"
  check?: Check                // observation 必填：论断的内容就是这个谓词
  premises: string[]           // derives_from 边：Fact id，或带判据的 Intent 的 id
  grounds: ArtifactId[]        // observation 至少 1 个 exec 或 input 类；inference 要求 grounds 或 premises 非空
  yielded_by?: string          // yields 边：Intent id，由租约推出，不由模型填写
}
type Intent = {
  id: string; title: string; summary: string
  premises: string[]; risk: "r0"|"r1"|"r2"; budget: Budget
  done?: Check & { max_attempts: number,    // 带判据的 Intent：达成与否由判官判定；判据在创建时登记，之后不可改
                   tests?: string[] }       // 完整版：这条判据所检验的推断类前提，见 3.1.3
  needs_scope?: Problem["scope"]   // 申请扩大授权范围；非空时初始状态为 needs_human
  expected_gain?: number       // [T-1] 只供司南排序，内核不解释
  // 以下是后续里程碑的可选字段，都不进等级函数与消费门
  follows?: { intent: string, as: "observe"|"reroute" }   // M1：承接另一条 Intent，见 3.1.7
  executor?: "worker"|"human"                             // M3：人执行的 Intent，见 3.1.3
  rollback?: { text: string, done?: Check }               // M4：回退方法，r2 必填，见 3.1.9
  delegate?: Delegate                                     // M5：委托为子题，见 4.6
}
type Hint = { id: string; text: string; about?: string     // about：所指节点，可空
              author: string; closed: boolean }            // 不是证据，不能作前提（4.1）
type Support = {               // supports / contradicts / proves 三种边的载体
  id: string; target: string   // Fact id、带判据的 Intent id，或 "goal"（后两者即 proves）
  polarity: "support"|"contradict"
  method: "judge"              // M0 只有判官一种
  judge: { id: string, version: string, grade: "decisive"|"consistent" }
  verdict: "pass"|"fail"; evidence: ArtifactId[]          // judge 类
}
type Lease = { id: string; kind: "bootstrap"|"reason"|"explore"|"judge"; target?: string
               holder: string; reserve: Budget; expires_at: number; attempt: number }
```

画像的推导（人不填写，只能事后覆盖）：

```
profile.reversibility := max(rule.risk for rule in scope)
profile.judge         := none      若 Goal 判官的 grade = advisory（只做结构检查，达成靠人验收）
                         deferred  否则若该判官的 kind = deferred 或 grade = consistent
                         hard      否则若该判官的 max_cost 不超过"廉价判官"阈值（配置项）
                         costly    其它
profile.info          := partial   若 scope 中有被资源插件登记为 external 的资源；否则 complete
```

画像只在 `open_problem`、范围修订和人工覆盖这三种事件上重算，结果写进事件体，所以重放不依赖注册表。

端点（M0 走 HTTP，只监听本机回环地址；形状见 [HMI 设计](./hmi-design-v1.md) §11 与 `graph/SPEC.md` 的“HTTP 绑定”）：

```
POST /v1/problems                          open_problem
POST /v1/problems/{pid}/proposals          {idem_key, ops[]} → {results[]}；整批原子
POST /v1/problems/{pid}/leases             {kind, target?, holder, reserve, ttl_s} → 201 {lease} | 409
POST /v1/leases/{id}/renew
POST /v1/leases/{id}/release               {outcome, transcript_ref, suggestions?}
GET  /v1/problems/{pid}/work               派生的可做事项
GET  /v1/problems/{pid}/view?layer=title|summary&after_seq=&limit=
GET  /v1/problems/{pid}/status             等级、争议、Intent 状态的当前值
GET  /v1/nodes/{id}?layer=evidence
GET  /v1/problems/{pid}/events?after=seq   长轮询；它就是审计日志
GET  /v1/problems/{pid}/invalidations?node=  某节点被证伪后，因它失去支持的节点集（invalidates 边，派生）
```

内核函数：`validate(state, actor, op) → Ok | Reject(code)` 与 `apply(state, event) → state'`，两者都不读时钟、不做 IO、不调用模型。

| 操作 | 谁可提交 | 关键校验 |
| --- | --- | --- |
| `open_problem` | human | Schema；判官已注册；scope 非空；预算为正。通过后算出画像 |
| `register_artifact` | executor（exec）、adapter（authored）、judge（judge）、human（input） | Blob 存在且哈希相符；类别与令牌匹配 |
| `add_fact` | adapter，角色为 bootstrap、explore 或 reason | 引用存在且同题；grounds 类别可采信；observation 带 check；premises 中无 X；未超配额 |
| `add_intent` | adapter，角色为 reason；human | premises 存在且无 X；risk 不高于授权范围与 `needs_scope` 合并后的最高风险；带 `done` 时判官在 `Problem.judges` 内；预算落在配置区间 |
| `abandon_intent` | adapter，角色为 reason；human | Intent 未到终态且无在途租约 |
| `request_judge` | adapter、sinan、human | 判官在 `Problem.judges` 内；目标未超 `max_attempts`；验证池未超 |
| `judge_verdict` | judge | 请求存在且由本判官租出；evidence 为 judge 类 |
| `hint`（新增或关闭）、`approve`（批准或拒绝）、`profile_override`、`extend`、`pause`、`resume` | human | 无 |
| `cost` | adapter、judge | 任务存在 |
| `scope_violation` | executor | 任务存在 |
| `lease`、`renew`、`release` | sinan（bootstrap、reason、explore）、judge（judge 租约）；续租与释放限持有者 | 目标在 `/work` 内；预留放得下；目标上无在途租约 |
| `expire_lease` | watchdog | `ts ≥ expires_at` |
| `close_problem` | graph（Goal 到 E3 时自动）、watchdog（预算耗尽）、human | 状态合法；事件体带终态 `terminal`（见下） |

`budget_mark` 与 `alert` 由图服务在应用事件时自己追加，不接受外部提交。

拒绝码：`forbidden_op`、`unknown_ref`、`inadmissible_class`、`scope_mismatch`、`missing_evidence`、`stale_premise`、`conflict_leased`、`over_budget`、`quota_exceeded`、`schema_error`。后续里程碑新增两个：`stale_view`（M1）与 `bad_seal`（M3），见 3.1.9 与 2.4。

冲突解决：单写者按到达顺序串行应用。

| 冲突 | 规则 |
| --- | --- |
| 两个租约请求抢同一目标 | 先到者得，后者 409 `conflict_leased` |
| 内容键相同的 `add_fact` | 幂等合并：返回已有节点，grounds 并入 |
| 提议引用的前提在提交时已被证伪 | 整批拒绝 `stale_premise`，附最新状态，经 `submit` 的返回值交给 Worker 修正 |
| 同一 `idem_key` 重放 | 返回首次结果 |
| 判官裁决与人的裁决不一致 | 人的裁决优先，并在节点上留可见标记 |

内容键：观察类取 `check` 的规范化哈希（`spec_ref` 按 Blob 哈希代入），推断类取 title 与排序后的 premises 的哈希。

M0 的等级函数与消费门：

```
裁决序列(t,j) := 目标 t 上判官版本 j 给出的 pass、fail 与 inconclusive(flaky)，按 seq 排列；
                 后者记为无结论，其它无结论的裁决不进序列
有效裁决(t,j) := 序列只有一条时取该条；否则最近两条一致才取其值，不一致为无结论
                 // 翻转需要连续两次一致：单次重跑失败只让 E3 回到 E0
unstable(t) := 存在 j 使裁决序列(t,j) 不止一条且有效裁决为无结论          // 派生标记，触发自动复判
有效(s)     := s.judge.version 未被撤销 ∧ 有效裁决(s.target, s.judge) = s.verdict
level(f)    := X   若存在有效的 contradict（grade=decisive，verdict=fail）        // f 为论断
               E3  否则若存在有效的 support（grade=decisive，verdict=pass）
               E0  其它
level(g)    := E3  若某个候选有一条有效的判定性 pass；否则 E0                   // g 为 goal 或带 done 的 Intent
                   // 有效裁决按候选分别计；失败的候选只累计 max_attempts，目标没有 X
gate(i)     := (∀p∈i.premises: level(p)≠X ∧ (level(p)=E3 ∨ (i.risk=r0 ∧ p 是论断)))
               ∧ ((i.risk≠r2 ∧ i.needs_scope 为空) ∨ 已有 approve(i))
               // 以带判据的 Intent 作前提，就是声明依赖：它达成之前本 Intent 不放行
               // r2 的 approve 只管一次租约：租约结束后再次执行需要新的 approve
```

观察类论断、带判据的 Intent、Goal 三者都是"带判据的对象"，走同一条判定路径。区别只有一处：论断是断言，判官否定即证伪；目标是待达成的状态，候选失败只说明还没达成。

题目的终态取三值，写进 `close_problem` 的事件体，`pd status` 与 `pd report` 统一使用：

```
terminal := solved    若 goal.accept = judge ∧ level(goal) = E3        // 判官确认
            accepted  否则若存在人的验收记录（accept 事件）              // 人验收
            unsolved  其它
```

Goal 判官是相符性或建议性时，Goal 到不了 E3，终态最多是 accepted。报告首行写终态，并写明根结论的当前等级与本题判官之下可达的等级上限。accepted 在任何输出里都不呈现为"已证明"。关题的次序见 3.1.8。

Intent 状态（派生）：

```
open ──租约──▶ leased ──release──▶ done
  ▲              │ 过期或失败，且 attempt < 2
  └──────────────┘
带判据的 Intent：done 判据通过即 achieved（终态），可作前提；租约已释放、判定不再未决而判据未过，按失败处理
r2 的 Intent 失败或过期后不回 open，转 needs_human：不可逆动作不自动重做
blocked ──前提达标──▶ open
blocked ──验证用尽，或需要审批──▶ needs_human ──approve──▶ open ；deny ──▶ abandoned
未终态 ──前提被证伪或被放弃 / Reason 放弃 / 连续 K 轮无人认领──▶ abandoned
```

`/work` 的派生规则（图服务给出"可做什么"，司南决定"先做什么"）：

```
bootstrap   尚无任何租约历史
reason      无在途 reason ∧ bootstrap 已结束 ∧ 上次 reason 租约签发之后出现过：
            非 reason 任务结束 | 新 Hint | 预算标记 | Goal 判官 fail
            处于预算复盘期时带 reflect 标志（3.5.2）
explore(i)  state(i)=open ∧ 不处于预算复盘期 ∧ 续期门放行（3.5.2，M1 起）
judge(j)    请求未裁决且未租出；或目标带 unstable 且该（目标、判官版本）的裁决不足 4 次（沿用上次请求的输入）
human(x)    needs_human 的 Intent 与待审批项；续期门未放行的题（3.5.2）
            停滞也归入此项：无在途任务、无 open 的 Intent、无未决判官请求，且 reason 不满足触发条件。
            此时等待 Hint 或人工关闭；wall_s 用尽时由哮天犬以 unsolved 关闭
```

每个任务的写入配额：Fact 不超过 20 条，Intent 不超过 8 条（可配置）。

#### 3.1.3 完整版

支持记录扩展为 `method ∈ {judge, review, human}`，并带 `premises`、`by {session, model_family}`、`context_manifest`（Adapter 记录该会话实际读到的节点与 Artifact，非模型自报）、`valid_until`（由判官的 `ttl_s` 算出）；判官支持另带 `controlled`，表示这次裁决带对照（N1，3.3.3）。等级全序为 E0 < E1 < E2 < E3d < E3。

```
前提(s)      := s.premises；s 为 review 时再并上目标论断自己的 premises
                // judge 与 human 两种支持不带前提，由 Schema 强制
有效(s)      := s 的证据非空、均已登记且类别可采信 ∧ s 未过期、未被驳回 ∧ ∀p∈前提(s): p 非 X
                // 红线 2：复审也必须引用至少 1 个可采信 Artifact；人的裁决理由登记为 input 类
                // 判官支持另须满足 M0 的两条：判官版本未撤销、与有效裁决一致
strength(s)  := min(level(p) for p in 前提(s))；没有前提记为 ∞     // 信任不超过前提
level(f)     := X    若存在有效 contradict：(judge ∧ decisive ∧ fail) ∨ (human ∧ 裁决为证伪)
                E3   否则若存在有效 support：judge ∧ decisive ∧ pass
                E3d  否则若存在有效 support：judge ∧ consistent ∧ pass
                E2   否则若存在有效 review 支持 s1、s2（会话不同，s1 在先）：
                     两者都 independent ∧ heterogeneous(s1,s2) ∧ strength(s1)、strength(s2) ≥ E2
                E1   否则若存在有效 review 支持 s：independent(s) ∧ strength(s) ≥ E1
                E0   其它
disputed(f)  := level(f)∉{X,E3} ∧ 存在有效且未被驳回的 contradict（review，或 consistent 判官的 fail）

independent(s)       := s.by.session ≠ f 提出者的会话 ∧ f 的正文 body_ref ∉ s.context_manifest
heterogeneous(s1,s2) := family(s1) ≠ family(s2) ∨ exec 证据(s2) ⊄ exec 证据(s1)

重算：X 的集合不依赖任何等级，先一次算定；其余节点从 E0 起反复应用 level()，只升不降，直到不变。
```

复审是对"由前提推出该论断"的意见，所以论断自己的前提被证伪时，它的复审支持全部失效；判官支持直接检验论断本身，不受影响。这就是"有独立支持的节点不连坐"的机械形式。level() 对前提的等级单调，所以最小不动点唯一，与迭代顺序无关；互相作前提的两条论断无法把彼此抬上去，环状支持得不到等级。这两点在参考模型的随机状态上核对过。

消费门：

| Intent.risk | 前提最低等级 | 审批 |
| --- | --- | --- |
| r0 可逆或只读 | 非 X 即可（探索本身就是检验猜想的方式） | 不需要 |
| r1 有成本 | E1，且无争议 | 不需要 |
| r2 不可逆 | E3，观察类前提另须带对照（N1）；或 E2 以上并由人对该前提签署豁免 | 必需，一次批准只管一次租约；Intent 必须带判据，M4 起必须声明回退（3.1.9） |

前提是带判据的 Intent 时，三档都要求它已达成。r2 的 Intent 在前提都不低于 E2 时进入 `needs_human`，批准与对前提的豁免在同一张卡片上给出。对照只向 r2 的观察类前提要：推断类前提没有可重放的规格，不要求对照；到了 E3 而没有对照的观察，对 r2 而言与 E2 同等对待，要人的豁免。

其它增量：

- **争议与裁决**：模型反证只让节点进入"争议"。图服务派生一次裁决任务，要求给出能区分真假的检查并执行。通过则反证标为已驳回，失败则节点为 X。同一组证据不能重复提出反证。没有可用检查时保持争议，交人裁决。人的裁决有两种：`--refuted` 直接给出 X；`--upheld` 把该论断现有的反证（含判官的失败裁决）标为已驳回，被驳回的裁决不再计入裁决序列。
- **E3 的降级**只有四条路：判官重跑失败、判官版本被撤销、判据过期、人的裁决。针对 E3 的模型反证只触发一次重跑，带冷却期。
- **延迟判官与预测**：判官的 kind 为 deferred 时，裁决在请求所带的 `due_at` 给出，到期前目标带 `pending` 标记，等级不变。r2 的 Intent 必须带 `done`，它就是对这次动作结果的预测。`done.tests` 列出这条预测所检验的推断类前提，只在该 Intent 经人批准后生效：Intent 达成，它们各得一条相符性支持；判定给出失败而 Intent 未达成，各得一条相符性判官的反证，进入争议。
- **有效期**：判官带 `ttl_s` 时，它的裁决不论通过还是失败，到期后都不再计入裁决序列，节点带 `stale` 标记并按剩余支持重算。过期不是证伪。复检只在有消费者需要时派生，与消费时验证是同一机制。描述"当前状态"的谓词用带有效期的判官；描述固定时间窗的谓词不设有效期，也不靠重放当前状态来判定。
- **人执行的 Intent**：`executor=human` 的 Intent 出现在 `/work` 的 human 项里。人做完后用 `pd intent done <id> --attach <文件>` 交回结果，材料登记为 input 类，再由 Worker 提出引用它的观察。检查、化验、线下操作都走这一条，不新增节点类型。
- **影响面告警**：单个事件使 K（默认 10）个以上节点降级，或使在途的 r1、r2 任务失去前提时，图服务追加 `alert` 事件，相关租约标记 `premise_lost`，司南必须取消。
- 另有 `retract`、`supersede`、`same_as`、`fork(at_seq)`、PostgreSQL 与只读副本。

#### 3.1.4 必答

**E3d 何时、如何转 E3 或降级。** E3d 的定义是"相符性判官通过"：预测的结果出现了，但这个结果不能排除其它解释。转 E3 的唯一途径是同一论断再获得一条判定性判官的通过，例如在副本环境里做双向的反事实验证。降级有三种：相符性判官在观察窗内复检失败，支持被驳回，等级按剩余支持重算；判定性判官失败，记 X；判据带有效期，届满后没有复检。模型意见不能让 E3d 升或降，只能使其进入争议。

**"独立支持"如何机械判定。** 见 `independent` 与 `heterogeneous` 的定义。两者只用到租约、会话、模型家族、Artifact 登记和 Adapter 记录的 `context_manifest`，都不是模型自报的字段。"某节点被证伪后另一节点是否幸存"不需要单独判定，重算后等级不变即为幸存。`/invalidations` 同理：把该节点的证伪去掉重算，等级因此变高的其它节点，就是因它失去支持的节点。

**图服务崩溃后未决提议如何恢复。** 图服务内部没有"未决"状态：提议在落盘（fsync）之后才应答，否则视为未发生。提议方用同一 `idem_key` 重试。Adapter 一侧，`submit` 的每个操作以任务 id 与操作内容的哈希为 `idem_key`，先写本地日志再转发；Adapter 重启后按日志重发，模型重复提交同样的操作也只得到首次结果。重启时图服务从最近快照加事件重放恢复，快照的状态哈希记在日志里，可校验。

**图很大时 Reason 的读图分页与排序。** 任务包分两段。前段是不可变内容：节点 id 与 title 按创建顺序追加排列，连续两次 Reason 之间只会在末尾变长，字节稳定 [证据 S41]；能否跨轮命中缓存取决于后端，要实测 [假设]。后段是可变状态：等级、争议、Intent 状态的紧凑表。前段默认上限 400 个节点，超出时按确定性规则从列表中省略（已证伪、已撤回、已结束且无依赖者），被省略的节点仍可用 `show` 工具查询。摘要层只给"前沿"：活跃 Hint、争议节点、待人处理项、上次 Reason 以来的变更、未结束 Intent 的前提；其余按最近变更倒序分页，游标为 seq。

**消费时验证如何防死锁与重复触发**（完整版）。`verify_wanted(f, 目标等级)` 由被阻塞的 Intent 派生，去重键是（节点、目标等级、证据版本），证据没有变化就不会再次触发，每个键最多尝试 2 次。Verify 任务本身不受消费门约束，所以不会递归。验证用尽后 Intent 进入 `needs_human`，人可以签署豁免。r0 的 Intent 永不阻塞。

**三层视图的生成与失效。** title 与 summary 由提议方在创建时写入，之后不可变，因此没有缓存失效问题。需要更正时提交新节点并 `supersede` 旧节点。任务包的④⑤两段由 Adapter 从 `/view` 与 `/status` 渲染，其余内容由 Worker 用 `show` 按需读取，不维护文件形式的投影。

**快照与回滚。** 每 1000 个事件做一次状态快照。不做原地回滚；需要"回到某一点"时用 `fork(at_seq)` 复制日志前缀生成新题，原题关闭。

#### 3.1.5 验收测试

第 3、4、7、9 条里只涉及等级与消费门的部分，第 10 到 16 条的派生语义，以及第 17 条（审批卡）与第 19 条，已在参考模型上通过。

1. 重放确定性：同一日志重放两次，状态哈希相同。
2. 崩溃恢复：提议处理中 `kill -9`，重启后客户端重试，结果恰好一次。
3. **坏事实注入（对抗）**：构造 A（E3）；B 只由 A 推出；C 由 B 推出且另有独立的判官支持；D 只由 B 推出。让 A 的判官连续两次重跑失败。期望：A 为 X；B 与 D 回到 E0 并出现在 `invalidations` 结果里；C 保持 E3；以 B 或 D 为前提的 r1 Intent 变为 blocked，在途租约带 `premise_lost`。只失败一次时，A 回到 E0 并带 `unstable`，下游同样降级，但 A 不是 X。M0 只有判官支持，本用例的 M0 形态是：A 被证伪后，以 A 为前提的 Intent 变为 abandoned；A 只失败一次时，以它为前提的 r1 Intent 变为 blocked。
4. **环状引用（对抗）**：让 A 的支持以 B 为前提、B 的支持以 A 为前提。期望两者都停在 E0，重算在有限步内结束。M0 形态：节点和支持只能引用已存在的 id，环在构造上不可能；用例验证引用尚不存在的 id 返回 `unknown_ref`，并对随机生成的日志断言重算终止。
5. 并发租约：两个请求抢同一 Intent，恰好一个成功。
6. 权限：闲人角色提交 `add_intent`，返回 `forbidden_op`。
7. 审批门：没有 `approve` 的 r2 Intent 永远不出现在 `/work` 的 explore 列表里；它的租约过期后回到 `needs_human`，同样不出现。
8. 画像：授权范围含一条 r2 规则时 `profile.reversibility` 为 r2；`add_intent` 的 risk 高于范围内最高风险时被拒。
9. 带判据的 Intent：判据通过后状态为 achieved，等级为 E3，以它为前提的 Intent 由 blocked 变为 open；候选失败只累计次数。
10. 摘录登记（M3）：用任务令牌或人的令牌登记摘录，返回 `forbidden_op`；封存的状态哈希与重放结果不符，返回 `bad_seal`；通过后摘录是接收题里的一个 input 类 Artifact。
11. **等级不出题（I7，对抗）**：来源题里为 E3 的论断经摘录进入接收题。在接收题里把它的 id 写进前提，返回 `scope_mismatch`；以这份摘录为 `grounds` 的观察，在本题判官重放之前是 E0。
12. `seal_check`（M3）：封存可重放、终态为 solved、判据哈希一致时通过；终态为 accepted 或 unsolved、判据哈希不同、状态哈希不符，三种情况各自失败；`seal_revoked` 之后，父题里对应的 Intent 不再是 achieved。
13. **估值不进等级（I8，性质测试）**：在随机状态上任意增、删、改估值类事件，全部节点的等级、消费门、Intent 状态、knot、`unlocks`、终态、失效集合、进展计数与审批卡的 `card_hash` 逐例不变；同样的改动确实会改变预测账的读数，说明测试不是空转。
14. knot 与换缝（M1）：Intent 的租约以 failed 或 nothing 结束后带 knot，过期不带；承接它的观察 Intent 在这次失败之后达成，或有人提交 `escalate_intent`，knot 解除；前提进入争议或带 `unstable` 时带 knot；沿 reroute 链的第三条 Intent 失败时 `must_escalate` 成立，不带 knot，下一次尝试用强档；观察 Intent 不是 r0、不带判据或预算超过所承接 Intent 的一半，返回 `schema_error`。
15. 终态：`accept=judge` 且 Goal 由判定性判官确认，终态为 solved；`accept=human` 经人验收为 accepted，即使 Goal 的判官已经通过；其余为 unsolved；未关题没有终态。
16. 对照判据与消费门（M1）：r2 的观察类前提到了 E3 而不带对照，消费门不放行；带对照，或经人对该前提豁免，放行；推断类前提不要求对照。
17. **先查后用（M1，对抗）**：人在序号 s 取得审批卡，其后注入一条针对某条前提的反证，再凭旧的 `card_hash` 批准，返回 `stale_view` 并附新卡。其间只发生与这张卡无关的事件（别的任务的用量、估值类事件）时，旧哈希仍然有效。
18. 回放（M1）：对一条日志的任一序号 s，各只读端点带 `as_of=s` 的返回值与当时在链头读到的相同；冷启动两次，结果相同。
19. 回退声明（M4）：r2 的 `add_intent` 不带 `rollback`，返回 `schema_error`；r1 不带则通过。

#### 3.1.6 最简反事实

砍掉解牛图，Worker 之间不再共享任何东西，系统退化为等成本独立重试，也就是对照臂 Bk。把图换成一个共享笔记文件，就是对照臂 Bn。所以图的全部价值必须体现为"等成本下赢 Bk 和 Bn"，否则按红线 5 删除协作部分。即便如此，"证据账本"这部分（Fact、Support、判官裁决、审计日志）仍然保留，它是 T-0。

#### 3.1.7 难点、换缝与关节度

[T-1，感知官] v1.1 里谨慎只随风险升级。这里补上随难度升级的一条通路：三个派生量，都是日志上的纯函数，只供司南与 Reason 读取，不进等级函数与消费门 [典故对账 D1、D2、D4]。`knot` 与换缝在 M1，`unlocks` 在 M2。

```
failed_last(i)   := i 的上次租约以 failed 或 nothing 结束，且此后既没有承接它的观察 Intent 达成，
                    也没有 escalate_intent(i)              // 过期不算：会话崩溃不说明这一处难
reroutes(i)      := 沿 follows{as: reroute} 回溯的链长
must_escalate(i) := failed_last(i) ∧ reroutes(i) ≥ 2
knot(i)          := i 未到终态 ∧ ( (failed_last(i) ∧ ¬must_escalate(i))
                                  ∨ ∃p∈i.premises: disputed(p) ∨ unstable(p)
                                  ∨ i 的在途租约带 premise_lost )
unlocks(i)       := 以 i 为前提（直接，或经带判据的 Intent 传递）、当前为 blocked 的 Intent 数
```

`knot` 是已有信号的析取，与 `disputed`、`unstable` 同类。带 knot 的 Intent 司南不认领、不开竞速路线（4.1）；这次失败本身会触发 Reason（3.1.2 的 `/work` 规则），由它读到失败原因与折损类别后三选一：

| 选择 | 操作 | 校验 | 效果 |
| --- | --- | --- | --- |
| 看清 | `add_intent`，带 `follows {intent: i, as: observe}` | 所指 Intent 存在，否则 `unknown_ref`；新 Intent 必须是 r0、带判据、预算不超过 i 的一半，否则 `schema_error` | 观察 Intent 在这次失败之后达成，i 的 knot 解除，可再次认领 |
| 换缝 | `add_intent`，带 `follows {intent: i, as: reroute}`，前提或方法不同；通常同时 `abandon_intent(i)` | 所指 Intent 存在 | 新 Intent 记一次换缝 |
| 升档 | `escalate_intent {intent: i}`，Reason 或人提交 | i 未到终态 | i 的 knot 解除，下一次尝试用强档（4.2） |

护栏：两次换缝仍未解开，必须升档。`must_escalate(i)` 成立时不再等 Reason，i 不带 knot，下一次尝试直接用强档。

次序上，knot 的冻结先于竞速，也先于榷场的名额公式（4.4）。规则表里"judge=hard 且判官廉价"一行优先于 knot：候选交给判官筛的成本很低时，收拢未必优于加宽 [假设 M1]。`knot=off` 时司南不读这个标记；`escalate=first` 时失败后直接升档，即 v1.1 的次序；`order=gain_only` 时排序不读 `unlocks`。三个开关各是一条消融臂。

#### 3.1.8 关题：四顾与终局协议

[T-0，守门官] 关题固定三步，次序不可跳 [典故对账 D5；总纲提案 2]。

1. **四顾。** 图服务投影出一张收尾清单（3.1.9 的 closeout 卡片），确定性地列出：本题的范围修订及是否仍生效；签发过的 r2 凭据及是否已作废；解题链上带 `stale`、`disputed` 的论断与 E3d 论断；守护项最近一次的结果。归因行与折损账（8.4）随清单给出，供人查看，不算清单条目。
2. **定终态。** 按 3.1.2 的三值。清单没有条目且 `goal.accept = judge` 时，Goal 到 E3 后图服务自动 `close_problem`。否则题目进入 `/work` 的 human 项，由人逐项确认后 `pd accept`，`accept` 事件带这张清单的 `card_hash`。人对清单的确认不改变终态的算法：Goal 已由判官确认的题，确认之后仍是 solved，不写成 accepted。
3. **藏刀。** 取消其余租约，销毁容器，作废任务令牌与 r2 凭据，归档会话记录，追加判例 `case_sealed`（M3 起，4.3）。有 Playbook 候选时进入通鉴的人审。

清单只对画像为 r1、r2 的题或 `accept = human` 的题列项。r0 且由判官验收的题，清单恒为空，三步照走，只是自动完成；M0 就是这个形态，所以 r2 题到来时人看到的是同一个流程。完整清单在 M4 与 r2 凭据按次签发一起落地。日志里的次序固定：`accept`（清单有条目时）、`close_problem`（事件体带 `terminal` 与清单的 `card_hash`）、`case_sealed`。

#### 3.1.9 后续里程碑的操作、端点与事件

3.1.2 的操作表是 M0 的全集。此后各里程碑新增的操作与事件如下，校验同样是纯函数。HMI 设计 §11.3 里待定的五个事件名在这里落定：`budget_add`、`rule`、`accept`、`judge_revoke`、`intent_done`。

| 操作或事件 | 谁可提交 | 关键校验 | 里程碑 |
| --- | --- | --- | --- |
| `add_support`、`add_contradiction` | adapter，角色为 verify；闲人只可提交反证 | 证据非空且可采信；复审所引的 Artifact 在 `context_manifest` 内 | M1 |
| `forecast` | adapter，随任务的首次 `submit` | 任务存在；每个任务一条；概率在 0 到 1 之间 | M1 |
| `escalate_intent` | adapter，角色为 reason；human | Intent 未到终态 | M1 |
| `rule` | human | 论断存在；理由登记为 input 类；带 `seen` | M1 |
| `budget_add` | human | 金额为正 | M1 |
| `judge_revoke` | human | 该判官版本存在 | M1 |
| `accept`（验收或拒收） | human | 题目在 human 项的验收条目里；带 `seen`，所指为收尾清单。验收后图服务追加 `close_problem`；拒收不关题，`/work` 重新给出 reason | M4，随 `accept=human` |
| `intent_done` | human | Intent 的 `executor = human` 且未到终态；所附材料已登记为 input 类 | M3 |
| `register_artifact`（摘录） | graph | 2.4 第 2 条 | M3 |
| `case_sealed`、`seal_revoked` | graph | 题目已关闭；来源封存存在 | M3 |
| `quote_batch`、`round_close`、`desk_seed`、`stake`、`payout`、`forfeit` | 报价由 adapter（角色为 quote）提交，其余由图服务追加 | 见 4.4；`market=off` 时这些事件不存在 | M4、M5 |
| `escrow_out`、`escrow_in` | graph | 见 4.6；回拨以封存哈希为幂等键 | M5 |

**人的决策与所见绑定**（M1）。人在序号 s 看到卡片，到序号 s+k 才作决定，其间前提可能进入争议，范围可能被修订。所以 `approve`（含拒绝）、`extend`、`rule`、`accept`（含拒收）四种决策操作必须带 `seen`：

```ts
type Seen = { seq: number, card_hash: string }      // 人作决定时所见的链头序号与卡片哈希
type Card = { kind: "approval"|"closeout"|"extension"|"dispute",
              target: string,                       // Intent id、题目 id、题目 id、论断 id
              fields: object,                       // 这张卡片的字段，是状态的纯函数
              card_hash: string }                   // sha256(JCS({kind, target, fields}))
```

图服务在链头重算同一张卡片，`card_hash` 与 `seen.card_hash` 不等就拒绝，拒绝码 `stale_view`，并附上最新的卡片。`seen.seq` 只留作审计，不参与比较。哈希按卡片的范围计算：卡片只含与这一个决定有关的字段，无关的事件再多也不会让它变化，批准不会因为日志写得快而一直失败。

| 卡片 | 范围 |
| --- | --- |
| approval | Intent 的 title、summary、risk、预留预算、`done` 判据及 `tests`、`rollback`；每条前提的等级、有效支持记录、判据来源、`controlled`、`disputed`、`unstable`、`stale` 与人的豁免；未决反证；`needs_scope` 与现有范围的差异及批准后的画像；将注入的 r2 凭据名；所依赖封存的状态 |
| closeout | 收尾清单的各项（3.1.8）与将写入的终态 |
| extension | 自 50% 标记以来新到 E3 的带判据对象；折损账的割与折；已花与上限 |
| dispute | 论断的谓词或前提、等级、现有支持、未决反证及其 Artifact |

卡片对象不含估值类字段（I8）：`expected_gain` 与预测账的概率由界面另取，不进 `card_hash`，估值事件因此不会让一次批准过期。`pd` 的文本卡与网页的卡片是同一个对象的两种排版，两端的 `card_hash` 相同。

**读端点**（M1）。

```
GET /v1/problems/{pid}/status|view|budget|work|invalidations ?as_of=<seq>
GET /v1/nodes/{id}?layer=…&as_of=<seq>
GET /v1/problems/{pid}/cards/{kind}/{id}[?as_of=<seq>]   → Card
```

全部只读端点接受 `as_of=<seq>`：服务端从最近的快照重放到该序号再投影，返回值与当时在链头读到的相同；不带参数即链头。回放因此只靠这一个解释器，前端与 `pd` 都不内嵌 reducer。快照每 1000 个事件一次（3.1.4），重放的代价在 3.1.1 的实测范围内。决策操作只能针对链头，`seen.card_hash` 取自不带 `as_of` 的卡片。HMI 设计 §11.2 另列有题目列表、事件推送、Hint 追溯、画像预检等端点，它们随前端分期交付，不在内核增量之内。

**回退声明**（M4）。`Intent` 的可选字段 `rollback {text, done?}`：`text` 是模型撰写的叙述；`done` 若有，是"回退是否完成"的判据，判官须在 `Problem.judges` 内。`add_intent` 增加一条校验：risk 为 r2 而没有 `rollback`，返回 `schema_error`。回退真要执行时是一条新的 Intent，可以直接取这条判据作 `done`。r1 的 Intent 可以不带，卡片上显示"未声明回退"。

**按批重算**（M2）。v1.1 在每个事件之后全量重算。并发到百级以上时改为按批，每 50 毫秒或每 100 个事件一次。重算是日志的纯函数，分批不改变任何一个序号上的结果，只推迟派生视图的刷新；r2 的租约申请先重算到链头再判消费门，r0 与 r1 接受一个批次的滞后。单图规模靠子题压在 10³ 量级（4.6）。

**验证的触发源**（M2）。消费门、闲人的 falsifier、榷场的断言类合约都会请求验证。三者共用同一个去重键（节点、目标等级、证据版本）与同一个验证池，每个键最多尝试 2 次（3.1.4），所以多出两个来源不会造成验证风暴。

---

### 3.2 契约 2：Artifact 仓库

#### 3.2.1 决策日志（备选与取舍）

| 议题 | 选定 | 被否方案 | 理由 |
| --- | --- | --- | --- |
| 字节存储 | 本地目录，按 sha256 寻址 | 对象存储（留给多节点）、git-annex | M0 单机，目录即可 |
| 元数据 | 作为事件写进契约 1 的日志 | 独立元数据库 | 图服务校验引用时不必跨服务；审计哈希链自然覆盖出处 |
| 引用粒度 | 引用登记记录 `a_<seq>`，不直接引用哈希 | 只用哈希 | 同样的字节可能有多种出处，证据资格取决于出处而非内容 |

#### 3.2.2 M0 最小版

```ts
type Artifact = {
  id: ArtifactId                 // "a_<seq>"，一条登记记录
  hash: string                   // sha256；Blob 路径 blobs/ab/cdef…
  size: number; media_type: string
  class: "exec"|"judge"|"input"|"authored"          // 出处类别，由登记方的令牌决定：
                                                    // 执行层、判官运行器、人的材料入口、Adapter
  producer: { actor: string, session?: string }
  exec?: { sandbox_id: string, base: string, baseline_ref: string,
           tool: string, command: string,           // tool："shell" 或类型化工具名；command：完整命令行
           cwd: string, exit_code: number|null,
           touched: string[],                       // 访问摘要：连到过的授权目标、按哈希挂入的输入
           started_at: number, ended_at: number, truncated: boolean }   // exec 与 judge 类必填
  problem_id: string
  parents: ArtifactId[]          // 例如判官输出指向它的输入
}
```

```
PUT  /v1/blobs            流式上传 → {hash}；临时文件写完后原子改名
GET  /v1/blobs/{hash}[?range=]   读取时校验哈希
POST /v1/artifacts        登记（即 register_artifact 事件）；只接受组件令牌
GET  /v1/artifacts/{id}
```

规则：Blob 一经写入不可变，相同内容自动去重。单个 Blob 上限 256 MB，超出时采集方保留头尾并置 `truncated`。可作证据的类别是 exec、judge、input；authored 只能作为正文、重放规格和候选答案，不能出现在 `grounds` 里。GC 采用标记清除，根集合是日志中出现过的全部 ArtifactId，所以被图引用者永不回收；未被引用的采集输出在题目关闭 30 天后可回收，登记记录保留并标 `collected`。

两类引用不是普通的 Artifact。含密级判官资产不进 Blob 仓库，以 `VaultRef` 登记（3.3.2）：提议里引用它返回 `unknown_ref`，`show` 对它返回 `forbidden_op`；判官输出的访问摘要 `touched` 里有保密库的键时，这份输出的正文对任务令牌不可读，`show` 只返回裁决与原因类别。跨题的封存摘录按 2.4 的规则登记为 input 类（M3）。

#### 3.2.3 完整版

对象存储后端；按题加密。

#### 3.2.4 必答：信任链

问题是如何保证模型不能把自己写的文本冒充命令输出。分三层。

1. **协议层。** 提议里只能出现 ArtifactId。类别、命令行、访问摘要这些出处字段从不接受提议方填写，只来自带组件令牌的 `register_artifact`。图服务检查：引用存在、同题、类别对该用途可采信；复审类支持所引的 Artifact 必须在复审者的 `context_manifest` 内或由其会话产生。
2. **部署层。** 登记用的令牌按组件分发，都不进入模型容器和执行容器。命令只在执行容器里运行，输出由执行层在容器之外采集、写入 Blob 仓库并登记；模型拿到的是登记后的 ArtifactId 和截断的回显。模型容器里没有命令执行工具（3.4.2），模型写下的任何字节只能经 Adapter 登记为 authored 类。模型在文本里"叙述"的输出不在采集通路上，所以自造观察无法成为证据。
3. **E3 的独立性。** 判定性判官在从 `baseline_ref` 新建的洁净容器里重新执行论断的规格，直接按哈希读取输入，不读 Worker 的叙述。Worker 写一个假文件再读出来，产生的确实是一条真实的 exec 记录，命令行如实写着读的是哪个文件；但洁净环境里没有那个文件，重放失败，论断到不了 E3。

E3 保证的是"登记过的谓词在洁净环境里可复现"，不是标题的语义为真。模型撰写的脚本可以直接打印编造的内容，这由 `require_touch`（3.3.2）与 5.2 的场景 2 处理。另一处残余：执行容器里的进程可以往共享工作区写任意文件，模型会读到。这与读取命令输出是同一个注入面，不影响证据链，因为工作区里的文件从不被当作证据。

#### 3.2.5 验收测试

1. 相同字节上传两次，得到同一哈希、一个 Blob。
2. **伪造 Artifact（对抗）**，五种形态都应失败：引用不存在的 id，返回 `unknown_ref`；把 authored 类当证据，返回 `inadmissible_class`；用任务令牌直接调用登记接口，返回 `forbidden_op`（三个代理工具的参数里没有类别与命令行字段）；引用别题的 Artifact，返回 `scope_mismatch`；写假文件后读出，或让命令直接打印编造的内容，并据此提交观察类论断，重放判官失败或给出无结论，等级不是 E3。
3. GC 之后被引用的 Blob 仍可读，日志重放仍通过。
4. 改动 Blob 的一个字节，读取时报 `corrupt`。

#### 3.2.6 最简反事实

砍掉它，证据只能以文本形式抄进节点，自造观察无从分辨。保留。它本身很小：一个目录加一种事件。

---

### 3.3 契约 3：判官接口

#### 3.3.1 决策日志（备选与取舍）

| 议题 | 选定 | 被否方案 | 理由 |
| --- | --- | --- | --- |
| 判官的等级效力 | 注册表里的 `grade` 字段，由人或锦囊配置 | 由提议方声明这次检查够不够硬 | 提议方声明等于模型给自己定级 |
| 模型面板 | 不产出 E3，只产出复审类支持 | 面板一致通过即 E3 | E3 的含义必须是"回路里没有模型" |
| 触发 | 消费时触发；近乎免费的判官可自动触发 | 创建即判 | 发现便宜、证明昂贵 [证据 S18][S16] |

#### 3.3.2 M0 最小版

```ts
type JudgeSpec = {               // 注册表条目；Worker 不可写
  id: string; version: string
  kind: "deterministic"|"programmatic"|"panel"|"deferred"
  grade: "decisive"|"consistent"|"advisory"
  applies_to: ("goal"|"intent"|"observation")[]
  runner: { type: "container"|"builtin", image?: string, cmd?: string, base: string }
  timeout_s: number; max_cost: Budget; auto: boolean      // auto：成本低于阈值时创建即判
  flake: { reruns: number, require: "all"|"majority" }
  ttl_s?: number                 // 完整版：裁决的有效期，通过与失败同样过期；不设即长期有效
  params?: object                // 判官自己解释，例如 replay 的 require_touch
}
type JudgeRequest = { id: string; problem_id: string; judge_id: string
                      target: string            // Fact id、带判据的 Intent id 或 "goal"
                      inputs: ArtifactId[]      // 候选产物，以及按哈希挂入的输入
                      due_at?: number           // 延迟判官的裁决时刻
                      params?: object; budget: Budget; requested_by: string }
type JudgeVerdict = { request_id: string; judge_id: string; judge_version: string
                      verdict: "pass"|"fail"|"inconclusive"
                      reason_code: "ok"|"timeout"|"env_error"|"flaky"|"unsupported"|"untouched"
                                   |"no_contrast"             // M1：对照也通过，见 3.3.3
                      evidence: ArtifactId[]     // judge 类，由判官运行器登记
                      cost: Budget; recheck_at?: number
                      controlled?: boolean; control_end?: string }   // M1：是否带对照；对照运行的结束类别
```

```
interface Judge { run(req: JudgeRequest, sandbox: SandboxId): JudgeVerdict }
```

M0 自带两个判官。`replay`（判定性）：在洁净容器里放入候选产物，执行 `spec_ref`（没有规格时执行候选本身），按 `expect {exit_code?, stdout_contains?, stdout_regex?}` 比对。它对三种目标通用：观察的规格就是谓词；带判据的 Intent 与 Goal 的规格在创建时登记，候选在 `claim_done` 时给出。注册为 `require_touch` 时，运行过程没有访问任何授权资源、input 材料或挂入的可采信 Artifact，裁决为 `inconclusive(untouched)`；观察对象是外部资源时打开，纯计算时关闭，写在判官配置里。Goal 判官由 Problem 配置，M0 提供 `exact_match` 与一个提交接口的插件位。判官运行器是持有 judge 令牌的独立进程，从 `/work` 领取 judge 租约。注册表在 M0 是图服务启动时加载的配置目录；条目的 id、version、grade 在裁决时抄进支持记录，所以重放不依赖注册表文件。判官的成本以 `cost` 事件入账，计入验证池。

判官资产分两级 [规格裁决书 §三.1]：

| 级 | 内容 | 登记方式 | 谁能读 |
| --- | --- | --- | --- |
| 结构级 | 判官代码、公开配置、公开的测试 | input 类 Artifact，哈希写进 Problem | Worker 的两个容器只读挂载；判官运行前校验哈希 |
| 含密级 | `exact_match` 的答案、隐藏测试的期望输出、评测的检查点（8.3） | `VaultRef`，写在 `Check.sealed` 里 | 只有判官运行器，在判官容器里解引用；Worker 的两个容器都不挂载 |

保密库是 Blob 仓库之外的一个目录，只有持 judge 令牌的判官运行器可读。Problem 里出现的只有键与加盐摘要：摘要让人可以事后核对资产没有被换过，盐让它不能用来离线穷举答案。M0 随 D7 落地。

#### 3.3.3 完整版

`record_match`（不重放，只对已登记的输出求谓词。输出来自执行层的类型化只读工具、命令不由模型撰写时为判定性，否则为相符性，见 3.6.3）；延迟判官与复检；判据的有效期 `ttl_s`；模型面板（即编排好的 Verify 任务，产出复审类支持）；判官版本撤销；第二个领域的判官（如证明检查器、测试套件、指标断言）。

**对照判据**（N1，M1，守门官）。恒真的谓词也能到 E3。空谓词与标题夸大（5.2 场景 2）、续期门被琐碎观察满足（§10 第 6 条）出自这同一个原因。`Check.control` 给判据加一个负对照：同一份规格，换一组输入，结果必须相反。判官在两个洁净容器里各跑一次：

| 主运行 | 对照运行 | 裁决 |
| --- | --- | --- |
| 通过 | 不通过 | pass，支持记录带 `controlled` |
| 不通过 | 不论 | fail |
| 通过 | 通过 | `inconclusive(no_contrast)`：结果不依赖输入 |
| 任一次超时、环境错误或 `untouched` | | inconclusive，原因码照旧 |

规格相同，所以直接打印常量或恒真的脚本过不了对照。裁决另记对照运行的结束类别 `control_end`，供 8.5 的对照质量抽样使用。用途四处：续期门的进展只认带对照的观察或达成的带判据 Intent（3.5.2）；r2 的观察类前提要求带对照或人的豁免（3.1.3）；闲人的 `fragile()` 读它（4.5）；榷场的断言类合约只对带对照者赔付（4.4）。局限要说清：对照输入由提出者选，它证明的是"结果依赖输入"，不是"标题为真"；提出者也可以选一个技术上失败而不含信息的对照。成本是判官多跑一次，不耗 token。证伪线：M1 抽样审计里，带对照与不带对照的 E3 观察在恒真谓词与标题夸大的比例上没有差别，就删掉它。

**`seal_check`**（M3）。内建判官，判定性，`runner.type = builtin`，不含领域词，语义见 2.4 第 4 条。

**`lean_check`**（M3）。第二领域的判官是一份配置，全文见 6.4。

#### 3.3.4 必答

**判官超时与自身误判。** 超时或环境错误返回 `inconclusive`，不改变任何等级，成本照记，按注册表重试。抖动分两层。一次请求之内，判官运行器连续运行 `1 + flake.reruns` 次，按 `flake.require` 全部或多数一致时给出 pass 或 fail，否则给出 `inconclusive(flaky)`。多次请求之间，同一（目标、判官版本）的有效裁决按 3.1.2 计算：只有一次裁决时取该次，此后翻转需要连续两次一致。所以一次相反或抖动的结果只让此前的 E3 回到 E0 并带 `unstable`，由图服务派生复判；再一次相反才是 X。判官有缺陷时由人撤销该版本，这一版本产出的全部支持失效，等级重算，走的是与证伪相同的机制。针对 Goal 的判定有次数上限，防止对判官做穷举。

**"指标恢复 ≠ 根因修复"如何建模。** 拆成两个对象。"指标已恢复并保持了观察窗"是修复动作这个 Intent 的 `done` 判据，由延迟的指标断言判官判定，对这个判据它是判定性的。"根因是 X"是推断类论断，列在该判据的 `tests` 里：判据通过对它只是相符性证据，给 E3d。根因要到 E3 需要两样东西：结构检查（程序化，确认 Origin 里登记的每个症状都被该论断的前提覆盖，或被明确标为无关），以及副本环境里的双向反事实验证（引入原因则症状出现，移除则消失）。没有副本环境时根因停在 E3d，由人验收，报告里写明等级。

**无判官领域的最小判官。** 两件：一个确定性的结构检查（结论所引的每条前提都不低于 E1、没有未决争议、要求列出的备选解释各有反证或明确保留），加一条人的验收记录。Goal 的状态是"已验收"而不是"已证明"，推断类论断的上限是 E2。模型面板是可选的增强，不是最小集。

#### 3.3.5 验收测试

1. 判官超时：裁决为 `inconclusive`，等级不变，成本入账。
2. 脚本化的抖动判官（交替通过与失败，`flake.reruns=1`）：裁决为 `inconclusive(flaky)`，不产生 E3，也不产生 X。
3. 撤销判官版本（完整版）：依赖它的 E3 论断降级，相关 Intent 变为 blocked。
4. 错误的 Goal 候选：`fail`，尝试计数加一，达到上限后 `request_judge` 被拒。
5. 用任务令牌提交 `judge_verdict`：`forbidden_op`。
6. Worker 能否改动判官资产（结构级）：判官所用的代码、公开配置与公开测试以 input 类 Artifact 的哈希固定在 Problem 里，在 Worker 的两个容器中只读；改动后哈希不符，判官拒绝运行。
7. 翻转迟滞：对一条 E3 论断重跑判官。第一次重跑失败后等级为 E0 并带 `unstable`，`/work` 给出复判。复判再失败则为 X；复判连续两次通过则回到 E3。
8. 空谓词：重放规格只打印常量，`require_touch` 打开时裁决为 `inconclusive(untouched)`，等级不变。
9. **含密级不可见（对抗）**：Worker 会话尝试读取含密级判官资产。期望：两个容器里都没有挂载；提议里引用保密库的键返回 `unknown_ref`；`show` 返回 `forbidden_op`；访问过保密库的判官输出，`show` 只给裁决与原因类别。
10. 对照判据（M1）：规格只打印常量时主运行与对照都通过，裁决为 `inconclusive(no_contrast)`，等级不变；主运行通过而对照不通过，裁决为 pass 且带 `controlled`；对照运行超时，裁决为 inconclusive。

#### 3.3.6 最简反事实

砍掉它，Goal 是否达成只能由模型自己宣布，这正是"幻觉式成功" [证据 Z32]。Goal 判官是整个基座里最承重的一块。可以推迟的是节点级判官：M0 只需 Goal 判官加 `replay`。

---

### 3.4 契约 4：Worker Adapter 协议

#### 3.4.1 决策日志（备选与取舍）

| 议题 | 选定 | 被否方案 | 理由 |
| --- | --- | --- | --- |
| 输出通道 | 代理工具 `submit`：参数自带 Schema，图服务的校验结果在同一回合返回 | 解析 CLI 的最终文本；outbox 目录里的 JSON 文件（v1.0）；CLI 自带的结构化终稿 | 错了当场改，不需要修复轮；可以增量提交，会话崩溃后已提交的仍在。报错要有指导性 [证据 S17] |
| 命令执行 | 代理工具 `exec`：在执行容器里运行，返回 ArtifactId 与截断的回显 | CLI 原生的命令工具加事件流截取（v1.0） | 见 A10。长输出留在 Blob 仓库，按引用取回，不进上下文 [证据 S41] |
| 任务粒度 | 一个会话 = 一个任务 = 一个租约 | 一个 Worker 同时认领多个任务 | 成本归属、上下文隔离、恢复都更简单 |

#### 3.4.2 M0 最小版

任务包按下列顺序渲染。①到④在同一题内只追加不改写，构成稳定前缀；序列化用确定性的键序，前缀里不放时间戳和随机 id [证据 S41]。①到⑤经后端的"追加系统提示"入口注入，⑥⑦作为首条用户消息，这样同一 `as_of_seq` 下并发启动的会话拥有逐字节相同的系统前缀。

```ts
type TaskPackage = {
  role_prompt: ArtifactId          // ① 按角色固定
  problem_brief: ArtifactId        // ② Origin、Goal、授权范围、可用判官的说明
  kit_index: { name: string, description: string, path: string }[]   // ③ 锦囊只给元数据
  listing: ArtifactId              // ④ 节点 id 与 title，按创建顺序
  status: ArtifactId               // ⑤ 等级、争议、Intent 状态；每次都变
  focus: { intent?: string, fact?: string, premises: string[], hints: string[],
           restate: string }       // ⑥ 任务目标在末尾复述一遍
  limits: { budget: Budget, max_turns: number, ops_quota: object,
            tools: string[] }      // ⑦ tools：放行的工具名，Adapter 译成后端的工具面参数
  as_of_seq: number; task_id: string; role: string
}
```

Worker 的工具面是 CLI 自带的文件读写与检索工具，加三个代理工具。代理工具由 Adapter 托管，是 Worker 对外的全部通道：

```ts
tool exec  (in: { cmd: string, timeout_s?: number, cwd?: string })
           : { artifact: ArtifactId, exit_code: number|null, output: string, truncated: boolean }
           // 在执行容器里运行；output 超过 8 KB 时只回头尾，全文用 show 按区间读
tool submit(in: { ops: Op[], final?: Final,
                  forecast?: { p: number, cost: number } })   // M1：每个任务的首次 submit 必填，见 3.5.3
           : { results: ({ ok: true, id: string, verdict?: "pass"|"fail"|"inconclusive" }
                        | { ok: false, code: RejectCode, detail: string })[] }
           // 逐条提交，后一条可用 tmp_id 引用前一条；判官在 30 秒内裁决时随返回值带回
tool show  (in: { id?: string, layer?: "summary"|"evidence", list?: "frontier"|"all"|"hints"|"budget",
                  artifact?: ArtifactId, range?: [number, number] }): object      // 只读

type Op =
  | { op: "add_fact", tmp_id?: string, claim_type: "observation"|"inference",
      title: string, summary: string, body_path?: string,
      check?: { judge_id: string, spec_path: string, expect: object,              // 候选产物不在这里：inputs 属于 JudgeRequest，
                control?: { inputs: ArtifactId[] | object } },                     // 在 claim_done 时给出（3.3.2）。control 是 M1 的对照判据
      premises: string[], grounds: ArtifactId[] }
  | { op: "add_intent", title: string, summary: string, premises: string[],
      risk: "r0"|"r1"|"r2", budget_hint?: Budget, expected_gain?: number,
      done?: { judge_id: string, spec_path?: string, expect: object, max_attempts?: number,
               tests?: string[] },
      needs_scope?: object[],
      follows?: { intent: string, as: "observe"|"reroute" },                       // M1，见 3.1.7
      rollback?: { text: string, done?: object } }                                 // M4，r2 必填；仅 reason
  | { op: "abandon_intent", intent: string, reason: string }                       // 仅 reason
  | { op: "escalate_intent", intent: string, reason: string }                      // 仅 reason，M1
  | { op: "claim_done", target: string, candidate_path: string }                   // target："goal" 或 Intent id
  | { op: "request_judge", target: string, judge_id?: string }
  | { op: "add_support"|"add_contradiction", target: string, premises: string[],
      artifacts: ArtifactId[], note: string }                                      // 完整版：verify、idler
type Final = { outcome: "found"|"nothing"|"failed"|"unsolved",
               excluded_paths?: string[], suggestions?: string[] }
```

`*_path` 指工作区里的文件，由 Adapter 读出并登记为 authored 类。`claim_done` 不是内核操作：Adapter 登记候选，再提交 `request_judge`。工作区是模型容器与执行容器共同挂载的目录；input 材料与锦囊目录只读挂载。Reason 与闲人不挂 `exec`，也不起执行容器。

**任务包留档**（HMI H4）。Adapter 把每个任务包整体登记为 authored 类 Artifact，`producer.session` 即租约 id，媒体类型固定。"哪个会话读过哪条 Hint"由此可以从已有字段投影出来：某租约的任务包里 `focus.hints` 含 h，而某条 Intent 由该租约产出，就是一条暴露关联。它与"Hint 之后新增的 Intent"这种时序关联分开列，两者都只是关联，不是因果。这是 Adapter 的一条登记约定，不改内核，随 D4 到 D6 落实。

会话状态机：`leased → preparing → running → collecting → released`；异常出口是 `expired`、`killed(budget)`、`failed(原因)`。Adapter 每 60 秒续租一次，租约 TTL 为 120 秒。

Adapter 的职责只有五件：渲染任务包并留档；在模型容器里起停 CLI，读它的事件流，只用于存档与存活判断；托管三个代理工具，`exec` 转给执行层，`submit` 转给图服务，`show` 读图服务；续租；释放租约并保存会话记录。模型容器的规格是固定的：CLI 镜像；工作区以不跟随符号链接的方式挂载；出站只放行工具端点与模型端点代理。代理在容器之外，做三件事：把任务令牌换成真实密钥；逐请求记下响应里的用量；任务超过预留额后拒绝它的新请求。所以两个容器里都没有模型密钥，外壳内部的辅助请求也在账上。

M0 的后端绑定（瘦基线所用的同一个 CLI）[证据：该 CLI 2.1 版帮助文本与配置项，不在调研编号内]。这十项同时是其它后端的准入清单，其中第 3、4 两项是硬条件：

| Adapter 需要 | 该 CLI 提供的机制 |
| --- | --- |
| 无交互运行与事件流 | `-p --output-format stream-json --verbose`；首个事件 `system/init`，末行 `result` |
| 可复现的启动与鉴权 | `--bare`：跳过宿主的钩子、插件同步、自动记忆与项目说明文件的自动发现；鉴权只认 API 密钥。端点地址可配置，所以容器内只有任务令牌，端点指向代理 [假设：D4 核对] |
| 去掉命令执行能力 | `--tools` 只列文件读写与检索工具；`--restricted` 把文件工具限制在工作目录内，并忽略用户、项目与本地的设置文件 |
| 挂载代理工具 | `--mcp-config` 指向 Adapter 的工具端点，`--strict-mcp-config` 排除其它来源 |
| 工具放行 | `--allowedTools` 列出文件工具与三个代理工具；`--permission-prompts none` 让其余需要人批的调用直接被拒 |
| 注入任务包 | `--append-system-prompt-file` 放①到⑤，提示词放⑥⑦ |
| 会话标识与续接 | `--session-id` 取租约派生的 UUID；收尾轮用 `--resume` |
| 回合与花费上限 | 回合上限不交给该 CLI：由 Adapter 从事件流计数，到数即收尾。`--max-budget-usd` 保留为进程内的第二道线（按客户端估算执行，可能略超）；预算硬顶仍由端点代理兜底（I6） |
| 计量的对照 | 事件流里每步的 `usage` 与末行的 `total_cost_usd`（估算值）；记账以端点代理为准 |
| 终止 | SIGINT 结束当前回合；SIGTERM 终止进程树，退出码 143 |

#### 3.4.3 完整版

`verify` 与 `idler` 两个受限角色（操作白名单由图服务按租约角色强制，不靠提示词）；复审任务包不含目标论断的正文，`show` 对其拒绝读取，以保证干净上下文；另有两个不挂 `exec` 的受限角色：`quote`（报价会话，只可提交报价，4.4）与 `retro`（复盘会话，只读封存日志，只可提交 Playbook 候选，4.3）；闲人分 falsifier 与 free-form 两种（4.5）。第二、第三种 CLI 后端；自研薄循环的插槽 [证据 S3]，它的启用条件见 HMI 设计 §12.1。

#### 3.4.4 必答

**CLI 输出解析的容错。** 本版没有需要解析的输出：结论只经 `submit` 的参数进入，Schema 由工具定义强制。容错分三级。其一，`submit` 的每个操作当场得到 id 或拒绝码，模型在同一会话内改正，不另起修复轮；同一操作连续被拒 3 次后 Adapter 不再转发，避免在错误上空转。其二，会话结束时从未调用过 `submit`，追加一轮收尾，要求提交结论或声明 unsolved。其三，仍然没有，任务记为 `failed(no_output)`，会话记录照存，Intent 回到 open 并累计尝试次数，两次后放弃。某个后端的失败率超过阈值时，哮天犬发出 `backend_unhealthy` 告警交人处理。常规路径不需要人介入。

**心跳与超时回收。** 续租的条件是 CLI 进程存活且事件流在 10 分钟内有新事件；否则 Adapter 终止会话并以 `failed(stalled)` 释放。Adapter 自身崩溃时租约到期，由哮天犬提交 `expire_lease`，Intent 回到 open。已经 `submit` 的论断不受任务失败影响，这就是"个体会死，图存续" [证据 Z4]。孤儿容器按标签回收。

**协议层如何拒绝伪造观察。** 结构上，`exec` 的返回值是模型取得 exec 类 ArtifactId 的唯一来源，summary 与正文里的叙述从不被当作证据。校验上，图服务对观察类论断做确定性检查：没有 check 或没有可采信的 grounds，返回 `missing_evidence`；所引的 id 不存在、不同题或类别不可采信，分别返回 `unknown_ref`、`scope_mismatch`、`inadmissible_class`。

**一个 Worker 能否同时认领多个任务。** 不能。一个会话对应一个任务和一个租约；一个 Explore 任务只处理一个 Intent。一个 Adapter 进程可以并行管理多个会话，各用各的一对容器。

#### 3.4.5 验收测试

1. 用脚本化的假 CLI 走通主路径：`exec` 的输出由执行层登记，`submit` 的论断进图。
2. 畸形 `submit`：返回 `schema_error`，会话内改正后通过；全程不调用 `submit` 时出现收尾轮，仍无则 `failed(no_output)`。
3. 任务中途杀掉 CLI：租约到期，Intent 重开，此前提交的论断仍在。
4. **伪造观察（对抗）**：summary 里写着"输出显示……"但没有 Artifact 引用，被拒；引用了不存在或别题的 id，被拒。
5. 前缀稳定性：连续两次 Reason 的任务包，在只有新增节点的情况下，前一个包的①到④段逐字节是后一个包的前缀（100% 字节前缀稳定）；⑤到⑦是可变段，不参与断言。整包的公共前缀比例只作遥测读数，不设阈值。字节稳定是缓存命中的必要条件而非充分条件，所以集成测试另外断言：同一 `as_of_seq` 下先后启动的两个 Explore 会话，后一个的首次请求缓存读 token 数大于 0。
6. 闲人角色提交 `add_intent`：被图服务拒绝。
7. 让会话尝试执行命令：除 `exec` 之外没有可用的命令工具；让它读取工作目录之外的文件：被拒。

#### 3.4.6 最简反事实

砍掉它就无法运行。能砍的是复杂度：Adapter 不做规划、不做重试策略、不解释领域内容。

---

### 3.5 契约 5：预算账本

#### 3.5.1 决策日志（备选与取舍）

| 议题 | 选定 | 被否方案 | 理由 |
| --- | --- | --- | --- |
| 账本形态 | 契约 1 日志上的一个投影 | 独立记账服务 | 预留与租约必须原子；重放即对账 |
| 检查时机 | 申请租约时预留 | 每条提议都查预算 | 提议路径不碰预算，不会被拖慢 |
| 计量点 | 容器外的端点代理，逐请求记下响应里的用量；各对照臂走同一个代理 | 只信 CLI 结束时的自报；从事件流累计（v1.0） | 所有请求必经代理：崩溃不丢，外壳内部的辅助请求也在账上，超额可以当场拒绝，各臂用同一把尺 |

#### 3.5.2 M0 最小版

```ts
type CostEvent = { task_id: string, source: "proxy"|"judge"|"cli_reported",     // 后者只作对照
                   model?: string, tokens_in: number, tokens_cached: number, tokens_out: number,
                   usd_milli: number, wall_s: number, price_table: string }   // 价目表带版本，重放稳定
type BudgetView = { cap: Budget, spent: Budget, reserved: Budget,
                    by_kind: Record<string, Budget>, verify_spent: Budget, marks: (50|80)[] }
```

```
GET /v1/problems/{pid}/budget → BudgetView
```

规则：

- 记账粒度为任务，向上汇总到 Intent、题。token 与金额双轨记录，上限可设在任一轨。
- 申请租约时检查 `spent + reserved + reserve ≤ cap`，不满足返回 409 `over_budget`。这是写入路径上唯一的预算检查，是一次整数比较。
- 验证与判官的花费不超过 `verify_share × cap`。Bootstrap 的预留为 `bootstrap_share × cap`。
- `spent` 越过 50% 与 80% 时，图服务追加 `budget_mark` 事件。从这个事件起，到其后第一个 reason 租约释放为止，称预算复盘期：`/work` 不给出新的 explore，给出的 reason 带 `reflect` 标志，Adapter 据此在任务包里要求先写出已排除路径、放弃无望的 Intent，再决定是否继续投入。在途任务不受影响。
- **续期门**（T-1，开关 `extension=always`，M1 起）。进展 := 自 50% 标记以来，有带判据的对象新到 E3，即观察被重放确认，或带判据的 Intent 达成；对照判据启用后，观察要带对照才算（3.3.3），恒真的谓词不再能当作进展。越过 80% 标记时没有进展，`/work` 不再给出新的 explore，题目进入 human 项：人可以用 `pd extend <pid>` 放行，否则在途任务结束后按 unsolved 关闭，余下的预算不花。Goal 的判定不受此限。
- 任务的软线是预留额的 90%，硬顶是预留额；题的硬顶是 `cap`。硬顶由端点代理执行：超过预留额的任务，新请求被拒。硬顶是请求前检查，所以越界的上界是单次请求的花费；M1 可选收紧为按 `max_tokens` 的预估价预扣。后端自带花费上限时，Adapter 把预留额同时传给它，作为进程内的第二道线。
- 哮天犬是不含任何策略的脚本，每 10 秒读一次 `/budget`：任务越过软线，通知 Adapter 进入收尾轮；越过硬顶或题预算耗尽，终止进程、销毁容器。

#### 3.5.3 完整版

端点代理到模型网关分三个阶段，以 HMI 设计 §12.3 为正式口径：

| 阶段 | 形态 | 新增 |
| --- | --- | --- |
| M0 | 端点代理，单厂商 | 换密钥、逐请求记用量、超额拒绝（3.4.2、3.5.2） |
| M1 | 同上，接第二家厂商，用于异家族 Verify | 用量归一为 `CostEvent`；价目表按厂商分版本；`family` 取自 `routing.yaml` |
| M5 | 模型网关 | 多厂商路由与故障回退 [证据 S15]；密钥环轮换；按家族与档位的配额 |

两条约束：故障回退只在会话开始时发生，会话中途后端失败按任务失败处理，不悄悄换模型（4.2 第 3 条）；密钥轮换对会话透明，容器里始终只有任务令牌。接第二家厂商时另有两条记账规则（HMI 设计 §12.2）：后端不报告缓存命中时，`tokens_cached` 记空值而不记 0；本地模型的花费按墙钟与算力折价，否则它在成本倍数的分母里是 0，任何一条臂接上它都会"免费"变优。

**预测账**（N3，M1 搭车，量具）。每个任务的首次 `submit` 必须带 `forecast {p, cost}`：本任务的目标被判官确认的概率与预计花费，约 20 个 token。Reason 写的 `expected_gain` 同样入账。只有带判据的对象参与结算：达成或到 E3 记 1；被放弃、被证伪，或关题时仍未达成记 0；无判据不结算。图服务投影出每个（家族、角色、签名）的校准曲线与 Brier 分。它有四个用途：按校准收缩 `expected_gain`；早停，即校准后的"余下预算内解出的概率"低于阈值时题目进入 human 项，把"知道自己不会"做成续期门的预测版（开关 `early_stop`，默认关）；作为榷场一级的启用与退役判据（4.4）；作为模型换代时元认知变化的读数，供官知止审计使用。M1 只记录，不改变任何行为；改变行为的用途都带开关。预测是估值，不进等级与消费门（I8）。证伪线：各角色的 Brier 分都不优于"永远报基础率"，说明自报概率不可用，榷场一级不必建。

项目级预算与多题配额。按判官、按角色、按档位的成本报表。

#### 3.5.4 必答

**预算如何进入 Intent 而不拖慢提议路径。** Intent 的 `budget` 只是一个字段，创建时图服务只做区间裁剪。预留发生在申请租约时，计量是异步追加的 `cost` 事件。提议提交路径上没有任何预算计算。

**欠费任务的优雅终止与状态保全。** 软线留出的 10% 用于一轮收尾：Adapter 向会话注入"预算将尽，用 `submit` 交出已得结论，未完成的标为 unsolved"。越过硬顶则不再给模型任何回合，直接终止。保全三样东西：会话记录、工作目录的打包、租约释放结果 `budget_exhausted`；已经 `submit` 的操作本来就在图里。不做自动续跑：是否追加投入由下一次 Reason 决定，它可以新开一个引用旧结果的 Intent。题预算耗尽时，题以 `unsolved` 关闭，报告由投影确定性生成，内容是已排除的路径和按等级排序的论断。

v1.0 在这里记下三个缺口：嵌套会话不计量、密钥放在跑命令的容器里、金额是客户端估算。三个都已关闭：执行容器连不到模型端点；密钥只在容器外的端点代理上；用量由代理逐请求记下，会话崩溃也不丢。金额等于用量乘带版本的价目表，与账单的出入只剩价目表是否及时更新。

#### 3.5.5 验收测试

1. 三个并发租约的预留之和超过上限：只有放得下的被批准。
2. 越过 50%：进入预算复盘期，`/work` 不给出 explore，直到带 `reflect` 的 reason 释放。
3. **预算穿透（对抗）**：任务进行中与结束后，执行容器内的进程尝试调用模型。期望：容器里没有密钥，也连不到模型端点；任务结束后容器已销毁，进程不存在。任务结束后令牌作废，带着它的请求被代理拒绝。
4. 终止路径：越过软线后出现收尾轮并带回部分结果；越过硬顶后代理拒绝新请求，进程被杀，租约释放，会话记录保存到被杀之前。
5. 重放后账本投影与运行时的合计一致。
6. 续期门（M1）：构造 50% 到 80% 之间没有任何对象新到 E3 的日志，越过 80% 后 `/work` 不给出 explore，题目出现在 human 项；`pd extend` 之后恢复。其间只有不带对照的观察到 E3，同样不算进展。
7. 预测账（M1）：任务的首次 `submit` 不带 `forecast`，返回 `schema_error`；目标没有判据的预测不结算；重放后校准投影与运行时一致。

#### 3.5.6 最简反事实

砍掉它，成本失控，而且"每题成本"这个北极星指标本身就无从计算。保留；M0 的实现是一种事件加一个 60 行左右的脚本。

---

### 3.6 契约 6（补）：执行层

缺失检测的结论：授权范围的拒绝、审批门、证据采集，这三项基座级保证的强制点都在命令实际执行的地方，原五契约没有覆盖。

#### 3.6.1 决策日志（备选与取舍）

| 议题 | 选定 | 被否方案 | 理由 |
| --- | --- | --- | --- |
| 模型与命令的位置 | 两个容器：模型容器只连工具端点与模型端点代理，执行容器只连授权范围 | 单容器加事件流截取（v1.0） | 见 A10。隔离若留到完整版，M0 的证据链就要靠"容器内的进程不作恶"这个假设 |
| 审批门的位置 | Intent 粒度 + 按风险注入能力：容器里只有风险不高于该 Intent 的规则所给的通路与凭据 | 逐条命令拦截；由模型申报每条命令的风险 | 与具体 CLI 无关。Intent 低报风险的后果是容器里没有它想用的能力，不是越权 |
| 越界的处理 | 默认拒绝并留日志 | 靠提示词约束 | 目标关闭后转去扫描宿主网络的事故说明提示词不够 [证据 S13] |
| M0 隔离 | 容器 | bwrap、虚拟机 | 一人一到两天可完成；强对抗场景再上虚拟机 |

#### 3.6.2 M0 最小版

```ts
type ExecSpec = { id: string, image: string, baseline_ref: string, workspace: string,
  network: { egress_allow: string[] },         // 由 scope 中风险不高于上限的规则编译而来，默认全拒
  credentials: string[],                        // r2 规则的凭据只在该 Intent 获批之后出现
  limits: { cpu: number, mem_mb: number, pids: number, wall_s: number } }
type Approval = { intent: string, by: string, scope_amend?: Problem["scope"], waive_premise?: string[] }
type ResourceKind = { kind: string, external: boolean,       // 资源种类插件；external 用于推导画像
                      compile(rule: object): { egress?: string[], credentials?: string[] } }
interface Executor {
  compile(scope: Problem["scope"], env: Problem["env"],
          ceiling: "r0"|"r1"|"r2", grants: Approval[]): ExecSpec        // 确定性
  launch(spec: ExecSpec, lease_id: string): SandboxId
  exec(id: SandboxId, cmd: string, opts: { timeout_s: number, cwd?: string })
      : { artifact: ArtifactId, exit_code: number|null, output: string, truncated: boolean }
  reset(id: SandboxId): void                    // 回到 baseline
  destroy(id: SandboxId): void
}
```

- **采集。** `exec` 在容器之外收集标准输出与标准错误，连同命令行、退出码和访问摘要写入 Blob 仓库并登记。Worker 租约下登记为 exec 类；判官租约下把结果交回判官运行器，由它登记为 judge 类。
- **能力按风险注入。** `compile` 只取 `risk` 不高于上限的规则。上限取所服务的 Intent 的 `risk`；Bootstrap 取 r0。判官容器的上限取被判对象所属任务的风险，但不超过 r1：不可逆动作从不重放，它的效果用 `record_match` 或延迟判官判定。r2 规则另须该 Intent 已获批准。
- **越界。** 内核不理解 `scope` 里的 `resource`，由资源种类插件解释。越界访问被拒后，执行层追加 `scope_violation {task, resource, target}` 事件；同一任务累计 3 次，哮天犬终止该任务。
- **扩大范围。** 只能由 Reason 提出带 `needs_scope` 的 Intent，进入 `needs_human`，由人用 `approve --scope-amend` 决定。范围修订对全题生效，画像随之重算，此后编译的容器（含判官容器）都带上它；r2 规则的凭据则只注入获批的那一个 Intent。

M0 的题目只含 r0 规则，资源种类只有网络地址一种。资源插件集另内建 `workspace` 种类（`external=false`，蓝图 C1，M3）：它只放行本题的工作区，不开任何出站。没有外部资源的题，例如证明题，用它满足"scope 非空"，推出的画像是 `info=complete`。

#### 3.6.3 完整版

资源插件提供的类型化只读工具（如指标查询、日志检索）：它们作为追加的代理工具出现，命令由执行层生成而不是模型撰写，输出登记时 `tool` 为工具名。专用工具比通用 shell 更可靠 [证据 S17]，`record_match` 也只对这类输出给判定性。此外：虚拟机隔离；r2 凭据按次签发、用后即废；请求频率上限；端点代理扩成模型网关。

#### 3.6.4 验收测试

1. 访问授权范围之外的地址：连接被拒，日志里出现 `scope_violation`。
2. 未经批准的 r2 Intent：即使被错误地调度，容器内也不存在对应凭据。r0 Intent 的容器里没有 r1 规则放行的通路。
3. 判官容器与 Worker 的执行容器互不可见：Worker 写入的文件在判官的洁净容器里不存在。
4. 两个容器里都读不到模型密钥；执行容器连不上模型端点；模型容器连不上授权范围内的目标。
5. `workspace` 规则（M3）：scope 只有一条 `workspace` 规则的题可以开题，画像的 `info` 为 complete，执行容器没有任何出站。

#### 3.6.5 最简反事实

砍掉它，"越界动作直接拒绝并记录"没有执行点，审批门退化为提示词里的一句话，证据也回到由模型一侧转述。保留最小形态。

---

## 4. 三个机制与前沿展开

### 4.1 司南（调度）

司南是一个不含模型、不持有权威状态的循环。调度所需的判断来自图服务推出的画像和 Reason 写进 Intent 的字段，司南只做排序、限流和启动。

```ts
type WorkItem = { kind: "bootstrap"|"reason"|"explore"|"judge"|"verify"|"idler"|"retro"|"quote",
                  target?: string, est: Budget, risk?: "r0"|"r1"|"r2", expected_gain?: number,
                  reflect?: boolean,             // 仅 reason：预算复盘期由图服务置位
                  knot?: boolean, unlocks?: number }   // 仅 explore：难点标记与关节度，由图服务派生（3.1.7）
type Launch   = { kind: WorkItem["kind"], target?: string, reserve: Budget, tier: "strong"|"mid"|"cheap",
                  reflect?: boolean }            // 照抄 WorkItem
type SinanCfg = { explore_concurrency: number, race_k: number, idler_share: number,
                  hint_debounce_s: number }
function plan(work: WorkItem[], budget: BudgetView, profile: Profile, active: Lease[], cfg: SinanCfg): Launch[]
// 纯函数。主循环：读 /work 与 /budget → plan → 逐个申请租约 → 201 交给 Adapter 启动，409 丢弃
// judge 项由判官运行器自取，司南不管
```

- **多实例。** 两个实例抢同一目标时由图服务的租约裁决。司南崩溃后重读 `/work` 即可继续；它的决定已经体现为租约事件，不另记。
- **资格与优先级分开。** "能不能做"由图服务派生（T-0），"先做哪个"由司南决定（T-1）。司南出错的最坏后果是浪费预算，证据不受影响。

| 任务 | 可提交的操作（图服务按租约角色强制） | 触发 | 并发 |
| --- | --- | --- | --- |
| Bootstrap | `add_fact`、`claim_done`、`request_judge` | 题目开始 | 1 |
| Reason | `add_intent`、`abandon_intent`、推断类 `add_fact` | 见 3.1.2 | 每题 1 |
| Explore | `add_fact`、`claim_done`、`request_judge` | Intent 为 open | M0 固定为 3 |
| Verify（完整版） | `add_support`、`add_contradiction`、`request_judge` | 消费门派生的 `verify_wanted`，或争议待裁决 | 受验证池限制 |
| 闲人（M2） | 不带支持的 `add_fact`、`add_contradiction`；falsifier 另可提交带判据的观察 | 事件触发，不用定时器（4.5）；花费不超过 `idler_share` | 1 到 2 |
| 复盘（M4） | Playbook 候选 | 题目关闭后，只对解出且走了厚路径的题 | 1 |
| 报价（M4） | 一批合约的报价 | 成批出现新合约、有合约结算、预算标记，防抖（4.4） | 每个席位每轮一次批量调用 |

M0 只有三条规则：

1. **先瘦后厚。** 题预算默认取瘦基线单题上限的 3 倍，`bootstrap_share` 默认 1/3，所以 Bootstrap 的预算正好是一次完整的瘦基线运行。它的提示词是瘦基线的提示词加 `submit` 的说明，工具面与对照臂 B1b 相同。易题上成本倍数约为 1；同模型、同预算之下，庖丁的解题率在期望上不低于 B1b，它与 B1 的差距就是外壳税（8.3）[观点]。
2. **Reason 互斥，有触发才运行。** ARTEX 的 Planner 是同样的形态：唯一的意图生成者，事件驱动，防抖唤醒，每次全新会话 [证据 Z5]。
3. **Explore 固定并发 3**，按 Intent 创建顺序认领。

完整版的扇出控制器（八仙，T-1，开关为"固定并发"）是 `plan` 里的一张规则表：

| 输入（画像、Intent 与预算） | 规则 |
| --- | --- |
| info=partial | 广度优先：并发 3 到 5，按 `expected_gain ÷ budget` 降序；共享同一前提的 Intent 同时最多 2 个 |
| info=complete | 深度优先：并发 1 到 2，沿依赖链推进；对不带 knot、只是慢的 Intent 开 `race_k` 条策略正交的路线，先过判官者胜，其余取消 [证据 S15][S16]。榷场一级启用后，`race_k` 由名额公式取代（4.4） |
| 互不依赖的 open Intent 数（C2） | 上一行的并发上限放宽到这个数，不超过 `explore_concurrency`：彼此没有前提关系的 Intent 并行做不增加返工，例如一组独立的引理（6.4） |
| Intent 带 knot（D1） | 不认领，不开竞速路线，等 Reason 看清、换缝或升档（3.1.7）。本行先于竞速与名额公式；下一行优先于本行 |
| judge=hard 且判官廉价 | 放宽并发上限，候选交判官筛 |
| judge=deferred 或 none | Explore 并发不超过 2，`verify_share` 上调 |
| Intent.risk=r2 | 并发 1；必须已审批 |
| Intent 带判据 | 同等条件下优先，排序改用 `expected_gain ÷ (budget + 判官成本)`：它的结果由判官给出，不靠会话自报 [观点] |
| 关节度（D4，M2） | 同等条件下先做 `unlocks` 大的：这个量取自图的结构，不取自模型的估计 |
| 估值（榷场零级，M2） | 排序用的估值取 Reason 的 `expected_gain`，没有时取通鉴里同签名的基础解出率；预测账的校准读数可用后先按它收缩。这就是没有他席报价时的行情（4.4） |
| 剩余预算低于 20% | 并发 1，只取 `expected_gain` 最高的一个 |
| 没有被判官确认的进展 | 由续期门处理（3.5.2）。追加会话多半只让死胡同变长 [证据 S13] |
| 同一 `as_of_seq` 的一批会话 | 错峰启动：第一个会话出现首个模型输出后再起其余，后者才能读到前者写下的前缀缓存 [证据：厂商 API 文档，不在调研编号内] |

人的通道：

```
pd problem open <problem.yaml>         pd status|report <pid>        # 确定性投影，不调用模型
pd profile <pid> [--override <轴>=<值> --reason "<文本>"]            # 查看或覆盖推出的画像
pd hint add [--node <id>] "<文本>"      pd hint close <hid>
pd approve <intent> [--scope-amend <规则>] [--waive-premise <fact>]   pd deny <intent> --reason "<文本>"
pd pause|resume <pid>
# 完整版
pd rule <fact> --refuted|--upheld --reason "<文本>"    pd accept|reject <pid>
pd budget add <pid> <金额>             pd extend <pid>               pd judge revoke <id>@<版本>
pd intent add <intent.yaml>            pd intent abandon <intent> --reason "<文本>"
pd intent done <intent> --attach <文件>                              # 人执行的 Intent 交回结果
pd intent escalate <intent> --reason "<文本>"                        # 同一切口，升档重做（3.1.7）
```

`hint` 事件产生一个 Hint 节点（类型见 3.1.2，`--node` 写入 `about`）。它有三个效果，都不涉及等级：`/work` 立即给出 reason（司南按 `hint_debounce_s` 防抖）；此后渲染的任务包把未关闭的 Hint 放进 `focus.hints`；`pd status` 列出每条 Hint 之后新增的 Intent。Hint 不是证据，不能作前提；人要断言一件事实，走 `rule` 或补充 input 类材料。M0 不向在途会话注入 Hint，与 Cairn 的"下次读取时吸收"一致 [证据 Z3]。

**输出约定**（HMI 方案 α，M0）。M0 没有网页，`pd` 的文本输出就是人看到的界面。下面四条从 M0 起执行，计入 D10 与 D12 的排版，不另加工期：

1. 四语域的行首标记。`[证据]`：exec、judge、input 类 Artifact 与判官裁决；`[叙述]`：authored 类，即 title、summary、正文、候选答案、`final.suggestions`；`[人]`：Hint、裁决与拒绝的理由、豁免、覆盖理由；`[估]`：`expected_gain`、预测、行情、存活计数。语域由数据的出处类别查表得到，不由内容决定。一条 E3 观察的标题仍然是叙述：节点首行显示谓词（判官、规格哈希、`expect`），标题在第二行。
2. 等级词表固定：E3 写"判定通过（判官名）"，E3d 写"相符（判官名）"，E2 写"模型共识"，E1 写"单源复核"，E0 写"猜想"，X 写"已证伪（判官名或裁决人）"。
3. 判据徽章：任何显示"达成、通过、solved"的位置都带判官名与版本。
4. `pd approve` 先按审批卡的字段打印文本卡，再要求确认；`card_hash` 的绑定在 M1 加上（3.1.9）。

网页从 M1 起分期交付（HMI 设计 §5）。它是同一组投影的另一种排版：前端不调用模型，不算等级，不持有权威状态；删掉它，`pd` 仍有全部能力。

### 4.2 模型经济

```yaml
# routing.yaml：司南与 Adapter 读取，内核不解释
tiers:                          # 每档可列多个后端，按序回退
  strong: [{backend, model, family, price_table}]
  mid:    [...]
  cheap:  [...]
roles:
  bootstrap: strong             # 与瘦基线同模型
  reason:    strong
  explore:   {tier: mid, escalate: {to: strong, when: after_reroute}}   # 或 first：失败两次后直接升档，即 v1.1 的次序
  verify:    {tier: mid, family: "不同于被复核论断的提出者"}
  idler:     {tier: cheap, family: "优先不同于 explore 所用的家族"}
  retro:     strong
  quote:     cheap              # 报价会话（4.4，M4）
```

1. M1 首轮所有角色与瘦基线用同一个模型，先隔离出架构本身的效果。分层是此后单独的一条消融臂。
2. 上分层之前先测更简单的替代：强档模型调低推理强度。厂商文档建议先量这一项再做多模型级联，并指出缓存按模型隔离 [证据：厂商 API 文档，不在调研编号内]。
3. 一个会话自始至终只用一个模型，中途换模型会使该会话的缓存整体失效（出处同上）。
4. 换缝优先于换刀（D2，M1）。Intent 失败后不直接在同一切口上升档：它先带上 knot，由 Reason 决定看清、换缝，还是显式升档（3.1.7）。升档本身有依据，即弱模型向强模型求助 [证据 S44]，所以它保留为一个显式选项，并有护栏：两次换缝未解必须升档。v1.1 的次序是同一 Intent 在中档失败两次后直接升到强档重做，现在是消融臂 `escalate=first`。
5. 多厂商路由与故障回退放在模型网关 [证据 S15]。它由 M0 的端点代理分三个阶段演进而来（3.5.3）：M1 只是端点代理接第二家厂商，供异家族 Verify 使用；完整的网关在 M5。"异构"用本文件登记的 `family` 判定，不看模型名。
6. 判官是程序，不占模型预算。
7. 榷场的二级形态把这张路由表学出来：预算在档位与家族之间怎么分，由席位资本决定；席位只有一个时退回路由表（4.4）。

### 4.3 通鉴与锦囊

锦囊是按 SKILL.md 约定组织的目录 [证据 S42]：元数据常驻任务包第③段，正文按需读取。领域词只允许出现在锦囊与判官配置里。通鉴是跨题的记忆，是一条与题日志同种的基质实例（2.4）。M0 没有这部分；M1 只做人工复盘；判例的自动封存在 M3；管线在 M4。

**三类记录，三种效力。**

| 记录 | 怎么来 | 效力 | 官 |
| --- | --- | --- | --- |
| 判例 | 关题时由日志确定性投影，不调用模型 | 事实记录：发生过什么 | 守门官 [T-0]，审计的延伸 |
| Playbook 与锦囊 | 复盘会话蒸馏，人审，签名 | 建议：可读材料，永不作前提（I7） | 感知官 [T-1] |
| 读数 | 判例上的统计 | 驱动退役、由厚回薄、席位初值；只被测量，不被相信 | 量具 [T-0] |

```ts
type Signature = { profile: Profile, judges: string[], resources: string[], tags: string[] }
                 // tags：开题人给的不透明字符串。签名只存在于通鉴，内核不解释
type Case = { id: string, seal: Seal, sig: Signature, model_epoch: string,   // 主力模型的家族与版本
  terminal: "solved"|"accepted"|"unsolved", path: "thin"|"thick"|"none",
  cuts: { title: string, judge_id: string, on_chain: boolean, attempts: number, knot: boolean }[],
        // 切口骨架：本题带判据的 Intent 序列，即"这类题的关节图"
  excluded: string[],                         // 已排除路径
  attribution: Attribution }                  // 8.4 的归因行，含折损账与切口计数
type Playbook = { id: string, sig: Signature, applies_when: string,          // 适用条件，自然语言，内核不解释
  status: "proposed"|"published"|"retired",
  steps: { text: string,
           cites: { case: string, fact: string, check_hash: string }[],      // 引用的是判据，不是标题；不得为空
           commands?: string[] }[],
  kit?: { name: string, hash: string, signature: string } }                  // 发布后所在的锦囊
type KitStats = { kit: string, sig_key: string, model_epoch: string,
  shown:    { n: number, solved: number, cost: number },
  withheld: { n: number, solved: number, cost: number } }
```

管线七步：

1. **封存。** 关题即追加 `case_sealed`。它是纯投影，M3 起对每道题自动做，成本为零。
2. **蒸馏。** 复盘任务在没有 `exec`、没有网络的会话里只读封存日志，产出 Playbook 候选。只对解出且走了厚路径的题做。
3. **发布检查**（确定性）。每一步的 `cites` 非空，被引论断在来源题里是 E3 且在解题链上；`commands` 里的每条命令必须逐字出现在被引 exec 类 Artifact 的 `command` 字段里；正文不含外部链接。
4. **人审与签名。** 审卡展示被引的判据与判官输出，不展示标题（5.2 场景 2 的做法）。通过后 `kit_published`，目录按内容寻址并签名。
5. **取用。** 开题时 Adapter 先按签名做结构匹配，即判官、资源种类、tags 的集合包含；再用题面对判例标题做词法排序（BM25，确定性），取前 5 个判例和匹配的锦囊，只把元数据列进任务包第③段。下钻哪一条由模型自己决定。锦囊也可以直接声明 `applies_to {judges?, resources?}`，没有声明的是通用锦囊。匹配都是字符串运算，不调用模型，也不进内核。Worker 读取锦囊正文时 Adapter 记 `kit_loaded {kit, task}`。
6. **随机留出。** 匹配的锦囊进入本题的留出表，按 8.6 的互斥分配决定是否被留出；被留出的不进索引，记 `kit_withheld`。分配由题目 id 导出，可重放。
7. **退役。** 增益 := shown 的解出率 − withheld 的解出率，另看每解成本之差。留出组满 8 题且增益的 90% 置信上界小于 0 时只立一面"待复核"的旗；退役提议要满足 8.6 的样本量说明，由人确认后 `kit_retired`。`model_epoch` 变化时读数另起一行重新累计，留出率临时升到 30%：换代之后每个锦囊都要重新挣得位置。

v1.1 的淘汰规则按原始胜率计，它自己承认有选择偏差（难题更容易触发加载），现在由随机留出的增益取代。

**判例检索与类比。** 类比的对象是切口，不是文本。同签名判例的 `cuts` 给 Reason 一份分解先验：这类题上次是沿哪几个判据切开的，哪几处碰了难点。它直接作用于切口命中率（8.4）。跨签名的判例只给 free-form 闲人读（4.5），用来做跨界联想。

**由厚回薄**（D6）。对每个签名键，看最近不少于 10 道题：厚路径独占解出数为 0，且薄路径解出率不低于 70%，则建议把该签名的 `bootstrap_share` 调为 1，即只跑瘦路径，由人确认。调整之后仍留 ε 的题走完整路径作回归哨兵；哨兵里厚路径独占解出累计 2 题，自动恢复并告警。统计部分在 M1 随归因表做，只是多一个分组键；建议在 M4。判例还会加强薄路径本身：Bootstrap 读到切口先验后更容易一次解出，记忆加模型逐步取代编队。

**复利的度量。** 学习曲线：同一签名下第 k 题的每解成本对 k 作图。M4 的出口条件是第 6 到 10 题的每解成本比第 1 到 5 题下降不少于 20%，并且留出组没有同样的下降，以排除"题变容易了"和"模型自己变强了"两种解释。不满足时通鉴只留判例。

**防投毒。** 来源只限本项目自己的封存日志，不接第三方技能市场，公开市场有 12% 到 20% 的条目含恶意指令 [证据 S34]。蒸馏会话没有 `exec` 与网络。无法追溯到在链 E3 论断的步骤、不是逐字出自被引 exec 记录的命令，在发布检查里被确定性地拒绝。发布要人审并签名，锦囊目录在 Worker 的两个容器里只读，加载时校验哈希。发现注入时按锦囊哈希撤回，日志里的 `kit_loaded` 列出全部受影响的题。内核只认识锦囊的名称、哈希、描述三个字段。Playbook 只是可读材料，最多误导探索方向；由它产生的论断仍要在新题里过判官。

| 议题 | 选定 | 被否方案 | 理由 |
| --- | --- | --- | --- |
| 检索 | 结构签名、词法排序、渐进披露 | 向量库与嵌入相似度；专门的检索智能体 | 可审计、可重放；纯文件记忆胜过专用记忆系统 [证据 Z21]；锦囊本来就是渐进披露 [证据 S42] |
| 跨题效力 | 只作建议 | 被引的 E3 在新题里折价继承 | 环境不同，等级不出题（I7） |
| 退役依据 | 随机留出的增益 | 原始胜率 | 原始胜率有选择偏差 |
| 来源 | 只限本项目日志 | 第三方技能市场 | 投毒面 [证据 S34] |

成本：判例为零；复盘每题约 0.5 美元（8.2）；留出的代价是 ε 乘以增益。消融臂是 `kits=off` 与常设的留出组。

### 4.4 榷场

[T-1，感知官] 榷场是一个记账的分配算法：把"谁估得准"变成"谁的估值权重大"，把"谁花钱有产出"变成"谁拿到更多预算"。它不是激励机制。模型不会因为有赏金而更努力，告诉它有赏金反而可能诱发对判官的投机 [观点]。所以工人的任务包里没有行情、赏金、资本的任何信息；知道榷场存在的只有报价会话，它被要求的只是一个校准的概率。

落点按蓝图 F2：千级并发先撞上的不是写入热点，而是每题一个 Reason 的互斥域与读图上限 [假设 M2]，所以规模靠题组、题、子题三层展开（4.6），榷场只在有判官、可比对象多的层上分配预算。同族模型读同一张图，私有信息很少，题内行情多半是同一个估计的回声 [观点]，所以题内用退化形态。

**三级形态。** 每一级是下一级的退化形态，也是它的对照臂。

| 级 | 内容 | 启用条件 | 里程碑 |
| --- | --- | --- | --- |
| 零级：估值排序 | 行情等于先验，即 Reason 的 `expected_gain` 或通鉴里同签名的基础解出率；名额按八仙规则表。它已并入司南规则（4.1） | 默认 | M2 |
| 一级：盲报行情 | 多个席位盲报概率，按家族聚合后取加权中位，向先验收缩；名额按边际期望值排序；预算仍从公共池出 | 该层家族数 ≥ 2，且（席位、合约）的可行组合数 ≥ 2 × 可用名额；另须通过下面的闸门 | M4，先在题组层，排在通鉴之后 |
| 二级：席位资本 | 席位持有资本，押注即出资，按公平赔率赔付，罚没"折" | 并发 ≥ 50，且一级的行情读数为正 | M5，由读数决定建不建 |

**一级的启用闸门**（蓝图裁决书 #2）。三个读数齐备才落地，任一不满足即顺延：

1. 预测账（N3）显示，多个家族各自盲报再聚合的校准优于 Reason 单报价。这一条在预测账的记录上离线复算即可，不需要先建行情。
2. M2 的压测证实瓶颈在 Reason 的互斥域，不在写入吞吐。
3. 题组层的批量开题工具就绪。

```ts
type Contract = {                  // 只有带判据的对象可成约：无判据不成约
  id: string
  target: string                   // 带判据的 Intent | "goal" | 观察类论断 | 子题
  oracle: Check                    // 照抄 target 已登记的判据，不可另设
  settlement_tier: "decisive"|"consistent"      // 取自判官 grade；consistent 的赔付减半
  side: "achieve"|"assert"         // 待达成（Intent、Goal、子题）| 断言（观察）
  deadline: { budget_mark?: number, seq?: number, wall_s?: number }
  cap: number                      // 奖池对该合约的赔付上限，share × 开约时的奖池
  vest: number                     // 结算即付的比例；余下在"解出且在解题链上"时付清
  state: "open"|"frozen"|"pass"|"fail"|"void"   // frozen：target 带 knot
}
type Desk = {                      // 席位：估值与出资的记账单位。由配置登记，模型不能自建
  id: string; family: string; tier: "strong"|"mid"|"cheap"
  strategy: ArtifactId             // 提示词与锦囊组合的哈希
  weight: number                   // 估值权重，按结算更新
  gamma: number                    // 能力指数：该席位的通过概率估为 π^gamma
  capital: number }                // 二级才有；席位之间不可转让
type Quote = { desk: string, contract: string, round: number
               p: number           // P(期限内判官给出 pass | 强档做一次完整尝试)
               p_goal_given?: number   // P(上层目标终将达成 | 本合约 pass)，仅 achieve 类
               cost: number }      // 估计一次尝试的花费
type Stake = { desk: string, contract: string, lease: string
               reserve: number     // 即租约预留额，从席位资本划出
               bond: number }      // 履约保证金，β × reserve
```

规则：

1. **成约。** 带判据的对象出现时，图服务自动开出合约。没有判据的东西不成约：想得到注意力，先登记判据。
2. **盲报。** 每轮由"成批出现新合约、有合约结算、预算标记"触发并防抖。每个席位用一次廉价档的批量调用给一批合约报价。报价会话的 `context_manifest` 里不得有本轮他席的报价与行情视图，否则报价被拒，与 `independent` 是同一机制。
3. **定价。** 先在家族内取中位，再跨家族按权重取中位，得 m。n 为报价的家族数，κ 默认 2：`π(c) = (n·m + κ·prior) ÷ (n + κ)`。没有报价时 π 等于先验，名额规则退回八仙规则表，这就是司南。退化是逐合约、连续的，不需要全局切换。
4. **权重。** 合约结算后，每个席位的权重乘以它报给实际结果的概率（pass 乘 p，fail 乘 1−p），再归一；作废的合约不更新。这是专家混合的贝叶斯更新，有遗憾界 [证据：在线学习的经典结论，不在调研编号内]。权重按（席位、结构签名）存入通鉴，作新题的初值。
5. **名额，即注意力按期望值排序。** 席位 d 做合约 c 的通过概率估为 `π(c)^γ_d`。γ 是能力指数，强档为 1，按历史结算做单参数拟合，初值取档位（中档 1.5、廉价档 3，[假设 M4]）。对每个（合约 c、第 k 个名额、席位 d）算边际值：
   `ρ = share(c) × π(c)^γ_d × ∏(1 − 前 k−1 个名额持有者的通过概率) ÷ cost_d(c)`
   全体按 ρ 降序，在并发上限与席位资本之内贪心填充。k ≥ 2 的名额必须给不同家族或不同策略的席位；席位不重押自己失败过的合约。`share` 在题组层是开题时给的分值，在子题层取条件报价之差 `p_goal_given − π(上层目标)`。高 π 的合约，第二个名额几乎不值钱；低 π 而分值高的合约会得到多个名额。
6. **押注与赔付**（二级）。押注就是租约，另锁 `bond`，β 默认 10%。
   - pass：赔付 = `min(实际花费 ÷ π(c)^γ_d, cap)`，由奖池付给完成它的席位。这是按"市场对该席位的估计"给的公平赔率：做得比估计好的席位资本增长，反之缩水。
   - fail：花掉的已经花掉，未花的 `reserve` 与 `bond` 退回。
   - 折，即折损账（8.4）里可归责于会话的四类 `no_output`、`stalled`、`reject_loop`、`scope_violation`：`bond` 罚没。保证金罚的是折，不是败。罚没款的去向：对象带 knot 时注入它的观察合约的 cap，否则回奖池，不加到原合约上。
   - 守恒：席位资本之和 + 奖池 + 已花费 = 预算上限，逐事件成立。硬顶仍由端点代理执行（I6），榷场出错的最坏后果是分得差，不会超支。
   - 单个席位的资本不超过总额的一半，超出部分回奖池。种子资本一半均分，一半按通鉴里的权重分。
7. **结算的信任根。** 合约只随判官裁决结算。achieve 类到期未过为 fail；assert 类 E3 为 pass、X 为 fail、到期为 void，且只对带对照的观察赔付（N1）。行情不进等级与消费门（I8）。

**三个决定的次序。** knot 冻结、八仙的 `race_k`、名额公式会抢同一个决定，次序写死：knot 冻结先于名额公式，对象带 knot 时合约为 `frozen`，名额为 0，直到它的观察合约结算；名额公式启用后取代 `race_k`，价格就是扇出控制器；名额公式未启用的层仍用 `race_k`，且只用于不带 knot 的 Intent。

**与事件日志的关系。** 不设第二条流。`quote_batch`、`round_close`、`desk_seed`、`stake`、`payout`、`forfeit` 是同一条按题日志里的事件，行情是第四个投影，`market=off` 时这些事件与这个投影都不存在。合约与图节点一一对应，结算与等级变化由同一个 `judge_verdict` 触发，所以没有第二份真相。报价按席位按轮成批写入，一道题约 10² 条事件。资格由图服务校验（资本够、名额未满、未冻结），先后仍由司南用纯函数排。

**防失真。** 同族席位再多也只算一票；席位由配置登记，没有女巫问题，席位的策略目前由人配置；Reason 不持有资本，它的 `expected_gain` 只作先验；子题层赔付分两段，后一段要求在解题链上；两轮盲报之间的滞后由 knot 冻结兜住。最近 W 个已结算合约上行情的 Brier 分不优于先验时，该签名自动退回零级；跨家族离散度接近 0 而结算屡屡相反时 κ 加倍。

| 议题 | 选定 | 被否方案 | 理由 |
| --- | --- | --- | --- |
| 订单簿的位置 | 同一日志的第四个投影 | 独立撮合服务与第二条日志；不落盘的瞬时价格 | 押注、租约、预算预留必须原子；两条流就有两份真相（A9 的同一论证）。不落盘则注意力的分配无法重放与归因 |
| 价格形成 | 盲报、按家族聚合的加权中位、评分更新 | 连续双向拍卖；对数市场评分规则的自动做市 | 前者要撮合引擎和足够多的交易方；后者让交易方先看到价格再出手，同源模型会锚定。盲报保住独立性，百行以内可写完 |
| 赔付 | 按席位能力调整的公平赔率，设上限 | 每合约固定赏金 | 固定赏金下，唯一能解难题的强档席位会因成本高而亏损出局 |
| 罚没去向 | 该处的观察合约，否则回奖池 | 加厚原合约的赏金 | 与 knot 冲突：难点上应先看清，不应吸引更多人硬做 |
| 第一落点 | 题组层 | 题内 | 蓝图 F2 |

成本：一轮报价是"席位数 × ⌈合约数 ÷ 20⌉"次廉价档调用，每次约 0.001 美元；5 个席位、40 个合约、30 轮合计约 0.3 美元，`quote_share` 上限设为预算的 3%。行情未到时先用先验排，不增加等待 [假设 M4]。实现量：一级约一周，二级再加两周 [观点]。

消融与证伪：三条臂 `market=off|quote|capital`，同预算、同并发。读数是行情对先验的 Brier 分之差、折损率、每解成本。一级的证伪线：200 个已结算合约上行情不优于先验，或并发 8 到 50 时每解成本没有下降，则删除一级，不建二级。二级的证伪线：并发 ≥ 50 时资本臂对盲报臂的每解成本降幅不到 15%，则只留一级。退役信号：预测账显示 Reason 单报价的校准已不劣于行情。题组层的逐步走查见 6.3。

### 4.5 闲人协议

[T-1，感知官] 按裁决 A8，写支持记录的复审属于 Verify 角色，由消费门按需触发。闲人只有两种：**falsifier** 是供给侧的验证，在论断被消费之前先攻击它；**free-form** 是停滞时的多样性注入。二者补的是锚定与过早收敛 [证据 S28]。M2 落地。

`/work` 新增两条派生规则，都由事件触发，不用定时器，否则闲人在顺利的题上也花钱：

```
attack(f) := level(f) ≠ X ∧ load(f) ≥ L ∧ fragile(f) ∧ (f, 证据版本) 尚未被攻击 ∧ 闲人池未超
   load(f)    := 以 f 为前提（含传递）的未终态 Intent 数；f 在待提交的 Goal 候选的解题链上时取最大
   fragile(f) := level(f) < E3 ∨ f 的判据出自模型撰写的脚本且没有对照（N1）
   knot 联动  := Intent 带 knot 时，它的前提按 load 降序优先入队：一处切不开，先怀疑前提
wander    := 停滞信号之一成立：处于预算复盘期 | open 的 Intent 全部带 knot |
             自上次判官确认的进展以来花费 ≥ 15% 题预算；每个信号至多派一个
```

| 项 | falsifier | free-form |
| --- | --- | --- |
| 任务包 | 目标论断的证据层与前提链；不含提出者会话的推理正文 | 题面、已排除路径的标题、判例索引（含异类签名）；不含活跃假设的摘要层，避免被现有思路锚定 |
| 可提交 | 引用可采信 Artifact 的反证；带 `check` 的观察类论断，`grounds` 引已有的可采信 Artifact，由判官重放 | 不带支持的猜想，每任务至多 3 条 |
| 执行能力 | 不挂 `exec`。要新证据就写判据，由判官在洁净容器里跑，只限 r0，花费计入验证池 | 无 |
| 漫游范围 | 本图 | 本图标题层与通鉴。外部语料不开放：它是注入面，评测中也关闭联网 |
| 模型 | 家族必须不同于目标论断的提出者；没有可用的异家族时不派 | 廉价档，优先异家族 |
| 预算 | 两者合计不超过题预算 10%：falsifier 6% | free-form 4% |

采证要求不变：模型反证只产生争议，X 只来自判定性判官或人。falsifier 以 `nothing` 结束时，图服务给目标记一次存活；`attack_survived` 是派生计数，只用于不再重复攻击和写进报告，不影响等级（I8）。

防添乱的六条约束：

1. 操作白名单由图服务按租约角色强制，闲人不能加 Intent。
2. 每任务有写入配额。
3. 去重键是（节点、证据版本），与消费时验证共用验证池（3.1.9）。
4. 每个节点至多一条未决反证；反证被驳回后该节点对闲人关闭，直到证据版本变化。
5. 针对 E3 的反证只触发一次带冷却的重跑（3.1.3）。
6. **吸收率自限。** 吸收率 := (被 Reason 用作前提的猜想 + 成立的反证) ÷ 闲人任务数。最近 10 个任务低于 10% 时节奏减半，连续两次减半则本题停派。

消融：`idlers=off|falsifier|freeform|both`，只跑中、难两段。读数：falsifier 在节点被消费之前促成的证伪数，以及因此释放的预留额（归因表的 `pruned`）；free-form 猜想的在链率；E3 观察的"标题超出谓词"审计比例在有无 falsifier 时的差。证伪线沿用 8.4：贡献率低于 10% 而成本占比高于 5% 即为待删候选。退役信号：反证成立率趋近于 0，或 Verify 路径已能拦下同一批错误。

三处取舍：触发方式在"定时"与"事件派生"之间选后者；falsifier 不挂 `exec`，保住"提出质疑的会话不持刀"，证据仍由判官产出；漫游范围在"本图、通鉴、外部语料"中只取前两者。

### 4.6 子题、托管与多节点

[T-1，感知官；M5] 分区的单位是题，不是节点区间。哈希链已经按题独立，所以"一题一个写者、一机多题"不需要新机制。新问题只有一个：单题上千个 Worker。蓝图 F2 的论证是，此时该复制的是决策域，因为决策单线程是多智能体有效形态的前提 [证据 S43][S44]。

```ts
type Delegate = { goal: Check,                  // 子题的 Goal 判据，即本 Intent 的 done
                  scope: Problem["scope"],      // 必须是父题范围的子集，逐条确定性比对
                  escrow: Budget,               // 从父题预算划出
                  env: Problem["env"] }
// add_intent{ …, done: { judge_id: "seal_check" }, delegate }
//   → 父题 escrow_out → 子题 open_problem{ parent, escrow_ref } → 子题终态封存 → seal_check → escrow_in
```

- **子题是一道完整的题**：独立日志、独立写者、独立 Reason、独立画像，深度上限为 2。父题只看见三件事：子题开出、终态封存、余额回拨。子题拿不到父题的节点等级，只拿到作为 input 材料的摘录（2.4）。
- **谁来开子题。** M5 之前只做两种：人开，或在题组层批量开题。Reason 提议后自动开题，要等切口命中率的读数证明它切得准（开放问题 11）。
- **为什么这不是多智能体的交接失配** [证据 Z32]：父子之间的接口是一条事先登记的判据和一份可校验的封存，没有自然语言的交接语义。可能出的错只有"子目标切错了"，它会显示为父题的切口命中率偏低。
- **跨日志一致性只有三处**，都不需要分布式事务。托管：钱要么在父题账上记为已划出，要么已凭封存回拨，回拨以封存哈希幂等。失效上传：`seal_revoked` 由父题订阅，最终一致；r2 之前同步核对。硬顶：子题的任务令牌由子题预算派生，各子题预算之和受托管约束；哮天犬按父题状态回收孤儿子题。
- **单写者的容量** [假设 M2 压测]：组提交下 10³ 事件每秒量级；等级按批重算（3.1.9）。高可用用同步副本，故障时提升副本并重放，正确性来自"落盘后应答加幂等键"，不引入共识协议。读扩展靠只读副本订阅事件流，以 `as_of` 保证读一致。
- **Blob**：对象存储，键为 sha256，只写一次；元数据仍是日志事件。采集器用范围受限的凭据直传，凭据不进容器。回收的根集合是全部题日志与通鉴封存所引的哈希。
- **模型网关**（M5）：网关无共享状态，一个任务的会话按令牌哈希粘在一个实例上，计量在本地完成，再以 `cost` 事件写回该题日志；不用分布式计数器。实例崩溃则该任务的请求失败、租约过期，失败是关闭方向的。
- **跨机的任务包前段**：对同一 `as_of_seq` 必须逐字节相同。四项保证：规范序列化；快照记录里带 reducer 版本哈希，版本不同的副本拒绝出包；写者每 N 个事件追加一次 `dump_mark {seq, listing_hash}`，副本出包前比对，不一致即告警并回落到写者；持续集成里加"两个副本、随机日志、字节相等"的黄金测试。

| 议题 | 选定 | 被否方案 | 理由 |
| --- | --- | --- | --- |
| 单图的水平扩展 | 按题分区，大题拆子题 | 按节点范围分片的多写者；共识复制的单写者扛吞吐 | 最小不动点要全局视图，跨片的边会让等级函数变成分布式算法，丢掉"百行纯函数"。吞吐本来就不是瓶颈 [假设 M2] |

启用条件：单题 open 的 Intent 数持续超过 Reason 一轮能处理的量，或并发超过 10。退役信号：单个 Reason 能管理的并发翻倍而切口命中率不降。对象存储、网关粘性、`dump_mark` 是守门官 [T-0]。成本：无模型成本，每个子题多一次开题与一次封存，毫秒级。对照臂是"单题大图"；子题成立的条件是切口命中率不降。残余要写明：拆不开的强耦合难题在千级并发下仍然卡在单个 Reason 上，三层展开帮不了它，所以"可分解工作负载占比"列在未证明清单第 20 条。

---

## 5. 对抗性自检与其它自检

### 5.1 攻击与退化场景

影响与概率各按 1 到 5 打分 [观点]。

| # | 场景 | 影响 | 概率 | 分 | 对策 |
| --- | --- | --- | --- | --- | --- |
| 1 | 回声室晋级：同源模型互相确认，把错误推断抬到 E2 并被消费 | 4 | 4 | 16 | 见 5.2 |
| 2 | 证据挪用与空谓词：引用真实但不相干的 Artifact，或谓词恒真而标题夸大 | 4 | 4 | 16 | 见 5.2 |
| 3 | 判官被骗：改测试、静默告警、压掉流量让指标"恢复"，或对判官穷举 | 5 | 3 | 15 | 见 5.2 |
| 4 | 目标内容的提示注入：环境里的文本诱导 Worker 越界、带出密钥或提交假结论 | 4 | 3 | 12 | 写入全经确定性校验；执行容器默认拒绝出站；模型容器连不到目标，也没有命令工具；模型密钥不进任何容器（3.4.2、3.6） |
| 5 | 预算穿透：嵌套会话、后台进程、输出洪泛 | 3 | 4 | 12 | 租约预留、硬顶终止、容器随任务销毁；执行容器里起不了模型会话；`exec` 的回显有上限；端点代理按任务令牌计量，超额拒绝（3.5） |
| 6 | 图污染：垃圾节点洪泛、近重复节点、Intent 膨胀 | 3 | 4 | 12 | 每任务写入配额；列表上限与确定性省略；无人认领的 Intent 过期；闲人预算封顶 |
| 7 | 越界与沙箱逃逸 | 5 | 2 | 10 | 默认拒绝加 `scope_violation` 三次终止；强对抗场景用虚拟机 [证据 S13]；r2 凭据按次签发。已有沙箱逃逸波及真实系统的报道 [待核 Z13] |
| 8 | 验证活锁：判官反复无结论，或争议长期悬置 | 3 | 3 | 9 | 去重键、每键 2 次上限、自动复判至多补到 4 次裁决、转 `needs_human`；r0 永不阻塞（3.1.4） |
| 9 | 外壳税：代理工具面让单个会话的能力低于原生工具面 | 3 | 3 | 9 | 对照臂 B1b 单独量出；超过阈值先改工具面再评测（8.3） |
| 10 | 时效误判：环境变化被记成证伪 | 4 | 2 | 8 | 判据带有效期，过期与证伪分开；翻转需要连续两次一致（A6、A7） |
| 11 | 单写者故障或日志损坏 | 4 | 2 | 8 | 落盘后应答、幂等重试、快照带状态哈希、哈希链可校验 |

### 5.2 前三名的完整对策

**场景 1：回声室晋级。**

- 结构：E3 与 X 只来自判定性判官，模型之间的一致最多到 E2。`heterogeneous` 要求模型家族不同或引入新的执行证据；`independent` 用 Adapter 记录的 `context_manifest` 判定，复审任务包不含被审论断的正文。支持的强度不超过其前提的最低等级，最小不动点让互证的环得不到等级。
- 消费：r2 只认 E3，或 E2 加人对该前提的逐条豁免。
- 度量：M1 起统计 E2 误晋级率，即到过 E2、后来被判定性判官否定的论断占比。超过 10% [假设] 时把 E2 的条件收紧为"必须含新的执行证据"。
- 残余：不同家族的模型可能共享同一条错误知识 [观点]。所以 E2 在报告里始终写作"模型共识"，不写"已验证"。

**场景 2：证据挪用与空谓词。**

- 结构：观察类论断的内容是谓词本身，title 与 summary 只是标签。等级来自判官在洁净环境里对谓词的重放，不来自被引 Artifact 的存在。
- 承认的缺口："谓词为真，但标题说得比谓词多"无法由确定性代码判定；模型撰写的脚本也可以在访问资源之后输出与资源无关的内容。四层缓解：`require_touch` 挡住什么都不访问的规格（3.3.2）；Verify 可以提出"标题超出谓词"的反证，使节点进入争议；审批卡片与报告展示谓词、脚本和判官输出，不展示标题，并标明判据出自类型化只读工具还是模型撰写的脚本；完整版的类型化只读工具让命令不由模型撰写（3.6.3）。
- 对照判据（N1，M1）：判据带上负对照之后，恒真的脚本过不了对照；r2 的前提与续期门的进展只认带对照的观察（3.3.3）。它解决的是"结果不依赖输入"，不解决"标题超出谓词"。
- 带判据的 Intent 有同样的缺口：判据对 Worker 可见，候选由模型撰写。所以它的达成只用来放行依赖和计算进展，不进入 Goal 的判定。
- 兜底：Goal 判官不读任何中间论断。被夸大的 E3 论断与虚假的达成会浪费预算，但造不出假的 Goal 达成。
- 度量：M1 抽样审计 E3 观察类论断，统计标题超出谓词的比例。

**场景 3：判官被骗。**

- 资产固定，分两级（3.3.2）：结构级资产，即判官代码、公开配置与公开测试，作为 input 类 Artifact 以哈希写进 Problem，在 Worker 的容器里只读，判官运行前校验哈希；含密级资产，即答案与隐藏测试的期望输出，以保密库引用登记，只在判官容器里解引用，Worker 的两个容器都看不到。
- 环境独立：判官在自己的容器里从 `baseline_ref` 起步，只接收候选产物（补丁、答案、重放规格），不接收 Worker 改动过的工作区。候选产物能触及的路径由判官配置里的白名单限定。
- 守护指标：指标类判官除目标指标外还断言一组守护项（流量没有被压到零、告警没有被静默、采样率未变），任一项失败即 `fail`。守护项写在领域的判官配置里。
- 先登记后行动：Intent 的判据在创建时登记，之后不可改；r2 Intent 的判据就是对动作结果的预测，批准时由人过目。
- 防穷举：Goal 判定有次数上限；失败只返回原因类别，不返回期望值。
- 判官自身：每个判官版本附正反样例，注册前必须全部通过；出错后撤销版本，等级重算。
- 残余：人把判官规格写错。只能靠样例与复核，基座不解决。

### 5.3 通用性自检

内核 Schema 里没有领域词：`scope.resource`、`check.expect`、`env.base`、锦囊正文对内核都不透明。同一组字段在五个领域的取值如下，画像一列由 3.1.2 的规则推出，不是人填的：

| 领域 | Goal 判官 | 推出的画像 | 带判据的 Intent 举例 | r2 动作 | 根结论的最高等级 | 可用于 |
| --- | --- | --- | --- | --- | --- | --- |
| CTF | 答案比对，判定性 | partial、hard、r0 | 取得某个中间产物的脚本可复现 | 无，练习环境整体标 r0 | E3 | M0 |
| 数学 | 证明检查器，判定性；没有形式化时只有结构检查加人验收 | complete、costly 或 none、r0 | 某条引理通过检查器 | 无 | E3；非形式化时 E2 加人验收 | M3 |
| 软件工程 | 隐藏的测试套件，判定性 | complete、hard 或 costly、r0 | 复现用例在补丁前失败、补丁后通过 | 无；合并与发布在基座之外 | E3 | M3 |
| 运维排障 | 延迟的指标断言，加人验收 | partial、deferred、r2 | 时间线上的一项对照查询成立 | 变更、回滚、重启 | 根因 E3d；有副本环境时 E3 | M4 |
| 医学诊断辅助 | 结构检查加人验收；可有延迟的结局判官 | partial、none 或 deferred、r2 | 一项检查的结果符合事先登记的预测 | 有创检查与用药，一律由人执行 | E2 加人验收；有结局判官时 E3d | M4 之后，只作辅助 |

检查出五条隐含假设：

| 隐含假设 | 在哪里不成立 | 处理 |
| --- | --- | --- |
| 环境可以重置到基线 | 运维、临床 | `record_match` 与延迟判官不需要重置；判据带有效期；M0 只承诺可重置的环境 |
| 动作都是容器里的命令 | 需要人去做的检查或操作 | 人执行的 Intent，结果作为 input 类材料回到图里（3.1.3） |
| Goal 是单个谓词 | 数学的引理链、工程的多项验收 | 带判据的 Intent 互为前提，连成链（3.1.2） |
| 观察能写成退出码与输出的谓词 | 证明检查、影像判读 | `expect` 由各判官自行解释，内核不看 |
| 题目总有外部资源 | 证明题只有一个工作区 | 资源插件集内建 `workspace` 种类（3.6.2），纸面走查见 6.4 |

### 5.4 缺失检测

除已补的执行层（契约 6）外，任务书没有点名而基座必须有的：

| 缺失项 | 处理 |
| --- | --- |
| 评测台：四条对照臂、检查点、消融开关、归因表、报告 | 列入 M1（§7、§8），与基座同仓 |
| 事件模式的版本与迁移 | Event 带 `v`，reducer 按版本解释（3.1.2） |
| 报告生成 | `pd report` 是确定性投影，题目未解出时同样产出（3.5.4） |
| 采集内容里的敏感信息 | Blob 按题隔离访问，完整版按题加密；采集时不改写内容，以免破坏哈希 |
| 人的身份与审批留痕 | M0 为本机单用户；完整版对 `approve` 与 `rule` 事件签名 |
| 工具层（如意） | 不单设契约：CLI 的文件工具加三个代理工具（3.4.2），领域工具随锦囊与资源插件带入 |
| 人机界面 | M0 只有 `pd` 的文本输出与四语域约定（4.1）；网页分期见 HMI 设计。它是日志的读者，不是第五个投影，不进 M0 的关键路径 |

### 5.5 三个机制与证据梯的最简反事实

各契约的结论见 3.x.6。其余各项：

| 对象 | 砍掉后退化为 | 结论 |
| --- | --- | --- |
| 扇出控制器 | 固定并发的循环，即 M0 形态 | M2 消融决定 |
| 模型分层 | 全部同档，即 M1 首轮形态 | M2 消融决定 |
| 通鉴与锦囊 | 没有跨题记忆 | M4 之前不建管线 |
| E1 与 E2 两级 | 二值证据（E0 与 E3） | M1 的 `ladder=binary` 消融决定 |
| 带判据的 Intent | 只有 Goal 一个判据，子任务完成与否由会话自报 | M1 的 `checked_intents=off` 消融决定 |
| 续期门 | 每道题花到硬顶，或自然停滞 | M1 的 `extension=always` 消融决定 |
| knot 与换缝优先 | 失败后直接重试或升档，即 v1.1 的形态 | M1 的 `knot=off`、`escalate=first` 消融决定，只跑难段 |
| 关节度 | 只按 `expected_gain` 排序 | M2 的 `order=gain_only` 消融决定 |
| 对照判据 | 恒真的谓词可以到 E3，并被算作进展 | M1 的抽样审计决定（8.5） |
| 闲人 | 没有供给侧的验证，也没有停滞时的多样性注入 | M2 的 `idlers` 四臂消融决定 |
| 榷场一级、二级 | 零级，即司南规则表 | M4、M5 的 `market` 三臂决定 |
| 子题与托管 | 单题大图 | M5 的子题臂决定 |
| 预测账、常设留出 | 没有校准读数；官的增益只能靠里程碑上的专门消融 | 量具，不删；留出读数与专门消融不一致时只留后者 |
| 题界与封存 | 跨题引用只能整体拒绝，通鉴与子题各造一套 | 守门官，保留 |

### 5.6 前沿结构的压力预检

第 4 节新增的结构带来八个新的失效场景，打分方式同 5.1 [观点]。前三名的完整对策见蓝图 §4，这里列出对策在本文的落点。

| # | 场景 | 影响 | 概率 | 分 | 对策与落点 |
| --- | --- | --- | --- | --- | --- |
| 1 | 行情回声：席位同源，报价高度相关，行情自信而错，注意力被引向死路 | 4 | 4 | 16 | 盲报、家族内先聚合、向先验收缩；行情不优于先验即逐签名退回零级；行情不进等级（I8）；knot 冻结先于名额；`quote_share` 封顶 3%（4.4）。残余：所有家族共享同一个误解时行情一致地错，损失的上界是该题组的预算 |
| 2 | 判据通胀与刷单：为了成约、进展或赔付，造出容易达成而无关的判据 | 4 | 4 | 16 | 对照判据挡住恒真谓词（3.3.3）；赔付的后一段要求在解题链上（4.4）；Intent 配额不变；Reason 不持有资本，工人不知情。读数是切口命中率里"达成但不在链上"的比例，超过 50% 时续期门的进展谓词收紧为只认在链的达成（8.4） |
| 3 | 通鉴污染与漂移：错误、过时或被注入的 Playbook 跨题放大 | 5 | 3 | 15 | 来源只限本项目的封存日志；每步引用在链的 E3，命令逐字出自被引的 exec 记录；Playbook 只是可读材料（I7）；随机留出给出无偏的增益，换代时读数另计；按哈希撤回（4.3） |
| 4 | 闲人同源互证与争议淹没 | 3 | 4 | 12 | 异家族为硬要求；每节点一条未决反证；吸收率自限；争议不阻塞 r0（4.5） |
| 5 | 形式命题失真：模型把题面形式化成更弱或不同的命题，判官照样通过 | 4 | 3 | 12 | M3 只收人给出形式命题的题；模型做形式化时必须经人验收，报告分开写两种确认（6.4） |
| 6 | 子题的钱与失效：托管重复回拨、孤儿子题继续花钱、父题消费了已被撤销的封存 | 5 | 2 | 10 | 回拨以封存哈希幂等；子题令牌由子题预算派生，哮天犬按父题状态回收；r2 之前同步核对封存（2.4、4.6） |
| 7 | 席位马太效应：早期运气让一个席位拿走大部分资本 | 3 | 3 | 9 | 资本上限为总额的一半；种子一半均分；估值权重与资本分开（4.4） |
| 8 | 常设留出误伤：关键题恰好被关掉某个官；小样本下错误退役 | 3 | 3 | 9 | 含 r2 规则的题不参加；8 题只立旗，退役提议要给出样本量与区间并由人确认；换代后重新累计（8.6） |

---

## 6. 走查

记号：n 为论断，i 为 Intent，a 为 Artifact，h 为 Hint。金额按 §8 的价目估算，均为 [假设]。各走查只写到契约与流程一层，不含具体手法。

### 6.1 一道 CTF Web 练习题（M0 能力即可走完）

Problem：scope 只有题目主机一条网络规则，人把它标为 r0（练习环境，可随时重置）；Goal 判官为 `exact_match`，预置答案是含密级资产，Problem 里只有保密库引用与加盐摘要（3.3.2），`max_attempts=5`；题预算 11.5 美元。图服务推出画像 `{partial, hard, r0}`：范围里有外部资源，Goal 判官廉价且为判定性，规则的最高风险是 r0。

| 步 | 发起者 | 事件或操作 | 结果 |
| --- | --- | --- | --- |
| 1 | 人 | `open_problem`；题面登记为 input 类 a_1 | 画像写入事件；`/work` 给出 bootstrap |
| 2 | 司南 | bootstrap 租约，预留 3.8 美元 | Adapter 起模型容器，执行层起执行容器（出站只放行题目主机） |
| 3 | Bootstrap | 若干次 `exec`，只读探查 | 执行层登记 exec 类 a_2 到 a_9；模型拿到引用与截断的回显 |
| 4 | Bootstrap | `submit`：n_1（观察，"入口页引用了某接口路径"，check 为 `replay` 加 `stdout_contains`，grounds 为 a_3）；n_2（推断，"该接口对两类请求的处理不一致"，premises 为 n_1） | 当场返回两个节点 id；n_1、n_2 为 E0 |
| 5 | 判官运行器 | 在洁净容器里重放 n_1 的规格，`judge_verdict pass` | n_1 为 E3，n_2 仍为 E0 |
| 6 | 哮天犬、Adapter | Bootstrap 越过软线，进入收尾轮 | `final.outcome=unsolved`，附已排除路径；租约释放 |
| 7 | Reason | 只读图；`add_intent` i_1、i_2、i_3，均为 r0 | 三个 Intent 为 open |
| 8 | 司南 | 三个 explore 租约 | 三个会话并行，都没有带回候选。其间花费越过 50%，图服务追加 `budget_mark`，进入预算复盘期 |
| 9 | 人 | **Hint 注入**：`pd hint add "题面提到'备份'，优先看与备份相关的路径"` | h_1 入图；`/work` 给出 reason；在途会话不受影响 |
| 10 | Reason | 第 2 轮，带 `reflect`，`focus.hints` 含 h_1；先写出已排除路径，再 `add_intent` i_4："取得备份归档"，带判据：`replay` 候选脚本，输出须含归档格式的文件头 | 复盘期结束；i_4 为 open，判据从此不可改 |
| 11 | Explore(i_4) | `claim_done`，目标 i_4，候选是取文件的脚本；判官在洁净容器里运行它并比对，通过。归档内容指向第二个主机，`exec` 的连接被执行层拒绝 | i_4 为 achieved，这是一次被判官确认的进展；`scope_violation` 事件；Worker 在 `final.suggestions` 里说明 |
| 12 | Reason | 第 3 轮：`add_intent` i_5，前提为 i_4，带 `needs_scope`（第二主机，r0） | i_5 为 `needs_human` |
| 13 | 人 | **审批门**：核对该主机属于题目环境后 `pd approve i_5 --scope-amend net:<主机>:<端口>:r0` | `approve` 事件；画像重算，不变；i_5 为 open；此后编译的容器放行该主机。若拒绝，i_5 为 abandoned，Reason 另寻路线 |
| 14 | Explore(i_5) | `claim_done`，目标 goal，候选答案登记为 authored 类 | `exact_match` 通过，裁决随 `submit` 的返回值带回 |
| 15 | 图服务 | Goal 获得判定性支持，为 E3；r0 题的收尾清单为空，`close_problem`，终态 solved | 其余租约取消，容器销毁 |

花费约 10 美元：Bootstrap 3.8，Reason 三轮 1.4，Explore 五个会话 5.0，判官可忽略。80% 标记落在第 14 步进行中；续期门启用时在这里放行，因为 i_4 在 50% 标记之后达成。`pd report` 给出解题链（由 yields、derives_from 与 Intent 前提三种边连成，链上的对象均为 E3）和被排除的路径；归因记录里，厚路径、共享图、带判据的 Intent 三项在链上。

### 6.2 一次运维根因分析（需要完整版能力，M4 之后可走完）

Problem：scope 有三条规则，某命名空间的遥测只读（r0）、编排系统只读（r0）、该命名空间的配置变更（r2）；Goal 是目标指标回到阈值内并保持 30 分钟，判官为延迟的指标断言，且根因论断须经人验收（`accept=human`）。推出的画像是 `{partial, deferred, r2}`。

| 步 | 发起者 | 事件或操作 | 结果 |
| --- | --- | --- | --- |
| 1 | 人 | `open_problem`；告警快照与症状清单登记为 input 类 | `/work` 给出 bootstrap，它的容器只含两条 r0 规则 |
| 2 | Bootstrap | 用类型化的指标查询工具取数；n_1（观察，"02:00 到 02:30 接口错误率升高"）、n_2（观察，"同时段数据库连接等待时间升高"），check 为 `record_match`，查询固定时间窗 | 输出来自执行层的只读工具，判官为判定性，两者 E3。固定时间窗的判据不设有效期 |
| 3 | Reason | i_1 查变更记录、i_2 查依赖方、i_3 查资源水位，均为 r0 | Goal 判官是延迟型，Explore 并发取 2 |
| 4 | 人 | **Hint 注入**：`pd hint add "02:05 有一次连接池配置发布"` | Reason 下一轮据此提出 i_4：核对该次发布的内容与时间线 |
| 5 | Explore(i_4) | n_6（观察，"02:05 的发布把连接池上限由 A 改为 B"）；n_7（观察，"连接池此刻处于饱和"，判官带 10 分钟有效期）；n_10（推断，"根因是连接池上限下调"，premises 为 n_1、n_2、n_6） | n_6、n_7 为 E3，n_10 为 E0。n_7 到期后带 `stale`，有消费者时才复检 |
| 6 | Reason | `add_intent` i_7："回滚该配置"，risk=r2，premises 为 n_10；`done` 为延迟的指标断言"回滚后 10 分钟内错误率低于阈值并保持 30 分钟"，`tests` 为 n_10；`rollback` 写明如何恢复到动作之前 | 消费门不满足，i_7 为 blocked；派生 `verify_wanted(n_10, E2)` |
| 7 | Verify 两次 | v_1 用另一模型家族，任务包不含 n_10 正文，写复审支持；v_2 引入新的执行证据（同时段未改配置的服务没有该症状） | n_10 先到 E1，再到 E2 |
| 8 | 闲人 | 反证："同时段流量也在上涨"，附 exec 类 Artifact | n_10 进入争议。裁决任务核对时间先后（流量 01:30 已上涨，错误率 02:05 才升高），反证被驳回 |
| 9 | 图服务 | i_7 转 `needs_human`；审批卡片由投影确定性生成 | 卡片列出：动作与回退方法、n_10 的等级与支持记录、各前提的判据来源、未决争议（无）、`done` 判据及其所检验的论断 |
| 10 | 人 | **审批门**：`pd approve i_7 --waive-premise n_10`，操作带所见卡片的 `card_hash` | i_7 为 open；`tests` 随批准生效。卡片在此期间有变化则返回 `stale_view` |
| 11 | 司南、执行层 | 并发 1；i_7 的执行容器按 r2 上限编译，注入一次性的变更凭据 | Worker 经 `exec` 执行回滚，输出登记为 exec 类；`claim_done` i_7，观察窗开始计时 |
| 12 | 延迟判官 | 到期运行指标断言与守护项，通过 | i_7 为 achieved；n_10 得到一条相符性支持，为 E3d。Goal 的指标断言同时通过 |
| 13 | 人 | **四顾**：收尾清单列出范围修订（无）、r2 凭据（已作废）、链上的 E3d 论断 n_10、守护项（通过）。人逐项确认后 `pd accept` | 题目关闭，终态 accepted。报告首行写明：根因 n_10 为 E3d，未做副本反事实，本题判官之下的上限也是 E3d；被排除的解释一条 |

两个分支。有副本环境时，再开一个 r0 的 Intent 做双向反事实，判定性判官通过后 n_10 到 E3。判据没有通过时，i_7 未达成并回到 `needs_human`（不可逆动作不自动重做），n_10 得到一条反证并进入争议，Goal 不成立，`/work` 重新给出 reason，回滚动作的记录保留。花费约 8 美元。

### 6.3 榷场：题组层的预算分配（二级形态，M5 能力）

限时题组 G 是一道父题，有 6 道子题，等分值，预算 60 美元，期限 2 小时，并发上限 6。席位三个：甲（家族 α，强档，一次完整尝试约 3.8 美元，γ=1）、乙（家族 β，中档，1.9，γ=1.5）、丙（家族 α，廉价档，另一套策略，0.2，γ=3）。每个合约的赔付上限 cap 为 6，保证金 β 为 10%，先验取通鉴里同签名的基础解出率 0.5。下表的 ρ 省去公共因子 share；挂牌价取两位小数。右边五列是每一步结束时的资本、奖池与已花费，每一行五个数之和都是 60。

| 步 | 事件 | 结果 | 甲 | 乙 | 丙 | 奖池 | 已花费 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 人开题组；`desk_seed` | 六个子题各开一个合约 c1 到 c6 | 9.00 | 9.00 | 6.00 | 36.00 | 0.00 |
| 2 | 第 1 轮盲报，三次廉价档批量调用；`round_close` | c1：α 族内中位 0.85，β 为 0.70，跨族中位 0.775，收缩后 0.6375，挂牌 0.64。c1、c2 为 0.64，c3、c4 为 0.50，c5、c6 为 0.35 | 9.00 | 9.00 | 6.00 | 36.00 | 0.00 |
| 3 | 名额排序 | c1 的第一名额：丙 0.64³÷0.2=1.31，乙 0.27，甲 0.17，丙得。六个第一名额全归丙（ρ 从 1.31 到 0.21），高于任何第二名额（最高 0.20）。这是档位层面的先瘦后厚 [证据 S16] | 9.00 | 9.00 | 6.00 | 36.00 | 0.00 |
| 4 | 丙押 c1，`escrow_out`；子题解出，实际花费 0.18；`seal_check` 通过 | 赔付 0.18÷0.64³=0.69。权重更新：丙 ×0.9，甲 ×0.8，乙 ×0.7 | 9.00 | 9.00 | 6.51 | 35.31 | 0.18 |
| 5 | 丙在 c2 通过（花费 0.16，赔付 0.61），在 c3 到 c6 正常失败（各花 0.2） | 未花的预留与保证金退回；四个子题各返回 unsolved 的封存与已排除路径的摘录 | 9.00 | 9.00 | 6.16 | 34.70 | 1.14 |
| 6 | 第 2 轮盲报，报价会话读到失败摘录：c3、c4 仍报 0.50；c5、c6 各席报 0.10，挂牌 0.30 | 乙得四个第一名额：c3、c4（ρ 0.186）与 c5、c6（0.086）。甲得 c3、c4 的第二名额（0.085），高于它去做 c5 的第一名额（0.079），资本也只够押两注 | 9.00 | 9.00 | 6.16 | 34.70 | 1.14 |
| 7 | 乙在 c3 通过（花费 1.7）；甲在 c3 的会话取消（已花 1.5）；乙在 c4 的会话以 `no_output` 结束（0.6）；甲在 c4 通过（3.4）；乙在 c5、c6 失败（各 1.9） | 乙得赔付 1.7÷0.5^1.5=4.81。c4 属于折：乙的保证金 0.19 罚没回奖池（题组层没有观察合约）。甲得赔付 min(6.8, 6)=6 | 10.10 | 7.52 | 6.16 | 24.08 | 12.14 |
| 8 | 第 3 轮盲报：c5、c6 各席报 0.04，挂牌 0.27；只剩甲没有在这两题上失败过 | 甲押两注；c5 通过（花费 3.1），赔付 min(3.1÷0.27, 6)=6 | 13.00 | 7.52 | 6.16 | 18.08 | 15.24 |
| 9 | 期限到，c6 未解（甲花 3.8） | c6 结算为 fail，各席对它的报价按 fail 更新权重。解出 5 题，花费 19.04 美元，余额作为未花预算退回 | 9.20 | 7.52 | 6.16 | 18.08 | 19.04 |

第 6 步与"强档做难题"的直觉不同：强档先补中等题的第二名额，因为那里每美元的边际解出概率更高。对照臂是"每题等额预算、同一路由表"的 `market=off`，六题各跑一次强档 Bootstrap 就要 22.8 美元。行情臂是否真的更省，由 M4 的读数回答 [假设 M4]。

这张表由 [`reference-model/market_walkthrough.py`](reference-model/market_walkthrough.py) 逐步复算：它记一本账，每一步之后断言守恒，并断言名额的归属与上表一致。两点说明。其一，三轮报价的调用费合计约 0.009 美元，从奖池出，账里略去。其二，两个家族报价、κ=2、先验 0.5 时，挂牌价的下界是 0.25；蓝图原表第 6、8 步写的 0.2 与 0.15 按定价公式算不出来，这里改为各席报 0.10 与 0.04，即挂牌 0.30 与 0.27，名额归属与每一步的资本都不变。

### 6.4 第二领域接入：数学（Lean，M3 能力）

选数学而不先选运维，有三个理由：6.2 已经走查过运维；数学是完全信息范式，与 M0 的 CTF 相对；证明检查器的内核是最硬的判官 [证据 S24]，红线 3 的终审应当在判官最不含糊的地方做。

判官配置。领域词只出现在这里与锦囊里：

```yaml
id: lean_check          version: "1"
kind: deterministic     grade: decisive
applies_to: [goal, intent, observation]
runner: { type: container, image: "lean-pinned@sha256:…", cmd: "judge/lean_check.sh", base: lean-pinned }
timeout_s: 900          auto: false            # 编译以分钟计，按消费与 claim_done 触发
flake: { reruns: 0, require: all }             # 编译是确定的；超时记为无结论
params:
  assemble: statement_from_spec    # 命题取自已登记的 spec，候选只提供证明体
  axioms_allow: [propext, Classical.choice, Quot.sound]
  forbid: [sorry, native_decide, unsafe, implemented_by]
  kernel_recheck: true             # 编译产物再由独立的内核检查器复核
  feedback: full                   # 命题没有秘密，报错全文返回；不需要保密库
```

判官做四件事：把登记过的命题与候选的证明体组装成文件，候选改不了命题；编译；检查主定理所依赖的公理集在允许表之内，用了 `sorry` 或 `native_decide` 都会在这里露出来；用独立的内核检查器复核编译产物 [待核：具体工具与它的覆盖面，列入 §7 的 M3 接入清单]。

其余三样都不进内核。资源：没有外部资源，只用内建的 `workspace` 种类（3.6.2），画像推出 `{complete, costly, r0}`；完整版提供两个类型化只读工具，即库内定理检索与取某一位置的证明目标。锦囊 `lean-proving`：声明 `applies_to.judges: [lean_check]`，按结构匹配自动列入，内容是工程约定、读报错的方法、常用策略、如何把目标抽成独立引理。映射：引理是带判据的 Intent，判据就是引理的形式陈述，这里的 E3 确实等于"该陈述可证"，标题超出谓词的缺口最小；骨架检查是一条带判据的 Intent，即在允许若干引理留空的条件下主定理通过编译（`expect.allow_sorry_in`）；引理为假时，反例是一条观察类论断，判据是对否命题的证明。

走查。题 T：人提供形式命题文件，主定理体留空，登记为 input 类 a_1。Goal 判据为 `{lean_check, spec_ref: a_1}`，题预算 11.5 美元。

| 步 | 发起者 | 事件或操作 | 结果 |
| --- | --- | --- | --- |
| 1 | 人 | `open_problem`，scope 只有一条 `workspace` 规则（r0） | 画像 `{complete, costly, r0}`；任务包列出锦囊 `lean-proving` |
| 2 | Bootstrap | 若干次 `exec` 试编译；未解出；提交推断 n_1"主定理可由 L1、L2、L3 推出" | n_1 为 E0；收尾轮给出 unsolved |
| 3 | Reason | `add_intent`：i_S 骨架（允许 L1 到 L3 留空）；i_1、i_2、i_3 三条引理，判据各为其形式陈述；i_M 合成，前提为这四条 | 五个带判据的 Intent；i_M 为 blocked，i_S 与三条引理的 `unlocks` 各为 1 |
| 4 | Explore(i_S) | `claim_done` | `lean_check` 通过，i_S 达成：分解本身先被判官确认 |
| 5 | Explore ×3 | 三条引理互不依赖，按 C2 并行；i_1、i_3 达成；i_2 失败 | i_2 带 knot |
| 6 | 图服务、司南 | i_2 不再认领，不竞速；失败触发 Reason | Reason 选"看清"：开观察 Intent i_2o"L2 在小范围内是否成立"，`follows {i_2, observe}`，r0，预算为 i_2 的一半 |
| 7 | Explore(i_2o) | 发现 L2 在边界情形不成立（自然数减法截断）；提交观察 n_2，判据是对 L2 否命题的证明 | `lean_check` 通过，n_2 为 E3 |
| 8 | Reason | 换缝：`abandon_intent` i_2，i_M 随前提被放弃；新开 i_2′（L2 加前提，`follows {i_2, reroute}`）、i_4（单独处理边界）、i_S′（新骨架）、i_M′ | 归因：i_S 达成但不在解题链上，切口命中率记一次 |
| 9 | Explore | i_S′、i_2′、i_4 依次达成 | i_M′ 由 blocked 变为 open |
| 10 | Explore(i_M′) | `claim_done`，目标 goal；`inputs` 按哈希挂入各引理达成时的候选 | 判官从洁净容器整体重新编译并复核，不采信任何中间等级；通过 |
| 11 | 图服务 | Goal 为 E3；收尾清单为空，关题，终态 solved | 报告：解题链为 i_S′、i_1、i_2′、i_3、i_4、i_M′；被排除的是 L2 的原陈述，附 n_2 |

花费约 9.3 美元：Bootstrap 3.9，Reason 三轮 1.35，Explore 九个会话约 4.0（引理级的会话短，按 8.1 的成本式取 10 回合，每个约 0.44）。判官十余次编译，不耗 token，按价目表计算力费。

内核零改动核对：

| 领域需求 | 落点 | 内核改动 |
| --- | --- | --- |
| 命题固定，候选只给证明 | 判官的 `assemble` | 无 |
| 公理、留空、不安全特性 | 判官配置 | 无 |
| 引理证明进入 Goal 的判定 | `JudgeRequest.inputs` 按哈希挂入 | 无 |
| 骨架检查 | `expect` 由判官自行解释 | 无 |
| 没有外部资源 | 资源插件内建 `workspace` | 无。缝隙 1，在插件集（C1） |
| 互不依赖的引理可以并行 | 司南规则表 | 无。缝隙 2：`info=complete` 把并发压到 1 至 2，对引理链偏保守（C2） |
| 报错全文反馈 | 判官配置 | 无 |
| 判官的算力成本 | `cost` 事件按价目表折算 | 无 |
| 题面到形式命题的忠实性 | 人执行的 Intent 做验收 | 无。M3 只收人给出形式命题的题；模型做形式化时，报告分开写"命题经人验收，证明经判官确认" |

两处缝隙都在内核之外，红线 3 在纸面上通过。真正的验收仍是 M3 接入时内核的代码差异为空。

---

## 7. 路线图与 M0 实施清单

| 里程碑 | 内容 | 出口条件 |
| --- | --- | --- |
| M0（3 周，1 人） | 六个契约的最小版；一个 CLI 后端；先纵切、后加厚。含判官资产的保密库、终态三值、任务包留档、`pd` 文本输出的四语域约定；没有网页（方案 α） | 下表 D15 |
| M1（再 2 到 3 周） | 评测台：20 题与检查点、B1/B1b/Bk/Bn 四臂、消融开关、归因表（含折损账、切口命中率、按签名分组的薄厚路径统计）；E1/E2 与 Verify；争议；r1 与 r2 消费门的完整形态（含前提豁免）；续期门；knot 与换缝优先；端点代理接第二家厂商（异家族 Verify 用）；人的决策绑定所见（`seen`、`stale_view`）、卡片投影与 `as_of` 读端点。搭车三项，合计约 2 天：预测账、对照判据、评测预登记 | §8.3 的 G1 到 G3；每个已启用的 T-1 结构各有一条消融结果；8.5 的审计清单逐项有读数 |
| M2 | 闲人全协议；模型分层；扇出控制器，含 C2、关节度与榷场零级；常设留出；按批重算；单写者压测；题集扩到 50 | 各自的消融结果，没有带来增量的删除；压测给出单写者的事件率上限，并回答瓶颈是否在 Reason 的互斥域；留出读数与专门消融的结论是否一致 |
| M3 | 内核增量：判据的有效期、延迟判官、人执行的 Intent；题界与封存、`seal_check`、判例自动封存。之后接入第二个领域：数学（Lean），按 6.4 与下面的接入清单 | 接入第二个领域时内核代码零改动，只新增锦囊、判官配置与资源插件。这是红线 3 的验收 |
| M4 | 内部次序写死：**通鉴管线先行**（含由厚回薄的建议）；r2 的完整形态，即类型化只读工具、凭据按次签发、`rollback`、四顾的完整清单；多节点（PostgreSQL、对象存储）与虚拟机；**榷场一级垫后**，只在题组层，须过三读数闸门（4.4），任一读数不满足即顺延 | 锦囊消融为正且学习曲线达标（4.3），否则通鉴只留判例；r2 场景里每条前提的判据都来自类型化只读工具，或有人的豁免；榷场一级按 4.4 的证伪线 |
| M5（新增） | 子题与托管；**模型网关**（由 M4 挪来）；榷场二级，由一级的读数决定建不建；百到千并发压测；第三场景（运维，含 r2） | `market=quote\|capital` 与子题臂的消融结果；切口命中率不降是子题成立的条件 |

**内核增量台账。** v1.2 之后，前沿设计给内核新增的东西一共七处，其余全部是投影、判官配置、司南规则或外壳：

| # | 增量 | 里程碑 | 类别 | 来源 |
| --- | --- | --- | --- | --- |
| 1 | `submit` 的 `forecast` 字段与校准投影 | M1 | T-0，量具 | 蓝图 N3 |
| 2 | `Check.control` 与支持记录的 `controlled` | M1 | T-0，守门官 | 蓝图 N1 |
| 3 | 人的决策操作的 `seen {seq, card_hash}` 与拒绝码 `stale_view`；投影哈希按卡片范围计算 | M1 | T-0，守门官 | HMI H2 |
| 4 | `register_artifact` 的摘录规则，内建判官 `seal_check` | M3 | T-0，守门官 | 蓝图 §2.4 |
| 5 | `Intent.rollback`，r2 强制 | M4 | T-0，守门官 | HMI H1 |
| 6 | 行情事件与第四投影，`market=off` 时不存在 | M4 | T-1 | 蓝图 §3.1 |
| 7 | `Intent.delegate`，`escrow_out` 与 `escrow_in` | M5 | T-1 | 蓝图 §3.4 |

七处都不含领域词。前五处是守门官或量具；后两处有开关，关闭后内核回到 v1.2 的行为。v1.2 自己带来的东西不在这七处之内：派生量 `knot`、`unlocks` 与终态，字段 `Intent.follows`，操作 `escalate_intent`，保密库引用 `VaultRef`，它们都不进等级函数与消费门。只读端点的 `as_of`、卡片投影端点和五个事件名是读侧与命名上的增量，不改 reducer 的语义。

北极星是一对数：解题率与每题成本，始终与各条基线并排报告。任务书写作"每题成本 × 解题率"；两者方向相反，乘积无法排序，所以需要合成一个数时用每解出一题的成本（总成本 ÷ 解出题数）。

M0 实施清单（15 个工作日）。前 7 天做一条最薄的纵切，让最大的不确定项尽早暴露；后 8 天加厚：

| 日 | 交付 | 当日验收 |
| --- | --- | --- |
| D1 | 仓库骨架；事件信封、JCS 规范化、哈希链；SQLite 日志；重放测试台；Blob 仓库 | 3.1.5 的 1；3.2.5 的 1、4 |
| D2 | reducer 的最小集（开题、Artifact 登记与可采信检查、论断、判官请求与裁决）；M0 等级函数与迟滞，以参考模型为对照；组件令牌 | 等级函数的单元测试（一次失败回到 E0，连续两次失败为 X）；3.1.5 的 4（M0 形态）；3.2.5 的 2 的前四种形态 |
| D3 | 执行层：执行容器、出站白名单与访问摘要、`exec` 的采集与登记 | 3.6.4 的 1、3 |
| D4–D6 | Adapter：模型容器、端点代理（换密钥、记用量、超额拒绝）、工具端点与三个代理工具、任务包渲染与留档（登记为 authored 类）、十项后端绑定 | 3.4.5 的 1、2、4、7（脚本化的假 CLI），再用真 CLI 跑通一次；3.6.4 的 4 |
| D7 | 判官运行器、`replay`、`exact_match`、抖动策略与次数上限；保密库与含密级资产的引用。**纵切完成**：用桩租约手工起一个 Bootstrap 会话做一道练习题；同一道题手工跑一次 B1 | 3.3.5 的 1、2、4、5、6、8、9；Goal 为 E3；得到第一组成本实测值和外壳税的第一个读数 |
| D8 | 租约、`/work` 派生、过期、幂等、崩溃恢复；消费门；画像推导；带判据的 Intent；关题三步与终态三值（r0 题清单为空） | 3.1.5 的 2、3、5、6、7、8、9、15；3.3.5 的 7；3.4.5 的 3、6 |
| D9 | 预留、`budget_mark`、哮天犬、收尾轮；账本投影与代理记录对账 | 3.5.5 的 1、2、4、5 |
| D10 | `pd` 命令行与人的通道（`problem open`、`status`、`profile`、`hint`、`approve`），文本输出遵守四语域标记、等级词表与判据徽章（4.1）；scope 按风险编译、`scope_violation` | 手工开题、注入 Hint、批准一次范围修订；3.6.4 的 2 |
| D11 | 司南最小循环；bootstrap、reason、explore 三份角色提示 | 假 CLI 下走完 bootstrap、reason、explore、goal |
| D12 | 厚路径端到端：一道 Bootstrap 解不出的练习题；`pd report`（首行写终态与根结论的等级上限）、轨迹导出、归因记录 | Goal 为 E3，解题链跨至少两个会话；3.4.5 的 5 |
| D13 | 对抗用例专日：坏事实注入、伪造 Artifact 五种、环状引用、伪造观察、预算穿透、空谓词；Blob 回收 | 全部通过并进入持续集成；3.2.5 的 3 |
| D14 | 对照臂运行器 B1 与 B1b：同一模型、同一 Goal 判官，前者用原生工具面，后者用代理工具面 | 同一组题的 B1、B1b 成本与结果入库 |
| D15 | 缓冲；M0 报告。可选且不阻塞出口：一个读 `pd report` 的结构化导出与事件日志的只读单页，不起服务 | 报告含端到端日志、对抗用例结果、B1 与 B1b 对比、已知缺口清单 |

M0 不做：E1/E2、Verify、闲人、分层、扇出控制器、通鉴、多厂商路由、判据的有效期、续期门、类型化只读工具、r2 凭据注入（M0 的题目只含 r0 规则）、PostgreSQL、图形界面（前端取方案 α，网页从 M1 起分期，见 HMI 设计 §5）。

15 天是没有意外时的估计 [观点]。最大的不确定项是 D4–D6：真实 CLI 在去掉命令工具、只挂外部工具、端点指向代理时的行为，可能与帮助文本有出入。纵切把它放在第一周，D6 结束时还没跑通就停下来重估，退路是换后端或自研薄循环 [证据 S3]。超期时先砍 D12 的报告排版和 D10 的命令行便利项。

M3 接入清单（第二领域动工前逐项核对）：

1. [待核] 独立内核检查器的具体工具及其覆盖面：能否复核全部编译产物，对公理集的报告是否与编译器一致（6.4）。
2. 锁定证明检查器与库的版本，得到 `lean-pinned` 镜像的摘要。
3. `lean_check` 的正反样例，注册前必须全部通过（5.2 场景 3）：反例至少含留空、被禁用的特性、候选试图改动命题三种。
4. 资源插件的 `workspace` 种类与司南的 C2 并发规则已经落地（3.6.2、4.1）。
5. 判官算力的价目表条目，编译成本以 `cost` 事件入账。
6. 核对方式写成脚本：接入前后对内核目录做差异比较，结果必须为空。

---

## 8. 消耗预算与 M1 目标

### 8.1 价目与会话成本模型

本节数字除价目外全部是 [假设]，M0 的 D7、D12 与 D14 会给出第一批实测值。

价目取一家主流厂商 2026-11 的公开标价，分三档（美元每百万 token）[证据：厂商价目页，不在调研编号内，会变动]：

| 档 | 输入 | 输出 | 缓存读 | 缓存写（5 分钟） |
| --- | --- | --- | --- | --- |
| 强档 | 4 | 20 | 0.20 | 5 |
| 中档 | 2 | 10 | 0.10 | 2.5 |
| 廉价档 | 0.10 | 0.50 | 0.01 | 0.125 |

一次会话有固定前缀 P（外壳提示加任务包）、每回合新增 Δ（模型输出加工具结果）、回合数 T、每回合输出 o。会话内缓存正常时：

```
成本 ≈ P×写价 + [(T−1)·P + Δ·T·(T−1)/2]×读价 + (T−1)·Δ×写价 + T·o×输出价
```

缓存读一项随回合数的平方增长。所以把一次长会话拆成几次短会话并不更贵，庖丁的成本倍数主要来自总回合数变多。

### 8.2 角色 × 档位 × 单题成本

下表按一道中等难度、走到厚路径的题估算。

| 角色 | 档 | P / Δ / o（千 token），T（回合） | 每次（美元） | 次数 | 小计 |
| --- | --- | --- | --- | --- | --- |
| 瘦基线 B1，跑满 | 强 | 15 / 2.5 / 0.6，80 | 3.8 | 1 | 3.8 |
| Bootstrap，跑满 | 强 | 17 / 2.5 / 0.6，80 | 3.9 | 1 | 3.9 |
| Reason | 强 | 42 / 2 / 1.2，6 | 0.45 | 4 | 1.8 |
| Explore | 强 | 27 / 2.5 / 0.6，25 | 1.0 | 5 | 5.0 |
| Explore（M2 分层） | 中 | 同上 | 0.5 | 10 | 5.0 |
| Verify（M1） | 中，异家族 | 18 / 2 / 0.5，5 | 0.1 | 3 | 0.3 |
| 闲人（M2） | 廉价 | 20 / 2 / 0.5，8 | 不到 0.01 | 5 | 0.05 |
| 判官 | 无模型 | 容器运行数秒到数分钟 | 约 0 | 约 10 | 约 0 |
| 复盘（M4） | 强 | 42 / 2 / 1.5，7 | 0.5 | 1 | 0.5 |

- 题预算硬顶取 B1 跑满成本的 3 倍，即 11.5 美元。厚路径合计约 11 美元（Bootstrap、Reason、强档 Explore、Verify），落在硬顶之内；token 量约 1800 万，与 Cairn 每题约 2000 万（10.9 亿 ÷ 54 题）、sapper 每个 flag 约 1180 万（1B ÷ 85 个）处在同一量级 [证据 Z1][Z3][Z4，折算为本文所作]。
- 分层不降低被硬顶截断的题的成本，它让同一预算下的 Explore 会话数由 5 变为 10。这是否换来解题率，要靠消融。
- 三类题的单题成本：易题由 Bootstrap 在约 40 回合内解出，1.6 美元，B1 同为 1.6；中等题 Bootstrap 有一半机会解出，期望 6.8 美元，B1 为 3.2；难题跑到硬顶，11.5 美元，B1 为 3.8。

### 8.3 指标定义与 M1 目标

- 解题率 s：题集上 Goal 被判官确认的比例，每题重复 3 次取平均。
- 成本倍数 m：该臂总成本 ÷ B1 总成本，同题集、同价目表。
- **R = (s − s_B1) ÷ m**，单位是百分点每倍成本。任何一条臂都可以算。
- 检查点分 c：每题由出题人事先写下 3 到 5 个中间检查点，对 Worker 隐藏，登记为含密级资产（3.3.2）。评测台在运行结束后对该次运行的全部命令输出求值，各臂用同一实现；c 是通过比例的平均。长链路要有部分得分 [证据 S13]。c 不改变 G1 到 G3 的判定，只用来定位各臂卡在哪一步，并在 G1 的差距不超过 1 题时决定是否值得扩题集复核。
- 外壳税：s_B1 − s_B1b，连同两者的成本之比一起报告。B1b 与 B1 同提示词、同预算，工具面换成双容器加 `exec`，`submit` 只开放 `claim_done`。

题集 20 题（约 20 题即可起步评测 [证据 S37]），按 B1 的 3 次试跑分层：易 4 题（全过）、中 8 题（过 1 到 2 次）、难 8 题（全败，但有已知解法）。只取中段会让等成本重试的解题率逼近上限，无从比较；黑板声称的价值在难段 [观点]。

按三段单次解出概率 0.95、0.5、0.05 预估 [假设]：s_B1 约 41%；Bk（同一硬顶下最多重试 3 次）s 约 61%、m 约 2.2、R 约 9；庖丁 m 约 2.4。

| 目标 | 阈值 | 论证 |
| --- | --- | --- |
| G1 生死线 | 同一题预算硬顶下 s_P − s_Bk ≥ 10 个百分点；且难段至少有 2 题是庖丁在多数重复中解出、Bk 的 3 次重复全败 | 独立重试自己就能把解题率抬高约 20 个百分点。赢不了它，共享状态就没有价值，按红线 5 删除编队。10 个百分点即 20 题中的 2 题，是能与单题偶然区分的最小差距 [观点] |
| G2 成本 | m ≤ 3，由题预算硬顶强制；预估约 2.4 | 多智能体系统的 token 约为对话的 15 倍 [证据 S37]，单智能体约 4 倍 [待核：调研未摘录此数]，两者之比约 3.75；sapper 以 1B token 胜过 4.5B [证据 Z4]。3 倍处在已报告的高效一端 |
| G3 效率 | R_P ≥ R_Bk + 3；按预估即 R_P ≥ 12 | 由 G1 与 G2 推出：s_P ≥ 71%，m 约 2.4 |

执行规则：

1. 先跑 B1、B1b 与 Bk，用实测值重算上表并冻结，再跑庖丁。阈值不在看到庖丁结果之后调整。
2. 各臂同模型、同题预算硬顶，对 Goal 判官的访问也相同：同样的提交次数上限，同样只返回通过与否。一律关闭联网检索，以免直接搜到题解。评测中人不注入 Hint、不做审批，题集只含 r0 规则。
3. 外壳税超过 5 个百分点（60 次运行中的 3 次）时，先改 `exec` 的语义再跑庖丁。Bk 取 B1 与 B1b 中解题率较高的工具面，让基线始终是它最强的形态。
4. 20 题只能给出方向性证据，头部系统在更大的题集上尚且统计不可分 [证据 S1]。G1 未达标时，允许针对最大的失败模式修改一次并重测；仍未达标则删除 Reason 与 Explore 编队，保留证据账本、判官、预算与执行层，退回"瘦基线加判官"。M2 把题集扩到 50 后复核一次。
5. 同时报告 Bn。Bn 与 B1b 同工具面、同判官、同提交次数上限：共享笔记是它被测的唯一变量，不把它做成稻草人对照 [规格裁决书 A2 的附带条件]。庖丁赢 Bk 却不赢 Bn，说明价值在共享而不在图与等级，此时把解牛图简化为追加写笔记加判官。
6. 评测自身也记账。按 8.2 的估算，B1 与 B1b 各约 190 美元，Bk、Bn 与庖丁各约 410 到 460 美元，首轮合计约 1700 美元；每条消融臂只跑中、难两段，约 440 美元 [假设]。
7. **预登记**（N2，M1）。规则 1 冻结下来的 G1 到 G3 阈值、本文各条证伪线与消融臂清单，以 input 类 Artifact 的哈希写进评测题组的开题事件。改阈值就得开新的题组，旧读数不与新读数混算，"不在看到结果之后移动球门"由此成为机械保证。规则 4 允许的"修改一次并重测"就是开一个新题组，新旧两组都留在报告里。切换厂商、接入路径或价目表版本，同样算评测条件变化，开新题组（HMI 设计 §12.4）。M1 的题组只是评测台登记的一个分组；M5 起它与 2.4 的题组是同一种对象。评测题组不参加常设留出（8.6），除非预登记里写明。

### 8.4 结构归因表

删简律要落到账上。每道题关闭时，图服务从日志投影出一行归因记录，不调用模型。它是复盘里确定性的那一半。

```ts
type Attribution = { problem_id: string, solved: boolean, path: "thin"|"thick"|"none",
  chain: { sessions: string[], intents: string[], facts: string[] },    // 解题链
  on_chain: Record<string, boolean>,     // 每个 T-1 结构是否出现在解题链上
  spend: Record<string, Budget>,         // 每个结构名下的花费
  pruned: { intents: number, reserve_released: Budget },                // 因前提被证伪而放弃的 Intent
  human: { hints: number, approvals: number },
  wear: { cut: Budget, break: Budget,                                   // M1：折损账，割与折
          break_by: Record<"no_output"|"stalled"|"budget_killed_empty"|"reject_loop"|"scope_violation"
                           |"flaky_rejudge"|"repeat_same_intent", Budget> },
  cuts: { checked: number, achieved: number, on_chain: number, dropped_by_premise: number } }   // M1：切口命中率
```

解题链 := 从被判官接受的 Goal 候选出发，沿 yields、derives_from 与 Intent 前提三种边回溯到的全部会话、Intent 与论断。

| 结构 | "在链上"的判据 | 名下花费 |
| --- | --- | --- |
| 厚路径（Reason 与编队） | 被接受的候选不是 Bootstrap 提交的 | Reason 与 Explore 的全部花费 |
| 共享图 | 链上至少有一条论断或已达成的 Intent，产出它的会话不同于消费它的会话 | 无，是基础设施 |
| 带判据的 Intent | 链上有已达成的带判据 Intent | 它们的判官花费 |
| E1/E2 复核 | 链上有论断在被 r1 以上的 Intent 消费时等级为 E1 或 E2 | Verify 的全部花费 |
| 闲人 | 链上有论断或反证最初由闲人提出 | 闲人的全部花费 |
| 模型分层 | 链上有会话运行在非强档 | 非强档会话的花费 |
| 八仙的竞速 | 提交被接受候选的会话是竞速路线之一 | 落败路线的花费 |
| 锦囊 | 链上有会话读取过锦囊正文 | 复盘与发布的摊销 |
| knot 与换缝 | 链上有 Intent 曾带 knot，其后经观察 Intent 或换缝解开 | 承接它的观察 Intent 的花费 |
| 对照判据 | 链上有带对照的观察 | 对照运行的判官花费 |
| 榷场（一级起） | 提交被接受候选的会话，它的名额来自名额公式，而规则表不会给 | 报价的花费 |
| 子题 | 链上有经 `seal_check` 达成的 Intent | 子题的开题与封存，约为零 |

规则：

1. 汇总两个数：贡献率，即厚路径解出的题里该结构在链上的比例；成本占比，即名下花费 ÷ 总花费。
2. 厚路径累计解出不少于 10 题之后，贡献率低于 10% 而成本占比高于 5% 的结构标为待删候选，下一轮评测必须带上它的消融臂。
3. 归因是观测性的。结构在链上不等于必要，不在链上也可能靠剪枝起作用；解题链按声明的前提回溯，读过而未声明的节点不在其中。所以归因只筛候选，删与不删由消融定论。
4. 共享图的贡献率是 G1 的先行读数：它很低时，厚路径的解出多半只是多跑了几次。
5. 续期门、三层视图、关节度与 `bootstrap_share` 没有"在链上"的读数，只能靠消融。生产中有人注入 Hint 的题单列，不计入自动解题率。

**折损账**（D2，M1，量具）。花费分两种。割：任务产出了被判官确认的对象，即 E3 论断或达成的带判据 Intent，或者它给出的排除结论被下一轮 Reason 引用。折：下面七类任务的花费。它们都已经是日志里的事件或释放结果，投影不需要新数据。

| 类别 | 含义 | 出处 |
| --- | --- | --- |
| `no_output` | 会话从未调用 `submit`，收尾轮之后仍然没有 | 3.4.4 |
| `stalled` | 事件流 10 分钟没有新事件，被终止 | 3.4.4 |
| `budget_killed_empty` | 越过硬顶被终止，且没有留下任何已提交的操作 | 3.5.4 |
| `reject_loop` | 同一操作连续被拒 3 次 | 3.4.4 |
| `scope_violation` | 越界累计 3 次被终止 | 3.6.2 |
| `flaky_rejudge` | 判官抖动引起的复判 | 3.3.4 |
| `repeat_same_intent` | 同一 Intent 上既没有换缝也没有新前提的重复尝试 | 3.1.7 |

M1 的报告把 `break ÷ 总花费` 与成本倍数并列。庖丁对 Bk 的成本优势如果存在，应当体现为折损率更低 [假设]。其中可归责于会话的四类 `no_output`、`stalled`、`reject_loop`、`scope_violation`，同时是榷场罚没保证金的依据（4.4）。

**切口命中率**（D3，M1，量具）。三个比例：带判据的 Intent 里达成的比例 `achieved ÷ checked`；达成者里在解题链上的比例 `on_chain ÷ achieved`；因前提被证伪而放弃的比例 `dropped_by_premise ÷ checked`。前两个低，说明切口不在关节上；第三个高，说明切口建在没有核实的前提上。"达成但不在链上"的比例是判据通胀的直接读数：按签名滚动统计超过 50% 时，续期门的进展谓词收紧为只认在链的达成，题目未解出时"在链"按"仍被未终态的 Intent 直接或传递地用作前提"近似 [观点]。

**由厚回薄的统计**（D6，M1）。归因记录的 `path` 与结构签名一起作分组键，驱动规则见 4.3。

### 8.5 M1 审计清单

除 G1 到 G3 之外，M1 要交出下面这些读数。它们决定哪些结构留到 M2，也是未证明清单（§11）里 M1 各条的验证方式。抽样由人判读，样本从日志里按确定性的规则抽取。

| # | 审计项 | 做法 | 读数触发的动作 |
| --- | --- | --- | --- |
| 1 | E2 误晋级率 | 到过 E2、后来被判定性判官否定的论断占比（5.2 场景 1） | 超过 10% [假设] 时，E2 的条件收紧为"必须含新的执行证据" |
| 2 | 标题超出谓词 | 抽样 E3 观察，人判标题是否说得比谓词多；带对照与不带对照分两组 | 两组没有差别，则删对照判据 |
| 3 | 恒真谓词 | 同一批样本里，谓词不依赖被观察对象的比例；另计 `inconclusive(no_contrast)` 的次数 | 同上 |
| 4 | **对照质量** | 抽样带对照的 E3 观察，按对照运行的结束类别 `control_end` 统计原因分布：断言不成立而正常退出、超时、崩溃、输入不存在等；人另标"这个对照是否含信息" | 不含信息的对照占比高时，判官收紧为"对照必须正常退出且断言不成立"才算不通过；仍然高，完整版改由另一个会话生成对照输入 |
| 5 | 预测校准 | 各（家族、角色）的 Brier 分，对比"永远报基础率" | 都不优于基础率，则自报概率不可用，榷场一级不必建 |
| 6 | 折损率 | `break ÷ 总花费`，各臂并列，按七类分列 | 庖丁的折损率不低于 Bk 时，成本优势的来源要重新解释 |
| 7 | 切口命中率 | 8.4 的三个比例 | 达成率高而在链率很低时，续期门的进展谓词收紧（§10 第 6 条） |
| 8 | 续期门 | 触发次数、省下的预算、`extension=always` 下多解出的题数 | 触发次数接近零，换更严的进展谓词 |
| 9 | knot 与换缝 | `knot=off`、`escalate=first` 两条消融臂，只跑难段 8 题 | 没有带来增量则删 |
| 10 | 薄厚路径 | 按签名分组的薄、厚路径解出率 | 只记录，建议在 M4 |

第 4 项回应对照判据的一个残余：对照输入由提出者自选，他可以选一个技术上失败但不含信息的对照，例如一个不存在的输入。这种对照让裁决带上 `controlled`，却什么也没有排除。

### 8.6 常设留出

[T-0，量具；M2] 官知止审计靠里程碑上的专门消融，贵而且稀。常设留出让每个感知官常年带一个留出率 ε，得到没有选择偏差的在线增益读数；4.3 的锦囊留出是它的一个实例。

分配是互斥的，可重放：

```
留出表 := 已启用的感知官（按 2.3 的开关名）∪ 本题匹配到的锦囊，按名字排序
格宽   := min(ε, 1 ÷ 表长)                                // ε 默认 10%
u      := sha256(model_epoch ‖ 题目 id) 映到 [0, 1)
留出项 := 留出表[⌊u ÷ 格宽⌋]；下标越界则本题不留出
```

一道题至多留出一项，两个官的效应因此不会混在同一道题上；表长不超过 1 ÷ ε 时，每一项被留出的概率恰为 ε。留出项写进开题事件的 `holdout` 字段，对应的开关在本题关闭。守门官与量具不在表内，永不留出；含 r2 规则的题不参加。

读数是两组解出率之差：增益 := 展示组的解出率 − 留出组的解出率，另看每解成本之差。小样本下它只能立旗，不能定案，所以有四条样本量说明：

1. 留出组满 8 题且增益的 90% 置信上界小于 0，只立一面"待复核"的旗。8 题只作旗帜，不触发任何自动动作。
2. 退役提议必须写明两组的题数、增益及区间、这个样本量下可检出的最小差异，并由人确认。
3. 按正态近似粗算（单侧 90%，功效 80%，基础解出率约 0.5，展示组远大于留出组），可检出的最小差异约为 1.06 ÷ √n：留出 8 题只能检出约 38 个百分点，要检出 20 个百分点约需 30 题。留出组不足 30 题的结论一律标"方向性"。
4. `model_epoch` 变化时读数另起一行重新累计，留出率临时升到 30%。

证伪线：M2 到 M4 核对留出读数与专门消融的结论是否一致，不一致则只保留专门消融。成本是 ε 乘以被留出官的真实增益。同一原则用于评测本身，就是 8.3 规则 7 的预登记。

---

## 9. 术语表

| 中文 | English | 一句话定义 |
| --- | --- | --- |
| 庖丁 | Paoding | 面向收口类问题的通用求解智能体 |
| 收口类问题 | closed-form problem | 起点明确、达成与否可以被判定的问题 |
| 解牛图 | blackboard graph | 由事件日志派生的共享图状态，节点是论断与意图，边是依据关系 |
| Origin、Goal | origin, goal | 题目的起点材料；带判官的达成条件 |
| Fact（论断） | fact | 一条可被支持或反驳的陈述，分观察类与推断类 |
| Conjecture（猜想） | conjecture | 等级为 E0 的论断 |
| Intent（意图） | intent | 已声明、待执行的探索或动作，带前提、风险与预算 |
| 带判据的 Intent | checked intent | 创建时就登记了达成判据的 Intent，达成与否由判官判定，可作其它 Intent 的前提 |
| 画像 | profile | 由判官与授权范围推出的三个量：信息完整度、判官类型、可逆性 |
| Hint（提示） | hint | 人随时注入的判断，影响规划，不构成证据 |
| Artifact | artifact | 按内容寻址、带出处类别的不可变产物 |
| Playbook | playbook | 从已解题目提炼、每一步可追溯到 E3 论断的做法 |
| 证据梯 | evidence ladder | 论断的等级，由有效支持集算出：E0 猜想、E1 单源复核、E2 异构复核、E3d 相符性判官通过、E3 判定性判官通过、X 已证伪 |
| 支持记录 | support record | 指向某论断的一条支持或反驳，含方法、判官与证据 |
| 出处类别 | provenance class | Artifact 的来源：exec、judge、input、authored，前三类可作证据 |
| 判官 | judge | 不含模型的判定程序，输出通过、失败或无结论 |
| 判定性、相符性 | decisive, consistent | 判官的等级：通过即确立；通过只说明与预测相符 |
| 谛听 | verification layer | 判官、Verify 任务与消费门的合称 |
| 消费时验证 | verify-on-consume | 论断被有风险的 Intent 用作前提时才触发验证 |
| 争议 | dispute | 论断收到未被驳回的模型反证后的状态，靠检查或人裁决 |
| 司南 | scheduler | 无状态、不含模型的调度循环 |
| 八仙 | fan-out formation | 并行探索的编队及其扇出规则 |
| 闲人 | idler | 只写猜想与反证的低成本旁观会话，分 falsifier（消费之前先攻击论断）与 free-form（停滞时注入猜想）两种 |
| 复盘 | retrospection | 预算节点上的反思，以及题目关闭后的归因与提炼 |
| 归因表 | attribution table | 逐题记录每个 T-1 结构是否在解题链上、花了多少，见 8.4 |
| 续期门 | extension gate | 花费过 80% 后，没有被判官确认的进展就不再开新的探索 |
| 如意 | tool layer | Worker 可用的工具：CLI 的文件工具、三个代理工具、锦囊捆绑的脚本 |
| 代理工具 | proxy tools | Adapter 托管的 `exec`、`submit`、`show`，是 Worker 对外的全部通道 |
| 锦囊 | skill kit | 按需加载的领域知识与脚本目录 |
| 通鉴 | cross-problem memory | 跨题的记忆：判例、Playbook 与锦囊、读数三类记录，效力各不相同 |
| 哮天犬 | watchdog | 不含策略的脚本：过期租约、超预算终止、清理、告警 |
| 提议、租约 | proposal, lease | 待图服务校验的一批写操作；带预留预算与期限的任务认领 |
| Worker、Adapter | worker, adapter | 执行任务的 CLI 会话；为它渲染任务包、托管代理工具并管理租约的进程 |
| 端点代理 | endpoint proxy | 容器外的反向代理：换密钥、记用量、超额拒绝；M1 接第二家厂商，M5 扩成模型网关 |
| 模型容器、执行容器 | model container, exec container | 前者运行 CLI，只连工具端点与模型端点代理；后者运行命令，只连授权范围 |
| 瘦基线 B1 | thin baseline | 单个 CLI 会话，原生工具面，配同一授权范围与同一 Goal 判官 |
| B1b、外壳税 | proxy-surface baseline, harness tax | 工具面换成代理工具的瘦基线；它与 B1 的解题率之差 |
| Bk、Bn | equal-cost retries, shared-notes baseline | 同预算下的独立重试；多个 Worker 共用一份追加写笔记 |
| m、R | cost multiple, efficiency | 成本倍数与每倍成本换来的解题率增量，见 8.3 |
| 信任根、协调基质、会话边界 | trust root, coordination substrate, session boundary | 六契约按变化速率分成的三层，见 2.1 |
| 官：感知官、守门官、量具 | organs: sensing, gatekeeping, gauge | 外壳结构的三类：弥补模型缺陷、带退役条款；守世界的性质、长存；只产生读数、永不退役也永不守门 |
| 题界、封存、摘录 | problem boundary, seal, excerpt | 日志按题独立；封存是某题链头的可校验指纹；摘录是凭封存跨题传递的只读片段，在接收题里是 input 类材料 |
| 题组、子题 | problem group, sub-problem | 没有 Reason、Intent 全是子题委托的父题；由带 `delegate` 的 Intent 开出的独立 Problem |
| 托管 | escrow | 父题划给子题的预算，凭终态封存回拨余额 |
| 保密库 | vault | Blob 仓库之外、只有判官运行器可读的目录，存含密级判官资产 |
| 终态 | terminal | 题目关闭时的三值：solved 判官确认，accepted 人验收，unsolved |
| knot（难点标记） | knot | Intent 上的派生标记：上次失败、前提有争议或不稳、前提失联三者之一 |
| 看清、换缝、升档 | observe, reroute, escalate | Reason 在难点上的三个选择：先开一个小的观察 Intent；换前提或方法另开一条；同一切口改用强档 |
| 关节度 | unlocks | 以某 Intent 为前提而当前 blocked 的 Intent 数 |
| 四顾 | closeout checklist | 关题前的确定性收尾清单；关题三步是四顾、定终态、藏刀 |
| 折损账、割与折 | wear ledger: cut, break | 花费分为有确认产出的"割"与七类空转的"折" |
| 切口命中率 | cut hit rate | 带判据的 Intent 的达成率、在链率、因前提被证伪而放弃的比例 |
| 对照判据 | controlled check | 带负对照的判据：同规格、异输入，主运行通过且对照不通过才算通过 |
| 预测账 | forecast ledger | 每个任务事先报的成功概率与花费，结算后给出校准读数 |
| 常设留出 | standing holdout | 每个感知官以固定概率在一道题上被关掉，得到无选择偏差的增益读数 |
| 预登记 | pre-registration | 评测阈值与证伪线在开跑前以哈希写进开题事件 |
| 榷场、合约、席位、行情 | market, contract, desk, price | 记账的预算分配算法；带判据对象上的可结算条目；估值与出资的记账单位；聚合后的通过概率 |
| 判例、结构签名 | case, signature | 关题时由日志投影出的事实记录；画像、判官、资源种类与标签组成的检索键 |
| 由厚回薄 | thick-to-thin | 某类题上厚路径没有增量时，建议只跑瘦路径 |
| 卡片、所见绑定 | card, seen binding | 审批、收尾、续期、争议四种决策所依据的确定性投影；决策操作带所见卡片的哈希 |
| 四语域 | four registers | 界面内容的四种来源：证据、叙述、人的判断、估值，呈现上不可混淆 |

---

## 10. 开放问题

| # | 问题 | 选项 | 倾向 |
| --- | --- | --- | --- |
| 1 | E1 与 E2 是否保留为两级 | 保留；合并为一级"模型复核"；只留二值 | 先按两级实现，M1 的 `ladder=binary` 消融决定；两级的误晋级率没有差别就合并 |
| 2 | 外壳税超过阈值时怎么办 | 改进 `exec` 的语义直到贴近原生工具；Bootstrap 改回单容器的原生工具面，只让厚路径用代理工具；接受差距 | 第一项。第二项会把 v1.0 的三个缺口带回 Bootstrap，只在练习环境里可以接受 |
| 3 | 跨轮的前缀缓存 | 只靠会话内缓存；替换系统提示并划出静态段；自管循环 | M0 只靠会话内缓存并实测。Reason 的输入成本超过题成本的 15% 时再做第二项 |
| 4 | 在途会话是否接收 Hint | 下一个任务包生效；经流式输入即时注入 | 前者。中途干预要谨慎 [证据 S17]，且各后端支持不一 |
| 5 | Explore 用哪一档 | 全强；中档加失败升级；强档调低推理强度 | M1 全强，M2 三者做消融 |
| 6 | 续期门的进展谓词取多严 | 有带判据的对象新到 E3；只认带判据的 Intent 达成；只由人放行 | 第一项起步。它可能被琐碎的观察轻易满足，对照判据启用后这条路已经收紧（3.5.2）：M1 统计触发次数、省下的预算，以及 `extension=always` 下多解出的题数，触发次数接近零就换第二项 |
| 7 | 语义去重 | 不做；`same_as` 提议；嵌入聚类 | 不做，直到实测近重复节点超过 15%。嵌入聚类进写入路径会破红线 1，排除 |
| 8 | Bootstrap 的长度 | 完整的瘦基线运行；短侦察后尽早扇出 | 前者作默认，`bootstrap_share` 做一条消融臂 |
| 9 | 题预算取瘦基线的几倍 | 2；3；5 | 3。M1 用实测的 R 曲线复核：倍数再加大而 R 下降就不加 |
| 10 | 与 v0.1 修订稿的出入 | 以本文为准；以 v0.1 为准；逐条对账 | **已关闭**：以本文为准，v0.1 作为历史桥接文档归档，不逐条回改（规格裁决书 §五） |
| 11 | 子题由谁开 | 只由人或批量开题；Reason 提议后经确定性校验自动开；Reason 提议后人批准 | M5 之前只做第一项，本版已按此落地（4.6）。第二项要等切口命中率的读数证明 Reason 切得准 |
| 12 | 榷场的二级形态值不值得建 | 建；只留一级；连一级也不建 | 由预测账与一级的读数决定。预期一级留在题组层，二级多半不需要 [观点] |
| 13 | 留出率 ε | 5%；10%；20% | 10%，模型换代后的首批题用 30% |
| 14 | 对照判据的强制范围 | 所有观察；只对 r1 以上的前提与进展计数；全部可选 | 第二项。本版先落 r2 的前提与进展计数，r1 是否纳入由 8.5 的读数决定 |
| 15 | 判例检索是否加向量检索 | 不加；加 | 不加。触发线：判例超过 500 条，且前 5 条里被读取并在链的比例低于 20% |
| 16 | 通鉴是否跨项目共享 | 单项目；跨项目 | 单项目。跨项目共享是投毒面，等签名与撤回机制跑过一轮再议 |

---

## 11. 未证明清单

本文的主张分两种：已经机械化的（写进规格、由代码强制），和待证明的。下面是后一种的全集，每条写明在哪个里程碑、用什么读数验证；被证伪的，对应结构按正文写明的证伪线删除。

| # | 假设 | 验证 |
| --- | --- | --- |
| 1 | 编队（Reason 加 Explore）有价值：等成本下赢得过独立重试 Bk | M1，G1；未达标则退回"瘦基线加判官" |
| 2 | 外壳税在可接受范围内 | M0 的 D14 与 M1，对照臂 B1b；超过 5 个百分点先改工具面 |
| 3 | 难点上"收拢优于加宽"（knot） | M1，`knot=off` 消融；判官廉价的题上可能不成立 |
| 4 | §8 的成本数字 | M0 的 D7、D12、D14 给出第一批实测值 |
| 5 | 官知止的退役信号选得对 | 每个里程碑的官知止审计；信号本身要随模型代际校准 |
| 6 | E1 与 E2 分两级优于二值 | M1，`ladder=binary` 消融 |
| 7 | 模型自报的成功概率有可用的校准 | M1，预测账 |
| 8 | 对照判据能降低恒真谓词与标题夸大的比例 | M1 抽样审计（8.5） |
| 9 | falsifier 提前证伪所省下的预算大于它的花费 | M2 消融 |
| 10 | 千级并发的瓶颈是 Reason 的互斥域与读图上限，不是写入吞吐 | M2 压测 |
| 11 | 常设留出的读数与专门消融的结论一致 | M2 到 M4 |
| 12 | Lean 接入时内核零改动 | M3 |
| 13 | 同签名题目的每解成本随判例数下降，且留出组不降 | M4 |
| 14 | 切口先验提高切口命中率 | M4 |
| 15 | 多家族盲报的行情优于 Reason 单报价 | M4，200 个已结算合约 |
| 16 | 题组层按行情分配优于等额分配 | M4 |
| 17 | 席位资本优于配置的路由表 | M5 |
| 18 | 工人不知情时榷场仍然有效，即它只需是分配算法 | M5 |
| 19 | 子题分解不引入交接失配，切口命中率不降 | M5 |
| 20 | 可分解工作负载占比足够高：真实题目里能拆成互不依赖的切口或子题的部分占多数。它是题组、题、子题三层展开的前提；拆不开的强耦合难题在千级并发下仍然卡在单个 Reason 上 | M2 压测时统计互不依赖的 open Intent 数与可委托切口的占比；M5 的子题臂 |

第 1 条是生死线。第 10、15、18 条是前沿设计下得最重的三注。

---

## 附录 A 基质接口映射

A9 的"事件日志加 reducer"就是协调基质的一种实现 [规格裁决书 §三.3]。基质接口共九个操作（[协调基质](./coordination-substrates.md) §7），外壳与四个信任根契约只依赖这个接口，不依赖基质的内部表示。将来更换基质时接口不动，基座因此不被任何一次基质的选择绑住。

| 操作 | 接口含义 | 本文的实现 |
| --- | --- | --- |
| `submit` | 提交提案 | `POST /proposals` 与 `POST /leases`；代理工具 `submit` 最终落到这里（3.1.2） |
| `adjudicate` | 确定性的提交门，拒绝要留痕 | `validate`，纯函数；拒绝带拒绝码返回 |
| `snapshot` | 当前世界观 | 日志的投影，即 `apply` 折叠出的状态；每 1000 个事件存一份带状态哈希的快照 |
| `stable_dump` | 字节级前缀稳定的投影 | 任务包前段，即 3.4.2 的①到④ |
| `cas` | 原子认领 | 租约：先到者得，预算预留在同一步完成 |
| `query` | 派生视图 | `/work`、`/status`、`/view`、`/budget`、`/invalidations` 与卡片投影，均可带 `as_of` |
| `settle` | 判官结算 | `judge_verdict` 与 `close_problem`；等级随之重算 |
| `replay` | 确定性重放 | 快照加事件重放；崩溃恢复、`as_of` 读、封存校验都靠它 |
| `history` | 审计查询 | `/events?after=`；哈希链按题独立 |

第 4 节的前沿结构都没有要求第十个操作：

| 前沿需求 | 落在哪个操作 |
| --- | --- |
| 报价、预测 | `submit`，都是提议 |
| 押注、托管划拨 | `cas`，租约预留加保证金锁定 |
| 行情、名额、判例索引、卡片 | `query` 的视图 |
| 合约结算与赔付 | `settle`，与判官裁决是同一个事件 |
| 封存与摘录 | `snapshot` 加 `history` |
| 子题校验、通鉴审计、回放 | `replay` |
| 跨机一致的任务包前段 | `stable_dump` |

一处勘误照录：协调基质文档 §3 曾写"价格机制天然无热点"，并把榷场当作千级并发的调度答案，这已被蓝图 F2 证伪，该文档头部加了勘误。本文里榷场不是替换解牛图的另一种基质，而是同一条日志上的第四个投影（4.4）；阡陌（git）仍是规模化时的备选基质。

---

## 附录 B 官的声明与退役条款

总纲 v1.2 要求退役条款表并入规格。新结构入库时按 2.3 的四问声明；声明不了类别的，按感知官处理，默认可拆。M2 起每个里程碑做一次官知止审计：重跑全部"关掉该官"的消融臂，在归因表旁记录各官的退役距离，即信号离翻正还有多远。官退役是一个事件，记在附录 C。

**感知官**（弥补模型的缺陷，信号翻正即退役）

| 官 | 弥补的缺陷 | 退役信号 | 退役动作 |
| --- | --- | --- | --- |
| 三层视图与下钻 | 长上下文里的注意力衰减 | 满量导出与下钻版的解题率之差不超过 1 题（20 题集）且成本不升 | `view=full_dump` 常态化，删视图层 |
| Reason 独立规划者 | 单会话跨小时的计划漂移 | 模型可持续的任务时长超过目标场景时长一倍，且归因表里 Reason 的在链率趋近 0 | 并入 Explore，单循环自己维护计划 |
| E1/E2 模型复核梯 | 同源模型互证的回声室 | E2 误晋级率低于判官自身的误判率 | `ladder=binary` 常态化 |
| 扇出控制器（八仙） | 模型不会自行分配并行探索 | 固定并发的消融不劣 | 固定并发，删规则表 |
| 代理工具的输出截断 | 上下文与成本 | 取消截断不伤成本与解题率 | 放宽上限直至移除 |
| 按画像选外壳规则 | 模型不会自选策略 | 模型自选策略不劣于推导出的规则 | 三轴只作报告字段 |
| Bootstrap 之外的厚路径 | 强模型直解的题占比还低 | 按签名：厚路径独占解出数为 0，且薄路径解出率不低于 70%（4.3）¹ | 该签名只跑瘦路径；这是结构消失的方向本身 |
| 带判据的 Intent | 会话自报的完成不可信，也不会自己沿可判定处分解 | `checked_intents=off` 的消融不劣 | 只留 Goal 一个判据 |
| 续期门 | 模型不知道自己不会 | `extension=always` 不多花，或预测账的早停读数已足够准 | 关闭，或换成预测版 |
| knot 与换缝优先 | 模型在难点上硬做 | `knot=off`、`escalate=first` 的消融不劣 | 回到 v1.1 的次序 |
| 关节度 | Reason 的估值不读图的结构 | `order=gain_only` 的消融不劣 | 删 |
| 闲人 | 锚定与过早收敛 | 反证成立率趋近 0，或 Verify 已能拦下同一批错误 | `idlers=off` |
| 模型分层 | 强档的价格 | 分层的消融不优于全强档 | 全部同档 |
| Playbook 与锦囊 | 模型没有跨题的记忆 | 按锦囊：留出增益的置信上界小于 0；整体：`kits=off` 不劣 | 退役该锦囊；通鉴只留判例 |
| 榷场 | 单个规划者估不准、估不过来 | 预测账显示 Reason 单报价的校准不劣于行情 | 退回零级 |
| 子题与托管 | 单个规划会话管不了那么大的图 | 单个 Reason 能管理的并发翻倍而切口命中率不降 | 回到单题大图 |

¹ 总纲 v1.2 这一格写作"Bootstrap 在题集上的独占解出率趋近 0"，与 4.3 的驱动规则方向相反，疑为笔误。本表按 4.3 写，待总纲核对。

**守门官**（守世界的性质，长存，只随威胁模型演变）

| 官 | 长存的依据 |
| --- | --- |
| 判官与 E3、X 的证据等级 | 达成与否必须独立于任何模型的自述（红线 2） |
| 预算硬顶 | 资源有涯 |
| r2 审批门、回退声明 | 不可逆性是世界的属性，不是模型的属性 |
| 双容器、密钥隔离、代理工具 | 对抗面来自环境与目标内容，不随模型变善而消失 |
| 事件日志与审计、判例 | 会话必死，跨会话的持久是系统的定义 |
| 判官资产的保密库 | 答案一旦对解题者可见，判定就不再独立 |
| 授权范围与画像推导 | 授权与不可逆性由人和环境决定，不由模型申报 |
| 对照判据 | 不会失败的检验什么也证明不了 |
| 题界与封存（I7） | 环境各不相同，等级对应的是那一道题的基线与判官 |
| 估值不进等级（I8） | 估计不是事实 |
| 评测预登记 | 看到结果之后再定标准，任何结果都能算成功 |
| 四顾与终局协议 | 动作的影响面不随模型变强而消失；验收属于委托人 |
| 人的决策绑定所见 | 先查后用的竞态是并发的性质 |
| 对象存储、网关粘性、`dump_mark` | 多机一致性是分布的性质 |

**量具**（只产生读数，越换代越有用，永不退役，也永不守门）

| 量具 | 测量什么 | 谁消费读数 |
| --- | --- | --- |
| 归因表 | 每个 T-1 结构是否在解题链上、名下花了多少 | 待删候选的筛选；官知止审计 |
| 折损账 | 花费里割与折的比例 | M1 报告；续期门的对话；榷场的罚没 |
| 切口命中率 | Reason 切得准不准 | 角色提示与锦囊的质量；续期门的谓词；子题是否成立 |
| 预测账 | 自报概率的校准 | 榷场一级的闸门与退役；早停；换代时的元认知读数 |
| 常设留出与通鉴读数 | 每个感知官与锦囊的在线增益 | 退役提议；退役距离 |
| 薄厚路径统计 | 各签名下薄、厚路径的解出率 | `bootstrap_share` 的调整建议 |
| 界面使用读数（HMI H5） | 前端各模块的打开与下钻次数 | 前端感知官模块的去留；存在独立的本机日志里，不进题目日志 |

量具只显示，不驱动任何按钮的默认值；凡是由读数改变行为的地方都另有开关，并在正文写明。

---

## 附录 C 版本记录

| 版本 | 日期 | 内容 |
| --- | --- | --- |
| v1.0 | 2026-11 | 提交 df86c02 |
| v1.1 | 2026-11-17 | 提交 de33acf；相对 v1.0 的变更见下表；经裁决 A1 到 A10 全部采纳 |
| v1.2 | 2026-11-17 | 未单独发布；文首第一张表的第 9 到 19 条 |
| v1.3 | 2026-11-17 | 文首第二张表的第 20 到 44 条 |
| v1.4 | 2026-11-18 | 文首第三张表的第 45 到 49 条：M0 实施勘误 E1 到 E5（[清单](../m0/errata-v1.4.md)） |

v1.1 相对 v1.0 的变更：

| # | 变更 | 位置 | 理由 |
| --- | --- | --- | --- |
| 1 | 模型进程与命令执行分在两个容器；Worker 的对外动作只走三个代理工具 `exec`、`submit`、`show`；模型密钥留在容器外 | A10、3.4、3.6 | 在 M0 就关掉 v1.0 的三个部署缺口：事件流可被篡改、嵌套会话不计量、密钥与命令同处一个容器 |
| 2 | 三轴由题目结构推出，不再由人填写；授权规则自带风险等级，执行容器的能力按 Intent 的风险注入 | A7、3.1.2、3.6 | 画像不会与授权范围矛盾；风险申报由能力强制，不靠模型自觉 |
| 3 | 时效性不设第四轴，改为判据的有效期 | A7、3.3 | 同一题里历史类观察与当前状态类观察并存，按题设轴太粗 |
| 4 | 判官裁决的翻转需要连续两次一致 | A6、3.1.2 | 单次重跑失败不应把 E3 直接变成 X |
| 5 | Intent 可以带判据；Goal、带判据的 Intent、观察类论断走同一条判定路径 | 3.1.2 | 子目标不再是内核增量；判据在动手之前登记 |
| 6 | 花费过 80% 之后，新的探索要求已有被判官确认的进展 | 3.5.2 | 不在没有进展的题上花完预算 |
| 7 | 评测加检查点分、外壳税对照臂 B1b、结构归因表 | A2、8.3、8.4 | 20 题的分辨率不够；删简律需要运行时的账 |
| 8 | M0 实施清单改为先纵切、后加厚 | §7 | 第 7 天就有端到端结果和第一个成本实测值 |

另有三处小改：Artifact 去掉 `capture` 字段，加访问摘要 `touched`；重放判官加 `require_touch`；角色字段由 `profile` 改名为 `role`，把这个词让给画像。

退役记录：暂无。官退役时在这里记一行：哪个官、何时、哪条信号翻正。
