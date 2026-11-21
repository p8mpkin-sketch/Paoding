# 04 缺口清单与分期路线

> 记号：● 完整　◐ 部分　○ 无。“完整”指 `main`（2026-11-19 重核，含 #87 设置层、#88 一句话开题一二期、#89）上已有代码与测试，且行为与本图该站的要求一致；“部分”写明缺哪一半。初版的核对点是 89fb471。
> 编号：Q# 是缺口（◐ 或 ○），K# 是已完整的位置。一句话开题（kaiti，PR #83）负责的缺口在“归属”一栏标出，本图不重复设计。
> 合计 59 个位置：v0.14 完整 48、部分 9、无 2（Q38 完整，L3b 收口）。v0.13 完整 47、部分 9、无 3（L3b 两个 PR 之后：Q34、Q35 完整）。完整 45、部分 9、无 5（v0.10，L3 第三步与 #110、#112 之后；分端计数没有随之重核）。v0.9 时完整 38、部分 11、无 10（2026-11-20 开放道修订后：新增 Q30–Q39 十个开放道位置，开放道第一步记 K40 但不计入 Q 位置；#105 合入后 Q18 → K39，#110 合入后 Q12、Q14 完整，计数随之变成 41、9、9）。此前 49 个位置：完整 38、部分 8、无 3（2026-11-19 L2 收口后；L2 第一批后为 37、9、3；L1 收口后为 32、11、6；v0.4 时为 27、15、7；初版为 48 个位置，完整 20、部分 12、无 16）。已完整的缺口留在表里，状态写 ●，同时在 §2 记一个 K 号。
> 前端与后端分开数（一个位置两边都有活就两边各算一次，见 §4）：前端 29 处，完整 25、部分 2、无 2；后端 34 处，完整 23、部分 7、无 4。

## 1. 缺口（Q）

| # | 站 | 位置 | 状态 | 缺什么 | 归属 | 分期 |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | S0 | 设置存储（快照 + 只追加变更日志 + 版本摘要）与 `/v1/settings` | ● | —（#87：`scripts/settings_hub.py`，→ K21） | 本图 03 §7 | L1 |
| Q2 | S0 | 密钥钥匙环（只在代理内存）与 `/v1/keys/{slot}` | ● | —（#87：`adapter/keyring.py`、`/v1/keys`、设置页密钥一节、金丝雀测试；配置文件写密钥按 D4 过渡一版，带告警，→ K22） | 本图 03 §4 | L1 |
| Q3 | S0 | 三道硬顶 | ● | —（#87：全局可配、单题硬顶进内核 `validate`、设置页刻度尺，→ K23）。练习上限今天只在 `vet` 里查，内核按道检查随 Q4 | 单题硬顶归 kaiti 增量 14；可配置与呈现归本图 | L1 |
| Q4 | S0 | 练习道信封（含练习预算上限） | ◐ | 信封文件 `qicao/kaiti.d/practice.yaml` 与 `vet` 的练习道判定已有，零确认开关关着；缺设置页呈现、内核按道检查练习上限、放行读数 | kaiti 增量 15；设置页呈现归本图 | L1b |
| Q5 | S0 | 预算先验 `PriorSource` 与占位表 | ● | —（#88：`qicao/policy.py` 的 `PriorSource`、占位表，→ K24） | kaiti §5.2 | L1 |
| Q6 | S0 | 设置页“系统”分组（模型档案、角色路由、密钥槽、硬顶、风险表、信封、先验源） | ● | —（#87 的密钥槽、硬顶、模型档案与角色路由、风险表、变更记录；#101 的运行时扩权一节；L1 收口补练习道信封与预算先验两节，只读，`GET /v1/settings/sources`，→ K28） | 本图 06 | L1 |
| Q7 | S1 | 一句话输入框 `/new` | ● | —（#88：`pages/Kaiti.tsx` 输入框与前置抽取，→ K25） | kaiti §7.1 | L1 |
| Q8 | S2 | 起草服务 `qicao/`（`POST /v1/drafts`） | ● | —（#88：`qicao/`、`scripts/kaiti_hub.py` 挂 `POST /v1/drafts`，→ K26） | kaiti §6 | L1 |
| Q9 | S3 | 校验层 `vet() → Vetted`（授权抽取、预算夹紧、出处账、道别） | ● | —（#88：`qicao/vet.py`，→ K27） | kaiti §2.3 | L1 |
| Q10 | S4 | 一步确认卡 | ● | —（#88 的确认卡与拒绝页；L1 收口补“模型”一块；L2 补“验收清单”一块：拒绝页第 02 条路选原句或自己写，确认卡“判据”组逐条列出、出处记“摘”或“人”，卡头写终态最多为人工验收，→ K33） | kaiti §7.3；本图 02 §3.2 补“模型档案”与“验收清单”两块 | L1（验收清单块 L2） |
| Q11 | S4 | 四步向导降级为高级编辑 `/new/advanced`（从草案带出处进入） | ● | —（#88 的 `/new/advanced` 与逐字段记号；L1 收口补原文编号与各字段摘自第几段，与确认卡同一套编号，人改过即不显示，→ K29） | kaiti §7.5 | L1 |
| Q12 | S5 | 开题事件体带 `settings_digest`、`settings_version`；任务级模型偏好 `prefs.model` | ● | —（#87 的 `settings.{version, digest}`；`prefs.model` 随 v5 第二期 #110 合入，→ K41） | 本图 03 §3 | L1（digest）、L3（prefs，#110） |
| Q13 | S5 | `goal.accept: human` 与验收清单 `goal.acceptance[]` | ● | —（L2：内核放开 `accept: human`，必须带清单，编号 a1… 由图服务分配、开题后不可改；起草服务 `acceptance` 入参，→ K34） | 放开归 kaiti 增量 16；清单归本图 02 §3.3 | L2 |
| Q14 | S6 | 按任务选模型档案（司南与 Adapter 按 `prefs.model` 解析） | ● | —（#110：适配器按 `prefs.model` 选会话模型、新建页“执行模型”，→ K42） | 本图 | L3（#110） |
| Q15 | S6 | 按租约花费（C1）与花费序列（C2） | ◐ | 后端已全：按租约花费（C1）`/budget` 的 `by_lease`、`pd status` 每会话一行（L3 第三步）；花费序列（C2）`GET /budget/series?step=`（L3 ⑤，v0.11）。网页：会话行金额已有（#112），花费随时间的曲线未画（归 v5） | 工作台设计 C1、C2 | L3 |
| Q16 | S7 | 结构检查类 advisory 判官（交付物存在、格式合法） | ● | —（L2：内建 `structure_check`，`expect {format, min_bytes}`，只给读数、Goal 停在 E0，→ K35） | 本图 02 §3.3 | L2 |
| Q17 | S7 | 召回复核的墙钟上限 60 秒 | ◐ | 只有至多 8 条的条数限界 | 2026-11-19 cz 记的 follow-up | L0 |
| Q18 | S8 | 续期门（严格道） | ◐ | 前端对话框已有；图服务返回 `not_enabled`。#105 已做（续期卡、`extend`、`budget_add`），待验收；“门关着而人不决定时”的时限已裁（D11：不加时限，墙钟与哮天犬兜底）。开放道不设续期门（D10） | 规格 3.5.2 | L3（#105） |
| Q19 | S8 | 扩权卡：开题授权 vs 申请的那一条、风险（只许上调）、批 / 拒（拒须写理由）/ 撤销；待办与工作区横幅 | ● | —（#99：扩权卡差异视图、只可上调风险、拒绝须理由、`card_hash` 绑定，待办、收件箱与工作区横幅，时间轴扩权节点，→ K30） | 运行时扩权 #91 §7 | L1（随运行时扩权提前，原 L3） |
| Q20 | S8 | 叫停（P8）：开放道 `halt` → 收尾交付；严格道 `terminate_lease`（C14） | ◐ | 开放道一半已做（L3 第三步）：`halt`（人）之后不再派 solve，哮天犬叫在途会话收尾、60 秒不交付即终止，追问解除叫停；`pd halt`；网页“停下并交付”（#112）。严格道的 `terminate_lease` 仍挂异议 web-workbench 第 5 条 | 开放道 §3.3；工作台设计 C14 | L3（开放道）、待裁决（严格道） |
| Q21 | S9 | 关题三步的交互界面 | ● | —（L2 第二批：人工验收的题，四顾清单列出运行时扩过的权限与在途会话；`accept` 带 `closeout` 逐条确认，缺项点名拒绝；验收卡上四顾逐条勾选，没勾完“验收通过”不可用并指出是哪一项；`pd accept --confirm`，→ K38） | 本图 02 §3.3 | L2 |
| Q22 | S10 | 结果页（结构化报告 C6，与 `pd report` 同源） | ● | —（L2：工作区关闭后顶部“结果”，首行终态与等级上限、判定来源、验收记录、按等级排的事实；`pd report` 加判定来源一行，→ K36） | 工作台设计 C6 | L2 |
| Q23 | S10 | 验收清单的逐条勾选与 `accept` 事件体校验 | ● | —（L2：`accept` 操作与校验、收尾卡带清单与待验收交付物、`pd accept/reject`、网页人工验收卡，全部过才 accepted；读数按判定来源分列，→ K37） | 本图 02 §3.3 | L2 |
| Q24 | S11 | 投影资产（判据模板、切口先验、花费画像） | ○ | 全部（M2 后半） | M2 设计 02 | L4 |
| Q25 | S11 | 记忆人工纠偏 `mem_pin`、`mem_forget` 的写端点与 `pd memory` | ◐ | 服务方法 `Tongjian.decide` 已有 | 2026-11-19 cz 记的 follow-up | L0 |
| Q26 | S11 | 读数页补齐“暂不可用”的量 | ◐ | 已有每解成本、按角色分项、验证池 | 视觉重做第四期 | L3 |
| Q28 | S0、S2 | 起草模型接设置层：全局默认（角色路由的“起草”）+ 每次起草的覆盖；密钥走同一钥匙环 | ● | —（#89 起草服务读设置存储；L1 收口：档案、端点、密钥槽每次起草从设置解析，密钥取自钥匙环，`kaiti.token_env` 只在槽位空着时兜底；确认卡“起草用”下拉，→ K32）。起草花费还没有经端点代理计量（“开题”账户），记在 Q15 旁 | 本图 03 §3.4；kaiti 一期预留钩子 | L1 |
| Q29 | S6、S8 | 运行时扩权：`request_scope`、`grant_scope`、`revoke_scope` 与 `state.scope_requests`；练习道白名单确定性自动批准（`actor = graph`，`validate` 重算判定）；闸门热加热撤；Adapter 的 `request_access` 工具；`needs_scope` 批准后编进容器（修 `compile_spec` 只读 `Problem.scope` 的缺陷）；设置 `grants` 一节 | ◐ | 内核三操作与练习道自动批准（#93）、`request_access` 工具与热加热撤闸门及隔离测试（#97）、网页扩权卡（#99）已合入；第四步“一句话开题切到零出站”在 #101 待验 | 运行时扩权 #91（cz 2026-11-19 裁决） | L1 |
| Q27 | 横切 | 工作区与任务库的“站位条”：这件任务现在在第几站、等谁 | ● | —（L1 收口：`model/stations.ts` 纯函数 + 工作区十二格、任务库“站位”一列，→ K31） | 本图 06 | L1 |
| Q30 | S10 | 开放道结果页：答案、结局与“未经判定”、主张与证据（无引用标“无留档支撑”）、自检、未验证、复核读数、花费 | ● | —（读端点即 `/status` 的 `deliveries[]`（#106），加 `follow_ups`、`halted`、`idle_close_at`（L3 第三步）；任务页“结果”一栏（#112），→ K43）。复核读数随 Q34 | 开放道 §3.5 | L3 |
| Q31 | S10→S6 | 追问 `follow_up`（人）：回到求解，带工作区与笔记；剩余预算低于收尾保留时追问须附追加预算（`budget_add`，受单题硬顶） | ● | —（L3 第三步：内核 `follow_up`，须看过最新交付（`seen.seq`），剩余低于收尾保留须附 `budget_add_usd_milli`、追加后受单题硬顶；/work 开新一轮、接力上限按轮计；适配层简报带上一轮交付与追问；`pd follow-up`；网页追问框（#112），→ K44） | 开放道 §3.5、§8；D10 | L3 |
| Q32 | S9 | 采纳与不采纳关题，带四顾 | ● | —（L3 第三步：开放道扩过权时人关题须带 `seen` 与逐条确认的 `closeout`，事件体记下名单；`pd close --confirm`；网页采纳 / 不采纳带四顾（#112），→ K45） | 开放道 §3.5 | L3 |
| Q33 | S9 | 交付后闲置自动关（缺省 7 天，不记反馈） | ● | —（L3 第三步：设置 `lanes.idle_close_days`（缺省 7）开题时抄为 `idle_close_s`；哮天犬从最后一次交付起计，期间追问即停表，关题原因 `idle`、不带反馈；墙钟改按轮计，交付之后等人的时间不算，→ K46） | 开放道 §12 第 8 条 | L3 |
| Q34 | S7 | 开放道复核会话（默认开，花验证份额，只给读数） | ● | —（内核：体质修炼 002（`review` 事件、`verify` 租约、验证份额、`/work` 的 verify 项、状态视图的复核读数）；功法：`h1.review@1` 绑 verify 席位（提示词 `adapter/prompts/review.md`、工具 `exec`、`show`、`review`，工作区拷自那次交付的求解会话）、`h2.sinan@2`（交付后先派复核，预留从验证份额出，求解的余额预留让出验证份额）、`h3.base@2`（工具面加 `review`）；设置 `lanes.review`（缺省开）；结果页“独立复核”一节、流程条“另一个模型复核”，→ K48） | 开放道 §3.6、§12 第 4 条 | L3b |
| Q35 | S11 | 开放道读数表（创建、交付、结局占比、采纳率、每次交付花费、复核读数） | ● | —（`GET /v1/readings/open`（`OpenReadingsView`）、`pd readings`；读数页“开放道”一节，→ K49） | 开放道 §5.2 | L3b |
| Q36 | S6、S8 | 开放道只读白名单：设置层人维护、默认空，命中即由图服务确定性自动批 | ◐ | 后端与 `pd` 已做（L3 ④，v0.11）：设置 `grants.readonly_allow`（`pd settings set` 可写）、`request_scope` 的只读判定与 `grant_scope via=readonly`（`actor = graph`，validate 当场重算，事件体戳白名单版本与摘要）；缺设置页一节（归 v5） | 开放道 §12 第 5 条 | L3 |
| Q37 | 横切 | 待办与站位条认开放道的人工项：`delivered`（等你看）、`blocked`（要你补什么）进待办计数；站位条亮 S10 | ● | —（`/work` 的 `delivered`、`blocked` 人工项；待办“看”“补”两种记号与站位条 `delivered` 落 S10（#112），→ K47） | 本图 02 §4 | L3 |
| Q38 | S3 | 起草不可用时用原话直开开放道 | ● | —（体质修炼 004：`vet()` 在草案为空、本来会进开放道时按原话出确定性草案（目标是原文全部句子、题名取第一句开头），出说明 `draft_unavailable`；有答案、验收清单、严格判定、关了开放道、已登记平台照旧拒；起草服务 `raw: true` 重新校验不再调模型；新建页接线，→ K50） | 开放道 §1.1；本图 01 S3；D14 | L3b |
| Q39 | S11 | 采纳的开放道结果一键转存为严格道练习题 | ○ | 全部 | 开放道 §5.3、第五步 | L4 |

状态合计（v0.14，2026-11-21 Q38 之后）：● 28 项（Q1、Q2、Q3、Q5、Q6、Q7、Q8、Q9、Q10、Q11、Q12、Q13、Q14、Q16、Q19、Q21、Q22、Q23、Q27、Q28、Q30、Q31、Q32、Q33、Q34、Q35、Q37、Q38，已记为 K21–K38、K41–K50），◐ 9 项（Q4、Q15、Q17、Q18、Q20、Q25、Q26、Q29、Q36），○ 2 项（Q24、Q39）。v0.13 时 ● 27、◐ 9、○ 3；v0.12 时 ● 25、◐ 11、○ 3。
此前（v0.11）：● 25、◐ 10、○ 4。L2 全部完整；L3 的后端只剩严格道一侧（Q18 续期门 #105、Q20 严格道叫停挂异议），其余缺的都是网页（归 v5）。
此前（v0.10）：● 25、◐ 9、○ 5。
此前（v0.9）：● 18、◐ 11、○ 10。
此前（2026-11-19 L2 收口后）：● 18、◐ 8、○ 3。
初版：○ 16 项、◐ 12 项。

## 2. 已完整的位置（K）

| # | 站 | 位置 | 代码 |
| --- | --- | --- | --- |
| K1 | S1 | 导入（JSON、CSV 逐题成草稿） | `web/src/pages/Import.tsx`、`model/importer.ts` |
| K2 | S1 | 克隆 `/new?from=<pid>` | `Wizard.tsx`、`app/draft.ts` |
| K3 | S3 | 画像推导与预览（人不填画像） | `graph` 的 `/v1/profile/preview` |
| K4 | S4 | 四步向导本身（作为高级编辑） | `pages/Wizard.tsx`、`model/wizard.ts` |
| K5 | S5 | `open_problem` 与材料登记（input 类、本机核对哈希） | `POST /v1/problems`、`PUT /v1/blobs`、`app/submit.ts` |
| K6 | S5 | 事件日志、哈希链、确定性裁决 | `graph/eventlog.py`、`reducer/` |
| K7 | S5 | 记忆召回清单与开题同批登记 | `tongjian/`（PR #81） |
| K8 | S6 | 司南调度（读 `/work`、租约、起会话） | `sinan/` |
| K9 | S6 | 会话边界：三个代理工具、端点代理计量与超额拒绝 | `adapter/` |
| K10 | S6 | 执行层沙箱、按租约编译授权、逐主机出站闸门 | `executor/` |
| K11 | S6 | 资源占用 `touches` 只许收窄 | `reducer/intent.py`、`work.py`（PR #80） |
| K12 | S6 | 哮天犬：过期回收、超预算终止、孤儿清扫 | `watchdog/` |
| K13 | S7 | 判官：`exact_match`、`replay`、保密库、判官运行器 | `judgebox/` |
| K14 | S8 | 审批卡（`seen.card_hash`，`approve_enabled`） | `ui/ApprovalCard.tsx`、`graph/cards.py` |
| K15 | S8 | Hint 注入与效果追溯 | `ui/Hints.tsx`、`/v1/hints/{id}/trace` |
| K16 | S8 | 待办（`/work` 的 human 项按任务分组，含停滞） | `pages/Inbox.tsx` |
| K17 | S6–S8 | 工作区（前沿、图、会话、指导、成本、时间轴回放） | `pages/Cockpit.tsx`、`ui/*` |
| K18 | S6–S9 | 今日（等你拍板、运行中、近七日、最近完成） | `pages/Dashboard.tsx` |
| K19 | S9 | 自动关题与终态三值；预算或墙钟耗尽以 unsolved 关闭 | `reducer/close.py`、`watchdog/` |
| K20 | S10 | 任务库按终态三值回看；三次点击到证据根与本机哈希校验 | `pages/Problems.tsx`、`ui/Inspector.tsx` |
| K21 | S0 | 设置存储（快照、只追加变更日志、版本摘要，`base_digest` 并发）与 `/v1/settings`、`pd settings`（原 Q1） | `scripts/settings_hub.py`（#87） |
| K22 | S0 | 钥匙环、`/v1/keys`、设置页密钥一节、日志遮盖、金丝雀测试、`pd keys`（原 Q2） | `adapter/keyring.py`、`pages/Settings.tsx`（#87） |
| K23 | S0 | 三道硬顶：全局可配、单题硬顶进内核、次序写入时校验（原 Q3） | `reducer/problem.py`、`settings_hub.py`（#87） |
| K24 | S0 | 预算先验 `PriorSource` 与占位表（原 Q5） | `qicao/policy.py`（#88） |
| K25 | S1 | 一句话输入框 `/new` 与前置抽取（原 Q7） | `web/src/pages/Kaiti.tsx`（#88） |
| K26 | S2 | 起草服务 `POST /v1/drafts`（原 Q8） | `qicao/`、`scripts/kaiti_hub.py`（#88） |
| K27 | S3 | 校验层 `vet() → Vetted`（原 Q9） | `qicao/vet.py`（#88） |
| K28 | S0 | 设置页“系统”分组全部各节，练习道信封与预算先验只读（原 Q6） | `pages/Settings.tsx`、`scripts/kaiti_hub.py` 的 `sources` |
| K29 | S4 | 高级编辑逐字段出处记号与原文编号（原 Q11） | `pages/Wizard.tsx`、`model/kaiti.ts` 的 `fieldRefs` |
| K30 | S8 | 扩权卡、待办与工作区横幅（原 Q19） | `ui/ScopeCard.tsx`（#99） |
| K31 | 横切 | 站位条（原 Q27） | `model/stations.ts`、`ui/StationStrip.tsx` |
| K32 | S0、S2 | 起草模型接设置层与钥匙环，确认卡“起草用”（原 Q28） | `scripts/kaiti_hub.py` 的 `pick`、`pages/Kaiti.tsx` 的 `ModelBlock` |
| K33 | S4 | 确认卡“验收清单”一块与拒绝页第 02 条路（原 Q10） | `pages/Kaiti.tsx` 的 `HumanWay`、`qicao/vet.py` 的 `_acceptance` |
| K34 | S5 | `accept: human` 与验收清单（原 Q13） | `graph/reducer/problem.py` 的 `_acceptance` |
| K35 | S7 | 结构检查 advisory 判官（原 Q16） | `judgebox/builtin.py` 的 `structure_check` |
| K36 | S10 | 结果页（原 Q22） | `ui/ResultReport.tsx`、`pd/render.py` 的 `report` |
| K38 | S9 | 四顾逐条确认，关题三步不可跳（原 Q21） | `work.closeout_items`、`reducer/close.py` 的 `_v_accept`、`ui/AcceptanceCard.tsx` |
| K37 | S10 | 逐条验收与 `accept` 校验，读数按判定来源分列（原 Q23） | `graph/reducer/close.py` 的 `_v_accept`、`ui/AcceptanceCard.tsx`、`views.py` 的 `by_authority` |
| K40 | S3–S11 | 开放道第一步：`accept: open`、`solve` 会话与接力、`deliver`（引用机械校验）、终态 `delivered`、`authority: self`、`close_problem.feedback`、读数隔离断言（开放道 §11.1，不占 Q 号） | `reducer/deliver.py`、`work.open_work`、`adapter/prompts/solve.md`、`graph/tests/test_open_lane.py`（#106、#109） |
| K41 | S5 | 任务级模型偏好 `prefs.model`（原 Q12 后一半） | `graph/reducer/problem.py` 的 `_prefs`（#110） |
| K42 | S6 | 按任务选模型档案（原 Q14） | `adapter/session.py` 的 `_model`（#110） |
| K43 | S10 | 开放道结果页（原 Q30） | `views.status` 的 `deliveries`、任务页“结果”一栏（#112） |
| K44 | S10→S6 | 追问 `follow_up`（原 Q31） | `reducer/deliver.py` 的 `_v_follow_up`、`work.open_work`、`adapter/package.py` 的 `open_brief`、`pd follow-up` |
| K45 | S9 | 开放道采纳与不采纳带四顾（原 Q32） | `reducer/close.py` 的 `_v_close_problem`、`pd close --confirm` |
| K46 | S9 | 交付后闲置自动关、墙钟按轮计（原 Q33） | `watchdog/dog.py` 的 `_open_lane`、`work.idle_close_at` |
| K47 | 横切 | 待办与站位条认 `delivered`、`blocked`（原 Q37） | `pages/Inbox.tsx`、`model/stations.ts`（#112） |
| K48 | S7 | 开放道复核会话（原 Q34） | `reducer/review.py`（体质修炼 002）、`fenjue/fires/h1.review.json`、`adapter/prompts/review.md`、`sinan/loop.py` 的 `_verify_room`、`ui/TaskResult.tsx` 的 `ReviewView` |
| K49 | S11 | 开放道读数表（原 Q35） | `views.open_readings`、`pd readings`、`pages/Readings.tsx` 的 `OpenLane` |
| K50 | S3 | 起草不可用时按原话直开开放道（原 Q38） | `qicao/vet.py` 的 `_raw_ok`、`_raw_draft`（体质修炼 004）、`qicao/service.py` 的 `raw`、`pages/Kaiti.tsx` |

K39 留给 #105 的续期门（Q18）。

## 3. 分期路线

**裁决（2026-11-19）**：cz 采纳本节分期，可以按 L1 开始出实现 PR；每一期的验收都包含金丝雀测试（05 AC-M5）。

排序的依据：先让“地图有入口、有设置”，再让“没有标准答案的任务能走完”，再补人的点位，最后是沉淀。每一期都不改变已有站的语义，只填空位。整条线排在项目既定次序之后：M1 收尾（G1 四臂与复做题组）→ M2 前半（记忆、`touches`）→ M2 后半（资产）→ G1 达标后并行。下面的 L1 可以与 M2 前半并行做，但不挤占 G1 读数。

| 期 | 目标（做完时人能做到什么） | 包含 | 前提 |
| --- | --- | --- | --- |
| L0 已排队 | 证明计划开跑前的两条 follow-up | Q17、Q25 | 无（cz 2026-11-19 已记） |
| L1 入口与设置 | 人贴一段话就能开出一道有标准答案的题（先全走确认道）；在设置页配好模型、密钥、硬顶，不碰配置文件；开题零出站，执行时按需扩权 | Q1、Q2、Q3、Q5、Q6、Q7、Q8、Q9、Q10（除验收清单块）、Q11、Q12（digest）、Q19、Q27、Q28、Q29 | 本图、kaiti 与运行时扩权（#91）裁决 |
| L1b 零确认 | 有标准答案的练习题零确认直开 | Q4 | L1 合入；放行开关在测试方，按 kaiti §10.3 的精确率读数放行（cz 2026-11-19） |
| L2 无答案路径 | 没有标准答案的自由任务能开题、执行、按验收清单验收，终态 accepted | Q13、Q16、Q21、Q22、Q23、Q10 的验收清单块 | D3 采纳 |
| L3 人的点位补齐 | 02 §4 的八种点位在开放道上都能走到：看结果、追问、采纳或不采纳、叫停、不理自动关、待办认得出；严格道续期门可用；任务可选模型；看得到每个会话花了多少 | Q12（prefs）、Q14、Q15、Q18、Q20（开放道一半）、Q30、Q31、Q32、Q33、Q36、Q37；Q26 | #105、#110 合入；网页部分随 v5 第三期 |
| L3b 开放道质量与读数 | 结果带独立复核读数；开放道读数单独成表；起草挂了也能开 | Q34、Q35、Q38 | L3 合入 |
| L4 沉淀 | 第二次做同类任务时默认值来自花费画像而不是占位表；资产有出处门与对照门；采纳的开放道结果喂养严格道 | Q24（及先验源接上花费画像）、Q39 | M2 后半；G1 达标 |

### 3.1 L1 的切法建议

L1 内部按依赖拆成四个 PR，顺序与 kaiti 迁移表的一、二期对齐：

1. 设置存储、钥匙环、三道硬顶的后端与 `pd settings`、`pd keys`（Q1、Q2、Q3），含金丝雀测试。
2. kaiti 一期：`qicao/` 的抽取与 `vet`、`PriorSource` 占位表（Q5、Q8、Q9）。
3. 设置页“系统”分组（Q6）。
4. kaiti 二期：`/new` 输入框、确认卡、`/new/advanced`、站位条（Q7、Q10、Q11、Q27），开题事件带 `settings_digest`（Q12）。
5. 运行时扩权（#91 §12 的五步）：一、内核三操作 + `needs_scope` 缺陷修复（验收门：回归测试修前失败、修后通过）+ `pd scope` + 设置 `grants`（缺省 off）；二、Adapter 申请工具与闸门热加热撤；三、网页扩权卡（Q19）；四、一句话开题切到零出站；五、评测比对三份摘要。

### 3.2 L3 的切法（v0.9，D13 已裁）

L3 原来的三项（续期门、模型偏好、会话花费）有两项已经有 PR；开放道裁决之后，L3 的重心换成开放道上的人的点位。前端 v5 线正在改首页、任务页与模型选择（#110，第三期是新任务与任务页），所以 **本线只做后端、`pd` 与读端点契约，网页部分交给 v5 第三期**，不在同一批文件上撞车。

| 步 | 内容 | 缺口 | 归属 | 状态 |
| --- | --- | --- | --- | --- |
| ① | 续期门（严格道）；开放道接入时补：开放道没有门 | Q18 | #105 | 待 cz 验收；时限 D11 |
| ② | 任务级模型偏好与按任务选模型 | Q12、Q14 | #110（v5 第二期） | 已合入 |
| ③ | 开放道人的点位后端：`follow_up`（剩余低于收尾保留时须附 `budget_add`）、`halt`（叫停 → 收尾轮，60 秒内不交付则终止租约）、采纳与不采纳关题带四顾、闲置自动关、交付的结构化读端点；`pd follow-up`、`pd halt`；金丝雀覆盖新路径 | Q20（开放道）、Q30（后端）、Q31、Q32（后端）、Q33 | 本线 | 已做（#111，按 D10、D12 的推荐项；裁决若改再调） |
| ④ | 只读白名单：设置 `grants.readonly_allow`、图服务按白名单自动批只读访问、`pd settings` 可写；设置页一节 | Q36 | 本线（设置页一节跟 v5） | 后端与 `pd` 已做（v0.11）；设置页一节待 v5 |
| ⑤ | 会话花费：按租约花费端点（C1）与花费序列（C2），`pd status` 每会话一行 | Q15（后端） | 本线 | C1 已随 ③ 做（`by_lease`、`pd status`）；C2 已做（v0.11，`/budget/series`） |
| ⑥ | 网页：任务页“结果”一栏（交付、主张与证据、自检、未验证）、追问框、采纳 / 不采纳 / 叫停按钮、待办“等你看”、站位条认 `delivered`、会话行金额 | Q30、Q31、Q32、Q37、Q15（网页） | v5 第三期 | 已合入（#112，照 ③ 的接口草案） |

**③⑤ 给 v5 第三期的接口**（2026-11-20 起草，随 ③ 在 #111 定稿；#112 照它实现）：

| 用途 | 接口 | 形状 |
| --- | --- | --- |
| 读交付（已有，#106） | `GET /v1/problems/{pid}/status` | 开放道题带 `deliveries[]`：`{id, seq, lease, outcome, answer, claims[{text, refs[{id, class}], supported}], self_check[{what, result, refs, item?}], unverified[], needs[]}`，另有 `self_checks[]`、`feedback?`；证据下钻 `GET /v1/artifacts/{id}`。③ 只加 `follow_ups[]`、`halted?`、`idle_close_at?`，不改已有字段 |
| 追问（Q31） | `POST /v1/problems/{pid}/proposals`，人的令牌 | `{op: "follow_up", body: {text, budget_add_usd_milli?, seen: {seq}}}`；`text` ≤ 2000 字符；剩余低于收尾保留而没附追加、或追加后超单题硬顶 → `over_budget`；非开放道 → `forbidden_op`；还没交付、或上一次追问还没交付 → `conflict`；`seen.seq` 早于最新交付 → `stale_view`。成功后 `/work` 再派一个 solve，`follow_ups[]` 追加 `{id, seq, text, after_delivery}` |
| 叫停（Q20） | 同上 | `{op: "halt", body: {reason?}}`；只认人的令牌；之后 `/work` 不再派 solve，在途会话收到收尾轮，60 秒不交付则终止；`halted: {seq}` |
| 采纳与不采纳（Q32） | 同上（已有 `close_problem.feedback`） | `{op: "close_problem", body: {feedback: "adopted"\|"rejected", reason?, closeout?, seen?}}`；有四顾项时必须带 `closeout`（已确认的四顾项名单）与 `seen`（`closeout` 卡），与 `accept` 同法；人不带 `terminal`（派生量，由图服务算） |
| 待办（Q37，已有） | `GET /v1/problems/{pid}/work` | 人工项 `why: "delivered"`（等你看）、`"blocked"`（要你补什么）、`"stalled"`、`"scope_request"` |
| 会话花费（Q15） | `GET /v1/problems/{pid}/budget` | 加 `by_lease[]`：`{lease, kind, role, model, usd_milli, tokens, active}`，各行之和等于 `spent` |
| 花费序列（Q15 C2，v0.11） | `GET /v1/problems/{pid}/budget/series?step=` | `{step, n_costs, points[]}`，点 `{seq, ts, usd_milli, tokens, by_lease{会话: 累计}}`，都是累计；每 `step` 条计量一点、最后一条总在，末点等于 `spent`；至多 500 点，超出时 `step` 自动放大（`BudgetSeriesResponse`） |
| 只读白名单（Q36，v0.11） | `GET /v1/problems/{pid}/cards/scope/{rid}`；`/ticks` | 扩权卡 `display.readonly`（命中时的白名单戳 `{version, digest}`）；`decision.via`、时间轴 `via` 取 `readonly` 即“图服务按只读白名单批准” |

每一步的验收都含金丝雀（AC-M5）与“开放道读数不进严格道统计”的既有断言（开放道裁决附加 1）。

## 4. 前端与后端分开数（2026-11-19 重核）

一个位置两边都有活就两边各算一次；只在一边的只算那一边。依据是上面两张表与代码，不是读数。

| 端 | 位置数 | ● 完整 | ◐ 部分 | ○ 无 |
| --- | --- | --- | --- | --- |
| 前端（`web/`） | 29 | 25：K1–K5、K14–K18、K20、K22、K23、K25、K28–K34、K36–K38、Q18 的续期对话框 | 2：Q15、Q26 | 2：Q4、Q20 |
| 后端（内核、组件、组装根、`pd`） | 34 | 23：K3、K5–K15、K19、K21–K24、K26、K27、K32、K34、K35、K37 | 7：Q4、Q12、Q15、Q17、Q25、Q26、Q29 | 4：Q14、Q18、Q20、Q24 |

v0.9 新增的十个位置（Q30–Q39）分端：前端 6 处（Q30、Q31、Q32、Q35、Q36、Q37，全部 ○，除 Q36 设置页一节外都归 v5 第三期）；后端 10 处（Q37 ●：`/work` 已给人工项；Q30、Q32、Q35 ◐；其余 ○）。加上之后前端 35 处 25/2/8，后端 44 处 24/10/10。

L1 收口（2026-11-19）：Q6、Q11、Q27、Q28 完整，Q10 的 L1 部分（模型一块）完整、剩 L2 的验收清单块；Q19 由 #99 完整；Q29 只剩第四步（#101 待验）。L1 之外：Q4 归 L1b，Q12 的 `prefs.model` 与 Q14 归 L3。
