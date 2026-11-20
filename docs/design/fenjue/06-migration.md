# 06 迁移路线：从今天的代码到焚决

> 焚决设计 v0.1 的第六篇。上位：[README](./README.md)。本篇把已合入的每项能力放到新架构里（体质、功法的某个火位、药鼎），给出分期，并说明每一步怎么保证旧事件回放逐字节不变、已合入的功能不丢。
>
> 依据 `main` 17b2217。在途 PR 标“即将落地”：#105 续期门、#111 地图 v0.9–v0.10 与 L3 第三步、#114 资料库第二期、#115 会话活动面板。

## 1. 现有能力的落位

### 1.1 体质

| 能力 | 代码 | 体质项 |
| --- | --- | --- |
| 事件日志、信封、按题哈希链、重放 | `graph/…/eventlog.py`、`envelope.py`、`replay.py`、`jcs.py` | T4 |
| 纯函数内核 `validate` 与 `apply`、等级派生 | `graph/…/reducer/`、`levels.py`、`refmodel.py` | T4（等级派生同时守 T5） |
| 可做事项 `/work`（内核派生的许可） | `graph/…/work.py` | T4 |
| 卡片与所见绑定（`seen.card_hash`）、人的操作 | `graph/…/cards.py`、`reducer/intent.py`、`close.py` | T4（经脉 M6） |
| Artifact 出处分类、可采信检查、交付引用校验 | `graph/contract.py`、`reducer/problem.py`、`reducer/deliver.py` | T5 |
| 判官运行器、内建判官、保密库 | `judgebox/` | T1 |
| 判据推导与开题校验 `vet()`、开放道分流 | `qicao/vet.py`、`policy.py` | T1 |
| 外部裁决（定源登记、`bind_deadline`，#94/#96/#98） | `judgebox/connector.py`、`reducer/problem.py` | T1 |
| 人工验收（`accept: human`、验收清单，#103/#104） | `reducer/close.py` | T1 |
| 执行层：能力编译、闸门、执行留档 | `executor/` | T2、T5 |
| 运行时扩权（#91–#101） | `reducer/grants.py`、执行层热加闸门 | T2 |
| 双容器、端点代理、钥匙环、凭据认出与遮盖 | `adapter/…/container.py`、`proxy.py`、`keyring.py`、`creds.py` | T2 |
| 预算预留、代理计量与硬顶、哮天犬 | `reducer/lease.py`、`adapter/…/proxy.py`、`watchdog/` | T3 |
| 通鉴记忆条目的状态派生与召回复核（规格 v1.5 列为守门官） | `tongjian/` 的 reducer 与复核 | T5 |
| knowledge 类不入依据（#114 的 K1，即将落地） | `graph/contract.py` | T5 |

### 1.2 功法（第 0 阶：旧法）

| 火位 | 本火（拟名） | 今天在哪 | 备注 |
| --- | --- | --- | --- |
| H1 会话形态 | `h1.triad` 三段式（bootstrap、reason、explore） | `adapter/prompts/{common,bootstrap,reason,explore}.md`、`adapter/…/package.py`、`session.py` 的角色分支 | 严格道 |
| H1 | `h1.solo` 独行（solve） | `adapter/prompts/solve.md`、`session.py` 与 `package.py` 里的 `if role == "solve"` | 开放道 |
| H1 | `h1.recall` 召回（无模型） | `tongjian/runner.py` | 先于 Bootstrap |
| H2 编排 | `h2.sinan` 司南固定次序 | `sinan/…/loop.py`：`TASK_ORDER`、`_reserve`、`thin_bootstrap`、`order_by_gain`、`wait_for_judges` | 开放道：预留剩余全部、接力至多 5 个、墙钟 90% 叫收尾 |
| H2 | 模型路由（角色 → 档案） | 设置层的角色路由（#110）、`routing.yaml`（规格 4.2） | 档案与路由的数据在设置层；火只定“按什么选” |
| H2 | 续期门的触发策略（#105，即将落地） | 设置 `budget.extension` | 门的卡片与 `budget_add` 属体质（M6、T3），何时出卡属功法 |
| H2 | 开放道的追问、叫停、闲置关（#111，即将落地） | `follow_up`、`halt`、`idle_close_s` | 操作本身属体质（人的令牌、内核校验）；宽限秒数、闲置天数是功法参数 |
| H3 工具面 | `h3.base` | `adapter/…/tools.py`：`exec`、`submit`、`show`、`request_access`、`deliver` | |
| H3 | `h3.kb`（#114，即将落地） | `kb_search`、`kb_read` | |
| H4 上下文 | `h4.views-notes` | 任务包的三层视图（`package.py`）；开放道工作区 `NOTES.md` 接力；收尾轮 | 无压缩 |
| H5 知识源 | `h5.shuku` | `shuku/`：文字类导入、确定性切分、混合检索、hash 向量器 | 第二期 #114 即将落地 |
| H5 | `h5.tongjian-recall` | `tongjian/recall.py`、`match.py` | 召回是感知官；条目的状态派生在体质 |
| H6 观察面 | `h6.workbench` | `web/`：今日、任务、任务页四分栏、前沿、时间轴回放、成本仪表、⌘K | v5 视觉 |
| H6 | `h6.activity`（#115，即将落地） | `adapter/activity.py`、`/v1/leases/{id}/activity`、`web/src/ui/SessionActivity.tsx` | 案例一的异火臂 A′ |
| H6 | `h6.pd` | `pd/`：四语域文本 | |
| H7 报告形态 | `h7.result` | 任务页“结果”分栏：答案、结局、主张与证据、自检、未验证、花费 | 交付体的字段集属 T5 |
| H8 起草 | `h8.kaiti` | `qicao/draft.py`、`extract.py`（抽取器三档，#92）、`kaiti.d/` | 起草只指认原文区间 |

### 1.3 药鼎（量具）

| 能力 | 代码 |
| --- | --- |
| 读数投影：`by_authority` 四列、每解成本、归因表、折损账、按会话分账（#111 的 `by_lease`） | `graph/…/views.py` |
| 四臂对照评测台（B1、B1b、Bk、Bn、full）与固定记录格式 | `eval/` |
| 开放道读数隔离断言 | `graph/tests/test_open_lane.py::test_readings_*`、`eval/tests/test_open_lane_isolation.py` |
| 预算先验数据源（可插拔，“档位 → 默认预算”表外部注入；设计中为〔占位〕表） | 设置层 `GET /v1/settings/sources` |

预算先验数据源不是火，也不是量具里的读数，它是外部注入的数据。列在这里只是因为试火要从它取预算。

### 1.4 核对：已合入功能不丢

迁移的每一步都要过下面四条，写进该步 PR 的验收：

1. §1.1–§1.3 每一行在迁移后仍有归属，没有一行变成“无主”；
2. 现有测试全绿：全量 `uv run pytest`、`web` 的单测与两组 e2e（mock 与真实全栈）；
3. 所有现有开关照旧有效：`lanes.open`、`grants.runtime`、`budget.extension`（#105）、`lanes.idle_close_days`（#111）、各消融开关；
4. 金丝雀密钥测试照旧在每一期的验收里（宪章 D4 附加条件）。

## 2. 分期

每一步独立可合、可回滚。F0 是本 PR。

| 步 | 内容 | 动体质吗 | 做完后能怎样 | 回滚 |
| --- | --- | --- | --- | --- |
| **F0 设计与命名** | 本目录；命名方案 | 否 | 有一张图可以裁决 | 关 PR |
| **F1 体质试炼与黄金日志** | ① 把散在各组件的体质测试收拢为 `tests/fenjue/trials.py`（T1–T5；F2 起以“一套功法”为参数）；② 按道补录黄金日志（§3.2）；③ 把经脉表与席位权能上限表写成数据，`check_deps` 加禁止表 | 否（只加测试与检查） | 任何改动都能一键问“体质还在吗” | 删测试 |
| **F2 火位立名（零差迁移）** | 新组件 `fenjue/`（`paoding_fenjue`）：`Fire`、`Gongfa` 的形状、清单装载、摘要计算。适配层按 H1 形态清单装提示词、工具、收尾与接力规则，删去 `if role == "solve"` 一类分支；司南按 H2 清单取次序与预留规则；工具面按 H3 清单。第 0 阶的每团火写成清单 | 否 | 品阶 1：行为与第 0 阶逐字节相同（R4），从此可以吞 | revert；行为本来就相同 |
| **F3 功法摘要入事件** | `open_problem` 事件体加可选 `gongfa: {jie, digest}`，`lease` 加可选 `form`，均由 `validate` 写入、`apply` 原样存；读端推断缺省值 | **是，一次**：给 T4 加两个可选的审计字段。这是焚决自身需要的唯一一次体质修炼，单列裁决（FJ5） | 每道题用哪套功法做的可查；读数可按品阶分组 | 字段可选，停写即可；已写的照常回放 |
| **F4 首炼** | 案例一“可回放的实时性”（[05 §1](./05-cases.md#1-案例一可回放的实时性)）走完六步 | 否（目标 0 行） | 品阶 2（若判火莲或合炼）；第一份完整炼档 | 散火：开关指回 `h6.activity` |
| **F5 炼档流程化** | 炼档模板与 CI 检查（功法里的每团火要么是本火，要么有炼档与入库四问）；常设留出按火位分配；进化读数页（归 v5 线） | 否 | 吞噬成为日常动作 | 关检查 |

**F1 与 F2 的顺序不能反。** 先有试炼与黄金日志，才能证明 F2 是零差。

**F4 可以不等 F2。** 案例一不碰会话形态与编排，只在 H6 与适配层的活动流水里改；验体可以先用 F1 的试炼手动拼。若 cz 希望先看到一次真实的吞噬，F4 可以排在 F2 之前（FJ14）。

## 3. 旧事件回放逐字节不变

### 3.1 五条做法

1. **不改写任何已有事件。** 迁移没有一个脚本触碰事件表。所谓迁移，只发生在读端与新事件上。
2. **信封不升版。** `SCHEMA_VERSION` 仍为 1，字段集 `FIELDS` 不变。`ROLES` 只在体质修炼时变，新形态绑定已有席位（[01 §6](./01-boundary.md#6-席位会话的权能上限)）。
3. **新字段只加可选的，缺省即今天的行为。** F3 的 `gongfa` 与 `form` 都是可选；缺省时 `apply` 的结果与今天逐字节相同，因为它不写进任何派生量。
4. **缺省值在读端推。** 没有 `gongfa` 的题显示“第 0 阶（旧法）”，没有 `form` 的租约按席位推出形态。推断是读端的纯函数，不写回日志，也不进状态哈希。
5. **配置不进回放。** `validate` 把取值写进事件体，`apply` 不读配置（`reducer/__init__.py` 文首的约定）。所以任何功法配置下重放同一份日志，状态都一样（R2）。

### 3.2 黄金日志

今天只有一份 `graph/tests/fixtures/m1_log_golden.json`（规格 v1.5 之前录下，web 夹具）。F1 按道补录，每份都记状态哈希、各前缀哈希、各题 `/work` 与状态视图的摘要，录制后冻结：

| 黄金日志 | 覆盖 |
| --- | --- |
| `m1_log_golden.json`（已有） | 严格道三段式、判官裁决 |
| `strict_external.json` | 外部裁决、`bind_deadline` |
| `strict_human.json` | `accept: human`、验收清单、四顾逐条确认 |
| `open_lane.json` | 开放道：`deliver` 三种结局、接力、`close_problem.feedback` |
| `open_lane_l3.json`（#111 合入后录） | 追问、叫停、闲置关、`by_lease` |
| `grants.json` | `request_scope`、`grant_scope`、`revoke_scope` |
| `curate.json` | 归档、回收站、改名、置顶 |
| `knowledge.json`（#114 合入后录） | knowledge 类、`kb_query` |

在途 PR 合入后补录对应的那一份；补录不改已冻结的。每份都跑 R1 与 R2；F3 之后再跑一遍 R3（新旧事件混放）。

**F1 的实现记录（2026-11-20）。** 黄金日志不手写剧本，而是由 `tests/fenjue/record_goldens.py` 在既有内核测试运行时截下每个测试台（`graph/tests/conftest.py` 的 `Kernel`）的日志：这些测试本来就逐一构造了各道的事件形状。只收“用今天的 reducer 从头重放、状态与测试台当时逐字节相同”的日志，再按事件形状（种类、提交者、事件体的键与分道取值）贪心去重，每道另留最长的一份。冻结结果在 `tests/fenjue/goldens/`，按道八份：

| 文件 | 来源测试 | 日志数 | 事件数 |
| --- | --- | --- | --- |
| `strict_kernel.json` | 内核与隔离、租约、人的操作、`touches`、所见绑定、控制、开题能力、偏好、练习信封 | 51 | 1210 |
| `strict_recall.json` | 通鉴召回 | 5 | 24 |
| `strict_external.json` | 外部裁决 | 8 | 57 |
| `strict_human.json` | 人工验收 | 5 | 59 |
| `open_lane.json` | 开放道 | 9 | 70 |
| `grants.json` | 运行时扩权 | 13 | 62 |
| `curate.json` | 整理 | 4 | 19 |
| `knowledge.json` | 资料类（#114） | 5 | 28 |

设计时列的 `open_lane_l3.json` 等 #111 合入后录。原有的 `m1_log_golden.json` 留在原处照跑。`tests/fenjue/test_t4_zhang.py` 逐份重放比对（R1）；随手把 `reducer/deliver.py` 里交付的 id 前缀改一个字母，开放道的六份立刻变红。`tests/fenjue/test_tables.py` 把权能矩阵（每种令牌、每个席位能提交哪些事件）冻结成 `tests/fenjue/tables.py` 的数据，与 `_who` 逐格比对，并断言信封不升版（R5）。`check_deps` 的禁止表要等 F2 有了火的代码才有对象，挪到 F2。

### 3.3 零差迁移的判据（F2）

F2 改写的是适配层与司南的分支，不碰内核，但会话的行为可能被无意改动。判据：

- 同一组假 CLI 剧本（覆盖三段式、独行、接力、收尾、扩权、受阻），在 F2 前后各跑一遍；
- 两份事件日志去掉 `ts`、`hash`、`prev_hash` 后逐条比对 `kind`、`actor`、`body`，必须完全相同；
- 每个会话的任务包（提示词与 `package.py` 的输出）逐字节相同；
- 通过后才合。这条测试在 F2 合入后保留，作为“功法装载器”的回归。

**F2 的实现记录（2026-11-20）。** 剧本没有另写，用的是适配层、司南与全栈集成里既有的假 CLI 测试（`tests/fenjue/zero_diff.py`）。在适配层与司南一行未改的提交上跑两遍，截下每个测试里所有图服务的日志与每个会话的任务包，两遍相同的才收：177 个测试、1558 条事件、113 份任务包与每轮的工具和提示，冻结在 `tests/fenjue/zerodiff.json`。另有 15 个测试两遍就不同（并行会话的竞态），不收。

比的时候抹掉的东西，都是跑与跑之间必然不同、且与功法无关的：`seq` 与由它派生的 id（并行会话的事件交错次序不定）、`ts`、`hash`、`prev_hash`、幂等键里的随机任务令牌、临时目录、一句话开题题号的随机后缀、Blob 的 sha256，以及会话叙述与执行输出的大小、执行的起止时刻。种类、提交者与其余全部内容逐字比；任务包按原文比。原稿“去掉 ts、hash、prev_hash 后逐条比对”做不到，因为同一份代码跑两遍，这几样本来就不同。

提示词（各席位，扩权与资料两段的四种组合）、全部工具的形状与司南的次序另记一份 `@surface`，`tests/fenjue/test_zero_diff_surface.py` 在 CI 里每次都比。整套剧本较慢，手动跑 `--check`。

**F3 的实现记录（2026-11-20）。** 体质修炼 001，变更表与三问见 [tizhi-001-gongfa-in-events.md](./tizhi-001-gongfa-in-events.md)。内核只多两个不透明的配置值（`Config.gongfa`、`Config.forms`），由组装根从 `paoding_fenjue.kernel_config()` 取来；读端缺省（第 0 阶、按席位推形态）是功法组件里的纯函数。零差剧本里只有经组装根开题的 4 个测试变了，变的正是这两个字段；拿掉它们之后 178 项全部相同。此后 `zero_diff.py` 缺省不比这两个字段（摘要随每次吞噬而变），由 `tests/fenjue/test_f3_gongfa.py` 单独测。

**#111 合入后的补录（2026-11-20）。** #111（地图 v0.9：追问、叫停、交付后闲置自动关）在 F1 冻结之后合入，带来两种只有人能提交的新事件 `follow_up`、`halt`。它与 F2 合流后焚决检查转红，由 #121 修回（旧日志重放逐字节不变、权能矩阵的人一行增补、`h1.solo` 升为第 2 版、零差基线重录）。新事件形状补录为第九份黄金日志 `open_lane_l3.json`（截自 `graph/tests/test_open_lane_people.py`）。体质修炼 001 的两个字段也补了试炼：`graph/tests/test_gongfa_fields.py` 在内核测试台上直接给不透明的配置值（T4-1 开题带功法摘要、T4-2 租约按席位带形态、提交体选不了、R2 重放与配置无关、R3 新旧混放），录为第十份黄金日志 `gongfa.json`；它与 `tests/fenjue/test_f3_gongfa.py` 一并列进体质试炼的 T4。另：#121 起 `Config.idle_close_s` 缺省 7 天，开放道新开的题都抄入它，所以 `record_goldens.py --check` 对开放道、资料类、整理三道会报“已冻结的日志重录不出来”：那是新写的事件体多了这个字段，不是旧日志重放变了（R1 照过）。

## 4. 与在途 PR 的关系

| PR | 状态 | 与焚决 |
| --- | --- | --- |
| #105 续期门 | 待合 | 不冲突。卡片与 `budget_add` 是体质（M6、T3），触发策略 `budget.extension` 进 H2 的参数。黄金日志在它合入后补录续期的一份 |
| #111 地图 v0.9–v0.10、L3 第三步 | 待裁 D9–D14 | 不冲突，焚决不改地图。#111 合入后，地图出一次修订（v0.11）：站表加一列“火位”，标出每站用到的火位；这次修订由地图线出，本稿裁决后通知 |
| #114 资料库第二期 | 待验收 | 不冲突。`kb_search`、`kb_read` 进 H3；knowledge 类与“引用不进执行记录分子”属 T5，已在 #114 的验收里，等于一次已经在走的体质修炼 |
| #115 会话活动面板 | 待验收 | 案例一的异火臂 A′。推荐按原样合入（FJ15）：A′ 必须先存在，F 才有对照 |

## 5. 风险

| 风险 | 说明 | 处置 |
| --- | --- | --- |
| 架构税 | 清单、炼档、三臂对照让每次吸收变重 | 炼档前三节就是设计稿，本来就要写；结构读数随 CI；运行读数只在火位影响严格道或开放道质量时才跑。炼化周期作为读数持续看 |
| 边界划错 | 某项被放进体质，结果每次吞噬都要改它 | “体质改动行数”读数（[04 §1](./04-evolution.md#1-四层读数)）；连续出现就修订本设计 |
| 火位不够用 | 将来的异火落不进八个火位 | 新增火位是一次功法层的结构改动，修订 [01 §5](./01-boundary.md#5-功法八个火位) 并裁决，不动体质 |
| 零差迁移漏测 | F2 改坏了某条冷路径 | 假 CLI 剧本覆盖表随 F2 一起审；F2 之后的第一次真实运行由测试方跑开放道验收十条 |
| 名字压过意思 | 新名词太多，读的人记不住 | [07](./07-naming.md) 只给 15 个名词，代码里一律用对照的英文或拼音标识，界面不出现这些名词（FJ1） |
