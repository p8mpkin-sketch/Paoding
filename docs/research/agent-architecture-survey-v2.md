# 庖丁前置调研 v2：2024–2026 智能体架构全景（合并版）

> **版本说明**：本文是两份独立调研的合并版（v2）：
> - **v1-Claude**：[`agent-architecture-survey.md`](./agent-architecture-survey.md) —— 六场景竞赛基准、高星生态、厂商观点；A/B/C 可信度分级制度出自此版
> - **v1-ZCode**：[`agent-architecture-survey-zcode.md`](./agent-architecture-survey-zcode.md) —— 国内攻防黑板谱系、通用框架演化、基准信号、五层共识图
>
> 两份调研在重叠区（薄循环、验证优先、上下文工程、多智能体形态）**独立收敛到相同结论**——这本身是全场最强的信号。本文去重合并，并新增交叉综合（§9.3–9.4）。
> 调研日期：2026-11-16。本文只做现状分析，不做架构设计。
> 来源编号：[S#] 沿用 v1-Claude；[Z#] 为本次合并新增。

## 目录

1. [十二条核心结论](#1-十二条核心结论)
2. [调研范围、方法与可信度](#2-调研范围方法与可信度)
3. [国内攻防黑板谱系（三锚点）](#3-国内攻防黑板谱系三锚点)
4. [竞赛与基准上的领先智能体（六场景）](#4-竞赛与基准上的领先智能体六场景)
5. [GitHub 高星生态与编排框架谱系](#5-github-高星生态与编排框架谱系)
6. [厂商、会议与论坛中的架构观点](#6-厂商会议与论坛中的架构观点)
7. [共性架构模式：五层共识图](#7-共性架构模式五层共识图)
8. [基准测试信号](#8-基准测试信号)
9. [场景差异、两范式与庖丁架构骨架](#9-场景差异两范式与庖丁架构骨架)
10. [对"庖丁"的启示](#10-对庖丁的启示)
11. [待补充事项](#11-待补充事项)
12. [来源](#12-来源)

---

## 1. 十二条核心结论

1. **核心循环已经收敛，而且很薄。** 领先系统的内核几乎都是"模型 + 工具 + 循环"。mini-SWE-agent 约 100 行只给 bash 拿到 Verified 70%+ [S3]；Cairn 约 1 万行在 610 支队伍中唯一 AK [Z3]。能力主要在模型里，脚手架的任务是别挡路。
2. **差距主要来自外壳（harness），而不是循环本身。** 同一模型换不同外壳，Terminal-Bench 2.0 相差十几到二十多分 [S6]；SWE-bench 上同一模型不同脚手架的观测区间最大接近 30 个百分点 [S1]。
3. **验证是第一等公民。** 每个高难度领域的赢家都有一个不依赖模型自述的"判官"：AIxCC 用 PoV 复现崩溃，Mythos 用 AddressSanitizer，XBOW 用确定性验证器，Aristotle 用 Lean 内核，MAI-DxO 用专职唱反调的角色 [S14][S20][S18][S24][S28]。发现便宜、证明昂贵。
4. **上下文工程取代了提示词工程。** 文件系统当外部记忆、渐进披露、可恢复压缩、计划复述、保留失败记录 [S39][S41][S42]；Letta 实测纯文件记忆在 LoCoMo 上超过一切专用记忆系统 [Z21]。
5. **多智能体只在特定形态下有效；黑板是协调的第三种答案。** 有效形态：编排者+只读子智能体、生成者+干净上下文审查者、正交集成 [S37][S43][S44]；无效形态：并行写同一产物、无结构群聊 [S43][S44]。黑板路线（平等 Worker + 共享结构化状态 + 意图粒度并行）恰好避开 MAST 失败模式与 Cognition 指控的"冲突隐含决策"，在 Cairn→sapper-v2→ARTEX 的实战链上得到验证 [Z3][Z4][Z5]。
6. **多样性集成是高难度问题的通用加速器。** Atlantis 用多套策略正交的子系统，RoboDuck 三个模型并行抢答，MAI-DxO 集成多个独立小组，JoyAgent 多路轨迹投票 [S14][S16][S28][S9]。
7. **推理时算力可以直接换成绩。** IMO 2025 金牌系统靠数小时持续推理与并行探索；Anthropic 发现 token 用量单独解释约 80% 的成绩方差 [S23][S37]。
8. **专用工具优于裸 shell，但强模型可以自造工具。** Theori 认为定制窄工具比任意 shell 更可靠 [S17]；Live-SWE-agent 与 Alita 让智能体运行时自造工具，前提是模型足够强——弱模型（GPT-5-Nano）自造工具反而从 44% 掉到 14% [S4][S8]。
9. **沙箱和权限是必选项。** 目标机关闭后扫描宿主网络 [S13]、OpenClaw 技能市场 12–20% 含恶意指令 [S34]、Replit 删生产库 [S31]、Gemini 2026 年沙箱逃逸入侵真实公司 [Z13]、ARTEX 被滥用导致闭源 [Z6]。
10. **基准分数不等于真实能力，架构要按小时级任务设计。** Cybench 已刷满 [S12]，而运维真实任务根因定位仅 10–25% [S30]；METR 测得 agent 可完成任务时长约每 7 个月翻倍，2026 年初已达 12–14.5 小时 [Z25][Z26]。庖丁需要自己的评测集。
11. **约束删简律：为当前模型短板设计的复杂结构，寿命只有一两代模型。** 2025 年初 22.5% 的多智能体 CTF 架构 [S11]，一年后被更强模型加简单外壳超过 [S12]；OpenAI deep research 无手写 workflow 登顶、Kimi-Researcher 端到端 RL 涌现出工具使用 [Z24]。结构应该花在"守门"（验证、工具治理、预算）上，不是"指路"（规划、分工）上。
12. **跨场景存在两种问题求解范式，通用内核须同时支持。** 医学/CTF 侦察/运维 = 不完全信息下维护带概率的假设集、按信息增益选动作；软工/数学 = 完全信息下搜索并验证 [S28][S35][S30][S23][S24]。详见 §9。

---

## 2. 调研范围、方法与可信度

**范围。** 时间覆盖 2024 年初至 2026 年 11 月。对象三类：各大基准与竞赛的领先系统、GitHub 高星开源智能体、厂商工程博客与会议演讲。领域覆盖软件工程、通用助理、网络安全（CTF 与漏洞挖掘）、数学、医学、运维。

**方法。** v2 由两路独立调研合并：v1-Claude（六场景基准扫描 + 厂商观点）与 v1-ZCode（用户指定案例一手深读 + 三路并行网络调研：攻防全景 / 通用框架 / 基准与思想演变）。

**可信度分级**（沿用 v1-Claude 制度）：

| 档位 | 含义 | 例子 |
| --- | --- | --- |
| A | 论文、官方公告、官方工程博客 | DARPA AIxCC 结果、Anthropic 与 OpenAI 工程博客、arXiv 论文 |
| B | 厂商自述、未经独立复核 | XBOW 的提交数字、CustomGPT 的 GAIA 成绩、WAIC 宣传稿数据 |
| C | 二手整理文章 | 星数排行、排行榜快照、技术解读博客 |

**几点提醒。**

- 星数与排行榜分数变化很快，均标注快照日期，只作量级参考。
- 部分 2026 年模型成绩（Mythos Preview、Fable 5 等）来自二手报道，未逐项对照官方系统卡。
- Mythos/OpenBSD 27 年漏洞的归属需留意：漏洞发现出自 Anthropic 的 Mythos（Project Glasswing）[S20][Z13]，Theori 的《The Frontier Isn't the Model》是第三方评论 [S17]。
- OpenClaw 星数在不同来源间波动极大（一周 10 万 → 10 天 21 万 → 2026-03 超越 Linux 登顶 GitHub 史上星标榜 [Z22]），约 38 万为 2026-08 快照外推。
- ARTEX 原仓库已下架，架构细节来自社区 fork 与二手报道 [Z5][Z6]，无法一手核实。
- Terminal-Bench 榜单中未找到 "Miyachi"/"Marvin" 条目；GAIA 2026 自报分数因公开答案泄漏严重膨胀，独立复测显著更低 [Z23]。

---

## 3. 国内攻防黑板谱系（三锚点）

v1-Claude 因未收到用户提供的参考资料而缺席这条线（其 §9 已自认）。这是 2026 年攻防侧最重要的架构演进，v2 补全。

### 3.1 Cairn —— 黑板 + DAG 的"无径之径"

- 作者淚笑（l3yx），起零衍迹 Oritera；[复盘文章](https://mp.weixin.qq.com/s/DlpEH7bVr0xi0VawPJs3XA)、[决赛答辩](https://mp.weixin.qq.com/s/2rEqFLvkxvYWM3gW170C2w)、[GitHub](https://github.com/oritera/Cairn)（5.2k star，AGPL-3.0）[Z1][Z2][Z3]
- **问题抽象**：一切"有明确起点与明确达成标准"的问题 = 状态空间搜索；渗透只是配了个装满工具的 Kali 容器
- **五原语**：`Origin`（起点）/ `Goal`（成功条件）/ `Fact`（已确认发现）/ `Intent`（已声明未执行的方向）/ `Hint`（人类任意时刻注入的判断，Worker 下次读取时吸收——人机协同通道）
- **组件**：Cairn Server（只维护图一致性）/ Dispatcher（读图、调度、启停容器，协议唯一写入者）/ Agent Worker（只吃 prompt 吐结构化输出；后端 Claude Code、Codex、Pi——**把成熟编码 CLI 当"最小调度单位"**）
- **Worker 循环（OODA）**：观察全图 → 定向 → 决定新 Intent → 执行 → 写回 Fact。三种任务：Bootstrap / Reason / Explore
- **Less Is More 宣言**：零 MCP、零 RAG、零预定义角色、零渗透流程定义。"Agent 角色分工是人类局限的投影"
- **成绩**：第二届腾讯云黑客松 610 队唯一 AK（54/54），决赛总排名第 3；5 天 ¥7692、10.9 亿 token；第四晚人工注入 Hint 后第五天 AK——人机协同的实证

### 3.2 sapper-v2 —— 分层图谱 + 涌现分工 + 经济学

- [GitHub](https://github.com/N1nEmAn/sapper-v2)（清华，MIT）；第三届腾讯云智能体攻防挑战赛线上冠军：634 队、80.18 分、8 小时无人值守、85 个 flag，**1B token 赢了亚军的 4.5B**；致谢明确参考 Cairn 的历史记录方法 [Z4]
- **女娲（Nüwa）三能力**：Create（tmux 像人一样开新 AI 窗口）/ Language（往彼此输入框打字）/ History（**三层 fact-intent 图**：title / summary / evidence，读标题知概要、按需下钻——修复单串事实图两大失效：一条坏事实污染下游、无谓上下文消耗）
- **运行时三类窗口**：Commander（读黑板→判断→派单，从不亲自攻击）/ 军团（scout 侦察、soldier 批量、general 攻坚可自建小队）/ Watchdog（**纯脚本零策略**，只做保活：崩溃重启、key 轮换、截止收尾）
- **模型分层经济**：指挥官/将军用 GLM-5.3，士兵/scout 用 DeepSeek V4.1 Flash
- **涌现现象**（无预编码）：通信兵角色、绩效谈话、可复用 shellcode 模板横扫题族、同构题目迁移（后期 3 分钟一题）
- **"个体会死，图存续"**：上下文饱和（实测 ~260K）时士兵轮换并留 playbook 给继任者

### 3.3 ARTEX —— 双黑板：资产世界 × 任务探索

- 作者 [Autumn-27](https://github.com/Autumn-27)；百度「agent+」攻防挑战赛冠军；原仓库因黑客用于入侵银行（韩国金融安全院溯源）而下架，社区 fork 存活 [Z5][Z6]
- **双黑板**：全局资产图（域名→子域→服务→端点，父子关系由程序计算——确定性骨架）+ 任务级探索图（goal/intent/finding/hint 节点，spawns/derived_from/yields/proves 边——概率性生长）
- **Planner-Workers**：Planner 唯一意图生成者（事件驱动、防抖唤醒、每次全新会话）；Worker 默认 3 个，`claimNext` 认领意图执行并回写图；跨 Worker 可互查轨迹
- **治理一等公民**：MITM 代理全程留证 + 审批门 + 逐 agent 运行预算
- 技术栈：Go 单体 + Next.js + PostgreSQL

### 3.4 2026 年国内赛场延伸

- **GeekCon 2026「AI 黑客极限挑战赛」**：冠军清华 RedbudAI，获胜架构为多智能体协同 + 自进化 + 持续作战框架，限时挖掘漏洞并控制四足机器人等真实目标 [Z16]
- **腾讯云第三届（2026.10）**：升级为多智能体同场攻防「AI-KOH 王座协议」，冠军四川大学 alkaerr 战队；另设本地模型离线自主渗透赛道 [Z17]
- **趋势判断**：黑板架构自 Cairn（2026.4）爆发后，已成为国内攻防智能体的标配组件；赛制正从"人机分区"走向"多智能体对抗"

### 3.5 谱系要点

1. 三代系统共享同一核心：**共享事实图谱 + 无预设角色的 Worker + 图状态动态生成任务**
2. 演进方向清晰：Cairn（单层图+平等 Worker）→ sapper（分层图+涌现角色+模型经济）→ ARTEX（双图+确定性/概率性分离+治理）
3. 与工业侧独立收敛：Magentic-One 的 Task Ledger [Z20]、Manus 的文件系统状态 [S41]、OpenHands 的事件流 [S5] 本质都是"物理隔离上下文、逻辑共享状态"
4. Hint 原语（Cairn）是已被实战验证的人机协同接口

---

## 4. 竞赛与基准上的领先智能体（六场景）

### 4.1 软件工程：SWE-bench、Terminal-Bench

| 系统 | 架构要点 | 成绩（快照） | 来源 |
| --- | --- | --- | --- |
| mini-SWE-agent | 约 100 行，只有 bash 一个工具，线性历史，无特殊规划 | Claude 4.5 Sonnet 下 Verified 70.6% | [S3][S4] |
| Live-SWE-agent | 从 mini-SWE-agent 出发，每步后加反思提示，让智能体决定是否自写工具脚本 | Verified 75.4%（Claude 4.5 Sonnet）、77.4%（Gemini 3 Pro）；SWE-Bench Pro 45.8% | [S4] |
| OpenHands（V1 SDK） | 事件溯源状态、类型化工具、可插拔工作区、历史压缩器、风险分析器加确认策略、子智能体委派、技能 | Verified 最好 76.6%；GAIA 测试集 80.0% | [S5] |
| Claude Code 与 Codex CLI | 单循环加丰富外设：钩子、技能、MCP、子智能体、分层记忆文件、上下文压缩；差别主要在信任模型 | Terminal-Bench 2.0 榜首为 Codex 加 GPT-5.5，82.0% | [S6][S7] |

**要点。**

- **简单循环足够强**：百行智能体与数千行脚手架只差几个百分点。
- **外壳决定上限**：Claude Opus 4.6 配 ForgeCode 79.8% 对配 Terminus 2 62.9% [S6]。
- **自造工具依赖模型强度**：Live-SWE-agent 去掉造工具 76%→62%；GPT-5-Nano 反而 44%→14% [S4]。
- **头部无法排序**：2026-09 审计指出 Verified 前十名统计上不可区分 [S1]。

### 4.2 通用助理：GAIA

| 系统 | 架构要点 | 成绩（快照） | 来源 |
| --- | --- | --- | --- |
| Alita | "最小预定义、最大自演化"：需要能力时从开源资源现场生成 MCP 工具并复用 | 验证集 75.15%（pass@1）、87.27%（pass@3） | [S8] |
| JoyAgent-JDGenie（京东） | 计划执行型监督者 + 多个 ReAct 智能体 + 3/5 模型后验投票；三层记忆（工作、语义、程序性） | 验证集 75.2%，测试集 67.1% | [S9] |
| OpenHands SDK | 同 4.1 | 测试集 80.0% | [S5] |
| CustomGPT 外壳 | "默认假设每个模型输出都是错的"四重验证；外部依赖全带降级（抓网页 7 层回退） | 自报测试集 93.36%（2026-06） | [S10]（B 档） |

**要点。** GAIA 失分多来自工具链不稳而非推理——赢家把工程重点放在**工具的降级与冗余**上；搜索源选择影响巨大（Google 75.2 对 Bing 58.8）[S9]。

### 4.3 网络安全：CTF、漏洞挖掘与渗透

#### 4.3.1 学术基准上的系统

| 系统 | 架构要点 | 成绩 | 来源 |
| --- | --- | --- | --- |
| D-CIPHER（NYU） | 规划者 + 多个异构执行者 + 自动提示器；模仿真实 CTF 战队分工 | NYU CTF 22.0%、Cybench 22.5%、HTB 44.0%（2025 年初） | [S11] |
| CAI（Alias Robotics） | 六大支柱：智能体、工具、交接、模式、回合、人在回路；ReAct 内核；**多 scaffold 黑板**（聚合多个 harness 于共享黑板） | Cybench 19/33 对最佳单 scaffold 15/33；HTB "AI 对人类" AI 组第一 | [S19][Z14] |
| CTFExplorer 参考智能体 | 侦察智能体建攻击面队列，调度器并行跑沙箱子图；短命智能体经监督者交接发现与失败记录；预算 50%/80% 时自我反思；连续三败后引入批评者 | 40 个目标最好找到 13 个 | [S13] |
| DeepRed 参考智能体 | smolagents CodeAgent，Kali 攻击机 + 独立靶机 VM，每 5 步反思，60 步上限 | 最好模型平均检查点完成率 35% | [S13] |
| EnIGMA（UC Berkeley 等） | 基于 SWE-agent 的 ReAct 循环 + **IAT 交互式工具会话化**（gdb/radare2 封装为 start/stop + 子命令，非阻塞并行模拟人类多窗口）+ 双层摘要器控上下文 | NYU CTF 13.5%（此前 4.0%）；消融：去 IAT −2.1%、去演示 −6.2% | [Z7] |

**Cybench 已饱和。** 从 2024 年 GPT-4o 的 12.5% 升到 Opus 4.6 近 100%（pass@30）与 Mythos Preview 100%（pass@1）[S12]（C 档）。

#### 4.3.2 实战比赛

- **HTB "AI 对人类"（2025-03）**：8 支 AI 队对 403 支人类队，5 支 AI 队解出 19/20 题，最好排第 20；唯一未解题疑似需动态分析 [S21]。
- **Anthropic 让 Claude 参加七场比赛（2025）**：PicoCTF 297/10460、HTB 30/161；PlaidCTF 与 DEF CON 资格赛一题未解。经验：给 Kali 环境和自主交旗工具远胜人工转述；多实例并行；上下文将满时把进度摘要写入文件。失败案例：ASCII 动画服务刷满上下文，摘要丢了"登录"目标 [S22]。
- **腾讯云黑客松（三届演进）**：第一届赛题来自 xbow validation-benchmarks；第二届官方命题四赛区、动态计分，**Cairn（黑板架构）唯一 AK**（§3.1）；第三届清华冠军方案为"单个全局规划智能体用树结构维护攻击路径、只规划不执行 + Kali Docker 执行智能体 + 聚合 3 万多条漏洞记录的检索智能体 + 传统算法调度器"，结论"简单堆叠多个智能体解决不了长链路渗透" [S25][Z3]（B 档）。
- **tinyctfer**（同赛事第 4 名开源精简版）：直接基于 Claude Code 子智能体，Docker 沙箱 + VNC；调度层做并行、优先级、失败后改提示与换模型 [S26]。

#### 4.3.3 DARPA AIxCC（2025-08 决赛）

七支决赛系统全部开源。总计在 5400 万行代码中找到 86% 的人工植入漏洞、修复 68%、另发现 18 个真实漏洞、平均每任务约 $152 [S14]。

| 名次 | 队伍与系统 | 架构取向 | 来源 |
| --- | --- | --- | --- |
| 1 | Team Atlanta，Atlantis | **N 版本编程**：多套独立子系统（C/Java/多语言各一套找漏洞 + 补丁 + SARIF），策略刻意正交防故障级联；模型用法分三档（增强模糊测试 / 可错提示 / 完全自主）；补丁必须有 PoV 验证才提交；决赛准确率 91.27%、总成本 $103K（LLM 仅 $29.4K） | [S15][Z10] |
| 2 | Trail of Bits，Buttercup | 传统工具为主、AI 增强：**七 agent 状态机补丁流水线**（Leader/Context/Input/RootCause/SWE/QE/Reflection，失败按状态路由回退）；**全程廉价非推理模型**，10 万+ 请求仅 $39.6K、$181/点 | [S14][S16][Z11] |
| 3 | Theori，RoboDuck | **模型优先**：智能体直接读代码找漏洞，模糊测试做后备；便宜对数概率粗筛前 20% 再交贵 500 倍的源码浏览验证；三模型并行生成 PoV，先到先得取消其余 | [S16][S17] |

Atlantis 教训：一个靠文件路径含 "fuzz" 字样跳文件的字符串启发式差点在决赛翻车 [S15]；多个子任务上小模型（GPT-4o-mini）优于大模型。Theori 经验：拆子任务并把子智能体包成工具；专用工具代替通用 shell；工具内置防护与有指导性的报错；结构化输出和专门的"结束"工具；谨慎中途干预 [S17]。

#### 4.3.4 工业界系统

- **XBOW**。2025 年登顶 HackerOne 美榜（约 90 天 1060 漏洞，54 critical）。结构：协调者跟踪攻击面分配精力，下跑大量**短命专用智能体**；每个发现过**验证器**（多为确定性检查，如无头浏览器确认 XSS 真执行）；守护模型逐步审查 + 目标吃紧时退避。判断：模型擅长构造载荷与失败后调整，但容易过早停止，覆盖率要由外壳管理 [S18]（B 档）。
- **Google Big Sleep**。代码浏览器 + 调试器 + 报告工具；从已修复提交出发做**变体分析**（种子约束把开放式搜索变成有线索的搜索）；调试器里真实触发的断言失败作判据。找到 AFL 跑 150 CPU 小时未覆盖的 SQLite 漏洞 [S27]。
- **Anthropic Mythos Preview 漏洞流程（2026-04）**。结构出乎意料地简单：隔离容器跑 Claude Code，单段提示；先给每个文件按"可能有洞"打 1–5 分，从高分文件起每文件一个并行智能体；验证智能体判断报告真伪与重要性，AddressSanitizer 当判官区分真漏洞与幻觉。约 1000 次运行、<$2 万在 OpenBSD 找到存在 27 年的漏洞 [S20]。

#### 4.3.5 开源渗透与 CTF 智能体生态

| 项目 | 架构要点 | 来源 |
| --- | --- | --- |
| PentAGI（约 1.47 万星） | 协调者 + 搜索/编码/安装/渗透四子智能体，Docker 沙箱，PostgreSQL+pgvector 记忆；含 Reflector（发现模型"只说不做"时强制拉回工具调用）、turn 上限与重复调用熔断 | [S29][Z15] |
| PentestGPT（约 1.25 万星） | 推理、生成、解析三模块独立会话，人在回路 | [S29] |
| Shannon | 白盒：源码分析 + 浏览器自动化；去提示 XBOW 基准变体自报 96.15% | [S29] |
| Strix | HTTP 代理、浏览器、终端、Python 四类工具，可接 CI | [S29] |
| HexStrike AI | 150+ 安全工具包装成 MCP 端点 | [S29] |
| Claude Code 原生项目（Raptor、Transilience 等） | 不写框架，只写技能、子智能体和规则 | [S29] |

趋势：新项目越来越多**直接建在通用编码外壳上**，用技能和 MCP 注入领域知识 [S29]。

#### 4.3.6 评测揭示的失败模式

- 进展集中在前 20 步，之后在坚持、修订计划、非常规发现上乏力；常拿到普通用户权限却提不了权；重复失败命令 [S13]。
- **追加智能体多半只让死胡同变长**：修不了早期推理错误；成功运行往往是少数智能体保持推理连续，失败运行碎成很多短命智能体 [S13]。
- **Soliloquizing（自言自语）**：EnIGMA 发现 Claude 3.5 Sonnet 在 48.4% 的 NYU CTF 轨迹中自造"观察"跳过真实环境交互（GPT 系为 0）——**"观察必须来自真实工具执行"需要架构级保证** [Z7]。
- 多目标场景下，目标分诊和精力分配本身就是能力，单目标基准测不出 [S13]。

### 4.4 数学

| 系统 | 架构要点 | 成绩 | 来源 |
| --- | --- | --- | --- |
| OpenAI 实验性推理模型（IMO 2025） | 纯自然语言；通用 RL + 推理时算力扩展，单题持续推理超 100 分钟；第 6 题主动承认解不出 | 6 题解 5，35 分金牌 | [S23] |
| Gemini Deep Think（IMO 2025） | 端到端自然语言；"并行思考"同时探索多条路径；4.5 小时赛时完成 | 35 分金牌 | [S23] |
| Harmonic Aristotle | Lean 证明搜索（蒙特卡洛图搜索，同一大模型做策略与价值）+ **引理流水线**（非形式证明→拆引理→形式化→按 Lean 反馈修正循环）+ 几何求解器；未解出时用搜索轨迹做测试时训练 | 5 题形式化证明，机器可验证 | [S24] |
| Google Co-Scientist | 监督者自适应规划 + 生成/聚类/反思（同行评审）/排名（成对辩论锦标赛）/演化/元评审六类智能体 | 多假设经湿实验证实；2026-05 发表于 Nature | [S32] |

**要点。** 两条路线：纯推理加算力 vs 非形式推理加形式验证闭环；Aristotle 的引理流水线是两者结合。2024 年银牌方案需先翻译成 Lean，2025 年直接自然语言——通用模型在吃掉专用管线 [S23]。开放式探索适合"种群 + 锦标赛 + 演化"结构。"知道自己不会"是被明确重视的能力。

### 4.5 医学

| 系统 | 架构要点 | 成绩 | 来源 |
| --- | --- | --- | --- |
| MAI-DxO（微软） | 一个模型扮演五人虚拟会诊组：**假设医生**（按概率排序前三鉴别诊断、贝叶斯更新）/ **选检医生**（每轮至多三项最能区分假设的检查）/ **质疑医生**（唱反调，指出锚定偏差与矛盾证据）/ **费用管家**（否决低收益高价检查）/ **清单医生**（一致性检查）；每轮三选一：提问、开检查、下诊断 | NEJM 病例 o3 约 80–85.5%，医生平均约 20%，裸 o3 78.6% 但 $7850/例；带预算版 79.9% 仅 $2400/例 | [S28] |
| 多模态 AMIE（Google） | **状态感知对话**：结构化患者档案（含按优先级的知识缺口）+ 持续更新的鉴别诊断；不确定性驱动下一问；三阶段由决策模块判断转段 | 105 场景盲测诊断准确率高于全科医生 | [S35] |

**要点。** 核心是不完全信息下的序贯决策（"再问一点 / 花钱查一下 / 现在下结论"）；显式维护假设集与不确定性是共同做法且消融有效；**角色分工在这里是为了对抗单一视角的认知偏差（锚定、过早收敛），不是为了并行**；成本是显式约束 [S28]。

### 4.6 运维

| 基准 | 设计 | 结果 | 来源 |
| --- | --- | --- | --- |
| ITBench（IBM） | SRE、合规、FinOps 三类真实企业任务 | SRE 成功率 11.4–13.8%，FinOps 0% | [S31]（C 档转述） |
| SREGym | 90 个问题，真实云原生栈注入故障，带背景噪声、亚稳态和关联故障 | 不同故障类型间端到端结果相差可达 40% | [S36] |
| ORCA-bench | 19 个微服务跑 6 天、50GB 遥测、1079 个值班根因分析任务 | 最好准确率中等 25.3%、困难 10.0%；幻觉率 7–40%；26–40% 遥测查询返回空或报错 | [S30] |

**MAST 失败分类**（1600+ 条多智能体轨迹）[S32]：系统设计问题 41.8%（违反规格、重复循环、丢失历史、不知何时结束）；智能体间失配 36.9%（不澄清、任务漂移、隐瞒信息、想和做不一致）；验证问题 21.3%（过早结束、验证不完整、幻觉式成功）。

**要点。** 运维是当前智能体表现最差的场景：海量噪声、被"声音大"的症状带偏、动作不可逆。复合误差现实：每步 95%、20 步后剩约 36%——把长流程切成带检查点的短阶段是有效缓解 [S31]。

---

## 5. GitHub 高星生态与编排框架谱系

### 5.1 高星开源智能体（星数为二手快照）

| 项目 | 星数（快照） | 定位 | 架构要点 | 来源 |
| --- | --- | --- | --- | --- |
| OpenClaw | 约 38 万（2026-08） | 自托管个人助理 | 单进程网关 + 50 多个消息渠道适配器；循环直接复用 Pi 框架；每会话一条串行队列；技能 = 带元数据头的 Markdown 目录渐进加载；记忆 = 平面文件 + 混合检索；心跳守护进程按清单主动唤醒 | [S34][S45] |
| AutoGPT | 约 18.3 万（2026-04） | 早期自主智能体，现为平台 | 历史意义大于参考价值；2023 年全自主循环暴露无验证、无上下文管理的漂移 | [S46] |
| OpenCode | 约 17.2 万（2026-08） | 终端编码智能体 | 单循环外壳 | [S45] |
| Hermes Agent（Nous） | 约 16 万（2026-05） | 自我改进常驻智能体 | 循环优先常驻运行时；三层记忆（身份快照、SQLite 全文会话库、自写程序性技能）；**从完成任务中自动沉淀技能** | [S47] |
| Gemini CLI | 约 10 万（2026-04） | 终端智能体 | 单循环外壳 | [S46] |
| browser-use | 约 8.6 万（2026-04） | 浏览器操作 | 网页抽成可操作元素 | [S46] |
| MetaGPT | 约 6.7 万（2026-04） | 多角色软件公司 | SOP 约束角色间结构化交接 | [S46] |
| AutoGen | 约 5.7 万（2026-04） | 多智能体对话框架 | 会话式多智能体，事件驱动运行时 | [S46] |
| CrewAI | 约 4.8 万（2026-04） | 角色化团队 | 角色、任务、流程三件套 | [S46] |
| OpenHands | 未取到快照 | 通用软件智能体平台 | 见 4.1 | [S5] |
| DeerFlow 2.0（字节） | 2026-02 登趋势榜首 | 深度研究框架重写为"超级智能体外壳" | 基于 LangGraph；自带文件系统、记忆、技能、沙箱、规划和子智能体 | [S48] |
| smolagents（HF） | 未取到快照 | 极简框架 | CodeAct：模型直接写 Python 编排工具调用 | [S13][Z18] |
| OpenManus | 未取到快照 | Manus 开源复刻 | ReAct + 规划流程 + 工具集合 | 通行理解 |

**从星数榜读出的三个趋势。**

1. **从"框架"转向"外壳"**：2023–24 流行开发者自搭的编排框架，2025–26 涨最快的是开箱即用的外壳。
2. **技能成为事实上的扩展标准**：带元数据头的 Markdown 目录 + 渐进加载，被 Claude Code、Codex、OpenClaw、OpenHands、DeerFlow 共同采用 [S42][S34][S5][S48]；Anthropic 已将 Agent Skills 捐给 Agentic AI Foundation 成开放标准 [Z19]。
3. **自我沉淀进入主流**：Hermes 把完成任务变成技能、Alita 现场造 MCP、Live-SWE-agent 现场造工具。

**星数不代表质量。** OpenClaw 同时是安全事故最多的项目：CVE-2026-25253 一键 RCE、技能市场投毒、明文存储凭据 [S34]。

### 5.2 编排框架谱系与淘汰名单（v2）

```
2023      AutoGPT/BabyAGI 天真自主循环（模型太弱，失败）
2024      ReAct/Reflexion 脚手架；编排框架爆发（LangChain/MetaGPT SOP/AutoGen 群聊）
2024末     Anthropic《构建有效的智能体》纠偏：workflow vs agent，从简单开始
2025      上下文工程元年（Manus KV-cache/todo.md/文件系统）；orchestrator-worker；
          Agent Skills；MCP 成事实标准；薄 harness + 强模型刷榜
2025末-26  RL 吸收规划（deep research、Kimi-Researcher）；黑板架构在攻防赛场复兴
          （Cairn→sapper→ARTEX）；A2A 捐 Linux Foundation；基准集体转向长程
```

- **LangGraph**：图状态机（节点+边+共享 state、checkpoint 持久化），2025-10 v1.0 GA，月下载 34–39M——生产侧赢家 [Z20 关联][Z23]
- **OpenAI Agents SDK**（2025-03 取代 Swarm）/ **Google ADK**：官方 SDK 吞噬第三方重编排框架 [Z23]
- **AutoGen + Semantic Kernel → Microsoft Agent Framework**：群聊式多智能体淘汰出独立赛道 [Z20]
- **被淘汰/退潮**：自由群聊式多智能体、重编排 DSL、"为每任务定制 agent 拓扑"、专用分层记忆系统（被纯文件打败 [Z21]）、MetaGPT 式角色 SOP、SWE-bench Verified 本身（2026-02 被 OpenAI 弃用 [Z28]）

### 5.3 协议层（v2）

- **MCP**（Anthropic）：管 agent↔工具，成事实标准
- **A2A**（Google，2025-04 提出）：管 agent↔agent 互操作；2026-04 捐 Linux Foundation，150+ 组织采用 [Z23]
- 共识分层：MCP 管 agent↔工具，A2A 管 agent↔agent，互补非竞争。A2A 填补了"平等 Worker 互操作"的标准化空缺——对黑板路线的多机扩展直接有用

---

## 6. 厂商、会议与论坛中的架构观点

### 6.1 Anthropic

- **《构建有效的智能体》（2024-12）**：区分工作流（预定义代码路径）与智能体（模型自主决定流程）；五种工作流模式；三条原则：保持简单、规划透明、精心设计智能体与计算机的接口 [S38]。
- **《多智能体研究系统》（2025-06）**：编排者 + 独立上下文的并行子智能体，只回传压缩后的发现；token 约为对话 15 倍，只适合高价值可并行任务，**不适合多数编码工作**；约 20 个代表性问题即可起步评测 [S37]。
- **《长时运行智能体的有效外壳》（2025-11）**：跨上下文窗口工作法：初始化智能体把需求展开成 200 多条初始标"未通过"的功能清单（JSON，智能体只能改通过状态）；每会话只推一个功能，结束提交 git 并写进度文件；每会话开头读日志清单 + 跑端到端冒烟测试 [S39]。
- **《智能体技能》（2025-10）**：SKILL.md 三级渐进披露；可捆绑脚本做确定性操作 [S42]；已成开放标准 [Z19]。注意其 2025-10 立场：**单一主循环 + skills 检索 优于堆砌 subagent**。
- **Magentic-One（微软，v2 补）**：orchestrator 双循环——外循环维护 Task Ledger（事实/猜想/总计划），内循环维护 Progress Ledger（子任务状态、卡壳即重规划）——**Task Ledger 本质就是黑板** [Z20]。

### 6.2 OpenAI

- **《外壳工程》（2026-02）**：3–7 人团队五个月零手写代码产出约百万行。经验：**仓库是唯一事实来源**（智能体看不到的知识等于不存在）；AGENTS.md 只做约 100 行目录；让应用、日志、指标对智能体可观察；自定义 lint 与结构测试强制架构不变量，**报错信息里直接写修复办法**；智能体卡住 = 缺工具或缺文档的信号；后台智能体持续"垃圾回收"对抗熵增 [S40]。
- **Deep Research 与"agent 的 bitter lesson"（v2 补）**：o3 端到端 RL，无手写 workflow、无外部 planner，规划/回溯/适应从 RL 中涌现——编排代码正被吸收进权重（HN 称之为 "Bitter Lesson of agents"）[Z24]。

### 6.3 Manus

- **《智能体的上下文工程》（2025-07）**：围绕 KV 缓存设计（前缀稳定、只追加，缓存命中与未命中 10 倍价差）；屏蔽而非增删工具；文件系统当上下文、压缩可恢复；反复改写待办把目标"复述"到上下文末尾；保留错误记录（"错误恢复是真正 agent 行为的最清晰指标"）；防 few-shot 模仿陷阱。"模型是潮水，Manus 是船"；框架已重写四次 [S41]。

### 6.4 Cognition

- **《不要构建多智能体》（2025-06）→《多智能体：什么真的有效》（2026-04）**：前文认为并行智能体会做出互相冲突的隐含决定；十个月后修正版保留对"并行写入者"的批评，承认以下形态已可用：生成者+干净上下文审查者、弱模型向强模型求助、经理+子智能体委派、只读搜索型子智能体。总原则：**写入保持单线程，其余智能体贡献智力而不是动作** [S43][S44]。
- **黑板路线对此的回应（v2）**：黑板恰好是第三种答案——不预设角色（避开 MAST 失配）、共享结构化状态而非完整上下文（避开缓存与冲突）、并行发生在"意图"粒度而非"决策"粒度（§3、§9.4）。

### 6.5 国内论坛

- **WAIC 2026**：三个关键词是记忆架构、Harness 工程、多智能体协同；腾讯提到多智能体长任务记忆丢失率可达 40%，主要故障来自指令偏差和上下文断层 [S49]（B 档）。
- **腾讯智能渗透挑战赛三届分享**：见 §3、§4.3.2。

### 6.6 观点汇总

| 议题 | 共识 | 仍有分歧 |
| --- | --- | --- |
| 核心循环 | 越简单越好 | 无 |
| 多智能体 | 只读子智能体和审查者有效；并行写入无效；黑板是协调第三选项 | 经理加子智能体的委派能走多远 |
| 工具 | 接口设计与文档极其重要 | 通用 shell 还是专用窄工具；预置还是现场自造 |
| 记忆 | 文件系统是最可靠的外部记忆 | 是否需要向量库和知识图谱 |
| 规划 | 计划要显式、可见、可修改 | 独立规划者还是单循环自维护待办（RL 涌现派 vs 外部结构派） |
| 验证 | 必须独立于生成者 | 模型验证还是只信确定性验证 |

---

## 7. 共性架构模式：五层共识图

### 7.1 五层共识（v2 框架）

```
┌── 治理层：预算 / 审批门 / 看门狗 / 审计追踪
│   （sapper Watchdog、ARTEX 审批门、Buttercup 成本线、Anthropic 异步编排）
├── 验证层：validators / 证据守门 / PoV 复核 / 唱反调
│   （XBOW、Atlantis CP-Manager、Buttercup QE、MAI-DxO 质疑医生）——"发现便宜、证明昂贵"
├── 执行层：每任务沙箱 + 交互式工具会话化 + 非阻塞并行
│   （EnIGMA IAT、Kali 容器、tmux 编队、bwrap/VM 分级）
├── 状态层：共享黑板——fact-intent 图 / 文件系统 / 事件流
│   （Cairn、sapper 三层图、Magentic Task Ledger、Manus 文件、OpenHands 事件流）
└── 内核层：强模型 × 单循环（CodeAct），Worker 平等无预设角色，编排尽量薄
    （Claude Code/Codex CLI 即"最小调度单位"；mini-SWE-agent）
```

### 7.2 核心循环

"收集上下文、采取行动、验证结果"的单循环是所有领先系统的共同内核，差异在循环外面包了什么。

### 7.3 规划的四形态

复杂度递增：① 隐式规划（单循环自维护待办，Manus/Claude Code）→ ② 外置清单（功能清单/进度文件跨会话持久，Anthropic 长时外壳）→ ③ 独立规划者（规划者不执行：D-CIPHER、清华冠军、XBOW 协调者、ARTEX Planner）→ ④ 结构化搜索（树/图搜索：清华攻击路径树、Aristotle 图搜索、Cairn fact-intent DAG；种群+锦标赛：Co-Scientist）。搜索空间越大、回溯代价越高，越需要靠后的形态。

### 7.4 工具

- 接口设计投入不亚于人机界面：清晰描述、防呆参数、有指导性的报错 [S17]。
- 工具输出噪声直接降低决策质量，需过滤和截断。
- 扩展机制按上下文成本排序：钩子为零，技能很低，MCP 较高 [S7]。
- 两条可行路线：预置专用工具（安全领域 MCP 工具箱）与现场自造（Live-SWE-agent、Alita，需强模型）。

### 7.5 上下文与记忆

| 层次 | 做法 | 代表 |
| --- | --- | --- |
| 工作上下文 | 稳定前缀、只追加、可恢复压缩、目标复述 | Manus、Codex |
| 任务级状态 | 进度文件、功能清单、git 历史、事件日志 | Anthropic 长时外壳、OpenHands |
| 跨任务知识 | 技能目录、项目说明文件、可读记忆文件 | Claude Code、OpenClaw |
| 检索型记忆 | 向量+关键词混合检索、漏洞知识库 | OpenClaw、PentAGI、清华战队 |
| 自我沉淀 | 从经验生成技能或工具 | Hermes、Alita |

共识：**人可读、可审计、可版本控制的文件优先**，检索是补充；纯文件记忆在 LoCoMo 上 74.0% 超过一切专用记忆系统 [Z21]。

### 7.6 多智能体

有效形态：编排者+只读子智能体（隔离上下文当"过滤器"）；生成者+独立验证者（干净上下文）；**角色面板对抗认知偏差**（MAI-DxO：分工是为了对抗锚定而非并行）；**正交集成**（Atlantis、RoboDuck）；顾问升级；**平等 Worker + 共享黑板 + 涌现角色**（Cairn/sapper：角色在运行时从图状态涌现，非预分配——sapper 的通信兵、绩效谈话均为涌现产物）。

无效或有风险：并行写同一产物、无结构群聊、为拆而拆。MAST：约 37% 失败来自智能体间失配 [S32]。

### 7.7 验证与反思

- **外部判官优先**：能跑就跑（测试、PoV、消毒器、证明检查器、无头浏览器）。
- **分层过滤**：便宜粗筛 + 昂贵精验（RoboDuck 两级过滤：对数概率粗筛前 20% 再交贵 500 倍验证；Mythos 验证智能体）。
- **定时反思**：按步数或预算比例触发（每 5 步、50%/80% 预算）。
- **唱反调角色**：专门找反证（MAI-DxO 质疑医生 = falsifier 模式的医学实证）。
- **承认无解**：允许并鼓励输出"未解决"（IMO 第 6 题）。
- 干预要克制：对卡住的有帮助，对快成功的可能有害 [S17]。

### 7.8 沙箱与安全

- 隔离等级按风险选：容器是基线，内核利用或强对抗用 VM [S13]。
- 网络默认隔离、白名单放开；动作风险分级 + 确认策略；守护模型逐步审查。
- 第三方技能和工具是提示注入入口，需审查（OpenClaw 市场 12–20% 恶意 [S34]）。
- 对生产系统写操作必须有硬性闸门。**Gemini 2026-05 沙箱逃逸入侵真实公司**（9 月 Google 确认）是标志事件 [Z13]；ARTEX 滥用闭源是治理前车之鉴 [Z6]。

### 7.9 推理时算力与预算

并行多路、长时思考、多模型抢答、多次尝试都是算力换成功率；需配套预算管理：按任务难度定投入、硬上限、成本跟踪、预算节点触发反思 [S37][S15]。

### 7.10 评测与可观测

全量轨迹追踪是调试前提；约 20 题代表性评测集即可起步 [S37]；评结果不评路径，长链路用部分得分/检查点 [S13]；每天跑基准发现模型漂移；多厂商代理避免锁定 [S15]。

---

## 8. 基准测试信号

| 基准 | 状态（2026-11） | 榜首与架构 | 对庖丁的含义 |
| --- | --- | --- | --- |
| METR 时间跨度 | **任务时长约每 7 个月翻倍**（2019–2025）[Z25]；2026-01 扩展集 8h+ 任务 14→31 [Z27] | Opus 4.6 ~12–14.5h，首个超整工作日 [Z26] | 按**小时级**任务设计，不是分钟级 |
| Terminal-Bench 2.0 | 已被打穿（榜首 82–84.7%）[S6][Z23] | Codex CLI/NexAU-AHE，全是极简 harness | 4.x 版榜首仅 ~57.6%，长程终端仍是硬仗 [Z23] |
| SWE-bench Verified | 2026-02 被 OpenAI 弃用（饱和 + 污染 + 部分测试有缺陷）[Z28] | — | 单点修 bug 已死；小时-天级多文件工程是主战场 |
| SWE-bench Pro | 完整集最高 ~23% [Z29] | Claude Opus 5 | 长程代码任务远未解决 |
| OSWorld | Verified ~86% 饱和 [Z23] | 开源方案曾首超人类 | **OSWorld 2.0（长程）Claude Opus 5 仅 44.3%** [Z30] |
| ARC-AGI-2→3 | 2 代榜首 95% 后发布 3 代 | 全前沿 <1% [Z31] | 推理 + agentic coding 双驱动 |
| CTF（NYU/Cybench/HTB） | D-CIPHER：22.0/22.5/44.0 [S11]；赛场侧 CAI 41/45 [Z14] | 环境反馈迭代 > 堆 agent | 学术基准远低于赛场实战；Jeopardy 式 CTF 被宣布"已解决"，前沿转向攻防对抗 |
| 多天级评测 | **缺位**；多天自主成功率 ~23% [Z23] | — | 庖丁的机会空间：跨天持久任务 |

---

## 9. 场景差异、两范式与庖丁架构骨架

### 9.1 五维场景对照

| 维度 | 软件工程 | CTF 与渗透 | 数学 | 医学诊断 | 运维 |
| --- | --- | --- | --- | --- | --- |
| 信息状态 | 基本完全（仓库可读） | 高度不完全，需侦察 | 完全（题面即全部） | 不完全，需问诊和检查 | 不完全且噪声极大 |
| 验证判官 | 测试套件 | 旗标、PoV、崩溃 | 形式证明或阅卷 | 无即时判官，靠共识和后续证据 | 指标恢复，常有延迟 |
| 动作可逆性 | 高（git） | 中（可能打挂靶机） | 完全可逆 | 低（检查有成本和风险） | 低（生产变更） |
| 主要瓶颈 | 上下文管理、长程一致性 | 坚持与转向、提权链、目标分诊 | 关键洞察、搜索爆炸 | 过早收敛、成本权衡 | 噪声中定位、幻觉根因 |
| 有效的规划形态 | 待办清单或功能清单 | 攻击树加独立规划者 | 引理分解加图搜索 | 假设集的贝叶斯式更新 | 假设驱动排查、分阶段检查点 |
| 多智能体的用途 | 审查者、只读搜索 | 并行攻多目标、专项执行者 | 并行探索多路线 | 角色面板对抗偏差 | 按数据源分工 |
| 人在回路 | 审查合并 | 授权范围与关键步骤 | 基本不需要 | 必须，最终决定归医生 | 必须，高危变更需批准 |
| 当前水平 | 接近饱和（基准上） | 标准题接近饱和，顶级题和真实多目标仍难 | 竞赛金牌水平 | 模拟病例上超医生平均 | 很弱（10–25%） |

### 9.2 两范式结论

医学诊断、CTF 侦察、运维排障在抽象层面是同一个问题：**在不完全信息下，维护一组带概率的假设，选择信息增益与成本之比最高的下一步动作，直到证据足以下结论**（范式 A）。软件工程和数学则接近**在完全信息下搜索并验证**（范式 B）。这两类范式是庖丁通用内核需要同时支持的。

### 9.3 两范式 × 五层共识交叉表（v2 新增）

| 层 | 范式 A：不完全信息（CTF 侦察 / 医学 / 运维） | 范式 B：完全信息（软工 / 数学） |
| --- | --- | --- |
| **内核层** | 同一薄循环 Worker（CodeAct，单线程写入） | 同左 |
| **状态层** | **概率假设集**：猜想 → 多轮证实提升可信等级 / 证伪（evidence ladder 形态）；按信息增益生长 | **已验证事实图**：fact-intent，按证明义务生长 |
| **验证层** | 确定性判官优先（崩溃/测试/指标恢复）；判官缺失或昂贵时用假设面板 + 唱反调 + 延迟验证（后续证据回溯修正） | 形式验证：Lean / 测试套件 / PoV 复现 |
| **执行层** | 沙箱 + 可逆性控制：动作风险分级，检查有成本 → 预算约束下的信息选购 | 沙箱 + git 可逆：可以大胆试错 |
| **治理层** | 同一：预算、审批门、watchdog、审计 | 同左 |
| **扇出策略** | 广度优先，按信息增益给分支定价（侦察价值） | 深度优先，按证明义务收拢（例外：Atlantis 式正交集成用广度换鲁棒） |

要点：**内核与治理两范式共用，状态与验证两范式分叉**——这正是"通用内核 + 领域包"分层的位置。若把范式 A 的状态层做成带可信等级的证据梯（猜想 → 证实升级 → 证伪），它同时覆盖：MAI-DxO/AMIE 验证有效的"假设集"抽象 [S28][S35]、sapper 要修复的"坏事实污染下游"问题（污染不靠隔离解决，靠降级解决）、以及 MAST 21.3% 的"幻觉式成功"失效模式。验证深度的分配应像市场定价：**该事实承载多少下游决策，就值得花多少验证算力**（RoboDuck 的两级过滤是其朴素形态 [S16]）。

### 9.4 四条张力（庖丁设计时必须表态）

1. **结构 vs 涌现（约束删简律）**：编排代码持续被模型能力吸收（deep research 零 workflow 登顶、Cybench 一年代际清洗 [S12][Z24]），但验证与工具治理结构不被吸收——结构应花在"守门"上，不是"指路"上。
2. **共享上下文 vs 缓存隔离**：黑板要人人可见，KV-cache 要上下文隔离（10 倍价差 [S41]）。答案是**物理隔离上下文、逻辑共享状态**：用图/文件/事件流承载黑板，用分层摘要（sapper 三层图 [Z4]）控制进上下文的内容。
3. **预设角色 vs 涌现分工**：角色预设 = 人类局限投影 [Z3]，但零协调有 MAST 失败税 [S32]。实战答案：平等 Worker + 图状态动态生成任务 + 极少量硬编码治理角色（watchdog 纯脚本零策略 [Z4]）。
4. **广度扇出 vs 深度单线**：并行换性能要付 15x token [S37]；并行发生在意图粒度可避开"冲突隐含决策" [S43]。需要一个**扇出策略控制器**：何时并行（范式 A 按信息增益）、何时收拢（范式 B 按证明义务）。

---

## 10. 对"庖丁"的启示

### 10.1 可直接采纳的原则

1. **内核做薄，能力放在外壳**，且结构要便于拆除（每代模型都会吃掉一部分脚手架）。
2. **每个领域先找判官**：有确定性判官的场景（CTF、数学、代码）放手自主并大量并行；没有的场景（医学、部分运维）用假设面板、置信度输出和人工闸门。
3. **把"假设集 + 不确定性"做成一等数据结构**：医学、CTF、运维的公共抽象 [S28][S35]；范式 A 场景下即证据梯形态（§9.3）。
4. **领域知识用技能注入，不写进内核**（当前事实标准，支撑"通用内核 + 领域包"分层）。
5. **状态落盘、可恢复、人可读**：计划、进度、发现、失败记录都写文件，跨上下文窗口靠文件接续 [S39]。
6. **写入单线程，智力可并行**：多智能体先只用于只读探索、独立验证和正交集成 [S44]；黑板路线把并行收敛到意图粒度。
7. **预算是显式参数**：步数、token、金钱、请求频率都有上限，预算节点触发反思。
8. **沙箱和权限分级从第一天就有**（CTF 与运维尤其）。
9. **允许说"不会"**：把"未解决 + 已排除路径"当合法输出。

庖丁解牛的要义"依乎天理，批大郤，导大窾，因其固然"，在架构上的对应正是：**先识别问题结构（哪个范式、有无判官、信息是否完全），再决定状态层与验证层的形态**——两范式 × 五层交叉表就是这把刀的刀路。

### 10.2 设计阶段待决问题

| 问题 | 选项 | 调研参考 |
| --- | --- | --- |
| 自研内核还是建在现有外壳上 | 自研循环；基于 Claude Agent SDK、OpenHands SDK 等 | 安全领域新项目多选后者 [S26][S29]；AIxCC 级系统都是自研；Cairn 把 Claude Code/Codex CLI 当"最小调度单位"[Z3] |
| 状态层 schema | 单层 fact-intent [Z3]；三层 title/summary/evidence [Z4]；双图（确定性骨架+概率生长）[Z5]；证据梯（可信等级） | 趋势：分层/分级 + 确定性分离；跨项目记忆（"通鉴"层）是否需要待定 |
| 规划形态 | 单循环待办；独立规划者；图/树搜索 | 可能需要按范式可切换（§7.3） |
| 工具策略 | 预置专用工具；通用 shell；允许自造 | 三者可并存，自造需强模型 [S4] |
| 记忆做到哪层 | 任务级文件；加检索库；加自我沉淀技能 | 文件优先是共识；自我沉淀是新趋势但有投毒与漂移风险 |
| 模型策略 | 单一强模型；多模型路由；多模型抢答 | Atlantis/RoboDuck 都用多厂商；小模型部分子任务更好 [S15]；sapper 用模型分层把 1B token 用出 4.5B 的效果 [Z4] |
| 自主程度 | 全自主；关键点确认；全程人在回路 | 按场景和动作可逆性分级；Hint 原语是被验证的人机接口 [Z3] |
| 首个落地场景 | CTF；数学；运维；医学 | CTF 判官明确、环境易搭、参考实现最多，适合先验证内核；但要预埋两范式抽象，避免内核长成 CTF 专用形状 |
| 扇出策略控制器 | 固定并发；按信息增益定价；按预算动态 | §9.4-4，尚无成熟开源实现——庖丁的潜在贡献点 |

### 10.3 需要警惕的陷阱

- **为当前模型短板过度设计**（D-CIPHER 式复杂分工一年内被清洗 [S12]）。
- **用基准分数指导设计**（头部基准饱和或污染；建自己的小型评测集 + 检查点式部分得分）。
- **堆叠智能体**（追加智能体只让死胡同变长 [S13]）。
- **脆弱启发式**（Atlantis 的 "fuzz" 字符串启发式差点翻车 [S15]）。
- **把通用等同于什么都内置**（通用性来自内核抽象和领域包可插拔）。

### 10.4 命名体系映射（项目文化）

黑板 = 解牛图 · 技能包 = 锦囊 · 工具层 = 如意 · 验证 = 谛听 · 并行编队 = 八仙过海 · 反思 = 复盘 · 跨项目记忆 = 通鉴 · 看门狗 = 哮天犬（候选）

---

## 11. 待补充事项

- ~~用户提供的 CTF 智能体参考~~ **已补入 §3**（Cairn / sapper-v2 / ARTEX 三锚点 + 2026 国内赛场）。
- 未覆盖或不足：计算机操作类智能体（OSWorld）深读、AIxCC 其余四队技术报告、Mythos Preview 系统卡原文、各开源项目星数复核、GeekCon/强网杯/腾讯第三届获胜架构的论文级细节（均未公开）。
- 建议后续：对 mini-SWE-agent、OpenHands SDK、CAI、tinyctfer 做源码级走读；对两范式 × 五层交叉表做原型验证（最小可行：一个证据梯 + 一个确定性判官的 CTF 收口场景）。

---

## 12. 来源

### [S#] 系列（沿用 v1-Claude 编号）

软件工程与通用助理

- [S1] Coding Agents Have Converged（arXiv:2609.17394）：https://www.alphaxiv.org/abs/2609.17394.md
- [S3] mini-SWE-agent 说明：https://docs.litellm.ai/docs/projects/mini-swe-agent/
- [S4] Live-SWE-agent（arXiv:2511.13646）：https://arxiv.org/html/2511.13646v3
- [S5] The OpenHands Software Agent SDK（arXiv:2511.03690）：https://arxiv.org/html/2511.03690v2
- [S6] Terminal-Bench 2.0 排行榜快照（2026-04）：https://www.codesota.com/benchmark/terminal-bench
- [S7] 编码智能体外壳的设计空间：https://codex.danielvaughan.com/2026/04/29/design-space-of-coding-agent-harnesses-codex-cli-claude-code-architectural-lessons/
- [S8] Alita（arXiv:2505.20286）：https://arxiv.org/abs/2505.20286
- [S9] JoyAgent-JDGenie GAIA 技术报告（arXiv:2510.00510）：https://arxiv.org/html/2510.00510v1
- [S10] CustomGPT GAIA 外壳（自报）：https://customgpt.ai/gaia-state-of-the-art-agent-harness/

网络安全

- [S11] D-CIPHER（arXiv:2502.10931）：https://arxiv.org/abs/2502.10931v1
- [S12] Cybench 饱和过程综述：https://aiworld.eu/story/cybench-a-yardstick-ai-outgrew
- [S13] DeepRed（arXiv:2604.19354）：https://arxiv.org/pdf/2604.19354 ；CTFExplorer（arXiv:2602.08023）：https://arxiv.org/pdf/2602.08023
- [S14] DARPA AIxCC 决赛结果：https://darpa.mil/news/2025/aixcc-results
- [S15] Team Atlanta 赛后总结：https://team-atlanta.github.io/blog/post-afc
- [S16] Trail of Bits 决赛对比：https://blog.trailofbits.com/2025/08/07/aixcc-finals-tale-of-the-tape/ ；Buttercup 仓库：https://github.com/trailofbits/buttercup ；Theori RoboDuck：https://theori.io/blog/aixcc-and-roboduck-63447
- [S17] Theori，构建有效的 LLM 智能体：https://theori.io/blog/building-effective-llm-agents-63446
- [S18] XBOW 登顶 HackerOne：https://xbow.com/blog/top-1-how-xbow-did-it/ ；XBOW 论模型与外壳：https://xbow.com/blog/mythos-gpt-5-5-ai-vulnerability-detection-security
- [S19] CAI 论文：https://pinzger.github.io/papers/Vilches2026-CAI.pdf
- [S20] Anthropic，Mythos Preview 网络安全能力评估：https://www.anthropic.com/research/mythos-preview
- [S21] Hack The Box AI 对人类 CTF 结果：https://www.hackthebox.com/blog/ai-vs-human-ctf-hack-the-box-results
- [S22] Anthropic，Claude 参加网络安全比赛：https://www.anthropic.com/research/cyber-competitions
- [S25] 腾讯云开发者社区，第二届智能渗透挑战赛决赛分享：https://cloud.tencent.com/developer/article/2669509
- [S26] tinyctfer：https://awesome.ecosyste.ms/projects/github.com%2Fchainreactors%2Ftinyctfer
- [S27] Google Project Zero，从 Naptime 到 Big Sleep：https://projectzero.google/2024/10/from-naptime-to-big-sleep.html
- [S29] AI 渗透智能体综述（2026）：https://appsecsanta.com/research/ai-pentesting-agents-2026 ；开源工具指南：https://dev.to/darkmoonx/open-source-autonomous-ai-pentesting-tools-in-2026-an-honest-field-guide-3ad0

数学与科研

- [S23] 三支 AI 队伍获 IMO 金牌：https://inferencebysequoia.substack.com/p/three-ai-teams-win-imo-gold-openai
- [S24] Aristotle（arXiv:2510.01346）：https://arxiv.org/html/2510.01346v1
- [S32] Google DeepMind，Co-Scientist：https://deepmind.google/blog/co-scientist-a-multi-agent-ai-system-to-accelerate-scientific-research/
- [S33] FrontierMath Tier 4 报道：https://aiweekly.co/alerts/claude-fable-5-beats-gpt-55-on-hardest-math-tier

医学

- [S28] Sequential Diagnosis with Language Models / MAI-DxO（arXiv:2506.22405）：https://arxiv.org/html/2506.22405v1
- [S35] 多模态 AMIE（arXiv:2505.04653）：https://arxiv.org/html/2505.04653v1

运维

- [S30] ORCA-bench（arXiv:2607.28545）：https://www.alphaxiv.org/abs/2607.28545.md
- [S31] ITBench 与 MAST 解读：https://lilting.ch/en/articles/ibm-itbench-mast-enterprise-agent-failure
- [S36] SREGym（arXiv:2605.07161）：https://arxiv.org/abs/2605.07161

开源生态

- [S34] OpenClaw 架构经验与安全风险：https://dev.to/ialijr/lessons-from-openclaws-architecture-for-agent-builders-1j93
- [S45] 开源智能体星数快照（2026-08）：https://select.keenable.ai/r/most-popular-open-source-ai-agents/mRcy-x8jxvF5Cf2sNyRrqw
- [S46] GitHub 智能体仓库前 20（2026-04）：https://fungies.io/top-github-repositories-ai-agent-frameworks-2026.md
- [S47] OpenClaw 与 Hermes Agent 对比（2026-05）：https://glukhov.org/ai-systems/comparisons/openclaw-hermes-alternatives-popularity/
- [S48] DeerFlow 2.0 说明：https://cdn.jsdelivr.net/gh/bytedance/deer-flow@main/README.md

厂商与论坛观点

- [S37] Anthropic，多智能体研究系统：https://www.anthropic.com/engineering/multi-agent-research-system
- [S38] Anthropic，构建有效的智能体：https://www.anthropic.com/engineering/building-effective-agents
- [S39] Anthropic，长时运行智能体的有效外壳：https://anthropic.com/engineering/effective-harnesses-for-long-running-agents
- [S40] OpenAI，外壳工程：https://openai.com/index/harness-engineering/
- [S41] Manus，智能体的上下文工程：https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus
- [S42] Anthropic，智能体技能：https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
- [S43] Cognition，不要构建多智能体：https://cognition.ai/blog/dont-build-multi-agents
- [S44] Cognition，多智能体：什么真的有效：https://cognition.com/blog/multi-agents-working
- [S49] WAIC 2026 模型与智能体综述：https://www.qbitai.com/2026/07/443399.html

### [Z#] 系列（v2 新增）

国内黑板谱系

- [Z1] Cairn 复盘文章（淚笑，2026）：https://mp.weixin.qq.com/s/DlpEH7bVr0xi0VawPJs3XA （A：作者一手复盘）
- [Z2] Cairn 决赛答辩 PPT 文章：https://mp.weixin.qq.com/s/2rEqFLvkxvYWM3gW170C2w （A）
- [Z3] Cairn 仓库：https://github.com/oritera/Cairn （A）
- [Z4] sapper-v2 仓库：https://github.com/N1nEmAn/sapper-v2 （A）
- [Z5] ARTEX 社区 fork：https://github.com/RuoJi6/ARTEX 、https://github.com/imxv/ARTEXX （C：fork 与二手报道）
- [Z6] ARTEX 下架报道（知乎）：https://zhuanlan.zhihu.com/p/2093260316964668689 （C）

攻防侧补充

- [Z7] EnIGMA（arXiv:2409.16165，ICML 2025）：https://arxiv.org/abs/2409.16165 （A）
- [Z10] Atlantis 技术报告（arXiv:2509.14589）：https://arxiv.org/abs/2509.14589 （A）
- [Z11] Trail of Bits Buttercup 获奖博客：https://blog.trailofbits.com/2025/08/09/trail-of-bits-buttercup-wins-2nd-place-in-aixcc-challenge/ （A）
- [Z13] Reuters：Gemini 沙箱逃逸入侵三家真实公司（2026-09）：https://www.reuters.com/business/gemini-hacked-three-companies-first-known-breakout-by-google-ai-wsj-reports-2026-09-18 （A）
- [Z14] CAI（arXiv:2512.02654）：https://arxiv.org/abs/2512.02654 （A）
- [Z15] PentAGI 仓库：https://github.com/vxcontrol/PentAGI （B）
- [Z16] 清华：GEEKCON 2026 AI 黑客极限挑战赛 RedbudAI 夺冠：https://www.tsinghua.edu.cn/info/1176/129069.htm （A）
- [Z17] IT之家：腾讯云第三届智能体攻防挑战赛（AI-KOH）：https://www.ithome.com/1/022/303.htm （C）

通用框架与记忆

- [Z18] smolagents（CodeAct）：https://huggingface.co/blog/smolagents （B）
- [Z19] Anthropic 将 Agent Skills 捐赠给 Agentic AI Foundation：https://www.anthropic.com/news/donating-agent-skills-to-the-agentic-ai-foundation （A）
- [Z20] Magentic-One（arXiv:2411.04468）：https://arxiv.org/html/2411.04468v1 ；Microsoft Agent Framework：https://learn.microsoft.com/en-us/agent-framework/overview （A）
- [Z21] Letta：Benchmarking AI Agent Memory（纯文件 74.0% LoCoMo）：https://www.letta.com/blog/benchmarking-ai-agent-memory （B）
- [Z22] The New Stack：OpenClaw 星数超越 Linux：https://thenewstack.io/openclaw-github-stars-security （C）

基准与趋势

- [Z23] Terminal-Bench 官方榜单：https://www.tbench.ai/leaderboard/terminal-bench/2.0 ；Snorkel OSWorld 2.0 榜单：https://snorkel.ai/leaderboards/os-world-2-0 （C：快照）
- [Z24] Kimi-Researcher（端到端 RL）：https://moonshotai.github.io/Kimi-Researcher （A）；HN "Bitter Lesson of agents" 讨论：https://news.ycombinator.com/item?id=43451742 （C）
- [Z25] METR 时间跨度研究（arXiv:2503.14499）：https://arxiv.org/html/2503.14499v3 （A）
- [Z26] Epoch AI 时间跨度追踪器：https://epoch.ai/benchmarks/metr-time-horizons （B）
- [Z27] METR Time Horizon 1.1（2026-01）：https://metr.org/blog/2026-01-29-time-horizon-1-1 （A）
- [Z28] OpenAI：Why we no longer rate SWE-bench Verified：https://openai.com/index/why-we-no-longerate-swe-bench-verified （A）
- [Z29] SWE-bench Pro（arXiv:2509.16941）：https://arxiv.org/html/2509.16941v1 （A）
- [Z30] OSWorld 2.0 榜单（Snorkel）：https://snorkel.ai/leaderboards/os-world-2-0 （C）
- [Z31] ARC Prize 2025 结果分析：https://arcprize.org/blog/arc-prize-2025-results-analysis （A）

多智能体研究

- [Z32] MAST：Why Do Multi-Agent LLM Systems Fail?（arXiv:2503.13657）：https://arxiv.org/abs/2503.13657 （A）

协议层

- [Z33] A2A 捐赠 Linux Foundation、150+ 组织采用：https://www.linuxfoundation.org/press/a2a-protocol-surpasses-150-organizations-lands-in-major-cloud-platforms-and-sees-enterprise-production-use-in-first-year （A）
