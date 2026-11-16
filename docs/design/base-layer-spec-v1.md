# 庖丁基座规格 v1.1

> 状态：提案（2026-11-17）。v1.0 见提交 df86c02，相对它的变更列在目录之前。
> 输入：[调研 v2](../research/agent-architecture-survey-v2.md)（[S#]/[Z#] 编号以其为准）、架构 v0 上传稿、任务书 §3.2 所列 v0.1 立场。v0.1 修订稿不在远端任何分支上，本文没有读到其正文；如与其冲突，以人的裁决为准。
> 论断标注：`[证据 S#/Z#]` 有调研来源；`[假设]` 待 M0/M1 验证；`[观点]` 作者判断；`[待核]` 来源未能一手核对。
> 结构标注：`[T-0]` 当前必要，且模型再强也需要；`[T-1]` 下一代模型可能吃掉，必须放外壳并带开关。
> 瘦基线：按任务书红线 5，取单个 Claude Code 会话。文中"该 CLI"均指它，M0 的 Worker 后端也用它（3.4.2）。

相对 v1.0 的变更，人可以逐条否决：

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

3.1 节的等级函数与消费门另有一份可运行的[参考模型](reference-model/README.md)（47 条测试，含坏事实注入、环状引用、伪造引用的前四种形态，以及两个走查的逐步核对）。建模时澄清了四处含糊，已写回正文：人的裁决如何驳回反证、`tests` 以 Intent 是否达成为准、失效集合的定义、`grounds` 不收 authored 类。

## 目录

1. [约束审计](#1-约束审计)
2. [基座总览](#2-基座总览)
3. [契约](#3-契约)（3.1 解牛图 · 3.2 Artifact 仓库 · 3.3 判官 · 3.4 Worker Adapter · 3.5 预算账本 · 3.6 执行层）
4. [三个机制](#4-三个机制)
5. [对抗性自检与其它自检](#5-对抗性自检与其它自检)
6. [两个走查](#6-两个走查)
7. [路线图与 M0 实施清单](#7-路线图与-m0-实施清单)
8. [消耗预算与 M1 目标](#8-消耗预算与-m1-目标)
9. [术语表](#9-术语表)
10. [开放问题](#10-开放问题)

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

---

## 2. 基座总览

基座 = 一条事件日志 + 一个确定性裁决器 + 四个插拔接口（判官、Worker Adapter、执行层、Blob 存储）。

三条主线贯穿全文：

- **判据先行。** Goal、带判据的 Intent（r2 动作的预测是其中一种）、M1 的达标线，都在动手之前登记，之后不可改。证据梯只认登记过的判官；带判据的 Intent 把题目沿可判定的关节切开。
- **结构自识。** 画像、执行容器的能力、调度形态、任务包里列出的锦囊，都由题目的判官与授权范围确定性地推出，不由人逐项填写，也不由模型自报。这是任务书"先识别问题结构，再决定解法形态"的机械形式。
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
```

数据流：

1. 人用 `pd problem open` 提交 Problem：授权范围（每条规则自带风险等级）、Goal 判据、预算。图服务据此算出画像。
2. 司南读 `/work`（图服务派生的可做事项），申请租约，同时预留预算。
3. 按租约起一对容器：模型容器归 Adapter，执行容器归执行层。CLI 在模型容器里运行，只有文件工具和三个代理工具，没有命令执行能力；它的模型请求经容器外的端点代理发出，密钥与计量都在那里。
4. 命令经 `exec` 在执行容器里运行。输出由执行层登记为 `exec` 类 Artifact，模型拿到的是截断后的输出和引用。
5. Worker 用 `submit` 提交结论。图服务当场确定性校验并追加事件；等级、预算、可做事项随之重算。
6. 需要判定时，判官运行器另起洁净的执行容器重放，提交裁决。
7. 哮天犬只做四件事：过期租约、超预算终止、清理孤儿容器、健康告警。

结构清单与成本影响：

| 结构 | 标签 | 成本影响 | 开关或消融臂 |
| --- | --- | --- | --- |
| 事件日志 + 确定性裁决 | T-0 | 无模型成本，毫秒级 | 无 |
| 出处类别与可采信检查 | T-0 | 无 | 无 |
| 模型容器与执行容器分离、代理工具 | T-0 | 每条命令多一跳，毫秒级；外壳税待测（B1b） | 无 |
| Goal 判官、重放判官 | T-0 | 每次一个洁净容器，秒到分钟，不耗 token | 自动重放的成本阈值 |
| 预算预留、硬顶、哮天犬 | T-0 | 无 | 无 |
| 授权范围、按风险注入能力、审批门 | T-0 | 人的等待时间 | 无 |
| 画像推导 | T-0 | 无 | 人可覆盖 |
| 归因表 | T-0 | 无，是日志上的投影 | 无 |
| Bootstrap 先瘦后厚 | T-1 | 易题上成本倍数约为 1 | `bootstrap_share` |
| 带判据的 Intent | T-1 | 每次判定一个洁净容器，不耗 token | `checked_intents=off` |
| 80% 续期门 | T-1 | 没有进展的题最多少花题预算的 20% [假设] | `extension=always` |
| Reason 串行、只有它能加 Intent | T-1 | 每轮约 0.45 美元（强档）[假设]；增加延迟 | 可改为 Explore 自行提 Intent |
| E1/E2 模型复核与异构要求 | T-1 | 每条被消费的推断多 0.1–0.4 美元 [假设] | `ladder=binary`、`hetero=off` |
| 三层视图与缓存友好布局 | T-1 | 任务包变小；同批并发会话可共享前缀缓存，跨轮命中取决于后端能否设断点 [假设] | `view=full_dump` |
| 八仙扇出控制器 | T-1 | 决定预算花得多快；成本倍数的上界由题预算硬顶给出 | 固定并发 |
| 闲人 | T-1 | 固定占比，不超过题预算 10% | `idlers=off` |
| 模型分层 | T-1 | 同一题预算下 Explore 会话数约翻倍 [假设]，见 §8 | 全强档 |
| 通鉴与锦囊 | T-1 | 复盘每题约 0.5 美元 [假设]；后续题降本 | `kits=off` |

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
type Check  = { judge_id: string, spec_ref?: ArtifactId, expect?: object }   // expect 由判官解释

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

端点（M0 走本机 Unix socket）：

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
| `close_problem` | graph（Goal 到 E3 时自动）、watchdog（预算耗尽）、human | 状态合法 |

`budget_mark` 与 `alert` 由图服务在应用事件时自己追加，不接受外部提交。

拒绝码：`forbidden_op`、`unknown_ref`、`inadmissible_class`、`scope_mismatch`、`missing_evidence`、`stale_premise`、`conflict_leased`、`over_budget`、`quota_exceeded`、`schema_error`。

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

支持记录扩展为 `method ∈ {judge, review, human}`，并带 `premises`、`by {session, model_family}`、`context_manifest`（Adapter 记录该会话实际读到的节点与 Artifact，非模型自报）、`valid_until`（由判官的 `ttl_s` 算出）。等级全序为 E0 < E1 < E2 < E3d < E3。

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
| r2 不可逆 | E3；或 E2 以上并由人对该前提签署豁免 | 必需，一次批准只管一次租约；Intent 必须带判据 |

前提是带判据的 Intent 时，三档都要求它已达成。r2 的 Intent 在前提都不低于 E2 时进入 `needs_human`，批准与对前提的豁免在同一张卡片上给出。

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

第 3、4、7、9 条里只涉及等级与消费门的部分，已在参考模型上通过。

1. 重放确定性：同一日志重放两次，状态哈希相同。
2. 崩溃恢复：提议处理中 `kill -9`，重启后客户端重试，结果恰好一次。
3. **坏事实注入（对抗）**：构造 A（E3）；B 只由 A 推出；C 由 B 推出且另有独立的判官支持；D 只由 B 推出。让 A 的判官连续两次重跑失败。期望：A 为 X；B 与 D 回到 E0 并出现在 `invalidations` 结果里；C 保持 E3；以 B 或 D 为前提的 r1 Intent 变为 blocked，在途租约带 `premise_lost`。只失败一次时，A 回到 E0 并带 `unstable`，下游同样降级，但 A 不是 X。M0 只有判官支持，本用例的 M0 形态是：A 被证伪后，以 A 为前提的 Intent 变为 abandoned；A 只失败一次时，以它为前提的 r1 Intent 变为 blocked。
4. **环状引用（对抗）**：让 A 的支持以 B 为前提、B 的支持以 A 为前提。期望两者都停在 E0，重算在有限步内结束。M0 形态：节点和支持只能引用已存在的 id，环在构造上不可能；用例验证引用尚不存在的 id 返回 `unknown_ref`，并对随机生成的日志断言重算终止。
5. 并发租约：两个请求抢同一 Intent，恰好一个成功。
6. 权限：闲人角色提交 `add_intent`，返回 `forbidden_op`。
7. 审批门：没有 `approve` 的 r2 Intent 永远不出现在 `/work` 的 explore 列表里；它的租约过期后回到 `needs_human`，同样不出现。
8. 画像：授权范围含一条 r2 规则时 `profile.reversibility` 为 r2；`add_intent` 的 risk 高于范围内最高风险时被拒。
9. 带判据的 Intent：判据通过后状态为 achieved，等级为 E3，以它为前提的 Intent 由 blocked 变为 open；候选失败只累计次数。

#### 3.1.6 最简反事实

砍掉解牛图，Worker 之间不再共享任何东西，系统退化为等成本独立重试，也就是对照臂 Bk。把图换成一个共享笔记文件，就是对照臂 Bn。所以图的全部价值必须体现为"等成本下赢 Bk 和 Bn"，否则按红线 5 删除协作部分。即便如此，"证据账本"这部分（Fact、Support、判官裁决、审计日志）仍然保留，它是 T-0。

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
                      evidence: ArtifactId[]     // judge 类，由判官运行器登记
                      cost: Budget; recheck_at?: number }
```

```
interface Judge { run(req: JudgeRequest, sandbox: SandboxId): JudgeVerdict }
```

M0 自带两个判官。`replay`（判定性）：在洁净容器里放入候选产物，执行 `spec_ref`（没有规格时执行候选本身），按 `expect {exit_code?, stdout_contains?, stdout_regex?}` 比对。它对三种目标通用：观察的规格就是谓词；带判据的 Intent 与 Goal 的规格在创建时登记，候选在 `claim_done` 时给出。注册为 `require_touch` 时，运行过程没有访问任何授权资源、input 材料或挂入的可采信 Artifact，裁决为 `inconclusive(untouched)`；观察对象是外部资源时打开，纯计算时关闭，写在判官配置里。Goal 判官由 Problem 配置，M0 提供 `exact_match` 与一个提交接口的插件位。判官运行器是持有 judge 令牌的独立进程，从 `/work` 领取 judge 租约。注册表在 M0 是图服务启动时加载的配置目录；条目的 id、version、grade 在裁决时抄进支持记录，所以重放不依赖注册表文件。判官的成本以 `cost` 事件入账，计入验证池。

#### 3.3.3 完整版

`record_match`（不重放，只对已登记的输出求谓词。输出来自执行层的类型化只读工具、命令不由模型撰写时为判定性，否则为相符性，见 3.6.3）；延迟判官与复检；判据的有效期 `ttl_s`；模型面板（即编排好的 Verify 任务，产出复审类支持）；判官版本撤销；第二个领域的判官（如证明检查器、测试套件、指标断言）。

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
6. Worker 能否改动判官资产：判官所用的测试与配置以 input 类 Artifact 的哈希固定在 Problem 里，在 Worker 的两个容器中只读；改动后哈希不符，判官拒绝运行。
7. 翻转迟滞：对一条 E3 论断重跑判官。第一次重跑失败后等级为 E0 并带 `unstable`，`/work` 给出复判。复判再失败则为 X；复判连续两次通过则回到 E3。
8. 空谓词：重放规格只打印常量，`require_touch` 打开时裁决为 `inconclusive(untouched)`，等级不变。

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
tool submit(in: { ops: Op[], final?: Final })
           : { results: ({ ok: true, id: string, verdict?: "pass"|"fail"|"inconclusive" }
                        | { ok: false, code: RejectCode, detail: string })[] }
           // 逐条提交，后一条可用 tmp_id 引用前一条；判官在 30 秒内裁决时随返回值带回
tool show  (in: { id?: string, layer?: "summary"|"evidence", list?: "frontier"|"all"|"hints"|"budget",
                  artifact?: ArtifactId, range?: [number, number] }): object      // 只读

type Op =
  | { op: "add_fact", tmp_id?: string, claim_type: "observation"|"inference",
      title: string, summary: string, body_path?: string,
      check?: { judge_id: string, spec_path: string, expect: object, inputs?: ArtifactId[] },
      premises: string[], grounds: ArtifactId[] }
  | { op: "add_intent", title: string, summary: string, premises: string[],
      risk: "r0"|"r1"|"r2", budget_hint?: Budget, expected_gain?: number,
      done?: { judge_id: string, spec_path?: string, expect: object, max_attempts?: number,
               tests?: string[] },
      needs_scope?: object[] }                                                     // 仅 reason
  | { op: "abandon_intent", intent: string, reason: string }                       // 仅 reason
  | { op: "claim_done", target: string, candidate_path: string }                   // target："goal" 或 Intent id
  | { op: "request_judge", target: string, judge_id?: string }
  | { op: "add_support"|"add_contradiction", target: string, premises: string[],
      artifacts: ArtifactId[], note: string }                                      // 完整版：verify、idler
type Final = { outcome: "found"|"nothing"|"failed"|"unsolved",
               excluded_paths?: string[], suggestions?: string[] }
```

`*_path` 指工作区里的文件，由 Adapter 读出并登记为 authored 类。`claim_done` 不是内核操作：Adapter 登记候选，再提交 `request_judge`。工作区是模型容器与执行容器共同挂载的目录；input 材料与锦囊目录只读挂载。Reason 与闲人不挂 `exec`，也不起执行容器。

会话状态机：`leased → preparing → running → collecting → released`；异常出口是 `expired`、`killed(budget)`、`failed(原因)`。Adapter 每 60 秒续租一次，租约 TTL 为 120 秒。

Adapter 的职责只有五件：渲染任务包；在模型容器里起停 CLI，读它的事件流，只用于存档与存活判断；托管三个代理工具，`exec` 转给执行层，`submit` 转给图服务，`show` 读图服务；续租；释放租约并保存会话记录。模型容器的规格是固定的：CLI 镜像；工作区以不跟随符号链接的方式挂载；出站只放行工具端点与模型端点代理。代理在容器之外，做三件事：把任务令牌换成真实密钥；逐请求记下响应里的用量；任务超过预留额后拒绝它的新请求。所以两个容器里都没有模型密钥，外壳内部的辅助请求也在账上。

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
| 回合与花费上限 | `--max-turns`、`--max-budget-usd`（按客户端估算执行，可能略超） |
| 计量的对照 | 事件流里每步的 `usage` 与末行的 `total_cost_usd`（估算值）；记账以端点代理为准 |
| 终止 | SIGINT 结束当前回合；SIGTERM 终止进程树，退出码 143 |

#### 3.4.3 完整版

`verify` 与 `idler` 两个受限角色（操作白名单由图服务按租约角色强制，不靠提示词）；复审任务包不含目标论断的正文，`show` 对其拒绝读取，以保证干净上下文；第二、第三种 CLI 后端；自研薄循环的插槽 [证据 S3]。

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
5. 前缀稳定性：连续两次 Reason 的任务包，在只有新增节点的情况下，公共前缀不少于前一个包的 90% 字节。字节稳定是缓存命中的必要条件而非充分条件，所以集成测试另外断言：同一 `as_of_seq` 下先后启动的两个 Explore 会话，后一个的首次请求缓存读 token 数大于 0。
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
- **续期门**（T-1，开关 `extension=always`，M1 起）。进展 := 自 50% 标记以来，有带判据的对象新到 E3，即观察被重放确认，或带判据的 Intent 达成。越过 80% 标记时没有进展，`/work` 不再给出新的 explore，题目进入 human 项：人可以用 `pd extend <pid>` 放行，否则在途任务结束后按 unsolved 关闭，余下的预算不花。Goal 的判定不受此限。
- 任务的软线是预留额的 90%，硬顶是预留额；题的硬顶是 `cap`。硬顶由端点代理执行：超过预留额的任务，新请求被拒。后端自带花费上限时，Adapter 把预留额同时传给它，作为进程内的第二道线。
- 哮天犬是不含任何策略的脚本，每 10 秒读一次 `/budget`：任务越过软线，通知 Adapter 进入收尾轮；越过硬顶或题预算耗尽，终止进程、销毁容器。

#### 3.5.3 完整版

端点代理扩成模型网关，承担多厂商路由与故障回退 [证据 S15]。项目级预算与多题配额。按判官、按角色、按档位的成本报表。

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
6. 续期门（M1）：构造 50% 到 80% 之间没有任何对象新到 E3 的日志，越过 80% 后 `/work` 不给出 explore，题目出现在 human 项；`pd extend` 之后恢复。

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

M0 的题目只含 r0 规则，资源种类只有网络地址一种。

#### 3.6.3 完整版

资源插件提供的类型化只读工具（如指标查询、日志检索）：它们作为追加的代理工具出现，命令由执行层生成而不是模型撰写，输出登记时 `tool` 为工具名。专用工具比通用 shell 更可靠 [证据 S17]，`record_match` 也只对这类输出给判定性。此外：虚拟机隔离；r2 凭据按次签发、用后即废；请求频率上限；端点代理扩成模型网关。

#### 3.6.4 验收测试

1. 访问授权范围之外的地址：连接被拒，日志里出现 `scope_violation`。
2. 未经批准的 r2 Intent：即使被错误地调度，容器内也不存在对应凭据。r0 Intent 的容器里没有 r1 规则放行的通路。
3. 判官容器与 Worker 的执行容器互不可见：Worker 写入的文件在判官的洁净容器里不存在。
4. 两个容器里都读不到模型密钥；执行容器连不上模型端点；模型容器连不上授权范围内的目标。

#### 3.6.5 最简反事实

砍掉它，"越界动作直接拒绝并记录"没有执行点，审批门退化为提示词里的一句话，证据也回到由模型一侧转述。保留最小形态。

---

## 4. 三个机制

### 4.1 司南（调度）

司南是一个不含模型、不持有权威状态的循环。调度所需的判断来自图服务推出的画像和 Reason 写进 Intent 的字段，司南只做排序、限流和启动。

```ts
type WorkItem = { kind: "bootstrap"|"reason"|"explore"|"judge"|"verify"|"idler"|"retro",
                  target?: string, est: Budget, risk?: "r0"|"r1"|"r2", expected_gain?: number,
                  reflect?: boolean }            // 仅 reason：预算复盘期由图服务置位
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
| 闲人（完整版） | 不带支持的 `add_fact`、`add_contradiction` | 定时，花费不超过 `idler_share` | 1 到 2 |
| 复盘（完整版） | Playbook 候选 | 题目关闭后 | 1 |

M0 只有三条规则：

1. **先瘦后厚。** 题预算默认取瘦基线单题上限的 3 倍，`bootstrap_share` 默认 1/3，所以 Bootstrap 的预算正好是一次完整的瘦基线运行。它的提示词是瘦基线的提示词加 `submit` 的说明，工具面与对照臂 B1b 相同。易题上成本倍数约为 1；同模型、同预算之下，庖丁的解题率在期望上不低于 B1b，它与 B1 的差距就是外壳税（8.3）[观点]。
2. **Reason 互斥，有触发才运行。** ARTEX 的 Planner 是同样的形态：唯一的意图生成者，事件驱动，防抖唤醒，每次全新会话 [证据 Z5]。
3. **Explore 固定并发 3**，按 Intent 创建顺序认领。

完整版的扇出控制器（八仙，T-1，开关为"固定并发"）是 `plan` 里的一张规则表：

| 输入（画像、Intent 与预算） | 规则 |
| --- | --- |
| info=partial | 广度优先：并发 3 到 5，按 `expected_gain ÷ budget` 降序；共享同一前提的 Intent 同时最多 2 个 |
| info=complete | 深度优先：并发 1 到 2，沿依赖链推进；对卡住的 Intent 开 `race_k` 条策略正交的路线，先过判官者胜，其余取消 [证据 S15][S16] |
| judge=hard 且判官廉价 | 放宽并发上限，候选交判官筛 |
| judge=deferred 或 none | Explore 并发不超过 2，`verify_share` 上调 |
| Intent.risk=r2 | 并发 1；必须已审批 |
| Intent 带判据 | 同等条件下优先，排序改用 `expected_gain ÷ (budget + 判官成本)`：它的结果由判官给出，不靠会话自报 [观点] |
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
```

`hint` 事件产生一个 Hint 节点（类型见 3.1.2，`--node` 写入 `about`）。它有三个效果，都不涉及等级：`/work` 立即给出 reason（司南按 `hint_debounce_s` 防抖）；此后渲染的任务包把未关闭的 Hint 放进 `focus.hints`；`pd status` 列出每条 Hint 之后新增的 Intent。Hint 不是证据，不能作前提；人要断言一件事实，走 `rule` 或补充 input 类材料。M0 不向在途会话注入 Hint，与 Cairn 的"下次读取时吸收"一致 [证据 Z3]。

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
  explore:   {tier: mid, escalate: {to: strong, after_failures: 2}}
  verify:    {tier: mid, family: "不同于被复核论断的提出者"}
  idler:     {tier: cheap, family: "优先不同于 explore 所用的家族"}
  retro:     strong
```

1. M1 首轮所有角色与瘦基线用同一个模型，先隔离出架构本身的效果。分层是此后单独的一条消融臂。
2. 上分层之前先测更简单的替代：强档模型调低推理强度。厂商文档建议先量这一项再做多模型级联，并指出缓存按模型隔离 [证据：厂商 API 文档，不在调研编号内]。
3. 一个会话自始至终只用一个模型，中途换模型会使该会话的缓存整体失效（出处同上）。
4. 同一 Intent 在中档失败两次后升到强档重做，即弱模型向强模型求助 [证据 S44]。
5. 多厂商路由与故障回退放在模型网关 [证据 S15]，它由 M0 的端点代理扩展而来。"异构"用本文件登记的 `family` 判定，不看模型名。
6. 判官是程序，不占模型预算。

### 4.3 通鉴与锦囊

锦囊是按 SKILL.md 约定组织的目录 [证据 S42]：元数据常驻任务包第③段，正文按需读取。领域词只允许出现在锦囊与判官配置里。通鉴是跨题的锦囊库加一张使用记录表。M0 没有这部分，M1 只做人工复盘，管线放在 M4。

```
题目关闭 → 复盘任务（只读日志与图）→ Playbook 候选（authored 类；每一步必须引用本题的 E3 论断）
        → playbook_proposed → 人审 → kit_published（目录按内容寻址并签名）→ 进入 kit_index
使用：Worker 读取锦囊正文时 Adapter 记 kit_loaded{kit, task}；题目关闭时归集每个锦囊的使用题数与解出题数
```

```ts
type Playbook = { id: string; title: string
                  applies_when: string                            // 适用条件，自然语言，内核不解释
                  steps: { text: string, cites: string[] }[]      // cites：来源题中 E3 论断的 id，不得为空
                  source_problem: string; body_ref: ArtifactId    // authored 类
                  status: "proposed"|"published"|"retired"
                  kit?: { name: string, hash: string, signature: string } }   // 发布后所在的锦囊
```

- **按结构取用。** 锦囊的元数据可以声明 `applies_to {judges?, resources?}`。Adapter 渲染任务包第③段时，只列出与本题的判官或资源种类有交集的锦囊，以及没有声明的通用锦囊。匹配是字符串相等，不调用模型，也不进内核。
- **淘汰。** 使用不少于 5 题且胜率低于同期整体胜率，或连续 3 题加载后未解出，标为待复核，由人确认后 `kit_retired`。这个统计有选择偏差（难题更容易触发加载），所以自动规则不直接下架；整体收益用 `kits=off` 消融臂衡量。
- **防投毒。** 来源只限本项目自己的日志，不接第三方技能市场，公开市场有 12% 到 20% 的条目含恶意指令 [证据 S34]。无法追溯到 E3 论断的步骤在发布时被确定性检查拒绝。发布要人审并签名，锦囊目录在 Worker 的两个容器里只读，加载时校验哈希。内核只认识锦囊的名称、哈希、描述三个字段。

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
- 带判据的 Intent 有同样的缺口：判据对 Worker 可见，候选由模型撰写。所以它的达成只用来放行依赖和计算进展，不进入 Goal 的判定。
- 兜底：Goal 判官不读任何中间论断。被夸大的 E3 论断与虚假的达成会浪费预算，但造不出假的 Goal 达成。
- 度量：M1 抽样审计 E3 观察类论断，统计标题超出谓词的比例。

**场景 3：判官被骗。**

- 资产固定：判官用到的测试、断言与配置作为 input 类 Artifact，以哈希写进 Problem；它们在 Worker 的容器里只读，判官运行前校验哈希。
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

检查出四条隐含假设：

| 隐含假设 | 在哪里不成立 | 处理 |
| --- | --- | --- |
| 环境可以重置到基线 | 运维、临床 | `record_match` 与延迟判官不需要重置；判据带有效期；M0 只承诺可重置的环境 |
| 动作都是容器里的命令 | 需要人去做的检查或操作 | 人执行的 Intent，结果作为 input 类材料回到图里（3.1.3） |
| Goal 是单个谓词 | 数学的引理链、工程的多项验收 | 带判据的 Intent 互为前提，连成链（3.1.2） |
| 观察能写成退出码与输出的谓词 | 证明检查、影像判读 | `expect` 由各判官自行解释，内核不看 |

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

### 5.5 三个机制与证据梯的最简反事实

各契约的结论见 3.x.6。其余六项：

| 对象 | 砍掉后退化为 | 结论 |
| --- | --- | --- |
| 扇出控制器 | 固定并发的循环，即 M0 形态 | M2 消融决定 |
| 模型分层 | 全部同档，即 M1 首轮形态 | M2 消融决定 |
| 通鉴与锦囊 | 没有跨题记忆 | M4 之前不建管线 |
| E1 与 E2 两级 | 二值证据（E0 与 E3） | M1 的 `ladder=binary` 消融决定 |
| 带判据的 Intent | 只有 Goal 一个判据，子任务完成与否由会话自报 | M1 的 `checked_intents=off` 消融决定 |
| 续期门 | 每道题花到硬顶，或自然停滞 | M1 的 `extension=always` 消融决定 |

---

## 6. 两个走查

记号：n 为论断，i 为 Intent，a 为 Artifact，h 为 Hint。金额按 §8 的价目估算，均为 [假设]。两个走查只写到契约与流程一层，不含具体手法。

### 6.1 一道 CTF Web 练习题（M0 能力即可走完）

Problem：scope 只有题目主机一条网络规则，人把它标为 r0（练习环境，可随时重置）；Goal 判官为 `exact_match`（对照预置答案的哈希），`max_attempts=5`；题预算 11.5 美元。图服务推出画像 `{partial, hard, r0}`：范围里有外部资源，Goal 判官廉价且为判定性，规则的最高风险是 r0。

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
| 15 | 图服务 | Goal 获得判定性支持，为 E3；`close_problem` | 其余租约取消，容器销毁 |

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
| 6 | Reason | `add_intent` i_7："回滚该配置"，risk=r2，premises 为 n_10；`done` 为延迟的指标断言"回滚后 10 分钟内错误率低于阈值并保持 30 分钟"，`tests` 为 n_10 | 消费门不满足，i_7 为 blocked；派生 `verify_wanted(n_10, E2)` |
| 7 | Verify 两次 | v_1 用另一模型家族，任务包不含 n_10 正文，写复审支持；v_2 引入新的执行证据（同时段未改配置的服务没有该症状） | n_10 先到 E1，再到 E2 |
| 8 | 闲人 | 反证："同时段流量也在上涨"，附 exec 类 Artifact | n_10 进入争议。裁决任务核对时间先后（流量 01:30 已上涨，错误率 02:05 才升高），反证被驳回 |
| 9 | 图服务 | i_7 转 `needs_human`；审批卡片由投影确定性生成 | 卡片列出：动作与回退方法、n_10 的等级与支持记录、各前提的判据来源、未决争议（无）、`done` 判据及其所检验的论断 |
| 10 | 人 | **审批门**：`pd approve i_7 --waive-premise n_10` | i_7 为 open；`tests` 随批准生效 |
| 11 | 司南、执行层 | 并发 1；i_7 的执行容器按 r2 上限编译，注入一次性的变更凭据 | Worker 经 `exec` 执行回滚，输出登记为 exec 类；`claim_done` i_7，观察窗开始计时 |
| 12 | 延迟判官 | 到期运行指标断言与守护项，通过 | i_7 为 achieved；n_10 得到一条相符性支持，为 E3d。Goal 的指标断言同时通过 |
| 13 | 人 | 报告写明：根因 n_10 为 E3d，未做副本反事实；被排除的解释一条。`pd accept` | 题目关闭，Goal 标为"已验收" |

两个分支。有副本环境时，再开一个 r0 的 Intent 做双向反事实，判定性判官通过后 n_10 到 E3。判据没有通过时，i_7 未达成并回到 `needs_human`（不可逆动作不自动重做），n_10 得到一条反证并进入争议，Goal 不成立，`/work` 重新给出 reason，回滚动作的记录保留。花费约 8 美元。

---

## 7. 路线图与 M0 实施清单

| 里程碑 | 内容 | 出口条件 |
| --- | --- | --- |
| M0（3 周，1 人） | 六个契约的最小版；一个 CLI 后端；先纵切、后加厚 | 下表 D15 |
| M1（再 2 到 3 周） | 评测台：20 题与检查点、B1/B1b/Bk/Bn 四臂、消融开关、归因表；E1/E2 与 Verify；争议；r1 与 r2 消费门的完整形态（含前提豁免）；续期门；多厂商网关 | §8.3 的 G1 到 G3；每个已启用的 T-1 结构各有一条消融结果 |
| M2 | 闲人、模型分层、扇出控制器；题集扩到 50 | 三者各自的消融结果，没有带来增量的删除 |
| M3 | 内核增量：判据的有效期、延迟判官、人执行的 Intent。之后接入第二个领域（数学或软件工程） | 接入第二个领域时内核代码零改动，只新增锦囊、判官配置与资源插件。这是红线 3 的验收 |
| M4 | 通鉴管线；多节点（PostgreSQL、对象存储）；类型化只读工具、r2 凭据按次签发、虚拟机 | 锦囊消融为正；r2 场景里每条前提的判据都来自类型化只读工具，或有人的豁免 |

北极星是一对数：解题率与每题成本，始终与各条基线并排报告。任务书写作"每题成本 × 解题率"；两者方向相反，乘积无法排序，所以需要合成一个数时用每解出一题的成本（总成本 ÷ 解出题数）。

M0 实施清单（15 个工作日）。前 7 天做一条最薄的纵切，让最大的不确定项尽早暴露；后 8 天加厚：

| 日 | 交付 | 当日验收 |
| --- | --- | --- |
| D1 | 仓库骨架；事件信封、JCS 规范化、哈希链；SQLite 日志；重放测试台；Blob 仓库 | 3.1.5 的 1；3.2.5 的 1、4 |
| D2 | reducer 的最小集（开题、Artifact 登记与可采信检查、论断、判官请求与裁决）；M0 等级函数与迟滞，以参考模型为对照；组件令牌 | 等级函数的单元测试（一次失败回到 E0，连续两次失败为 X）；3.1.5 的 4（M0 形态）；3.2.5 的 2 的前四种形态 |
| D3 | 执行层：执行容器、出站白名单与访问摘要、`exec` 的采集与登记 | 3.6.4 的 1、3 |
| D4–D6 | Adapter：模型容器、端点代理（换密钥、记用量、超额拒绝）、工具端点与三个代理工具、任务包渲染、十项后端绑定 | 3.4.5 的 1、2、4、7（脚本化的假 CLI），再用真 CLI 跑通一次；3.6.4 的 4 |
| D7 | 判官运行器、`replay`、`exact_match`、抖动策略与次数上限。**纵切完成**：用桩租约手工起一个 Bootstrap 会话做一道练习题；同一道题手工跑一次 B1 | 3.3.5 的 1、2、4、5、6、8；Goal 为 E3；得到第一组成本实测值和外壳税的第一个读数 |
| D8 | 租约、`/work` 派生、过期、幂等、崩溃恢复；消费门；画像推导；带判据的 Intent | 3.1.5 的 2、3、5、6、7、8、9；3.3.5 的 7；3.4.5 的 3、6 |
| D9 | 预留、`budget_mark`、哮天犬、收尾轮；账本投影与代理记录对账 | 3.5.5 的 1、2、4、5 |
| D10 | `pd` 命令行与人的通道（`problem open`、`status`、`profile`、`hint`、`approve`）；scope 按风险编译、`scope_violation` | 手工开题、注入 Hint、批准一次范围修订；3.6.4 的 2 |
| D11 | 司南最小循环；bootstrap、reason、explore 三份角色提示 | 假 CLI 下走完 bootstrap、reason、explore、goal |
| D12 | 厚路径端到端：一道 Bootstrap 解不出的练习题；`pd report`、轨迹导出、归因记录 | Goal 为 E3，解题链跨至少两个会话；3.4.5 的 5 |
| D13 | 对抗用例专日：坏事实注入、伪造 Artifact 五种、环状引用、伪造观察、预算穿透、空谓词；Blob 回收 | 全部通过并进入持续集成；3.2.5 的 3 |
| D14 | 对照臂运行器 B1 与 B1b：同一模型、同一 Goal 判官，前者用原生工具面，后者用代理工具面 | 同一组题的 B1、B1b 成本与结果入库 |
| D15 | 缓冲；M0 报告 | 报告含端到端日志、对抗用例结果、B1 与 B1b 对比、已知缺口清单 |

M0 不做：E1/E2、Verify、闲人、分层、扇出控制器、通鉴、多厂商路由、判据的有效期、续期门、类型化只读工具、r2 凭据注入（M0 的题目只含 r0 规则）、PostgreSQL、图形界面。

15 天是没有意外时的估计 [观点]。最大的不确定项是 D4–D6：真实 CLI 在去掉命令工具、只挂外部工具、端点指向代理时的行为，可能与帮助文本有出入。纵切把它放在第一周，D6 结束时还没跑通就停下来重估，退路是换后端或自研薄循环 [证据 S3]。超期时先砍 D12 的报告排版和 D10 的命令行便利项。

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
- 检查点分 c：每题由出题人事先写下 3 到 5 个中间检查点，对 Worker 隐藏。评测台在运行结束后对该次运行的全部命令输出求值，各臂用同一实现；c 是通过比例的平均。长链路要有部分得分 [证据 S13]。c 不改变 G1 到 G3 的判定，只用来定位各臂卡在哪一步，并在 G1 的差距不超过 1 题时决定是否值得扩题集复核。
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
5. 同时报告 Bn。庖丁赢 Bk 却不赢 Bn，说明价值在共享而不在图与等级，此时把解牛图简化为追加写笔记加判官。
6. 评测自身也记账。按 8.2 的估算，B1 与 B1b 各约 190 美元，Bk、Bn 与庖丁各约 410 到 460 美元，首轮合计约 1700 美元；每条消融臂只跑中、难两段，约 440 美元 [假设]。

### 8.4 结构归因表

删简律要落到账上。每道题关闭时，图服务从日志投影出一行归因记录，不调用模型。它是复盘里确定性的那一半。

```ts
type Attribution = { problem_id: string, solved: boolean, path: "thin"|"thick"|"none",
  chain: { sessions: string[], intents: string[], facts: string[] },    // 解题链
  on_chain: Record<string, boolean>,     // 每个 T-1 结构是否出现在解题链上
  spend: Record<string, Budget>,         // 每个结构名下的花费
  pruned: { intents: number, reserve_released: Budget },                // 因前提被证伪而放弃的 Intent
  human: { hints: number, approvals: number } }
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

规则：

1. 汇总两个数：贡献率，即厚路径解出的题里该结构在链上的比例；成本占比，即名下花费 ÷ 总花费。
2. 厚路径累计解出不少于 10 题之后，贡献率低于 10% 而成本占比高于 5% 的结构标为待删候选，下一轮评测必须带上它的消融臂。
3. 归因是观测性的。结构在链上不等于必要，不在链上也可能靠剪枝起作用；解题链按声明的前提回溯，读过而未声明的节点不在其中。所以归因只筛候选，删与不删由消融定论。
4. 共享图的贡献率是 G1 的先行读数：它很低时，厚路径的解出多半只是多跑了几次。
5. 续期门、三层视图与 `bootstrap_share` 没有"在链上"的读数，只能靠消融。生产中有人注入 Hint 的题单列，不计入自动解题率。

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
| 闲人 | idler | 只写猜想与反证的低成本旁观会话 |
| 复盘 | retrospection | 预算节点上的反思，以及题目关闭后的归因与提炼 |
| 归因表 | attribution table | 逐题记录每个 T-1 结构是否在解题链上、花了多少，见 8.4 |
| 续期门 | extension gate | 花费过 80% 后，没有被判官确认的进展就不再开新的探索 |
| 如意 | tool layer | Worker 可用的工具：CLI 的文件工具、三个代理工具、锦囊捆绑的脚本 |
| 代理工具 | proxy tools | Adapter 托管的 `exec`、`submit`、`show`，是 Worker 对外的全部通道 |
| 锦囊 | skill kit | 按需加载的领域知识与脚本目录 |
| 通鉴 | cross-problem memory | 跨题的锦囊库与使用记录 |
| 哮天犬 | watchdog | 不含策略的脚本：过期租约、超预算终止、清理、告警 |
| 提议、租约 | proposal, lease | 待图服务校验的一批写操作；带预留预算与期限的任务认领 |
| Worker、Adapter | worker, adapter | 执行任务的 CLI 会话；为它渲染任务包、托管代理工具并管理租约的进程 |
| 端点代理 | endpoint proxy | 容器外的反向代理：换密钥、记用量、超额拒绝；之后扩成多厂商网关 |
| 模型容器、执行容器 | model container, exec container | 前者运行 CLI，只连工具端点与模型端点代理；后者运行命令，只连授权范围 |
| 瘦基线 B1 | thin baseline | 单个 CLI 会话，原生工具面，配同一授权范围与同一 Goal 判官 |
| B1b、外壳税 | proxy-surface baseline, harness tax | 工具面换成代理工具的瘦基线；它与 B1 的解题率之差 |
| Bk、Bn | equal-cost retries, shared-notes baseline | 同预算下的独立重试；多个 Worker 共用一份追加写笔记 |
| m、R | cost multiple, efficiency | 成本倍数与每倍成本换来的解题率增量，见 8.3 |

---

## 10. 开放问题

| # | 问题 | 选项 | 倾向 |
| --- | --- | --- | --- |
| 1 | E1 与 E2 是否保留为两级 | 保留；合并为一级"模型复核"；只留二值 | 先按两级实现，M1 的 `ladder=binary` 消融决定；两级的误晋级率没有差别就合并 |
| 2 | 外壳税超过阈值时怎么办 | 改进 `exec` 的语义直到贴近原生工具；Bootstrap 改回单容器的原生工具面，只让厚路径用代理工具；接受差距 | 第一项。第二项会把 v1.0 的三个缺口带回 Bootstrap，只在练习环境里可以接受 |
| 3 | 跨轮的前缀缓存 | 只靠会话内缓存；替换系统提示并划出静态段；自管循环 | M0 只靠会话内缓存并实测。Reason 的输入成本超过题成本的 15% 时再做第二项 |
| 4 | 在途会话是否接收 Hint | 下一个任务包生效；经流式输入即时注入 | 前者。中途干预要谨慎 [证据 S17]，且各后端支持不一 |
| 5 | Explore 用哪一档 | 全强；中档加失败升级；强档调低推理强度 | M1 全强，M2 三者做消融 |
| 6 | 续期门的进展谓词取多严 | 有带判据的对象新到 E3；只认带判据的 Intent 达成；只由人放行 | 第一项起步。它可能被琐碎的观察轻易满足：M1 统计触发次数、省下的预算，以及 `extension=always` 下多解出的题数，触发次数接近零就换第二项 |
| 7 | 语义去重 | 不做；`same_as` 提议；嵌入聚类 | 不做，直到实测近重复节点超过 15%。嵌入聚类进写入路径会破红线 1，排除 |
| 8 | Bootstrap 的长度 | 完整的瘦基线运行；短侦察后尽早扇出 | 前者作默认，`bootstrap_share` 做一条消融臂 |
| 9 | 题预算取瘦基线的几倍 | 2；3；5 | 3。M1 用实测的 R 曲线复核：倍数再加大而 R 下降就不加 |
| 10 | 与 v0.1 修订稿的出入 | 以本文为准；以 v0.1 为准；逐条对账 | 逐条对账。本文没有读到 v0.1 正文，需要人提供 |
