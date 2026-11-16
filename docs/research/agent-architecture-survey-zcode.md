# 庖丁前置调研：2024–2026 智能体架构全景分析

> 定稿：2026-11-16 ｜ 用途：为通用问题求解智能体「庖丁」的架构设计提供前置输入
> 方法：用户指定案例一手拆解 + 三路并行调研（攻防竞赛 / 通用框架 / 基准与思想演变）

---

## 0. TL;DR：一页结论

1. **竞赛侧、工业侧、学术侧正在收敛到同一张架构图**：
   强模型驱动的单循环 Worker + 共享结构化状态（黑板/图谱/文件系统）+ 严格验证环 + 沙箱执行 + 模型分层经济。
2. **三条演化主线**：流程工程（2023–24，角色/SOP/编排 DSL）→ 上下文工程（2025，KV-cache/todo.md/文件系统）→ **环境与经济工程**（2026，沙箱、验证环、token 预算分层、治理）。外部编排结构持续被模型能力吸收——这就是用户观察到的"约束删简"。
3. **黑板架构不是复古**，而是工业共识"物理隔离上下文、逻辑共享状态"在攻防赛场的表达：Worker 各自持有独立上下文窗口，通过共享事实图谱协调（Stigmergy，共识激发），而非共享 prompt。
4. 多智能体的角色预设已被证伪，但**平等 Worker + 共享状态 + 涌现分工**在三个独立赛场（Cairn、sapper-v2、CAI 多 scaffold 黑板）得到验证。

---

## 1. 锚点案例深拆（用户指定三案）

### 1.1 Cairn —— 黑板 + DAG 的"无径之径"

- 作者：淚笑（l3yx），起零衍迹 Oritera 开源组织；[复盘文章](https://mp.weixin.qq.com/s/DlpEH7bVr0xi0VawPJs3XA)、[决赛答辩 PPT](https://mp.weixin.qq.com/s/2rEqFLvkxvYWM3gW170C2w)、[GitHub](https://github.com/oritera/Cairn)（5.2k star，AGPL-3.0）
- **问题抽象**：一切"有明确起点与明确达成标准"的问题 = 状态空间搜索。渗透只是配了个装满工具的 Kali 容器。
- **五原语**：
  - `Origin`：已知起点（如目标 IP）
  - `Goal`：明确成功条件（如拿到 flag）
  - `Fact`：已确认的客观发现，写入黑板
  - `Intent`：已声明未执行的探索方向
  - `Hint`：人类任意时刻注入的判断，Worker 下次读取时吸收（人机协同通道）
- **组件**：Cairn Server（只维护图一致性）/ Dispatcher（读图、调度、启停 Worker 容器，协议唯一写入者）/ Agent Worker（只吃 prompt 吐结构化输出，后端 Claude Code、Codex、Pi）
- **Worker 循环（OODA）**：观察全图 → 定向 → 决定新 Intent → 执行探索 → 写回 Fact
- **三种任务**：Bootstrap（开局直接尝试解题）/ Reason（读全图判断是否达成、下一步干嘛）/ Explore（认领一个 Intent 执行并报告一个 Fact）
- **Less Is More 宣言**：零 MCP、零 RAG、零预定义角色、零渗透流程定义；工具能力全部下沉到 Worker（把 Claude Code/Codex 当"最小调度单位"）。"Agent 角色分工是人类局限的投影"
- **成绩与成本**：第二届腾讯云黑客松 610 队中唯一 AK（54/54），因开局配置失误总排名第 4/决赛第 3；5 天 ¥7692、10.9 亿 token；第四天注入"人类意图"（Hint）后第五天 AK——人机协同的实证

### 1.2 sapper-v2 —— 分层图谱 + 涌现分工 + 经济学

- [GitHub](https://github.com/N1nEmAn/sapper-v2)（清华，MIT）；第三届腾讯云智能体攻防挑战赛线上冠军（634 队、80.18 分、8 小时无人值守）；致谢明确参考 Cairn 的历史记录方法
- **女娲（Nüwa）测试**：给 AI 一条生存公理 + 三能力，观察其长出分工协作：
  - `Create`（生育）：通过 tmux 像人一样敲命令开新 AI 窗口
  - `Language`（语言）：智能体往彼此输入框打字交流
  - `History`（历史/石碑）：**三层 fact-intent 图**（title / summary / evidence document），读标题知概要、按需下钻——修复单串事实图的两大失效：一条坏事实污染下游、无谓上下文消耗
- **运行时只有三类窗口**：Commander（读黑板→判断→派单，从不亲自攻击）/ 军团（tmux 并行，scout 侦察、soldier 批量、general 攻坚可自建小队）/ Watchdog（**纯脚本零策略**，只做保活：崩溃重启、key 轮换、截止收尾）
- **模型分层经济（1B token 赢 4.5B 的关键）**：指挥官/将军用 GLM-5.3，士兵/scout 用 DeepSeek V4.1 Flash
- **涌现现象**（无预编码）：通信兵角色（士兵反复交旗失败后，指挥官新设专职统一收旗）、绩效谈话、可复用 shellcode 模板横扫题族、同构题目迁移（后期 3 分钟一题）
- **"个体会死，图存续"**：上下文饱和（实测 ~260K）时士兵轮换并留 playbook 给继任者；指挥官给自己写交接文档
- 附：提出 taggant（攻击工具水印溯源）提案应对滥用

### 1.3 ARTEX —— 双黑板：资产世界 × 任务探索

- 作者 [Autumn-27](https://github.com/Autumn-27)；百度「agent+」攻防挑战赛冠军；原仓库已因韩国金融安全院追踪到入侵银行的黑客使用本工具而下架（[知乎报道](https://zhuanlan.zhihu.com/p/2093260316964668689)），社区 fork 存活：[RuoJi6/ARTEX](https://github.com/RuoJi6/ARTEX)、[imxv/ARTEXX](https://github.com/imxv/ARTEXX) 等
- **双黑板**：
  - 全局**资产图**：域名→子域→服务→端点，父子关系由程序计算（世界模型的确定性骨架）
  - 任务级**探索图**：goal/intent/finding/hint 节点 + spawns/derived_from/yields/proves 边
- **Planner-Workers**：Planner 是唯一意图生成者（事件驱动、防抖唤醒、每次全新会话）；Worker 默认 3 个，`claimNext` 认领意图执行并回写图；跨 Worker 可 `search_all_worker_traces` 互查轨迹
- **治理一等公民**：MITM 代理全程留证 + 审批门 + 逐 agent 运行预算
- 技术栈：Go 单体 + Next.js + PostgreSQL，agent 能力由 norma SDK 提供

---

## 2. 攻防侧竞赛全景（谁在赢，凭什么）

| 系统 | 架构核心 | 成绩/数据 |
|---|---|---|
| **XBOW** | **验证环为王**：每个发现由 validators（LLM + headless 浏览器实际执行 payload）双重确认；SimHash+截图 imagehash 去重资产 | ~90 天 1060 漏洞（54 critical），[HackerOne 美榜第一的非人类](https://xbow.com/blog/top-1-how-xbow-did-it) |
| **ATLANTIS**（AIxCC 冠军，$4M） | 符号执行 + AFLGo 定向 fuzzing + LLM 混合编排；CP-Manager 证据守门（PoV 唯一才提交）；模块化预算分配 | [arXiv 2509.14589](https://arxiv.org/abs/2509.14589)；43/70 漏洞、补丁成功率 72.1%、总成本 $103K |
| **Buttercup**（AIxCC 亚军，$3M） | 七 agent 状态机补丁流水线（Leader/Context/Input/RootCause/SWE/QE/Reflection），失败按状态路由回退；**全程廉价非推理模型** | $181/点；10 万+ 请求仅 $39.6K；[开源](https://blog.trailofbits.com/2025/08/09/trail-of-bits-buttercup-wins-2nd-place-in-aixcc-challenge) |
| **Big Sleep**（Google P0） | **种子约束**：以已知漏洞 diff 为种子做变体分析，假设驱动迭代（读码→建测试→跑崩→根因→报告），工具面小而深 | 首个 AI 发现真实可利用 0day（SQLite）；2025 首次挫败在野利用（[博客](https://projectzero.google/2024/10/from-naptime-to-big-sleep.html)） |
| **EnIGMA** | **IAT 交互式工具会话化**：gdb/radare2 等封装为 start/stop+子命令，非阻塞并行（模拟人类多窗口）；双层摘要器控上下文 | NYU CTF 13.5%（此前 4.0%）；[arXiv 2409.16165](https://arxiv.org/abs/2409.16165) |
| **CAI**（Alias Robotics） | **多 scaffold 黑板**：聚合多个 harness 于共享黑板 | Cybench 19/33 vs 最佳单 scaffold 15/33；Neurogrid CTF 41/45 夺 $50K；宣布 "Jeopardy CTF 已是 solved game" |
| **PentAGI**（34.3k star） | 角色化多 agent + Reflector（发现模型"只说不做"时强制拉回工具调用） | [GitHub](https://github.com/vxcontrol/PentAGI) |

**国内赛场（2026）**：GeekCon「AI 黑客极限挑战赛」冠军清华 RedbudAI（多智能体协同+自进化+持续作战，控制四足机器人等真实目标）；腾讯云第三届升级为多智能体同场攻防「AI-KOH 王座协议」（冠军川大 alkaerr）；强网杯第九届设漏洞智能分析赛道。架构细节均未论文级公开。

**攻防侧六条共性**：
1. **验证驱动**：发现便宜、证明昂贵，架构重心永远在验证环（XBOW validators / CP-Manager / QEAgent）
2. **经典工具为主体、LLM 为编排层**：纯 LLM 找洞不可行；Big Sleep 与 Fuzzilli 结果仅 ~25% 重叠，互补
3. **记忆 = 图 + 分层摘要**：结构化世界模型，上下文只放摘要（ARTEX 双图 / sapper 三层 / EnIGMA 双摘要器）
4. **意图与执行分离**：Planner/Dispatcher 唯一出意图，Worker 无状态认领（ARTEX / Cairn）
5. **模型分层省钱**：Buttercup 全非推理模型 $181/点；CAI 声称小模型降本 50 倍；sapper 1B 赢 4.5B
6. **沙箱与护栏一等公民**：每任务 Docker、turn 上限、重复调用熔断、审批门留证；Gemini 2026 年 5 月沙箱逃逸入侵真实公司（[Reuters](https://www.reuters.com/business/gemini-hacked-three-companies-first-known-breakout-by-google-ai-wsj-reports-2026-09-18)）反证其必要性

**反幻觉教训**：EnIGMA 发现 Claude 3.5 Sonnet 在 48.4% 轨迹中"自言自语"自造观察（soliloquizing）跳过真实环境交互——**"观察必须来自真实工具执行"需要架构级保证**。

---

## 3. 通用侧：框架与产品的赢家和淘汰者

### 3.1 演化时间线

```
2023      AutoGPT/BabyAGI 天真自主循环（模型太弱，失败）
2024      ReAct/Reflexion 脚手架；编排框架爆发（LangChain/MetaGPT SOP/AutoGen 群聊）
2024末     Anthropic《Building Effective Agents》纠偏：workflow vs agent，从简单开始
2025      上下文工程元年：Manus KV-cache/todo.md/文件系统；orchestrator-worker；
          Agent Skills 渐进披露；MCP 成事实标准；薄 harness + 强模型刷榜
2025末-26  RL 吸收规划（deep research、Kimi-Researcher、agentic RL）；
          黑板架构在攻防赛场复兴（Cairn→sapper→ARTEX）；A2A 捐 Linux Foundation；
          基准集体转向长程（TB 4.x / OSWorld 2.0 / SWE-bench Pro / Gaia2）
```

### 3.2 被验证的赢家

| 机制 | 证据 | 来源 |
|---|---|---|
| **薄 harness + 强模型** | Terminal-Bench 2.0 榜首全是极简 harness（Codex CLI 82.2%、Mini-SWE-agent 百行代码登顶独立榜）；编排复杂度与分数不相关 | [tbench.ai](https://www.tbench.ai/leaderboard/terminal-bench/2.0) |
| **orchestrator-worker（广度任务）** | Anthropic 多智能体研究系统比单 agent +90.2%，但耗 15x token；token 用量解释 80% 性能方差 | [Anthropic](https://www.anthropic.com/research/multi-agent-research-system) |
| **KV-cache 感知设计** | IO token ≈100:1，缓存命中 $0.30 vs 未命中 $3.00/MTok（10 倍）；append-only + 前缀稳定 + 显式断点 | [Manus 博客](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus) |
| **todo.md 诵读 / 文件系统即上下文** | 反复重写 todo = 把全局计划"背诵"到上下文末尾对抗 lost-in-the-middle；网页只留 URL、文档只留沙箱路径 | 同上 |
| **保留错误轨迹** | "错误恢复是真正 agent 行为的最清晰指标"；反对清理式架构补丁 | 同上 |
| **mask, don't remove** | 工具用 logits 掩码而非动态增删（护缓存防幻觉） | 同上 |
| **文件系统记忆打败专用记忆系统** | Letta 实测纯文件存对话在 LoCoMo 得 74.0%，超过一切专用记忆系统 | [Letta](https://www.letta.com/blog/benchmarking-ai-agent-memory) |
| **CodeAct 代码即行动** | smolagents：写 Python 而非 JSON 调工具，一步多调用 | [HF 博客](https://huggingface.co/blog/smolagents) |
| **Agent Skills 渐进披露** | SKILL.md 只预载元数据按需加载正文；已成开放标准（Manus/OpenAI 跟进） | [Anthropic](https://www.anthropic.com/research/equipping-agents-for-the-real-world-with-agent-skills) |
| **Task Ledger ≈ 黑板** | Magentic-One 双循环：外循环 Task Ledger（事实/猜想/总计划）、内循环 Progress Ledger（子任务状态、卡壳重规划） | [论文](https://arxiv.org/html/2411.04468v1) |
| **事件流架构** | OpenHands：所有交互皆类型化事件过中央总线，任何组件可订阅历史；~50k star | [OpenReview](https://openreview.net/forum?id=OJd3ayDDoF) |
| **MCP + A2A 双层协议** | MCP 管 agent↔工具成事实标准；A2A 管 agent↔agent，150+ 组织采用 | [LF 公告](https://www.linuxfoundation.org/press/a2a-protocol-surpasses-150-organizations-lands-in-major-cloud-platforms-and-sees-enterprise-production-use-in-first-year) |
| **agentic RL** | Kimi-Researcher 端到端 RL 从 8.6%→26.9% HLE，工具使用为涌现能力；RL 环境投入超 $1B | [Moonshot](https://moonshotai.github.io/Kimi-Researcher) |

### 3.3 被淘汰/退潮

- 自由群聊式多 agent（AutoGen 独立赛道被官方 Microsoft Agent Framework 吸收）
- 重编排 DSL 与"为每任务定制 agent 拓扑"
- 专用分层记忆系统（被纯文件方案打败）
- MetaGPT 式角色 SOP 流水线（热度大降）
- **SWE-bench Verified 本身**：2026.2 被 OpenAI 弃用（饱和 93.9% + 59.4% 任务测试有缺陷 + 污染）

### 3.4 多智能体之争（关键辩论）

- **MAST**（Berkeley，NeurIPS 2025）：标注 1600+ 轨迹，14 种失败模式/3 类——多智能体常败于 agent 间失调与信息不对称（[arXiv 2503.13657](https://arxiv.org/abs/2503.13657)）
- **Cognition《Don't Build Multi-Agents》**（2025.6）两原则：共享完整上下文；行动携带隐含决策（并行 agent 必然做出冲突的隐含决策）→ 默认单 agent + 上下文工程；2026.4 [跟进文](https://cognition.com/blog/multi-agents-working)软化为"部分模式已 work，但并行冲突仍在"
- **与黑板路线的关系**：黑板路线恰好是对这场争论的第三种回答——不预设角色（避开 MAST 的规格失配）、共享**结构化状态**而非共享完整上下文（避开 KV-cache 与上下文冲突）、并行发生在"探索意图"粒度而非"决策"粒度。CAI 的多 scaffold 黑板（19/33 > 15/33）与 sapper 的实战冠军是两条独立实证。

---

## 4. 基准测试的信号

| 基准 | 状态（2026.11） | 榜首与架构 | 对庖丁的含义 |
|---|---|---|---|
| METR 时间跨度 | **任务时长每 ~7 个月翻倍**（2019–2025） | Opus 4.6 ~12–14.5h，首个超整工作日 | 按**小时级**任务设计，不是分钟级 |
| Terminal-Bench 2.0 | 已被打穿（84.7%） | NexAU-AHE(GPT-5.5)、Codex CLI，全是极简 harness | 4.x 版榜首仅 ~57.6%，长程终端仍是硬仗 |
| SWE-bench Verified | 被官方弃用 | — | 单点修 bug 已死；小时-天级多文件工程是主战场 |
| SWE-bench Pro | 完整集最高 ~23% | Claude Opus 5 | 长程代码任务远未解决 |
| OSWorld | Verified ~86% 饱和 | Agent S3 等开源方案曾首超人类 | **OSWorld 2.0（长程）Claude Opus 5 仅 44.3%** |
| ARC-AGI-2→3 | 2 代榜首 95% 后发布 3 代 | 全前沿 <1% | 推理+agentic coding 双驱动 |
| CTF（NYU/Cybench/HTB） | D-CIPHER：22.0% / 22.5% / 44.0% | 环境反馈迭代 > 堆 agent | 学术基准远低于赛场实战（CAI 41/45） |
| 多天级评测 | **缺位** | 多天自主成功率 ~23% | 庖丁的机会空间：跨天持久任务 |

---

## 5. 综合判断：共识架构图与四条张力

### 5.1 共识架构（五层）

```
┌── 治理层：预算 / 审批门 / 看门狗 / 审计追踪（sapper Watchdog、ARTEX 审批门、Buttercup 成本线）
├── 验证层：validators / 证据守门 / PoV 复核（XBOW、CP-Manager、QEAgent）——"发现便宜、证明昂贵"
├── 执行层：每任务沙箱 + 交互式工具会话化 + 非阻塞并行（EnIGMA IAT、Kali 容器、tmux）
├── 状态层：共享黑板——fact-intent 图 / 文件系统 / 事件流（Cairn、sapper、Magentic Ledger、Manus 文件）
└── 内核层：强模型 × 单循环 CodeAct，Worker 平等无预设角色，编排尽量薄
            （Claude Code/Codex CLI 即"最小调度单位"）
```

### 5.2 四条张力（庖丁设计时必须表态的四个问题）

1. **结构 vs 涌现（约束删简律）**：外部编排代码持续被模型能力吸收（deep research 无手写 workflow 登顶；Anthropic 2025-10 立场：单主循环 + skills 检索 > 堆 subagent）。但**验证与工具治理结构不被吸收**——结构应该花在"守门"上，不是"指路"上。
2. **共享上下文 vs 缓存隔离**：黑板要人人可见 vs KV-cache 要上下文隔离。2025–26 的答案是**物理隔离上下文、逻辑共享状态**：用图/文件/事件流承载黑板，用分层摘要控制进上下文的东西（sapper 三层图谱正是为此而生）。
3. **预设角色 vs 涌现分工**：角色预设 = 人类局限投影（Cairn）；但零协调也有 MAST 失败税。实战答案：**平等 Worker + 图状态动态生成任务 + 极少量硬编码治理角色**（watchdog）。
4. **广度扇出 vs 深度单线**：并行换 90% 性能提升要付 15x token（Anthropic）；并行发生在意图粒度可避免 Cognition 说的"冲突隐含决策"。庖丁需要一个**扇出策略控制器**（何时并行、何时收拢）。

---

## 6. 给庖丁的启示（设计前的问题清单，不是设计）

1. **问题抽象直接继承 Cairn 同构**：Origin / Goal / Fact / Intent / Hint 五原语就是"庖丁解牛"的刀路——起点、终点、纹理（Fact）、下刀方向（Intent）、持刀人的提示（Hint）。
2. **六个待决策问题**（下一步架构设计要逐一回答）：
   - Worker 载体：Claude Code/Codex CLI 当最小调度单位（Cairn 路线），还是自研薄循环（Mini-SWE-agent 路线），还是混合？
   - 图谱 schema：单层（Cairn）还是三层（sapper）还是双图（ARTEX）？跨项目记忆（"通鉴"层）要不要？
   - 验证层形态：领域无关的"证据守门"怎么抽象（医学的验证 ≠ CTF 的 flag ≠ 数学的证明检查）？
   - 经济层：模型分级路由（sapper 路线）+ 预算分配（ATLANTIS 路线）怎么进架构？
   - 安全治理：审批门、沙箱等级、审计、授权边界（ARTEX 事件是前车之鉴）
   - 跨域适配层：CTF=Kali 容器，医学/数学/运维各配什么"工具容器"？领域适配的接口标准是什么？
3. **命名体系预映射**（延续中文典故命名）：黑板=`解牛图`、技能包=`锦囊`、工具层=`如意`、验证=`谛听`、多智能体编队=`八仙过海`、反思=`复盘`、跨项目记忆=`通鉴`、看门狗=`哮天犬`（可选）。

---

## 附录：未能核实的信息（诚实清单）

- Google CTF 2025 "Gemini 击败 N 支人类队伍"的官方博客原文未找到（易混淆事件：ICPC 2025 Gemini 金牌级）
- GeekCon 2026 / 腾讯第三届 AI-KOH / 强网杯 AI 赛道获胜架构的论文级细节未公开
- XBOW 内部模型与 agent 拓扑未公开（仅 validators 概念）
- Terminal-Bench 榜单中未找到 "Miyachi"/"Marvin" 条目
- ARTEX"双黑板"细节来自 fork 仓库 README 与二手报道，原仓库已下架无法一手核实
- OSWorld 2026 榜首分数（86–90%）未能独立交叉验证
