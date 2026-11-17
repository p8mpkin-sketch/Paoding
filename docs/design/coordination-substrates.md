# 庖丁协调基质设计：可插拔的非黑板路线

> 状态：提案（2026-11-17）｜上游：[architecture-v0.md](./architecture-v0.md)（v0.1 修订）、[greenfield-base-run.md](./greenfield-base-run.md)
> 回答的问题：能不能不用黑板契约？答案：能——黑板不是基座，只是"协调基质"的一个默认插件。本文给出两种替代基质（阡陌/榷场）、两个挂载包（擂台/判例）、基质接口定义与迁移路线。
>
> **勘误（2026-11-17，经蓝图 v2 对抗评审）**：本文 §3 与 §6 中"价格机制天然无热点""榷场是千级并发的调度答案"两处断言**已被修正**——千级并发的瓶颈是每题一个 Reason 的互斥域与读图上限，不是写入吞吐（单写者+组提交可扛 10³ 事件/秒量级）。正确路线：题组/题/子题三层展开、复制决策域；榷场落在题组层，降格为**记账的分配算法**（盲报集成 + 公平赔率，工人不知情），题内用退化形态。原"激励机制"设计（赏金、做多做空）被移除——同族模型读同一张图时题内行情只是回声，且激励面会诱发对判官的投机。详见 [architecture-blueprint-v2.md](./architecture-blueprint-v2.md) §3.1（F2）与 [blueprint-v2-review.md](../reviews/blueprint-v2-review.md) §1。本文其余部分（基质接口九操作、阡陌、判例、路线建议）不受影响。

---

## 0. 关键解锁：黑板不是基座

绿地实验的裁决已经证明：五契约中只有 **Ledger（黑板）是协调范式专属的**，TaskSpec / Judge / Evidence / Executor 在任何协调范式下都存活。因此：

```
基座 = TaskSpec + Judge + Evidence + Executor + 协调基质接口（Substrate Interface）
协调基质 = 可插拔模块：黑板(Ledger) / 阡陌(git) / 榷场(市场)
```

**实证边界（必须先说清）**："不用黑板"有两层含义：

1. **不用"自建黑板服务"**——完全可行，方案 B（阡陌）更瘦且删简律免疫；
2. **不用"持久共享状态"范式**——要付实证代价。纯消息传递/群聊式协调已被 MAST（37% 失败源于 agent 间失配）与 Cognition 分析证伪。共享状态可以**变形**（事实图→git 仓库→订单簿），不能**消失**——否则持久、审计、认识论三个刚需没有挂载点。

一个诚实的讽刺：榷场的订单簿本质上仍是 append-only 账本——市场消灭了调度器，消灭不了账本。

## 1. 四刚需（任何基质必须覆盖）

| 刚需 | 含义 | 出处 |
| --- | --- | --- |
| 持久 | 状态超越个体上下文死亡（"个体会死，图存续"） | sapper-v2 [Z4] |
| 审计 | append-only、可重放、字节级可复现 | 红线 1 |
| 认识论 | 证据等级/可信状态是显式的 | MAI-DxO/证据梯 [S28] |
| 协调 | 多个平等 Worker 的任务生成、认领、冲突消解 | Cairn [Z3] |

## 2. 基质 B：阡陌——git 即协调（M0 推荐）

名字取自"阡陌交通"——分支就是田间小路。

### 2.1 仓库即状态

```
problem-repo/
  task.toml            # TaskSpec：origin/goal/judge_chain/budget/caps/plugins
  evidence/            # 内容寻址对象（git blob 天然 sha256 寻址）
  claims/<id>.md       # 主张：frontmatter{kind,tier,refs,plausibility} + 正文
  intents/<id>.md      # 意图：frontmatter{claim,bounty,cost,owner,state}
  judges/              # 判官代码 + CI 配置（判官只读 evidence/ 挂载）
  views/               # 派生投影：make views 生成，永不手改（含证伪传播规则）
```

### 2.2 机制映射

| 基质行为 | git 实现 |
| --- | --- |
| Worker | worktree + 分支 |
| 提案 | commit / merge request |
| commit 门（红线 1） | pre-receive hooks：refs 校验 + schema lint（确定性代码） |
| 意图认领（原子 CAS） | `git update-ref` 带旧值检查（分布式锁） |
| 判官结算 | main 分支保护 + CI 流水线通过才可合并 |
| 审计 | git log + reflog（append-only 白送） |
| 快照 | tag |
| 重放验收 | `clone + make views` 字节一致 |
| 证伪传播 | views 生成器中的确定性规则（投影层，不碰真相层） |
| Hint 人机通道 | 人直接编辑 claims/intents 文件提 PR（任何编辑器可介入） |
| stable_dump | `views/world.md`，由 make 生成，字节级前缀不变量 |

### 2.3 评估

- **优点**：零新基础设施（M0 从"两三周"缩到"几天"）；git 删简律免疫；与 OpenAI《外壳工程》"仓库是唯一事实来源"同构；人机协同零成本；绿地 Ledger 本质是重新发明 git——阡陌说：别重新发明，直接用。
- **代价**：并发粒度粗（merge 即协调是有损的）；schema 约束弱（lint 补）；图查询弱（派生 SQLite 索引补，索引永远是派生非权威）；热意图的 ref 竞争在千级并发下会成为热点。
- **红线检查**：五条全过（hooks=确定性写入门；evidence=内容寻址；judges/ 目录=领域外置；git 不会死；CI 即判官）。

## 3. 基质 A：榷场——市场即调度（规模化研究方向）

名字取自宋代官办监管互市"榷场"——官方监管、异域商人自由交易。异构模型就是那些商人。

### 3.1 机制

- 每个开放问题发行**合约 Contract**：`{claim, oracle(judge_ref), settlement_tier, bounty, deadline}`
- **Solver 押注干活**：认领意图押保证金（真扣预算）；判官通过领赏金；失败保证金归池继续资助后续工作
- **猜想是可交易证券**：任何 agent 可做多（支持）或做空（攻击/证伪）；价格 = 共识概率，由多个独立做市商报价取中位数（= "异构晋级要求"的市场化形态）
- **注意力 = 期望值排序**：高不确定性 × 高赏金自然吸引 worker——**扇出控制器不用写，价格就是扇出控制器**
- **模型经济 = 资本分层**：便宜模型小注多下、强模型大注重点下。一个机制吃掉原四个：调度、扇出控制、验证定价、模型分层
- 结算信任根仍是判官（与现设计完全一致，市场不碰红线 2）

### 3.2 关键数学性质

**市场是调度器的极限形式**：agent 数 → 1、流动性 → 0 时，榷场退化为"期望值排序调度器"，恰好就是司南。因此榷场不是替代司南，而是司南在第八阶段（上千智能体）的连续推广。黑板/阡陌在千级并发下有写入热点与调度瓶颈，价格机制天然没有。

### 3.3 诚实的三个问题

1. **流动性**：agent 少时无价格发现——M0 单机跑不了市场（但退化形态可用）
2. **操纵**：结算靠判官所以拉抬无用；但流动性差时价格失真会误导注意力
3. **复杂度**：撮合与清算是新代码（估 2–4 周，M1 之后才值得）

**定位**：论文级创新点 + 第八阶段的调度答案；M0/M1 不实现，只在基质接口上预留语义。

## 4. 策略包 C：擂台——谱系锦标赛（范式 B 专用）

没有世界图，只有**候选解种群**：生成变异 → 廉价判官粗筛 → 锦标赛 → 幸存者变异/交叉 → 名人堂（通鉴雏形）。已实证：Co-Scientist 的排名锦标赛、Atlantis 的 N 版本编程。适用于数学证明、exploit 链生成等"完全信息搜索"任务。**做成策略包挂载在任意基质上，不做基座。**

## 5. 记忆层 D：判例——对抗制 + 判例库

所有已结算的 claim 变成**判例**（含判决书=verdict 证据链）；新问题先类比检索判例（case-based reasoning），对抗检验后立新判例。与协调基质正交，直接长在通鉴上；"判例效力"复用判官 tier 表（L0–L4 判例的引用权重不同）。

## 6. 对照矩阵

| 维度 | 解牛图（黑板） | 阡陌（git） | 榷场（市场） | 擂台（进化） | 判例（记忆） |
| --- | --- | --- | --- | --- | --- |
| 持久 | 事件链 | git 历史 | 订单簿（仍是账本） | 种群库 | 判例库 |
| 审计 | 事件重放 | reflog | 成交记录 | 谱系 | 判决书 |
| 认识论 | 节点 tier | frontmatter tier + 派生视图 | **价格** | fitness | 判决效力 |
| 协调 | commit 门 + 图任务 | merge + ref CAS | **出清** | 锦标赛 | 类比匹配 |
| M0 成本 | 中（自建服务） | **最低（几天）** | 高（不可用） | 低（策略包） | 低（挂载） |
| 千级并发 | 写入热点风险 | ref 竞争热点 | **天然无热点** | 天然并行 | — |
| 删简律 | 服务会被重发明替代 | **git 不死** | 调度器思想可持续 | 会进模型 | 检索会长存 |

## 7. 协调基质接口（Substrate Interface v0）——本文真正的核心产出

四契约与外壳只依赖此接口，不依赖基质内部表示。基质可互换的前提是接口稳定：

```
# 任何基质（解牛图/阡陌/榷场）必须实现：

submit(proposal) -> proposal_id
    # 提案：节点/边、工具调用结果、判官 verdict、goal_refine …

adjudicate(proposal_id) -> committed | rejected{why}
    # 确定性 commit 门（红线 1）：schema 校验、引用完整性、配额、迁移规则
    # 拒绝必须留痕（node_reject / 拒绝成交）

snapshot() -> world_ref
    # 当前世界观（权威状态或可重算的确定态）

stable_dump(world_ref) -> bytes
    # 字节级前缀稳定投影（KV-cache 架构保证；易变字段排除；CI 黄金测试）

cas(key, expected, new) -> ok | conflict
    # 原子认领：意图认领、锁、榷场的保证金锁定

query(view_spec) -> derived
    # 派生视图：投影规则在此运行（证伪传播+阻尼落位于此）

settle(verdict) -> transitions
    # 判官结算：tier 迁移、goal_verified / answered_unverified 终态判定
    # 只接受 Evidence 锚定的 verdict（红线 2）

replay(events) -> snapshot      # 确定性重放（审计验收：字节一致）
history(filter) -> events       # 审计查询
```

红线到接口的映射：`adjudicate` 纯函数（红线 1）；`settle` 只认 Evidence（红线 2）；接口与视图不得含领域词（红线 3）；`stable_dump` 前缀不变量（消耗红线）；`replay` 字节一致（红线 5 的审计基础）。

三基质的接口实现映射：

| 接口 | 解牛图（黑板） | 阡陌（git） | 榷场（市场） |
| --- | --- | --- | --- |
| submit | append 事件 | commit / PR | 挂单 / 报价 |
| adjudicate | commit 门校验 | pre-receive hook | 撮合规则 |
| snapshot | reduce(events) | tag / tree | 订单簿状态 |
| stable_dump | 规范序列化 | make views 产物 | 行情快照 |
| cas | 行锁 | update-ref 带旧值 | 保证金锁定 |
| settle | transition 事件 | main 合并 + CI 通过 | 结算清算 |
| replay | 重放事件 | clone + make views | 重放成交流 |

## 8. 路线建议

1. **M0 = 四契约 + 基质接口 + 阡陌实现**（黑板服务从基座消失；M0 周期从 2–3 周缩至数天～1 周）
2. **M1 = 瘦基线对照 + 消融**（不变：ΔPassRate ≥ +10pp、成本 ≤ 3×、单机制消融 3pp/−20% 门槛）
3. **M2+ = 擂台与判例包**（策略/记忆增强，挂在阡陌上）
4. **规模化研究 = 榷场**（第八阶段上千 worker 前启动；先做"EV 排序退化形态"再上完整市场）
5. **黑板（解牛图）降级为参考实现**：保留设计文档与绿地 Ledger 规格，作为基质接口的第一个验证实现（或对照实现）

## 9. 对立场层的修订（本文产生的变更）

| 原立场 | 修订为 | 依据 |
| --- | --- | --- |
| 唯一写入者是确定性图服务 | 唯一写入者是确定性 commit 门（基质无关，接口 adjudicate） | 本文 §0/§7 |
| 五契约含 Ledger/Worker Adapter/预算账本 | 四契约（TaskSpec/Judge/Evidence/Executor）+ 基质接口；预算=TaskSpec 标量+Executor 硬门+Records 查询；Worker Adapter=外壳 | 绿地裁决 + 本文 |
| 证据梯 E0–E3d/X 六级 | 节点 tier 三分（claim/reviewed/verified）× 判官 L0–L4 + 终态二分（goal_verified / answered_unverified）；证伪传播=投影规则 | 绿地裁决 |
| 司南是调度器 | 司南=榷场在零流动性下的退化形态；调度器与市场是同一机制的两种参数化 | 本文 §3.2 |

## 10. 开放问题

1. 阡陌的 ref 竞争热点在多大并发下成为瓶颈？（M2 压测：50 并发 worker 认领行为）
2. views 派生索引（SQLite）的失效策略：每次 commit 全量重建 vs 增量？
3. 榷场的保证金经济学：押注比例、失败罚没的去向（池 / 复盘基金）？
4. 判例的类比检索在跨域时的退化行为（CTF 判例对运维任务的价值）？
5. 基质接口是否需要 `fork()` 语义（子任务=子仓库 vs 单仓库子目录）？绿地开放问题 3 的延续。
