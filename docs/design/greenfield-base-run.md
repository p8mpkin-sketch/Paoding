# 绿地对照运行：「庖丁」基座设计（无预设推导）

> **实验设置**：2026-11-17。由全新上下文的子智能体（未读 v0、未读立场层、未读本对话）仅依据「问题定义 + 调研证据浓缩（11 条）+ 五条红线」从零推导。禁止联网与读文件，0 次工具调用，纯推理产出约 5600 字。
> **用途**：与 `architecture-v0.md`（含 v0.1 修订）做收敛/发散对照。收敛 = 双重验证；发散 = 三方仲裁清单。
> **注意**：本产出未受我方立场层约束，其切分方案与术语（TaskSpec/Ledger/Evidence/Judge/Executor）为独立推导结果，不代表已采纳。

---

## 1. 基座切分决策

**推导起点**：从五条红线反推基座必须固化的东西。红线 2（反幻觉）要求存在一个内容寻址的产物层；红线 1（写入路径无模型）要求存在一个由确定性代码把守的共享状态层；「先找判官」的哲学与红线 5（诚实对照）要求 Goal 的判定机制是独立可分发、可版本化的单元；红线 3 要求领域以插件形态注入，即存在能力注册与授权的执行层；证据 4 要求上下文装配受物理约束（前缀稳定）而不只是策略。这五个"必须"互相不可合并推导（见下），得出五契约。

**候选方案对比**：

| | 甲：三契约 | 乙：五契约（选定） | 丙：七契约 |
|---|---|---|---|
| 构成 | Mission（任务+判定合一）/ Log（证据+状态合一）/ Runner | TaskSpec / Judge / Evidence / Ledger / Executor | 乙 + Context + Budget 独立 |
| 优点 | 最薄，M0 最快 | 每契约一个不可合并的"必须"；信任边界清晰 | 职责最细 |
| 致命缺点 | 判官被降格为任务字段：领域包的主体就是判官（测试套件、验证脚本），合并使领域包与任务定义耦合；证据与状态机合一后，审计/评测无法绕过状态机直接验证据 | — | Context 是策略密集层 [证据9]，做成契约会把会被吃掉的东西焊进内核，违反删简律；Budget 无独立生命周期，是 Executor 与 TaskSpec 的标量维度 |

**决策日志**：
- 否甲：判官需要独立信任根（代码内容寻址、独立沙箱、独立版本），不是任务描述的属性，是任务的对端。医学场景中判官形态（评审面板计票）与 CTF（脚本比对）完全不同，必须可插拔 [证据10]。
- 否丙：上下文装配器必须可整体替换（下一代模型可能不需要复述计划、不需要下钻 [证据9]），基座只固化其物理约束（前缀不变量，挂在 Ledger 契约内），不单列契约。
- 选乙。判定依据：红线 1/2/3 的落点各不相同（状态机/对象库/执行授权），强行合并 = 一个契约守多条红线，改一处动全身。

## 2. 基座总览

```
            ┌─────────────────── 外壳（可整体替换，不在基座内）──────────────────┐
            │ 编排策略(单写者+只读worker) │ 上下文装配器 │ 审查模板 │ 领域插件包   │
            │   (judge包/tool包/kind扩展/goal模板)          [全部 T-1]           │
            └──────▲───────────────────────────▲─────────────────────────────┘
                   │ 快照+stable_dump(只读)     │ propose(节点提案/工具调用)
  ┌────────────────┴───────────────────────────┴───────────────────────────────┐
  │                     基座 paoding-base v0（五契约，确定性）                    │
  │ ①TaskSpec ──判定绑定──> ②Judge ──verdict(Evidence化)──┐                     │
  │    │ origin/goal/预算/工具白名单                        ▼                   │
  │    ▼            ┌──────────────> ④Ledger(append-only事件链)                 │
  │ ⑤Executor ──────┘   commit门(纯函数校验) ──reduce──> 世界观快照               │
  │    ▲ 调用              │引用完整性                      │stable_dump          │
  │  沙箱+权限门+预算熔断    ▼                              ▼(前缀不变量)         │
  │        └──────> ③Evidence(内容寻址对象库: Blob+执行Record)                   │
  └─────────────────────────────────────────────────────────────────────────────┘
```

**数据流（一轮循环）**：① 装配器（外壳）读 Ledger 快照的 stable_dump（前缀复用保 KV-cache [证据4]）构造 prompt → ② 模型输出仅两类：节点/边提案、工具调用 → ③ 工具调用过权限/预算门，Executor 在沙箱执行，产出 Evidence（执行 Record + 产物 Blob）→ ④ 提案过 commit 门（确定性校验）写入 Ledger → ⑤ 触发或周期性运行判官链，verdict 亦 Evidence 化后写入 Ledger → ⑥ 存在 PASS 且 tier 达标的 verdict 时，基座将任务迁移至 `goal_verified`。模型在整个环中只能产生字节（进 Evidence 或作为提案），**任何状态迁移由规则代码执行**。

## 3. 各契约详设

### 3.1 TaskSpec——任务契约 [T-0]

回答"起点在哪、终点如何判定、花多少钱、可用什么"。Origin 与 Goal 都是内容寻址锚，任务定义本身可审计。

```json
{
  "spec_version": "paoding/v0",
  "task_id": "t_01H...",
  "origin": { "snapshot_ref": "sha256:...", "description": "仅阅读用" },
  "goal": {
    "statement": "自然语言，仅供模型阅读，不参与判定",
    "verdict_tier_required": "L1",
    "judge_chain": ["j_screen@1", "j_final@1"]
  },
  "budget": { "usd": 20.0, "wallclock_s": 7200, "events_max": 5000 },
  "tools": ["http_probe@1", "shell@1"],
  "plugins": ["pkg_web@0.3"],
  "info_structure": "full_information"
}
```

- **判定等级表**（本基座核心决策之一，综合证据 3/9/10）：`L0 proof`（形式验证）> `L1 test`（可复现测试/PoV）> `L2 metric`（指标恢复到阈值）> `L3 panel`（多模型独立评审+确定性计票）> `L4 human`。`goal_verified` 终态仅当 verdict tier ≥ `verdict_tier_required` 且该要求 ≤ L2；L3/L4 判定只能置 `answered_unverified` 终态。理由：不完全信息问题（医学、部分运维）常无强判官 [证据10]，若不允许弱判定终态，用户会绕过基座；若允许弱判定冒充达成，则红线 2 失效。终态二分是唯一诚实解。
- **判官保密**：Goal 谓词常含秘密（如答案哈希）。`snapshot_ref`/判官 `args` 支持 `vault:` 引用，仅在判官沙箱内解引用，TaskSpec 与模型可见层不含明文（走查 5.1 暴露此缝隙后补入）。
- `info_structure`（full_information / sequential_decision，对应证据 10 两范式）：**[T-1]** 可选字段，仅供外壳选编排模板，模型自己判断结构可能更好。
- 备选对比：Goal 用纯自然语言（否，判定不可复现）；Goal 用 DSL 内嵌（否，DSL 会膨胀成领域语言，违反红线 3）。选定"自然语言陈述 + 判官代码引用"二分离：语义给模型读，判定给代码跑。
- **验收**：同 TaskSpec 双机解析字节一致；goal 的 judge_chain 中任一判官 code_ref 变更 → task_id 失效；预算字段缺省拒绝创建。

### 3.2 Judge——判定契约 [T-0]（框架）；链调度策略 [T-1]

判官是领域包的第一主体。「发现便宜、证明昂贵」[证据3] 固化为判官链：便宜筛选判官在前，昂贵确证判官按需触发。

```json
// Judge manifest
{ "judge_id": "j_final@1", "code_ref": "sha256:...",
  "tier": "L1", "cost_est": {"usd": 0.01, "wallclock_s": 30},
  "sandbox": {"fs": "ro:evidence", "net": "none", "secrets": ["vault:..."]},
  "input": "evidence_refs", "output": "Verdict" }

// Verdict（判定过程本身入 Evidence，留证 [证据7 ARTEX]）
{ "run_id": "...", "judge_id": "j_final@1",
  "status": "PASS | FAIL | INCONCLUSIVE", "tier": "L1",
  "basis_refs": ["sha256:..."], "details_ref": "sha256:..." }
```

- 判官本体 = 确定性代码于独立沙箱执行，只读 Evidence 挂载、断网、可解引用 vault 秘密。L3 panel 判官的实现 = 确定性驱动代码调 N 个模型（各模型输出入 Evidence）+ 确定性计票——模型"投票"是产生字节，计票与写入是代码，红线 1 不破。
- **verdict 缓存**：同 (judge_id, basis_refs 集合) 不重复执行，结果复用。判定预算目标 < 总预算 10% [假设，M1 验证]。
- 备选对比：判官进内核硬编码（否，违反红线 3）；判官即模型提示（否，直接违反红线 2）。选定外置代码 + tier 诚实标注。
- **验收**：tier 伪造测试——L3 判官 PASS 不能置 goal_verified（基座在 transition 门硬拒）；判官沙箱断网测试；同输入重放 verdict 字节一致。

### 3.3 Evidence——证据契约 [T-0]

反幻觉不变量的物理载体。对象库两类对象：Blob（任意字节）与 Record（执行记录）。**无 Record 的观察不得进入任何 prompt；模型生成的文本永远不是 Evidence**——这是对 soliloquizing（48.4% 轨迹自造观察 [证据6]）的架构级封堵。

```json
// objects/<sha256>；Record 本身也是 Blob
{ "kind": "tool_run | judge_run | budget_event",
  "task_id": "...", "tool_id": "shell@1", "args_ref": "sha256:...",
  "exit": 0, "stdout_ref": "sha256:...", "stderr_ref": "sha256:...",
  "sandbox_id": "...", "ts": "…", "artifacts": ["sha256:..."] }
```

- 大对象（>1MB）只存哈希+字节范围引用，防存储与 token 双膨胀（成本影响约 +5% 存储，换审计完整性）。
- 备选对比：结构化数据库存证据（否，字节级内容寻址才有跨机可复现性，数据库是可变状态）；全文入上下文（否，即下钻机制缺失）。
- **验收**：同字节同哈希、跨机一致；无 provenance 的"观察"注入测试被基座拒绝；删除任一对象后快照 reduce 必须报引用断裂。

### 3.4 Ledger——黑板契约 [T-0]（append-only + commit 门 + 前缀不变量）；kind 分类学与下钻 [T-1]

借鉴黑板系实践 [证据7]：append-only 事件链 + 确定性 reduce + 三层下钻防上下文浪费 + 保留错误轨迹 [证据4]。与 Cairn/sapper-v2 的差异：写入门必须是纯函数（红线 1），原语核心字段封闭、kind 开放（领域插件可扩展 kind，但 Node 结构本身不可变）。

```
Event := {"seq":n, "prev":"sha256:…", "ts":t, "body": Body}
Body  := {"t":"node_propose","node":Node}          // 模型(经装配器)提案
       | {"t":"node_commit","node_id":id}           // 仅基座写：校验通过后
       | {"t":"node_reject","node_id":id,"why":code}// 拒绝留痕[证据4]
       | {"t":"edge","edge":Edge}
       | {"t":"claim_upgrade","node_id":id,"refs":[…]}  // claim→verified 需 refs 非空
       | {"t":"judge_verdict","verdict":Verdict}
       | {"t":"goal_refine","new_goal_ref":"sha256:…","approved_tier":"L4"}
       | {"t":"transition","from":S,"to":S}
S ∈ {open, running, goal_verified, answered_unverified, budget_exhausted, aborted}

Node := { "id":"n_…",
  "kind":"question|hypothesis|finding|plan|obstacle|deadend|<plugin>",
  "title":"≤80字符恒定短字段",           // 一切投影必含
  "tier":"verified | reviewed | claim",  // verified ⇔ refs 锚定≥1真实执行产物
  "plausibility":0-100,                  // 仅 hypothesis；排序策略在外壳[T-1]
  "refs":["sha256:…"], "body_ref":"sha256:…" }   // 按需下钻[证据7]
Edge := {"from":id,"to":id,"rel":"supports|contradicts|depends_on|enables|refines"}
```

- **commit 门（红线 1 落点）**，纯函数校验：schema 合法；refs 每个哈希存在于对象库（引用完整性）；seq/prev 链连续；events 配额未超；transition 规则（goal_verified 仅当存在达标 verdict）。拒绝写 node_reject。**准确表述反幻觉不变量**：基座保证"verified 节点可追溯至真实执行产物"（锚定），"证据是否真支持命题"（支持度）由判官/审查者判定——语义校验不进基座。
- 冲突不删除：contradicts 边共存，deadend 节点保留（模型自我纠错需要错误轨迹 [证据4]）。
- **stable_dump（前缀不变量，[T-0]，物理约束而非能力补丁）**：`dump(世界观_n)` 是 `dump(世界观_{n+1})` 的字节级前缀；字段序固定、键排序、规范换行。这是 KV-cache 命中率——第一生产指标 [证据4]——的架构保证，装配器违反前缀复用视为实现缺陷（CI 强制）。
- 备选对比：Cairn 五原语直译（否，Hint/Intent 语义重叠且无校验边界）；双部认知图 claims+links（否，缺 plan/obstacle 等决策状态，运维场景表达不了）。选定统一 Node/Edge + 开放 kind。
- **验收**：跨机重放同事件流 → 快照字节一致；引用不存在拒收；dump 前缀稳定性回归测试；双提案并发 → 后到者 seq 冲突被拒。

### 3.5 Executor——执行契约 [T-0]

沙箱与权限是必选项 [证据11]（技能市场 12–20% 恶意指令、沙箱逃逸事件），预算是显式约束 [证据11]（带预算 $2400 达 79.9% vs 无预算 $7850 达 78.6%）。

```
Tool := {"tool_id":"shell@1","code_ref":"sha256:…",
         "caps":{"fs_ro":[…],"fs_rw":[…],"net":[…],"proc":true},
         "cost_model":{"usd_per_call":0,…}}
invoke(tool_id, args, ctx) -> Record    // 失败也是 Record（留痕）
```

- 门序：caps ⊆ TaskSpec 授权 → 预算先行扣减（不足即拒，不执行）→ 沙箱执行 → 强制产出 Record。熔断时任务转 `budget_exhausted`，已获 Evidence 与快照照常导出（审计不因熔断丢失）。
- 备选对比：信任模型自律（否 [证据11]）；全局能力不做任务级白名单（否，最小权限）。cost_model 精细化 [T-1]。
- **验收**：越权工具调用被拒；预算耗尽熔断且产出 budget_event Record；沙箱内文件逃逸测试。

### 3.6 外壳挂点（非基座，标注可拆除）

编排（单写者+只读子智能体、生成者+干净上下文审查者 [证据5]，M0 用约百行主循环 [证据1]）、假设排序与信息增益选动作策略 [证据10]、prompt 模板、复述计划技巧 [证据4]、领域包。全部 [T-1]。

## 4. 对抗性自检（影响×概率排序）

1. **判官欺骗/判定材料被篡改**（影响：全盘，概率：高——求解压力下模型必然尝试改测试、伪造提交）。对策（完整）：判官代码 content-addressed 且与 TaskSpec 哈希互锁；判官只读 Evidence 快照而非活文件系统（模型改掉工作区测试文件不影响判定，判官跑的是 Evidence 里的原始测试）；判官断网独立沙箱；verdict 自身 Evidence 化可审计。
2. **幻觉以 claim 面目混入 verified 投影**（影响：高，概率：高——48.4% 轨迹有自造观察史 [证据6]）。对策（完整）：tier 三分硬隔离，投影器只取 verified；claim→verified 唯一路径是 claim_upgrade 事件且 refs 非空且哈希存在于对象库；装配器渲染 claim 时强制带 `[未锚定]` 标记；L3 审查通过最多升到 reviewed。
3. **前缀不稳定导致 KV-cache 失效、成本爆炸 10×**（影响：高，概率：中——stable_dump 实现极易无意破坏前缀，如时间戳渗入）。对策（完整）：时间戳等易变字段排除出 dump；增量 dump 由基座生成（装配器不得自行序列化快照）；CI 用「第 n 轮 prompt 必须是第 n-1 轮前缀」的黄金测试锁死。
4. **预算耗尽于昂贵判定循环**（中×中）：判官链分级 + verdict 缓存；判定成本占比纳入 M1 监控。
5. **黑板退化为无结构流水 / 节点洪泛**（中×中）：events_max 配额 + title 短字段强制 + 下钻；接受部分退化（无预设角色是特性 [证据7]）。
6. **多智能体失配**（中×高，37% 失败率 [证据5]）：M0 固化单写者+只读 worker 形态于外壳模板，写路径唯一。

## 5. 纸面走查

**5.1 CTF web 题**：领域包注册 `flag_submit` 工具与 `j_flag` 判官（tier L1，持 `vault:flag_hash`）。Origin.snapshot_ref = 环境描述+初始可观测响应集。模型侦察：invoke http_probe → Record（请求/响应 Blob）→ 提案 Node{kind:finding, tier:claim, refs:[响应差异]}「参数 X 存在注入」→ 二次验证调用产生对照 Record → claim_upgrade。提交流程：invoke flag_submit(candidate) → Record → 触发 j_flag → basis_refs 指向提交 Record → PASS(L1) ≥ required → 基座置 goal_verified。**暴露缝隙两处**：判官须保密（→ vault 机制，已补入 3.1/3.2）；判定材料须防活文件篡改（→ 判官只读 Evidence 快照，已补入 3.2）。均已在契约层修复，无缝隙遗留。

**5.2 运维根因分析**：Origin.snapshot_ref = 告警事件+授权访问声明+初始监控查询 Record（不能快照生产环境，快照锚定的是"环境描述+初始观测"，够审计即可）。难点：Goal 初始不可完全形式化（不知"根因"谓词长相）。流程：模型建 hypothesis 节点集（带 plausibility 排序，贝叶斯式更新策略在外壳 [证据10]）→ 选信息增益/成本比最高的查询 → invoke metrics_query → Record → edge supports/contradicts → 收敛。Goal 处理：初始 Goal 为弱形式（`j_rca` 判官 tier L2：同一根因在受控重放下指标恢复）；若任务中途发现 Goal 表述错误 → `goal_refine` 事件一次性重定义，须 L4（human）批准——初始 Goal 不可改写，只能追加 refinement 事件，审计链不断。终态可能是 answered_unverified（panel 级根因结论）+ 建议的复现实验作为后续 TaskSpec。**暴露缝隙**：goal_refine 与 hypothesis 有序集均为原设计所无，走查后补入 Ledger 契约。

**通用性自检**：两走查复用同一套 schema 与状态机；`flag`、`靶机`、`根因` 仅出现于领域包与走查叙述，契约字段全为通用认知词（question/hypothesis/finding…）。通过。

## 6. 消耗预算与 M1 目标

**指标**：效率 E = ΔPassRate(pp) / CostMultiplier，CostMultiplier = cost(庖丁) / cost(瘦基线)。瘦基线 = 仓库内一等公民：单个成熟编码 CLI 直接做题，每次评测必跑 [红线5]。

各机制成本影响：Evidence 全留存约 +5% 存储；判官链目标 < 总预算 10%（筛选判官 ~$0.01/次，确证按需）；stable_dump 换 KV 命中率 >70% [假设]；三层下钻预期上下文 −40% [假设]；诚实对照使评测成本 ×2（必付）。

**M1 目标**：两个基准（CTF 子集 50 题 + 故障注入运维集 20 例）：ΔPassRate ≥ +10pp 且 CostMultiplier ≤ 3.0。任一机制（判官链/下钻/stable_dump）消融实验须独立证明 ΔPass ≥ 3pp 或成本 −20%，否则拆除 [红线4/5]。赢不过薄外壳+强模型的结构整体删除。

## 7. 开放问题

1. **判官信任根**：judge_ref 可信度由谁背书？选项：a) 内容寻址+人工白名单源；b) 声誉市场。倾向 a（M0/M1），恶意技能占比 12–20% [证据11] 时期不宜开放市场。
2. **claim→verified 的 L3 升级**：是否允许 reviewed 视同 verified 用于后续推理？倾向否——保持三 tier 硬隔离，宁可投影保守。
3. **Ledger 分区/分支**：小时级任务 [证据8] 单链会否过长？倾向 M0 单链 + 子任务=子 TaskSpec（天然分区），分支留 M1。
4. **stable_dump 与模型上下文格式耦合度**：dump 格式由基座定死还是装配器可选（需声明）？倾向基座定死一种（M0），杠杆证据 [证据2] 表明格式影响 10–30pp，但属策略，M1 做对照实验后决定是否下放。
5. **判定等级表的边界**：L2 metric 的阈值由谁定（任务发起人 vs 领域包）？倾向领域包提供默认、TaskSpec 可收紧不可放松。
