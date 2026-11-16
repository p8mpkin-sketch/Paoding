# 庖丁基座规格 v1.0

> 状态：提案（2026-11-17）。
> 输入：[调研 v2](../research/agent-architecture-survey-v2.md)（[S#]/[Z#] 编号以其为准）、架构 v0 上传稿、任务书 §3.2 所列 v0.1 立场。v0.1 修订稿不在远端任何分支上，本文没有读到其正文；如与其冲突，以人的裁决为准。
> 论断标注：`[证据 S#/Z#]` 有调研来源；`[假设]` 待 M0/M1 验证；`[观点]` 作者判断；`[待核]` 来源未能一手核对。
> 结构标注：`[T-0]` 当前必要，且模型再强也需要；`[T-1]` 下一代模型可能吃掉，必须放外壳并带开关。
> 瘦基线：按任务书红线 5，取单个 Claude Code 会话。文中"该 CLI"均指它，M0 的 Worker 后端也用它（3.4.2）。

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
| 红线 2 反幻觉不变量 | 承重墙，但不充分 | 收紧（A1） |
| 红线 3 领域知识不进内核 | 承重墙 | 维持；授权范围对内核不透明，由执行层解释 |
| 红线 4 删简律 | 承重墙，但原文不可操作 | 补操作化：每个 T-1 结构必须有开关和一条 M1/M2 消融臂 |
| 红线 5 诚实对照 | 承重墙，但基线定义偏松 | 收紧（A2） |
| 立场 1 证据梯六态 | 方向对；E1 与 E2 分两级没有直接证据 | 重构实现（A4）；E1/E2 标 T-1 |
| 立场 2 E1→E2 异构 | 方向对；"不同视角"不可机检 | 收紧（A5） |
| 立场 3 闲人写入面 | 维持 | 澄清复审的归属（A8） |
| 立场 4 消费时验证 | 承重墙 | 维持，补死锁出口（3.1.4） |
| 立场 5 三轴分立 | 维持 | 补第四轴（A7） |
| 立场 6 复用成熟 CLI | 依据是单一数据点 [证据 Z3]，但路径最短 | 维持，改输出通道（A10） |
| 立场 7 证伪阻尼 | 目标对，机制可以更简单 | 重构（A6） |
| 立场 8 司南无权威状态 | 承重墙 | 维持 |
| 五契约的切分 | 部分是惯性 | 部署合并，补一条（A9） |

从众风险最大的不是某条立场，而是黑板路线本身。它的证据是比赛成绩，属作者自述且没有对照组 [证据 Z3][Z4]。A2 的两条对照臂专门检验这一点。

### 1.2 异议清单

下列各条本文均按替代方案书写。人可以逐条否决，否决后按原立场改回。

| 编号 | 被挑战的约束 | 替代方案 | 论证 | 迁移成本 |
| --- | --- | --- | --- | --- |
| A1 | 红线 2："引用 Artifact"即可晋级 | ① Artifact 带出处类别 `exec/judge/input/authored`，只有前三类可作证据；② 观察类论断的内容就是可机检的谓词；③ E3 只来自判官在洁净环境中的独立重放，不来自 Worker 自己的执行记录 | 引用只保证出处，不保证相关；也挡不住"先写文件再读出来"。自造观察是常见失败 [证据 Z7]；AIxCC 只认可独立复现的 PoV [证据 S14][S15] | Artifact 加 2 个字段；Fact 加 `claim_type` 与 `check` |
| A2 | 红线 5：对照 = 单次瘦基线 | 三条对照臂：B1 单次瘦基线；Bk 等成本独立重试（任一次成功即算解出）；Bn 共享笔记（多 Worker 共用一个追加写的 Markdown，无图无等级） | 独立重试本身就能涨解题率，只对 B1 计算"增量/成本倍数"会虚高 [观点]。赢 Bk 才说明共享状态有价值；赢 Bn 才说明图和等级有价值 | 评测脚本多两条臂，约 1 天 |
| A3 | 红线 1 的边界 | 图服务只做内容键精确去重；语义合并是一种提议（`same_as`，完整版）；title 与 summary 由提议方撰写且不可变。图服务的任何路径都不调用模型 | 语义去重和摘要生成是最容易破线的两处 | 无 |
| A4 | 立场 1：等级是可晋级的状态 | 等级不存储，是"有效支持集"的纯函数；取消"晋级请求"操作。E3 与 E3d 的区别由判官注册表里的 `grade`（判定性/相符性）决定，不由提议方声明；"等待延迟判官"是标记，不是等级 | 可写的等级字段会带来晋级竞态和不可重放的状态 [观点] | v0.1 的晋级状态机改写为"支持记录 + 重算" |
| A5 | 立场 2："同模型不同视角"也算异构 | 异构 := 模型家族不同，或后一条支持引入了前一条没有的执行证据 | 只换提示词不能消除相关错误，且不可机检 [观点] | 无（收紧） |
| A6 | 立场 7：连坐豁免规则 + 传播深度上限 | ① X 只来自判定性判官失败或人的裁决，模型反证只产生"争议"；② 等级按最小不动点全量重算，有独立有效支持的节点自然保留；③ 单个事件导致 K 个以上节点降级时告警。不设深度上限 | 截断传播会留下"地基已塌、上层照旧"的节点。真正要防的是错误的证伪，所以门槛设在 X 的产生上。重算是经典真值维护（JTMS，Doyle 1979，不在调研编号内）[观点] | 新增派生标记 `disputed` |
| A7 | 立场 5：三轴 | 补第四轴 时效性 `drift ∈ {static, drifting}` | 在会变化的环境里（运维、对抗赛），重放失败的含义是"已过期"，不是"曾为假"；不区分会产生错误的 X。它与另三轴独立：运维为 drifting，静态题与数学为 static [观点] | axes 加一个字段；M0 只实现 static |
| A8 | 立场 3 中复审者的归属 | 写支持记录的复审属于 Verify 任务档；闲人只写猜想与反证，反证同样必须带可采信 Artifact | 与"闲人只写 E0 与反证"一致，消除 v0 中 reviewer 的歧义 | 无 |
| A9 | 五契约的切分 | ① 契约 1、2、5 的权威状态是同一条事件日志，图、Artifact 登记、预算是它的三个投影；接口分立，M0 部署为一个进程。② 新增契约 6 执行层 | 三套存储要做跨库一致性，没有收益 [观点]。授权范围、审批门、证据采集的强制点都在执行层，原五契约里没有落点 | 无（尚未实现） |
| A10 | 立场 6：解析 CLI 的输出 | 维持 CLI 复用；Worker 的结论不从聊天文本解析，改为 outbox 文件 + JSON Schema。记录 M0 的已知缺口：transcript 采集可被沙箱内进程篡改；沙箱内嵌套启动的会话不计量；模型密钥放在沙箱里 | 文件 + Schema 的容错成本远低于文本解析 [观点]；缺口的补法见 3.2.4（broker 采集）与 3.5.4（模型网关） | 无 |

---

## 2. 基座总览

基座 = 一条事件日志 + 一个确定性裁决器 + 四个插拔接口（判官、Worker Adapter、执行层、Blob 存储）。

```
        人 ──(open / hint / approve / 裁决 / 验收)───────────┐
                                                           ▼
 ┌─────────┐  /work · 租约   ┌────────────────────────────────────────────┐
 │ 司南 ×N  │◀──────────────▶│ 契约1 解牛图服务：唯一写入者，确定性代码        │
 └────┬────┘                │ 事件日志 ─▶ 投影：图与等级 │ Artifact 登记(契约2) │ 预算(契约5) │
      │ 启动                 └───────▲───────────────▲──────────────▲────────┘
      ▼                             │ 提议           │ 裁决          │ 过期/终止
 ┌───────────────┐  outbox+事件流   │         ┌──────┴───────┐  ┌───┴────┐
 │ 契约4 Adapter  │─────────────────┘         │ 契约3 判官运行器│  │ 哮天犬  │
 │  └ CLI Worker  │                           └──────┬───────┘  └────────┘
 └──────┬────────┘                                  │ 洁净重放
        ▼ 命令                                       ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ 契约6 执行层：沙箱 · 授权范围 · 采集 ──▶ Blob 仓库(契约2，按 sha256 寻址) │
 └──────────────────────────────────────────────────────────────┘
```

数据流：

1. 人用 `pd problem open` 提交 Problem，其中授权范围、判官、预算、四轴都是必填。
2. 司南读 `/work`（图服务派生的可做事项），申请租约，同时预留预算。
3. Adapter 按租约起沙箱，渲染任务包，启动 CLI。
4. CLI 执行命令。输出由执行层或 Adapter 采集并登记为 `exec` 类 Artifact，模型只拿到引用。
5. Worker 把结论写进 outbox 文件。Adapter 校验后作为提议提交。
6. 图服务确定性校验并追加事件；等级、预算、可做事项随之重算。
7. 需要判定时，判官运行器在洁净沙箱里重放，提交裁决。
8. 哮天犬只做四件事：过期租约、超预算终止、清理孤儿沙箱、健康告警。

结构清单与成本影响：

| 结构 | 标签 | 成本影响 | 开关或消融臂 |
| --- | --- | --- | --- |
| 事件日志 + 确定性裁决 | T-0 | 无模型成本，毫秒级 | 无 |
| 出处类别与可采信检查 | T-0 | 无 | 无 |
| Goal 判官、重放判官 | T-0 | 每次一个洁净沙箱，秒到分钟，不耗 token | 自动重放的成本阈值 |
| 预算预留、硬顶、哮天犬 | T-0 | 无 | 无 |
| 授权范围与审批门 | T-0 | 人的等待时间 | 无 |
| Bootstrap 先瘦后厚 | T-1 | 易题上成本倍数约为 1 | `bootstrap_share` |
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
| 证伪传播 | 每个事件后全量重算（最小不动点） | 增量传播 + 深度上限 | 精确，百行内可写完；该规模下毫秒级 [假设] |
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
           profile?: "bootstrap"|"reason"|"explore"|"verify"|"idler" }  // 由租约决定，非模型自报
  kind: string                // 见操作表
  body: object
  idem_key: string            // 提议方生成；同键重放返回首次结果
  prev_hash: string           // 同题上一条事件的 hash；哈希链按题独立，可单独导出与校验
  hash: string                // sha256(JCS(除 hash 外的全部字段))，JCS 即 RFC 8785 规范化 JSON
}

type Axes = { info: "complete"|"partial",                 // 信息完整度 → 司南的生长规则
              judge: "hard"|"costly"|"deferred"|"none",   // 判官类型 → Goal 的可达上限
              reversibility: "r0"|"r1"|"r2",              // 可逆性 → 审批门默认值
              drift: "static"|"drifting" }                // 时效性 → 观察的有效期（M0 只实现 static）
type Budget = { usd_milli: number, tokens?: number, wall_s: number }
type Check  = { judge_id: string, spec_ref?: ArtifactId, expect?: object }   // expect 由判官解释

type Problem = {
  id: string; title: string
  origin: { statement_ref: ArtifactId, materials: ArtifactId[] }              // input 类
  goal:   { statement: string, check: Check, max_attempts: number,
            accept: "judge"|"human" }                                         // M0 只实现 judge
  axes: Axes
  scope: { resource: string, pattern: string, actions: string[] }[]          // 必填；内核不解释
  budget: Budget & { verify_share: number, bootstrap_share: number }
  env: { sandbox_profile: string, baseline_ref: string }
  judges: string[]                                                            // 本题启用的判官
}
type Fact = {                  // 等级为 E0 时称 Conjecture；存储上是同一种记录
  id: string
  title: string                // 第一层，≤120 字符
  summary: string              // 第二层，≤600 字符
  body_ref?: ArtifactId        // 第三层正文，authored 类
  claim_type: "observation"|"inference"
  check?: Check                // observation 必填：论断的内容就是这个谓词
  premises: string[]           // derives_from 边
  grounds: ArtifactId[]        // observation 至少 1 个 exec 或 input 类；inference 要求 grounds 或 premises 非空
  yielded_by?: string          // yields 边：Intent id，由租约推出，不由模型填写
}
type Intent = {
  id: string; title: string; summary: string
  premises: string[]; risk: "r0"|"r1"|"r2"; budget: Budget
  needs_scope?: Problem["scope"]   // 申请扩大授权范围；非空时初始状态为 needs_human
  expected_gain?: number       // [T-1] 只供司南排序，内核不解释
}
type Hint = { id: string; text: string; about?: string     // about：所指节点，可空
              author: string; closed: boolean }            // 不是证据，不能作前提（4.1）
type Support = {               // supports / contradicts / proves 三种边的载体
  id: string; target: string   // Fact id，或 "goal"（此时即 proves）
  polarity: "support"|"contradict"
  method: "judge"              // M0 只有判官一种
  judge: { id: string, version: string, grade: "decisive"|"consistent" }
  verdict: "pass"|"fail"; evidence: ArtifactId[]          // judge 类
}
type Lease = { id: string; kind: "bootstrap"|"reason"|"explore"|"judge"; target?: string
               holder: string; reserve: Budget; expires_at: number; attempt: number }
```

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
| `open_problem` | human | Schema；判官已注册；scope 非空；预算为正 |
| `register_artifact` | adapter（exec、authored）、judge（judge）、human（input）、executor（exec） | Blob 存在且哈希相符；类别与令牌匹配 |
| `add_fact` | adapter，档位为 bootstrap/explore/reason | 引用存在且同题；grounds 类别可采信；observation 带 check；premises 中无 X；未超配额 |
| `add_intent` | adapter 档位为 reason；human | premises 存在且无 X；预算落在配置区间 |
| `abandon_intent` | adapter 档位为 reason；human | Intent 未到终态且无在途租约 |
| `request_judge` | adapter、sinan、human | 判官在 `Problem.judges` 内；Goal 未超 `max_attempts`；验证池未超 |
| `judge_verdict` | judge | 请求存在且由本判官租出；evidence 为 judge 类 |
| `hint`（新增或关闭）、`approve`（批准或拒绝）、`pause`、`resume` | human | 无 |
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
| 提议引用的前提在提交时已被证伪 | 整批拒绝 `stale_premise`，附最新状态，由 Adapter 回注给 Worker 修正 |
| 同一 `idem_key` 重放 | 返回首次结果 |
| 判官裁决与人的裁决不一致 | 人的裁决优先，并在节点上留可见标记 |

内容键：观察类取 `check` 的规范化哈希（`spec_ref` 按 Blob 哈希代入），推断类取 title 与排序后的 premises 的哈希。

M0 的等级函数与消费门：

```
有效裁决(t,j) := 目标 t 上判官版本 j 最近一次 reason_code ∈ {ok, flaky} 的裁决；ok 取其 verdict，flaky 视为无结论
有效(s)     := s.judge.version 未被撤销 ∧ 有效裁决(s.target, s.judge) = s.verdict
level(f)    := X   若存在有效的 contradict（grade=decisive，verdict=fail）
               E3  否则若存在有效的 support（grade=decisive，verdict=pass）
               E0  其它
level(goal) := E3  若某个候选有一条有效的判定性 pass；否则 E0
                   // 有效裁决按候选分别计；失败的候选只累计 max_attempts，Goal 没有 X
gate(i)     := (∀p∈i.premises: level(p)≠X ∧ (i.risk=r0 ∨ level(p)=E3))
               ∧ ((i.risk≠r2 ∧ i.needs_scope 为空) ∨ 已有 approve(i))
```

Intent 状态（派生）：

```
open ──租约──▶ leased ──release──▶ done
  ▲              │ 过期或失败，且 attempt < 2
  └──────────────┘
blocked ──前提达标──▶ open
blocked ──验证用尽，或需要审批──▶ needs_human ──approve──▶ open ；deny ──▶ abandoned
未终态 ──前提被证伪 / Reason 放弃 / 连续 K 轮无人认领──▶ abandoned
```

`/work` 的派生规则（图服务给出"可做什么"，司南决定"先做什么"）：

```
bootstrap   尚无任何租约历史
reason      无在途 reason ∧ bootstrap 已结束 ∧ 上次 reason 租约签发之后出现过：
            非 reason 任务结束 | 新 Hint | 预算标记 | Goal 判官 fail
            处于预算复盘期时带 reflect 标志（3.5.2）
explore(i)  state(i)=open ∧ 不处于预算复盘期
judge(j)    请求未裁决且未租出
human(x)    needs_human 的 Intent 与待审批项
            停滞也归入此项：无在途任务、无 open 的 Intent、无未决判官请求，且 reason 不满足触发条件。
            此时等待 Hint 或人工关闭；wall_s 用尽时由哮天犬以 unsolved 关闭
```

每个任务的写入配额：Fact 不超过 20 条，Intent 不超过 8 条（可配置）。

#### 3.1.3 完整版

支持记录扩展为 `method ∈ {judge, review, human}`，并带 `premises`、`by {session, model_family}`、`context_manifest`（Adapter 记录该会话实际读到的节点与 Artifact，非模型自报）、`valid_until`。等级全序为 E0 < E1 < E2 < E3d < E3。

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

复审是对"由前提推出该论断"的意见，所以论断自己的前提被证伪时，它的复审支持全部失效；判官支持直接检验论断本身，不受影响。这就是"有独立支持的节点不连坐"的机械形式。level() 对前提的等级单调，所以最小不动点唯一，与迭代顺序无关；互相作前提的两条论断无法把彼此抬上去，环状支持得不到等级。

消费门：

| Intent.risk | 前提最低等级 | 审批 |
| --- | --- | --- |
| r0 可逆或只读 | 非 X 即可（探索本身就是检验猜想的方式） | 不需要 |
| r1 有成本 | E1，且无争议 | 不需要 |
| r2 不可逆 | E3；或 E2 以上并由人对该前提签署豁免 | 必需 |

其它增量：

- **争议与裁决**：模型反证只让节点进入"争议"。图服务派生一次裁决任务，要求给出能区分真假的检查并执行。通过则反证标为已驳回，失败则节点为 X。同一组证据不能重复提出反证。没有可用检查时保持争议，交人裁决。
- **E3 的降级**只有三条路：判官重跑失败、判官版本被撤销、人的裁决。针对 E3 的模型反证只触发一次重跑，带冷却期。
- **延迟判官**：`register_deferred {target, judge_id, due_at, recheck}`。到期前节点带 `pending` 标记，等级不变。r2 的 Intent 必须附带一条预测，即一条延迟判官的规格；图服务在批准时登记，动作之后不可改。
- **时效性**：drifting 环境下，观察类支持带 `valid_until`；重放不一致时支持记为过期，节点按剩余支持重算，不记 X。
- **影响面告警**：单个事件使 K（默认 10）个以上节点降级，或使在途的 r1、r2 任务失去前提时，图服务追加 `alert` 事件，相关租约标记 `premise_lost`，司南必须取消。
- 另有 `retract`、`supersede`、`same_as`、带 `done_check` 的子目标、`fork(at_seq)`、PostgreSQL 与只读副本。

#### 3.1.4 必答

**E3d 何时、如何转 E3 或降级。** E3d 的定义是"相符性判官通过"：预测的结果出现了，但这个结果不能排除其它解释。转 E3 的唯一途径是同一论断再获得一条判定性判官的通过，例如在副本环境里做双向的反事实验证。降级有三种：相符性判官在观察窗内复检失败，支持被驳回，等级按剩余支持重算；判定性判官失败，记 X；drifting 环境下有效期届满且未续期。模型意见不能让 E3d 升或降，只能使其进入争议。

**"独立支持"如何机械判定。** 见 `independent` 与 `heterogeneous` 的定义。两者只用到租约、会话、模型家族、Artifact 登记和 Adapter 记录的 `context_manifest`，都不是模型自报的字段。"某节点被证伪后另一节点是否幸存"不需要单独判定，重算后等级不变即为幸存。

**图服务崩溃后未决提议如何恢复。** 图服务内部没有"未决"状态：提议在落盘（fsync）之后才应答，否则视为未发生。提议方用同一 `idem_key` 重试。Adapter 一侧，Worker 的 outbox 文件先存为 authored 类 Artifact 再提交，Adapter 重启后从文件重新生成同样的 `idem_key`（任务 id 与操作内容的哈希）。重启时图服务从最近快照加事件重放恢复，快照的状态哈希记在日志里，可校验。

**图很大时 Reason 的读图分页与排序。** 任务包分两段。前段是不可变内容：节点 id 与 title 按创建顺序追加排列，连续两次 Reason 之间只会在末尾变长。自管循环或后端允许设缓存断点时，这一段可以跨轮命中缓存 [证据 S41]；CLI 复用下能否命中要实测 [假设]。后段是可变状态：等级、争议、Intent 状态的紧凑表。前段默认上限 400 个节点，超出时按确定性规则从列表中省略（已证伪、已撤回、已结束且无依赖者），被省略的节点仍可用 `pd show` 查询。摘要层只给"前沿"：活跃 Hint、争议节点、待人处理项、上次 Reason 以来的新增与变更、未结束 Intent 的前提，其余按最近变更倒序分页，游标为 seq。

**消费时验证如何防死锁与重复触发**（完整版）。`verify_wanted(f, 目标等级)` 由被阻塞的 Intent 派生，去重键是（节点、目标等级、证据版本），证据没有变化就不会再次触发，每个键最多尝试 2 次。Verify 任务本身不受消费门约束，所以不会递归。验证用尽后 Intent 进入 `needs_human`，人可以签署豁免。r0 的 Intent 永不阻塞。

**三层视图的生成与失效。** title 与 summary 由提议方在创建时写入，之后不可变，因此没有缓存失效问题。需要更正时提交新节点并 `supersede` 旧节点。投影目录中 `LISTING.md` 只追加，`STATUS.tsv` 每次重写，`nodes/<id>.md` 只在状态变化时重写。

**快照与回滚。** 每 1000 个事件做一次状态快照。不做原地回滚；需要"回到某一点"时用 `fork(at_seq)` 复制日志前缀生成新题，原题关闭。

#### 3.1.5 验收测试

1. 重放确定性：同一日志重放两次，状态哈希相同。
2. 崩溃恢复：提议处理中 `kill -9`，重启后客户端重试，结果恰好一次。
3. **坏事实注入（对抗）**：构造 A（E3）；B 只由 A 推出；C 由 B 推出且另有独立的判官支持；D 只由 B 推出。让 A 的判官重跑失败。期望：A 为 X；B 与 D 回到 E0 并出现在 `invalidations` 结果里；C 保持 E3；以 B 或 D 为前提的 r1 Intent 变为 blocked，在途租约带 `premise_lost`。M0 只有判官支持，本用例的 M0 形态是：A 被证伪后，以 A 为前提的 Intent 变为 abandoned。
4. **环状引用（对抗）**：让 A 的支持以 B 为前提、B 的支持以 A 为前提。期望两者都停在 E0，重算在有限步内结束。M0 形态：节点和支持只能引用已存在的 id，环在构造上不可能；用例验证引用尚不存在的 id 返回 `unknown_ref`，并对随机生成的日志断言重算终止。
5. 并发租约：两个请求抢同一 Intent，恰好一个成功。
6. 权限：闲人档提交 `add_intent`，返回 `forbidden_op`。
7. 审批门：没有 `approve` 的 r2 Intent 永远不出现在 `/work` 的 explore 列表里。

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
  class: "exec"|"judge"|"input"|"authored"          // 出处类别，由登记方的令牌决定
  capture: "transcript"|"broker"|"judge_runner"|"intake"|"adapter"   // 采集路径
  producer: { actor: string, session?: string }
  exec?: { sandbox_id: string, sandbox_profile: string, baseline_ref: string,
           tool: string, command: string,           // 完整命令行
           cwd: string, exit_code: number|null,
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

规则：Blob 一经写入不可变，相同内容自动去重。单个 Blob 上限 256 MB，超出时采集方保留头尾并置 `truncated`。可作证据的类别是 exec、judge、input；authored 只能作为正文、重放规格、候选答案和 E0 猜想的依据。GC 采用标记清除，根集合是日志中出现过的全部 ArtifactId，所以被图引用者永不回收；未被引用的采集输出在题目关闭 30 天后可回收，登记记录保留并标 `collected`。

#### 3.2.3 完整版

对象存储后端；broker 采集（3.6）；"切片引用"（会话记录的哈希 + 字节区间）以消除工具输出与会话记录的重复存储；按题加密。

#### 3.2.4 必答：信任链

问题是如何保证模型不能把自己写的文本冒充命令输出。分三层。

1. **协议层。** 提议里只能出现 ArtifactId。类别、采集路径、命令行这些出处字段从不接受提议方填写，只来自带组件令牌的 `register_artifact`。图服务检查：引用存在、同题、类别对该用途可采信；复审类支持所引的 Artifact 必须在复审者的 `context_manifest` 内或由其会话产生。
2. **部署层。** 登记用的令牌按组件分发，adapter、executor、judge、intake 的令牌都不进入 Worker 沙箱。沙箱到图服务只有两条通路：只读查询，以及往 outbox 目录放文件。M0 中 exec 类 Artifact 由沙箱外的 Adapter 从 CLI 的结构化事件流里截取工具返回值来登记（`capture=transcript`）。M0 所选 CLI 的无交互模式逐行输出 JSON 事件，工具调用与工具结果是外壳发出的独立消息，不是模型生成的文本 [证据：该 CLI 官方文档，不在调研编号内]；其它后端接入前要逐一核对。模型在文本里"叙述"的输出不在这条通路上，所以自造观察无法成为证据。
3. **E3 的独立性。** 判定性判官在从 `baseline_ref` 新建的洁净沙箱里重新执行论断的规格，直接按哈希读取输入，不读 Worker 的叙述。Worker 在自己沙箱里写一个假文件再读出来，产生的确实是一条真实的 exec 记录，命令行如实写着读的是哪个文件；但洁净环境里没有那个文件，重放失败，论断到不了 E3。

M0 的残余风险：沙箱内的进程理论上可以篡改 CLI 的事件流。M0 接受这一点（单人、练习环境），并规定 r2 动作的审批材料只认 `capture ∈ {broker, judge_runner}` 的证据。完整版用 broker 采集关闭这个缺口。

#### 3.2.5 验收测试

1. 相同字节上传两次，得到同一哈希、一个 Blob。
2. **伪造 Artifact（对抗）**，五种形态都应失败：引用不存在的 id，返回 `unknown_ref`；把 authored 类当证据，返回 `inadmissible_class`；用 Worker 侧的通路登记 exec 类，返回 `forbidden_op`；引用别题的 Artifact，返回 `scope_mismatch`；写假文件后读出并据此提交观察类论断，重放判官失败，等级不是 E3。
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
  applies_to: "goal"|"observation"|"any"
  runner: { type: "container"|"builtin", image?: string, cmd?: string, sandbox_profile: string }
  timeout_s: number; max_cost: Budget; auto: boolean      // auto：成本低于阈值时创建即判
  flake: { reruns: number, require: "all"|"majority" }
}
type JudgeRequest = { id: string; problem_id: string; judge_id: string
                      target: string            // Fact id 或 "goal"
                      inputs: ArtifactId[]; params?: object; budget: Budget; requested_by: string }
type JudgeVerdict = { request_id: string; judge_id: string; judge_version: string
                      verdict: "pass"|"fail"|"inconclusive"
                      reason_code: "ok"|"timeout"|"env_error"|"flaky"|"unsupported"
                      evidence: ArtifactId[]     // judge 类，由判官运行器登记
                      cost: Budget; recheck_at?: number }
```

```
interface Judge { run(req: JudgeRequest, sandbox: SandboxId): JudgeVerdict }
```

M0 自带两个判官。`replay`（判定性，适用于观察类）：在洁净沙箱里执行 `spec_ref`，按 `expect {exit_code?, stdout_contains?, stdout_regex?}` 比对。Goal 判官由 Problem 配置，M0 提供 `exact_match` 与一个提交接口的插件位。判官运行器是持有 judge 令牌的独立进程，从 `/work` 领取 judge 租约。注册表在 M0 是图服务启动时加载的配置目录；条目的 id、version、grade 在裁决时抄进支持记录，所以重放不依赖注册表文件。判官的成本以 `cost` 事件入账，计入验证池。

#### 3.3.3 完整版

`record_match`（不重放，只对已登记的输出求谓词；采集路径可信时为判定性，否则为相符性）；`outcome_match`（相符性：批准时登记的预测规格，与它内容键相同的观察在期限内到 E3 即通过）；延迟判官与复检；模型面板（即编排好的 Verify 任务，产出复审类支持）；判官版本撤销；第二个领域的判官（如证明检查器、测试套件、指标断言）。

#### 3.3.4 必答

**判官超时与自身误判。** 超时或环境错误返回 `inconclusive`，不改变任何等级，成本照记，按注册表重试。抖动：判官运行器每次请求连续运行 `1 + flake.reruns` 次，按 `flake.require` 全部或多数一致时给出 pass 或 fail，否则给出 `inconclusive(flaky)`。同一（论断、判官版本）以最近一次非超时、非环境错误的裁决为有效裁决，所以一次抖动结果会让此前的 E3 失效，但不记 X。判官有缺陷时由人撤销该版本，这一版本产出的全部支持失效，等级重算，走的是与证伪相同的机制。针对 Goal 的判定有次数上限，防止对判官做穷举。

**"指标恢复 ≠ 根因修复"如何建模。** 拆成两条论断。"指标已恢复并保持了观察窗"是观察类论断，用延迟的指标断言判官判定，对这条论断它是判定性的。"根因是 X"是推断类论断，指标恢复对它只是相符性证据，给 E3d。根因要到 E3 需要两样东西：结构检查（程序化，确认 Origin 里登记的每个症状都被该论断的前提覆盖，或被明确标为无关），以及副本环境里的双向反事实验证（引入原因则症状出现，移除则消失）。没有副本环境时根因停在 E3d，由人验收，报告里写明等级。

**无判官领域的最小判官。** 两件：一个确定性的结构检查（结论所引的每条前提都不低于 E1、没有未决争议、要求列出的备选解释各有反证或明确保留），加一条人的验收记录。Goal 的状态是"已验收"而不是"已证明"，推断类论断的上限是 E2。模型面板是可选的增强，不是最小集。

#### 3.3.5 验收测试

1. 判官超时：裁决为 `inconclusive`，等级不变，成本入账。
2. 脚本化的抖动判官（交替通过与失败，`flake.reruns=1`）：裁决为 `inconclusive(flaky)`，不产生 E3，也不产生 X。
3. 撤销判官版本：依赖它的 E3 论断降级，相关 Intent 变为 blocked。
4. 错误的 Goal 候选：`fail`，尝试计数加一，达到上限后 `request_judge` 被拒。
5. 用 Worker 侧的通路提交 `judge_verdict`：`forbidden_op`。
6. Worker 能否改动判官资产：判官所用的测试与配置以 input 类 Artifact 的哈希固定在 Problem 里，Worker 沙箱中对其只读；改动后哈希不符，判官拒绝运行。

#### 3.3.6 最简反事实

砍掉它，Goal 是否达成只能由模型自己宣布，这正是"幻觉式成功" [证据 Z32]。Goal 判官是整个基座里最承重的一块。可以推迟的是节点级判官：M0 只需 Goal 判官加 `replay`。

---

### 3.4 契约 4：Worker Adapter 协议

#### 3.4.1 决策日志（备选与取舍）

| 议题 | 选定 | 被否方案 | 理由 |
| --- | --- | --- | --- |
| 输出通道 | outbox 目录里的 JSON 文件，按 Schema 校验 | 解析 CLI 的最终文本；让 Worker 直接调图服务；CLI 自带的结构化终稿 | 文件可以增量提交、崩溃后可抢救、与具体 CLI 无关。结构化终稿只在正常结束时给一次，只作 `final` 的兜底 |
| 证据引用 | Adapter 自动登记每次工具返回，Worker 用 `pd evidence` 查到 id 后引用 | 命令包装器；让模型引用"第几次调用" | 不改变 CLI 的原生工具，模型不接触出处字段 |
| 任务粒度 | 一个会话 = 一个任务 = 一个租约 | 一个 Worker 同时认领多个任务 | 成本归属、上下文隔离、恢复都更简单 |

#### 3.4.2 M0 最小版

任务包按下列顺序渲染。①到④在同一题内只追加不改写，构成稳定前缀；序列化用确定性的键序，前缀里不放时间戳和随机 id [证据 S41]。①到⑤经后端的"追加系统提示"入口注入，⑥⑦作为首条用户消息，这样同一 `as_of_seq` 下并发启动的会话拥有逐字节相同的系统前缀。

```ts
type TaskPackage = {
  role_prompt: ArtifactId          // ① 按 profile 固定
  problem_brief: ArtifactId        // ② Origin、Goal、授权范围、可用判官的说明
  kit_index: { name: string, description: string, path: string }[]   // ③ 锦囊只给元数据
  listing: ArtifactId              // ④ 节点 id 与 title，按创建顺序
  status: ArtifactId               // ⑤ 等级、争议、Intent 状态；每次都变
  focus: { intent?: string, fact?: string, premises: string[], hints: string[],
           restate: string }       // ⑥ 任务目标在末尾复述一遍
  limits: { budget: Budget, max_turns: number, ops_quota: object, sandbox_profile: string,
            tools: string[] }      // ⑦ tools：放行的工具名，Adapter 译成后端的工具面参数
  as_of_seq: number; task_id: string; profile: string; outbox: string
}
```

Worker 的输出：

```ts
type Outbox = {                    // 文件 outbox/NNN.json；可以多次提交
  schema_version: 1; task_id: string
  ops: (
    | { op: "add_fact", tmp_id?: string, claim_type: "observation"|"inference",
        title: string, summary: string, body_path?: string,
        check?: { judge_id: string, spec_path: string, expect: object },
        premises: string[], grounds: ArtifactId[] }
    | { op: "add_intent", title: string, summary: string, premises: string[],
        risk: "r0"|"r1"|"r2", budget_hint?: Budget, expected_gain?: number,
        needs_scope?: object[] }                                                   // 仅 reason 档
    | { op: "abandon_intent", intent: string, reason: string }                     // 仅 reason 档
    | { op: "claim_goal", candidate_path: string }
    | { op: "request_judge", target: string, judge_id?: string }
    | { op: "add_support"|"add_contradiction", target: string, premises: string[],
        artifacts: ArtifactId[], note: string }                                    // 完整版：verify、idler 档
  )[]
  final?: { outcome: "found"|"nothing"|"failed"|"unsolved",
            excluded_paths?: string[], suggestions?: string[] }
}
```

沙箱内的只读命令 `pd`：`pd show <id> [--layer evidence]`、`pd list`、`pd evidence [--grep]`（本会话已登记的工具输出）、`pd artifact cat <id>`、`pd status`。

会话状态机：`leased → preparing → running → collecting → released`；异常出口是 `expired`、`killed(budget)`、`failed(原因)`。Adapter 每 60 秒续租一次，租约 TTL 为 120 秒。

Adapter 的职责只有五件：渲染任务包；启动 CLI 并读取其事件流；把工具返回登记为 Artifact 并累计 token 用量；监视 outbox、校验并提交；释放租约并保存会话记录。

M0 的后端绑定（瘦基线所用的同一个 CLI）[证据：该 CLI 官方文档，不在调研编号内]。这九项同时是其它后端的准入清单：

| Adapter 需要 | 该 CLI 提供的机制 |
| --- | --- |
| 无交互运行与事件流 | `-p --output-format stream-json --verbose`；首个事件 `system/init`，末行 `result` |
| 可复现的启动 | `--bare`：跳过宿主的钩子、插件同步、自动记忆与项目说明文件的自动发现；鉴权只认 API 密钥 |
| 注入任务包 | `--append-system-prompt-file` 放①到⑤，提示词放⑥⑦ |
| 截取证据 | 流中 `user` 消息的 `tool_result` 块，与 `assistant` 消息的 `tool_use` 块按 id 配对 |
| 会话标识与续接 | `--session-id` 取租约派生的 UUID；修复轮与收尾轮用 `--resume` |
| 回合与花费上限 | `--max-turns`、`--max-budget-usd`（按客户端估算执行，可能略超） |
| 计量 | 每步 `usage` 按消息 id 去重，输出 token 以 `result` 为准；`total_cost_usd` 是估算值 |
| 终止 | SIGINT 结束当前回合；SIGTERM 终止进程树，退出码 143 |
| 工具面 | `--tools` 限定内置工具，`--allowedTools` 预先放行；`--permission-prompts none` 让其余需要人批的调用直接被拒 |

#### 3.4.3 完整版

`verify` 与 `idler` 两个受限档位（操作白名单由图服务按租约档位强制，不靠提示词）；复审任务包不含目标论断的正文，`pd` 对其拒绝读取，以保证干净上下文；第二、第三种 CLI 后端；自研薄循环的插槽 [证据 S3]；经模型网关的按任务密钥。

#### 3.4.4 必答

**CLI 输出解析的容错。** 分五级。Schema 校验失败时，把错误列表回注到同一会话，最多修两轮。仍不合格则逐条抢救，合格的操作照常提交，不合格的记入日志。会话结束时 outbox 为空，则追加一轮收尾，要求写出结论或声明 unsolved。仍为空，任务记为 `failed(no_output)`，会话记录照存，Intent 回到 open 并累计尝试次数，两次后放弃。某个后端的失败率超过阈值时，哮天犬发出 `backend_unhealthy` 告警交人处理。常规路径不需要人介入。

**心跳与超时回收。** 续租的条件是 CLI 进程存活且事件流在 10 分钟内有新事件；否则 Adapter 终止会话并以 `failed(stalled)` 释放。Adapter 自身崩溃时租约到期，由哮天犬提交 `expire_lease`，Intent 回到 open。已经通过 outbox 提交的论断不受任务失败影响，这就是"个体会死，图存续" [证据 Z4]。孤儿沙箱按标签回收。

**协议层如何拒绝伪造观察。** 两道确定性检查。Adapter 侧：操作里引用的 ArtifactId 必须在本会话的证据索引或图中存在，否则不提交并回注修正要求。图服务侧：观察类论断没有 check 或没有可采信的 grounds，返回 `missing_evidence`；summary 与正文里的叙述从不被当作证据。

**一个 Worker 能否同时认领多个任务。** 不能。一个会话对应一个任务和一个租约；一个 Explore 任务只处理一个 Intent。一个 Adapter 进程可以并行管理多个会话，各用各的沙箱。

#### 3.4.5 验收测试

1. 用脚本化的假 CLI 走通主路径：事件流中的工具返回被登记，outbox 中的论断被提交。
2. 畸形 outbox：一轮修复后通过；持续畸形时逐条抢救。
3. 任务中途杀掉 CLI：租约到期，Intent 重开，此前提交的论断仍在。
4. **伪造观察（对抗）**：summary 里写着"输出显示……"但没有 Artifact 引用，被拒；引用了不属于本会话也不在图里的 id，被拒。
5. 前缀稳定性：连续两次 Reason 的任务包，在只有新增节点的情况下，公共前缀不少于前一个包的 90% 字节。字节稳定是缓存命中的必要条件而非充分条件，所以集成测试另外断言：同一 `as_of_seq` 下先后启动的两个 Explore 会话，后一个的首次请求缓存读 token 数大于 0。
6. 闲人档提交 `add_intent`：被图服务拒绝。

#### 3.4.6 最简反事实

砍掉它就无法运行。能砍的是复杂度：Adapter 不做规划、不做重试策略、不解释领域内容。

---

### 3.5 契约 5：预算账本

#### 3.5.1 决策日志（备选与取舍）

| 议题 | 选定 | 被否方案 | 理由 |
| --- | --- | --- | --- |
| 账本形态 | 契约 1 日志上的一个投影 | 独立记账服务 | 预留与租约必须原子；重放即对账 |
| 检查时机 | 申请租约时预留 | 每条提议都查预算 | 提议路径不碰预算，不会被拖慢 |
| 计量点 | M0：Adapter 从事件流累计；M1：模型网关 | 只信 CLI 结束时的自报 | 自报在崩溃时丢失；网关还能按任务密钥拒绝超支调用 |

#### 3.5.2 M0 最小版

```ts
type CostEvent = { task_id: string, source: "adapter_stream"|"cli_reported"|"judge"|"gateway",
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
- 任务的软线是预留额的 90%，硬顶是预留额；题的硬顶是 `cap`。后端自带花费上限时，Adapter 把预留额同时传给它，作为进程内的第二道线。
- 哮天犬是不含任何策略的脚本，每 10 秒读一次 `/budget`：任务越过软线，通知 Adapter 进入收尾轮；越过硬顶或题预算耗尽，终止进程、销毁沙箱。

#### 3.5.3 完整版

模型网关：每个任务一把虚拟密钥，带额度，任务结束即吊销，同时承担多厂商路由 [证据 S15]。项目级预算与多题配额。按判官、按档位的成本报表。

#### 3.5.4 必答

**预算如何进入 Intent 而不拖慢提议路径。** Intent 的 `budget` 只是一个字段，创建时图服务只做区间裁剪。预留发生在申请租约时，计量是异步追加的 `cost` 事件。提议提交路径上没有任何预算计算。

**欠费任务的优雅终止与状态保全。** 软线留出的 10% 用于一轮收尾：Adapter 向会话注入"预算将尽，把已得结论写入 outbox，未完成的标为 unsolved"。越过硬顶则不再给模型任何回合，直接终止。保全四样东西：会话记录、outbox 中可抢救的操作、工作目录的打包、租约释放结果 `budget_exhausted`。不做自动续跑：是否追加投入由下一次 Reason 决定，它可以新开一个引用旧结果的 Intent。题预算耗尽时，题以 `unsolved` 关闭，报告由投影确定性生成，内容是已排除的路径和按等级排序的论断。

M0 已知缺口有三个。其一，沙箱内嵌套启动的模型会话不经过 Adapter 的事件流，不被计量。其二，CLI 报告的金额是客户端估算而非账单，会话崩溃时可能拿不到终值，此时该任务按预留额记满。其三，沙箱里放着模型密钥，被目标内容诱导的 Worker 可能把它带出去。M0 的兜底是一把在供应方一侧设了消费上限的专用密钥；M1 用网关和按任务签发的临时密钥关闭这三个缺口。

#### 3.5.5 验收测试

1. 三个并发租约的预留之和超过上限：只有放得下的被批准。
2. 越过 50%：进入预算复盘期，`/work` 不给出 explore，直到带 `reflect` 的 reason 释放。
3. **预算穿透（对抗）**：任务结束后沙箱内仍有后台进程尝试调用模型。期望沙箱已销毁，进程不存在；M1 起再加一条，密钥已吊销，调用被网关拒绝。
4. 终止路径：越过软线后出现收尾轮并带回部分结果；越过硬顶后进程被杀，租约释放，会话记录保存到被杀之前。
5. 重放后账本投影与运行时的合计一致。

#### 3.5.6 最简反事实

砍掉它，成本失控，而且"每题成本"这个北极星指标本身就无从计算。保留；M0 的实现是一种事件加一个 60 行左右的脚本。

---

### 3.6 契约 6（补）：执行层

缺失检测的结论：授权范围的拒绝、审批门、证据采集，这三项基座级保证的强制点都在命令实际执行的地方，原五契约没有覆盖。

#### 3.6.1 决策日志（备选与取舍）

| 议题 | 选定 | 被否方案 | 理由 |
| --- | --- | --- | --- |
| 审批门的位置 | Intent 粒度 + 能力注入：未获批准的任务，其沙箱里根本没有执行该动作所需的凭据或网络通路 | 逐条命令拦截 | 与具体 CLI 无关；不依赖模型如实申报每条命令的风险 |
| 越界的处理 | 沙箱默认拒绝并留日志 | 靠提示词约束 | 目标关闭后转去扫描宿主网络的事故说明提示词不够 [证据 S13] |
| M0 隔离 | 容器 | bwrap、虚拟机 | 一人两天可完成；强对抗场景再上虚拟机 |

#### 3.6.2 M0 最小版

```ts
type SandboxProfile = { id: string, isolation: "container", image: string, baseline_ref: string,
  network: { egress_allow: string[] },         // 由 Problem.scope 编译而来，默认全拒
  credentials: string[],                        // 只有已批准的 Intent 才会注入
  limits: { cpu: number, mem_mb: number, pids: number, wall_s: number },
  capture: "transcript"|"broker" }
type Approval = { intent: string, by: string, scope_amend?: Problem["scope"], waive_premise?: string[] }
interface Executor {
  compile(scope: Problem["scope"], base: string, grants: Approval[]): SandboxProfile   // 确定性
  launch(profile: SandboxProfile, lease_id: string): SandboxId
  reset(id: SandboxId): void                    // 回到 baseline
  destroy(id: SandboxId): void
}
```

内核不理解 `scope` 里的 `resource`，由执行层按资源种类的编译插件解释。越界访问被拒后，执行层追加 `scope_violation {task, resource, target}` 事件；同一任务累计 3 次，哮天犬终止该任务。Worker 认为确需扩大范围时，只能由 Reason 提出带 `needs_scope` 的 Intent，进入 `needs_human`，由人用 `approve --scope-amend` 决定。范围修订对全题生效，此后编译的沙箱（含判官沙箱）都带上它；r2 动作的凭据则只注入获批的那一个 Intent。

#### 3.6.3 完整版

broker 采集：模型所在的容器不持有任何写令牌，命令经执行代理在另一个容器里运行，输出由代理登记，`exec(id, argv, timeout_s) → ArtifactId`。两个容器的网络分开：模型容器只能连模型网关，执行容器只能连授权范围，模型密钥因此到不了目标一侧。虚拟机隔离。r2 动作的凭据按次签发、用后即废。请求频率上限。

#### 3.6.4 验收测试

1. 访问授权范围之外的地址：连接被拒，日志里出现 `scope_violation`。
2. 未经批准的 r2 Intent：即使被错误地调度，沙箱内也不存在对应凭据。
3. 判官沙箱与 Worker 沙箱互不可见：Worker 写入的文件在判官的洁净沙箱里不存在。

#### 3.6.5 最简反事实

砍掉它，"越界动作直接拒绝并记录"没有执行点，审批门退化为提示词里的一句话。保留最小形态。

---

## 4. 三个机制

### 4.1 司南（调度）

司南是一个不含模型、不持有权威状态的循环。调度所需的判断来自 Reason 写进 Intent 的字段，司南只做排序、限流和启动。

```ts
type WorkItem = { kind: "bootstrap"|"reason"|"explore"|"judge"|"verify"|"idler"|"retro",
                  target?: string, est: Budget, risk?: "r0"|"r1"|"r2", expected_gain?: number,
                  reflect?: boolean }            // 仅 reason：预算复盘期由图服务置位
type Launch   = { kind: WorkItem["kind"], target?: string, reserve: Budget, tier: "strong"|"mid"|"cheap",
                  reflect?: boolean }            // 照抄 WorkItem；停滞规则下由司南置位
type SinanCfg = { explore_concurrency: number, race_k: number, idler_share: number,
                  hint_debounce_s: number, stall_rounds: number }
function plan(work: WorkItem[], budget: BudgetView, axes: Axes, active: Lease[], cfg: SinanCfg): Launch[]
// 纯函数。主循环：读 /work 与 /budget → plan → 逐个申请租约 → 201 交给 Adapter 启动，409 丢弃
// judge 项由判官运行器自取，司南不管
```

- **多实例。** 两个实例抢同一目标时由图服务的租约裁决。司南崩溃后重读 `/work` 即可继续；它的决定已经体现为租约事件，不另记。
- **资格与优先级分开。** "能不能做"由图服务派生（T-0），"先做哪个"由司南决定（T-1）。司南出错的最坏后果是浪费预算，证据不受影响。

| 任务 | 可写的 outbox 操作（图服务按租约档位强制） | 触发 | 并发 |
| --- | --- | --- | --- |
| Bootstrap | `add_fact`、`claim_goal`、`request_judge` | 题目开始 | 1 |
| Reason | `add_intent`、`abandon_intent`、推断类 `add_fact` | 见 3.1.2 | 每题 1 |
| Explore | `add_fact`、`claim_goal`、`request_judge` | Intent 为 open | M0 固定为 3 |
| Verify（完整版） | `add_support`、`add_contradiction`、`request_judge` | 消费门派生的 `verify_wanted`，或争议待裁决 | 受验证池限制 |
| 闲人（完整版） | 不带支持的 `add_fact`、`add_contradiction` | 定时，花费不超过 `idler_share` | 1 到 2 |
| 复盘（完整版） | Playbook 候选 | 题目关闭后 | 1 |

M0 只有三条规则：

1. **先瘦后厚。** 题预算默认取瘦基线单题上限的 3 倍，`bootstrap_share` 默认 1/3，所以 Bootstrap 的预算正好是一次完整的瘦基线运行，它的提示词就是瘦基线的提示词加 outbox 说明。易题上成本倍数约为 1；同模型、同外壳、同预算之下，庖丁的解题率在期望上不低于瘦基线 [观点]。
2. **Reason 互斥，有触发才运行。** ARTEX 的 Planner 是同样的形态：唯一的意图生成者，事件驱动，防抖唤醒，每次全新会话 [证据 Z5]。
3. **Explore 固定并发 3**，按 Intent 创建顺序认领。

完整版的扇出控制器（八仙，T-1，开关为"固定并发"）是 `plan` 里的一张规则表：

| 输入 | 规则 |
| --- | --- |
| info=partial | 广度优先：并发 3 到 5，按 `expected_gain ÷ budget` 降序；共享同一前提的 Intent 同时最多 2 个 |
| info=complete | 深度优先：并发 1 到 2，沿依赖链推进；对卡住的 Intent 开 `race_k` 条策略正交的路线，先过判官者胜，其余取消 [证据 S15][S16] |
| judge=hard 且判官廉价 | 放宽并发上限，候选交判官筛 |
| judge=deferred 或 none | Explore 并发不超过 2，`verify_share` 上调 |
| Intent.risk=r2 | 并发 1；必须已审批；采集路径必须是 broker |
| 剩余预算低于 20% | 并发 1，只取 `expected_gain` 最高的一个 |
| 连续 `stall_rounds` 轮 Reason 之后没有任何节点升级 | 只放行带 `reflect` 标志的 Reason；再停滞则转 `needs_human`。追加会话多半只让死胡同变长 [证据 S13] |
| 同一 `as_of_seq` 的一批会话 | 错峰启动：第一个会话出现首个模型输出后再起其余，后者才能读到前者写下的前缀缓存 [证据：厂商 API 文档，不在调研编号内] |

人的通道：

```
pd problem open <problem.yaml>         pd status|report <pid>        # 确定性投影，不调用模型
pd hint add [--node <id>] "<文本>"      pd hint close <hid>
pd approve <intent> [--scope-amend <规则>] [--waive-premise <fact>]   pd deny <intent> --reason "<文本>"
pd pause|resume <pid>
# 完整版
pd rule <fact> --refuted|--upheld --reason "<文本>"    pd accept|reject <pid>
pd budget add <pid> <金额>             pd judge revoke <id>@<版本>
pd intent add <intent.yaml>            pd intent abandon <intent> --reason "<文本>"
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
5. 多厂商路由放在模型网关 [证据 S15]，网关同时承担按任务密钥、计量与故障回退。"异构"用本文件登记的 `family` 判定，不看模型名。
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

- **淘汰。** 使用不少于 5 题且胜率低于同期整体胜率，或连续 3 题加载后未解出，标为待复核，由人确认后 `kit_retired`。这个统计有选择偏差（难题更容易触发加载），所以自动规则不直接下架；整体收益用 `kits=off` 消融臂衡量。
- **防投毒。** 来源只限本项目自己的日志，不接第三方技能市场，公开市场有 12% 到 20% 的条目含恶意指令 [证据 S34]。无法追溯到 E3 论断的步骤在发布时被确定性检查拒绝。发布要人审并签名，Worker 沙箱对锦囊目录只读，加载时校验哈希。内核只认识锦囊的名称、哈希、描述三个字段。

---

## 5. 对抗性自检与其它自检

### 5.1 攻击与退化场景

影响与概率各按 1 到 5 打分 [观点]。

| # | 场景 | 影响 | 概率 | 分 | 对策 |
| --- | --- | --- | --- | --- | --- |
| 1 | 回声室晋级：同源模型互相确认，把错误推断抬到 E2 并被消费 | 4 | 4 | 16 | 见 5.2 |
| 2 | 证据挪用与空谓词：引用真实但不相干的 Artifact，或谓词恒真而标题夸大 | 4 | 4 | 16 | 见 5.2 |
| 3 | 判官被骗：改测试、静默告警、压掉流量让指标"恢复"，或对判官穷举 | 5 | 3 | 15 | 见 5.2 |
| 4 | 目标内容的提示注入：环境里的文本诱导 Worker 越界、带出密钥或提交假结论 | 4 | 3 | 12 | 写入全经确定性校验；沙箱默认拒绝出站；M1 起沙箱内只有按任务的临时密钥；完整版把模型容器与执行容器的网络分开（3.6.3） |
| 5 | 预算穿透：嵌套会话、后台进程、输出洪泛 | 3 | 4 | 12 | 租约预留、硬顶终止、沙箱随任务销毁；M1 网关按任务密钥拒付（3.5） |
| 6 | 图污染：垃圾节点洪泛、近重复节点、Intent 膨胀 | 3 | 4 | 12 | 每任务写入配额；列表上限与确定性省略；无人认领的 Intent 过期；闲人预算封顶 |
| 7 | 越界与沙箱逃逸 | 5 | 2 | 10 | 默认拒绝加 `scope_violation` 三次终止；强对抗场景用虚拟机 [证据 S13]；r2 凭据按次签发。已有沙箱逃逸波及真实系统的报道 [待核 Z13] |
| 8 | 验证活锁：判官反复无结论，或争议长期悬置 | 3 | 3 | 9 | 去重键、每键 2 次上限、转 `needs_human`；r0 永不阻塞（3.1.4） |
| 9 | 时效误判：环境变化被记成证伪 | 4 | 2 | 8 | 第四轴 `drift`，过期与证伪分开（A7） |
| 10 | 单写者故障或日志损坏 | 4 | 2 | 8 | 落盘后应答、幂等重试、快照带状态哈希、哈希链可校验 |

### 5.2 前三名的完整对策

**场景 1：回声室晋级。**

- 结构：E3 与 X 只来自判定性判官，模型之间的一致最多到 E2。`heterogeneous` 要求模型家族不同或引入新的执行证据；`independent` 用 Adapter 记录的 `context_manifest` 判定，复审任务包不含被审论断的正文。支持的强度不超过其前提的最低等级，最小不动点让互证的环得不到等级。
- 消费：r2 只认 E3，或 E2 加人对该前提的逐条豁免。
- 度量：M1 起统计 E2 误晋级率，即到过 E2、后来被判定性判官否定的论断占比。超过 10% [假设] 时把 E2 的条件收紧为"必须含新的执行证据"。
- 残余：不同家族的模型可能共享同一条错误知识 [观点]。所以 E2 在报告里始终写作"模型共识"，不写"已验证"。

**场景 2：证据挪用与空谓词。**

- 结构：观察类论断的内容是谓词本身，title 与 summary 只是标签。等级来自判官在洁净环境里对谓词的重放，不来自被引 Artifact 的存在。
- 承认的缺口："谓词为真，但标题说得比谓词多"无法由确定性代码判定。三层缓解：重放过程中没有访问任何授权资源或 input 材料的规格，判官返回 `inconclusive`；Verify 可以提出"标题超出谓词"的反证，使节点进入争议；审批卡片与报告展示的是谓词和判官输出，不是标题。
- 兜底：Goal 判官不读任何中间论断。被夸大的 E3 论断会浪费预算，但造不出假的 Goal 达成。
- 度量：M1 抽样审计 E3 观察类论断，统计标题超出谓词的比例。

**场景 3：判官被骗。**

- 资产固定：判官用到的测试、断言与配置作为 input 类 Artifact，以哈希写进 Problem；Worker 沙箱对其只读，判官运行前校验哈希。
- 环境独立：判官在自己的沙箱里从 `baseline_ref` 起步，只接收候选产物（补丁、答案、重放规格），不接收 Worker 改动过的工作区。候选产物能触及的路径由判官配置里的白名单限定。
- 守护指标：指标类判官除目标指标外还断言一组守护项（流量没有被压到零、告警没有被静默、采样率未变），任一项失败即 `fail`。守护项写在领域的判官配置里。
- 先登记后行动：r2 Intent 的预测在批准时登记，动作之后不可改。
- 防穷举：Goal 判定有次数上限；失败只返回原因类别，不返回期望值。
- 判官自身：每个判官版本附正反样例，注册前必须全部通过；出错后撤销版本，等级重算。
- 残余：人把判官规格写错。只能靠样例与复核，基座不解决。

### 5.3 通用性自检

内核 Schema 里没有领域词：`scope.resource`、`check.expect`、`sandbox_profile`、锦囊正文对内核都不透明。检查出四条隐含假设：

| 隐含假设 | 在哪里不成立 | 处理 |
| --- | --- | --- |
| 环境可以重置到基线 | 运维、临床 | `record_match` 与延迟判官不需要重置；`drift` 轴；M0 只承诺 static |
| 动作都是沙箱里的命令 | 需要人去做的检查或操作 | Intent 进入 `needs_human`，结果作为 input 类材料回到图里（开放问题 6） |
| Goal 是单个谓词 | 数学的引理链、工程的多项验收 | 完整版的子目标与 `done_check` |
| 观察能写成退出码与输出的谓词 | 证明检查、影像判读 | `expect` 由各判官自行解释，内核不看 |

### 5.4 缺失检测

除已补的执行层（契约 6）外，任务书没有点名而基座必须有的：

| 缺失项 | 处理 |
| --- | --- |
| 评测台：三条基线臂、消融开关、报告 | 列入 M1（§7），与基座同仓 |
| 事件模式的版本与迁移 | Event 带 `v`，reducer 按版本解释（3.1.2） |
| 报告生成 | `pd report` 是确定性投影，题目未解出时同样产出（3.5.4） |
| 采集内容里的敏感信息 | Blob 按题隔离访问，完整版按题加密；采集时不改写内容，以免破坏哈希 |
| 人的身份与审批留痕 | M0 为本机单用户；完整版对 `approve` 与 `rule` 事件签名 |
| 工具层（如意） | 不单设契约：CLI 自带工具加 `pd`，领域工具随锦囊带入 |

### 5.5 三个机制与证据梯的最简反事实

各契约的结论见 3.x.6。其余四项：

| 对象 | 砍掉后退化为 | 结论 |
| --- | --- | --- |
| 扇出控制器 | 固定并发的循环，即 M0 形态 | M2 消融决定 |
| 模型分层 | 全部同档，即 M1 首轮形态 | M2 消融决定 |
| 通鉴与锦囊 | 没有跨题记忆 | M4 之前不建管线 |
| E1 与 E2 两级 | 二值证据（E0 与 E3） | M1 的 `ladder=binary` 消融决定 |

---

## 6. 两个走查

记号：n 为论断，i 为 Intent，a 为 Artifact，h 为 Hint。金额按 §8 的价目估算，均为 [假设]。

### 6.1 一道 CTF Web 练习题（M0 能力即可走完）

Problem：四轴 `{partial, hard, r0, static}`；scope 只有题目主机一条网络规则；Goal 判官为 `exact_match`（对照预置答案的哈希），`max_attempts=5`；题预算 11.5 美元。

| 步 | 发起者 | 事件或操作 | 结果 |
| --- | --- | --- | --- |
| 1 | 人 | `open_problem`；题面登记为 input 类 a_1 | `/work` 给出 bootstrap |
| 2 | 司南 | bootstrap 租约，预留 3.8 美元 | Adapter 起沙箱（出站只放行题目主机），启动 CLI |
| 3 | Bootstrap | 若干只读探查命令 | Adapter 登记 exec 类 a_2 到 a_9 |
| 4 | Bootstrap | outbox：n_1（观察，"入口页引用了某接口路径"，check 为 `replay` 加 `stdout_contains`，grounds 为 a_3）；n_2（推断，"该接口对两类请求的处理不一致"，premises 为 n_1） | 校验通过，n_1、n_2 为 E0 |
| 5 | 判官运行器 | 在洁净沙箱重放 n_1 的规格，`judge_verdict pass` | n_1 为 E3，n_2 仍为 E0 |
| 6 | 哮天犬、Adapter | Bootstrap 越过软线，进入收尾轮 | `final.outcome=unsolved`，附已排除路径；租约释放 |
| 7 | Reason | 只读图；`add_intent` i_1、i_2、i_3，均为 r0 | 三个 Intent 为 open |
| 8 | 司南 | 三个 explore 租约 | 三个会话并行。其间花费越过 50%，图服务追加 `budget_mark`，进入预算复盘期 |
| 9 | 人 | **Hint 注入**：`pd hint add "题面提到'备份'，优先看与备份相关的路径"` | h_1 入图；`/work` 给出 reason；在途会话不受影响 |
| 10 | Reason | 第 2 轮，带 `reflect`，任务包的 `focus.hints` 含 h_1；先写出已排除路径，再 `add_intent` i_4 | 复盘期结束；i_4 为 open |
| 11 | Explore(i_4) | n_5（观察，重放后 E3）："某路径可取得一个归档文件"。归档内容指向第二个主机，连接被执行层拒绝 | `scope_violation` 事件；Worker 在 `final.suggestions` 里说明 |
| 12 | Reason | 第 3 轮：`add_intent` i_5，带 `needs_scope`（第二主机） | i_5 为 `needs_human` |
| 13 | 人 | **审批门**：核对该主机属于题目环境后 `pd approve i_5 --scope-amend net:<主机>:<端口>` | `approve` 事件；i_5 为 open；此后编译的沙箱放行该主机。若拒绝，i_5 为 abandoned，Reason 另寻路线 |
| 14 | Explore(i_5) | outbox：`claim_goal`，候选答案存为 authored 类 | Adapter 提交 `request_judge`，目标为 goal |
| 15 | 判官运行器 | `exact_match` 通过 | Goal 获得判定性支持，为 E3；图服务 `close_problem`；其余租约取消，沙箱销毁 |

花费约 10 美元：Bootstrap 3.8，Reason 三轮 1.4，Explore 五个会话 5.0，判官可忽略。80% 标记落在第 14 步进行中，题目在下一次复盘之前关闭。`pd report` 给出解题链（由 yields 与 derives_from 边连成，链上论断均为 E3）和被排除的路径。

### 6.2 一次运维根因分析（需要完整版能力，M4 之后可走完）

Problem：四轴 `{partial, deferred, r2, drifting}`；scope 为某命名空间的遥测只读与编排系统只读；Goal 是目标指标回到阈值内并保持 30 分钟，且根因论断经人验收（`accept=human`）。

| 步 | 发起者 | 事件或操作 | 结果 |
| --- | --- | --- | --- |
| 1 | 人 | `open_problem`；告警快照与症状清单登记为 input 类 | `/work` 给出 bootstrap |
| 2 | Bootstrap | 只读查询；n_1（观察，"02:00 到 02:30 接口错误率升高"）、n_2（观察，"同时段数据库连接等待时间升高"），check 为 `record_match`，查询固定时间窗 | 采集路径为 broker，判官为判定性，两者 E3。固定时间窗的历史数据不设有效期，"当前状态"类观察才带 `valid_until` |
| 3 | Reason | i_1 查变更记录、i_2 查依赖方、i_3 查资源水位，均为 r0 | 判官非 hard，Explore 并发取 2 |
| 4 | 人 | **Hint 注入**：`pd hint add "02:05 有一次连接池配置发布"` | Reason 下一轮据此提出 i_4：核对该次发布的内容与时间线 |
| 5 | Explore(i_4) | n_6（观察，"02:05 的发布把连接池上限由 A 改为 B"）；n_10（推断，"根因是连接池上限下调"，premises 为 n_1、n_2、n_6） | n_6 为 E3，n_10 为 E0 |
| 6 | Reason | `add_intent` i_7："回滚该配置"，risk=r2，premises 为 n_10，附预测"回滚后 10 分钟内错误率低于阈值并保持 30 分钟" | 消费门不满足，i_7 为 blocked；派生 `verify_wanted(n_10, E2)` |
| 7 | Verify 两次 | v_1 用另一模型家族，任务包不含 n_10 正文，写复审支持；v_2 引入新的执行证据（同时段未改配置的服务没有该症状） | n_10 先到 E1，再到 E2 |
| 8 | 闲人 | 反证："同时段流量也在上涨"，附 exec 类 Artifact | n_10 进入争议。裁决任务核对时间先后（流量 01:30 已上涨，错误率 02:05 才升高），反证被驳回 |
| 9 | 图服务 | i_7 转 `needs_human`；审批卡片由投影确定性生成 | 卡片列出：动作与回退方法、n_10 的等级与支持记录、未决争议（无）、预测 |
| 10 | 人 | **审批门**：`pd approve i_7 --waive-premise n_10` | 预测登记为延迟判官 `outcome_match`；i_7 为 open |
| 11 | 司南、执行层 | 并发 1；为 i_7 的沙箱注入一次性变更凭据，采集路径 broker | Worker 执行回滚，输出登记为 exec 类；提交 n_11（观察，"回滚后指标恢复"） |
| 12 | 延迟判官 | 到期运行指标断言与守护项，通过 | n_11 为 E3；`outcome_match` 随之通过，等级为相符性，n_10 为 E3d |
| 13 | 人 | 报告写明：根因 n_10 为 E3d，未做副本反事实；被排除的解释一条。`pd accept` | 题目关闭，Goal 标为"已验收" |

两个分支。有副本环境时，再开一个 r0 的 Intent 做双向反事实，判定性判官通过后 n_10 到 E3。观察窗内复检失败时，n_11 的支持失效，n_10 回到 E2，Goal 不成立，`/work` 重新给出 reason，回滚动作的记录保留。花费约 8 美元。

---

## 7. 路线图与 M0 实施清单

| 里程碑 | 内容 | 出口条件 |
| --- | --- | --- |
| M0（3 周，1 人） | 六个契约的最小版；一个 CLI 后端；一道练习题端到端 | 下表 D15 |
| M1（再 2 到 3 周） | 评测台：20 题、B1/Bk/Bn 三臂、消融开关；E1/E2 与 Verify；争议；r1 与 r2 消费门的完整形态（含前提豁免）；模型网关 | §8.3 的 G1 到 G3；每个已启用的 T-1 结构各有一条消融结果 |
| M2 | 闲人、模型分层、扇出控制器；题集扩到 50 | 三者各自的消融结果，没有带来增量的删除 |
| M3 | 内核增量：子目标、`drift`、延迟判官。之后接入第二个领域（数学或软件工程） | 接入第二个领域时内核代码零改动，只新增锦囊与判官配置。这是红线 3 的验收 |
| M4 | 通鉴管线；多节点（PostgreSQL、对象存储）；broker 采集、r2 凭据按次签发、虚拟机 | 锦囊消融为正；r2 场景的证据全部来自 broker |

北极星是一对数：解题率与每题成本，始终与三条基线并排报告。任务书写作"每题成本 × 解题率"；两者方向相反，乘积无法排序，所以需要合成一个数时用每解出一题的成本（总成本 ÷ 解出题数）。

M0 实施清单（15 个工作日）：

| 日 | 交付 | 当日验收 |
| --- | --- | --- |
| D1 | 仓库骨架；事件信封、JCS 规范化、哈希链；SQLite 日志；重放测试台 | 3.1.5 的 1 |
| D2 | reducer 的 `validate` 与 `apply`；M0 等级函数与消费门；操作与档位的授权表 | 3.1.5 的 3、4、6 |
| D3 | 租约、`/work` 派生、过期、幂等；崩溃恢复 | 3.1.5 的 2、5、7 |
| D4 | Blob 仓库、Artifact 登记、可采信检查、组件令牌 | 3.2.5 的 1、3、4，以及 2 的前四种形态 |
| D5 | 读接口与投影目录；`pd` 命令行（只读部分、`problem open`、`hint`、`approve`） | 手工开一道题并查看 `pd status` |
| D6 | 执行层：容器启动器、出站白名单、scope 编译、`scope_violation` | 3.6.4 的 1、3 |
| D7–D8 | Adapter：任务包渲染、九项后端绑定、事件流截取、outbox 监视与修复轮、续租与释放 | 3.4.5 的 1 到 4 与 6（脚本化的假 CLI），再用真 CLI 跑通一次 |
| D9 | 判官运行器、`replay`、`exact_match`、抖动策略与次数上限 | 3.3.5 的 1、2、4、5、6 |
| D10 | 计量、预留、`budget_mark`、哮天犬、收尾轮 | 3.5.5 的 1、2、4、5 |
| D11 | 司南最小循环；bootstrap、reason、explore 三份角色提示 | 假 CLI 下走完 bootstrap、reason、explore、goal |
| D12 | 一道练习题端到端；`pd report`；轨迹导出 | Goal 为 E3，报告含完整解题链；3.4.5 的 5 |
| D13 | 对抗用例专日：坏事实注入、伪造 Artifact 五种、环状引用、伪造观察、预算穿透 | 全部通过并进入持续集成 |
| D14 | 瘦基线运行器 B1：同一 CLI、同一沙箱、同一 Goal 判官 | 同一道题的 B1 成本与结果入库 |
| D15 | 缓冲；M0 报告 | 报告含端到端日志、对抗用例结果、B1 对比、已知缺口清单 |

M0 不做：E1/E2、Verify、闲人、分层、扇出控制器、通鉴、网关、broker、r2 凭据注入（M0 的题目不含 r2 动作）、PostgreSQL、图形界面。最大的不确定项是 D7–D8，即真实 CLI 的行为与文档的出入；超期时先砍 D5 的投影目录（只留接口）和 D12 的报告排版。

---

## 8. 消耗预算与 M1 目标

### 8.1 价目与会话成本模型

本节数字除价目外全部是 [假设]，M0 的 D12 与 D14 会给出第一批实测值。

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
| 判官 | 无模型 | 沙箱运行数秒到数分钟 | 约 0 | 约 10 | 约 0 |
| 复盘（M4） | 强 | 42 / 2 / 1.5，7 | 0.5 | 1 | 0.5 |

- 题预算硬顶取 B1 跑满成本的 3 倍，即 11.5 美元。厚路径合计约 11 美元（Bootstrap、Reason、强档 Explore、Verify），落在硬顶之内；token 量约 1800 万，与 Cairn 每题约 2000 万（10.9 亿 ÷ 54 题）、sapper 每个 flag 约 1180 万（1B ÷ 85 个）处在同一量级 [证据 Z1][Z3][Z4，折算为本文所作]。
- 分层不降低被硬顶截断的题的成本，它让同一预算下的 Explore 会话数由 5 变为 10。这是否换来解题率，要靠消融。
- 三类题的单题成本：易题由 Bootstrap 在约 40 回合内解出，1.6 美元，B1 同为 1.6；中等题 Bootstrap 有一半机会解出，期望 6.8 美元，B1 为 3.2；难题跑到硬顶，11.5 美元，B1 为 3.8。

### 8.3 指标定义与 M1 目标

- 解题率 s：题集上 Goal 被判官确认的比例，每题重复 3 次取平均。
- 成本倍数 m：该臂总成本 ÷ B1 总成本，同题集、同价目表。
- **R = (s − s_B1) ÷ m**，单位是百分点每倍成本。任何一条臂都可以算。

题集 20 题（约 20 题即可起步评测 [证据 S37]），按 B1 的 3 次试跑分层：易 4 题（全过）、中 8 题（过 1 到 2 次）、难 8 题（全败，但有已知解法）。只取中段会让等成本重试的解题率逼近上限，无从比较；黑板声称的价值在难段 [观点]。

按三段单次解出概率 0.95、0.5、0.05 预估 [假设]：s_B1 约 41%；Bk（同一硬顶下最多重试 3 次）s 约 61%、m 约 2.2、R 约 9；庖丁 m 约 2.4。

| 目标 | 阈值 | 论证 |
| --- | --- | --- |
| G1 生死线 | 同一题预算硬顶下 s_P − s_Bk ≥ 10 个百分点；且难段至少有 2 题是庖丁在多数重复中解出、Bk 的 3 次重复全败 | 独立重试自己就能把解题率抬高约 20 个百分点。赢不了它，共享状态就没有价值，按红线 5 删除编队。10 个百分点即 20 题中的 2 题，是能与单题偶然区分的最小差距 [观点] |
| G2 成本 | m ≤ 3，由题预算硬顶强制；预估约 2.4 | 多智能体系统的 token 约为对话的 15 倍 [证据 S37]，单智能体约 4 倍 [待核：调研未摘录此数]，两者之比约 3.75；sapper 以 1B token 胜过 4.5B [证据 Z4]。3 倍处在已报告的高效一端 |
| G3 效率 | R_P ≥ R_Bk + 3；按预估即 R_P ≥ 12 | 由 G1 与 G2 推出：s_P ≥ 71%，m 约 2.4 |

执行规则：

1. 先跑 B1 与 Bk，用实测值重算上表并冻结，再跑庖丁。阈值不在看到庖丁结果之后调整。
2. M1 首轮所有角色与 B1 用同一个模型。
3. 20 题只能给出方向性证据，头部系统在更大的题集上尚且统计不可分 [证据 S1]。G1 未达标时，允许针对最大的失败模式修改一次并重测；仍未达标则删除 Reason 与 Explore 编队，保留证据账本、判官、预算与执行层，退回"瘦基线加判官"。M2 把题集扩到 50 后复核一次。
4. 同时报告 Bn。庖丁赢 Bk 却不赢 Bn，说明价值在共享而不在图与等级，此时把解牛图简化为追加写笔记加判官。

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
| 复盘 | retrospection | 预算节点上的反思，以及题目关闭后的提炼 |
| 如意 | tool layer | Worker 可用的工具：CLI 自带工具、`pd`、锦囊捆绑的脚本 |
| 锦囊 | skill kit | 按需加载的领域知识与脚本目录 |
| 通鉴 | cross-problem memory | 跨题的锦囊库与使用记录 |
| 哮天犬 | watchdog | 不含策略的脚本：过期租约、超预算终止、清理、告警 |
| 提议、租约 | proposal, lease | 待图服务校验的一批写操作；带预留预算与期限的任务认领 |
| Worker、Adapter | worker, adapter | 执行任务的 CLI 会话；在它与图服务之间做渲染、采集、提交的进程 |
| 瘦基线 B1 | thin baseline | 单个 CLI 会话，配同一沙箱与同一 Goal 判官 |
| Bk、Bn | equal-cost retries, shared-notes baseline | 同预算下的独立重试；多个 Worker 共用一份追加写笔记 |
| 四轴 | four axes | 信息完整度、判官类型、可逆性、时效性 |
| m、R | cost multiple, efficiency | 成本倍数与每倍成本换来的解题率增量，见 8.3 |

---

## 10. 开放问题

| # | 问题 | 选项 | 倾向 |
| --- | --- | --- | --- |
| 1 | E1 与 E2 是否保留为两级 | 保留；合并为一级"模型复核"；只留二值 | 先按两级实现，M1 的 `ladder=binary` 消融决定；两级的误晋级率没有差别就合并 |
| 2 | 证据采集路径 | 一律 transcript；一律 broker；按风险 | 按风险：r2 与非练习环境用 broker，其余用 transcript |
| 3 | 跨轮的前缀缓存 | 只靠会话内缓存；替换系统提示并划出静态段；自管循环 | M0 只靠会话内缓存并实测。Reason 的输入成本超过题成本的 15% 时再做第二项 |
| 4 | 在途会话是否接收 Hint | 下一个任务包生效；经流式输入即时注入 | 前者。中途干预要谨慎 [证据 S17]，且各后端支持不一 |
| 5 | Explore 用哪一档 | 全强；中档加失败升级；强档调低推理强度 | M1 全强，M2 三者做消融 |
| 6 | 需要人去执行的动作如何表示 | 新增节点类型；`needs_human` 的 Intent 加 input 类材料 | 后者，不增加类型 |
| 7 | 语义去重 | 不做；`same_as` 提议；嵌入聚类 | 不做，直到实测近重复节点超过 15%。嵌入聚类进写入路径会破红线 1，排除 |
| 8 | 何时迁到 PostgreSQL | M1；多主机时；不迁 | 多主机时（M4）。单写者加 SQLite 足以支撑到那时 [假设] |
| 9 | 单人项目的锦囊审核 | 逐条人审；抽审加自动标记；不审 | 逐条人审，数量小；有协作者之后改抽审 |
| 10 | Bootstrap 的长度 | 完整的瘦基线运行；短侦察后尽早扇出 | 前者作默认，`bootstrap_share` 做一条消融臂 |
| 11 | 题预算取瘦基线的几倍 | 2；3；5 | 3。M1 用实测的 R 曲线复核：倍数再加大而 R 下降就不加 |
| 12 | 与 v0.1 修订稿的出入 | 以本文为准；以 v0.1 为准；逐条对账 | 逐条对账。本文没有读到 v0.1 正文，需要你提供 |
