# 体质修炼 002：开放道交付的复核读数（地图 Q34）

> 地图 L3b 的第一项（[04 §3](../task-lifecycle/04-gaps-roadmap.md#3-分期路线)，cz 2026-11-21 排期）。复核本身的方向早已裁过：开放道 §12 第 4 条（a，默认开，花费限在验证份额内），§3.6 的形状。复核会话绑定**已有的** verify 席位（[01 §6](./01-boundary.md#6-席位会话的权能上限)：“只读复核”绑定 verify 席位），不新增席位；但 verify 席位今天在内核里没有任何租约种类和可提交的事件，要让它能交回读数，就要给体质加一个事件种类、一种租约，这是体质修炼。按 [01 §7](./01-boundary.md#7-体质修炼不经吞噬协议) 走规格变更表，**与复核会话的形态（功法，H1）分开提**（吸取开放道补档 [05 §0](./05-cases.md#0-案例零补档-000一个会话做到底) 的教训）。本表四条逐条可否决，待 cz 裁决后并入规格 v1.7。

## 一、变更表

| # | 变更 | 位置（代码） | 理由 |
| --- | --- | --- | --- |
| T1-1 | 新事件 `review`：只由**本题在途、核这一次交付**的 verify 会话提交（`_who`：adapter 且 role=verify；validate 再查令牌的会话是 verify 租约、租约的 target 就是体里的 `delivery`）。体：`delivery`、`claims[]`（`{claim, verdict, note, refs?}`，交付的每条主张**恰好核一次**，verdict 取 supported、unsupported、unclear）、`reruns[]`（`{check, result, note?, refs?}`，check 是交付里的自检下标、不重复，result 取 pass、fail、not_rerun，说重跑了必须附执行留档）、`counterexamples[]`、`summary`。依据与 `deliver` 同一套机械检查（存在、属本题、exec、input 或 knowledge 类）。一次交付至多一份复核（`conflict`） | `reducer/review.py`（新）、`reducer/__init__.py`（`_who`、`KINDS`、两张分派表）、`state.py`（`Problem.reviews`） | 复核要交回东西才有用；不入事件就只是会话记录里的一段话，读数表数不出，也没法事后核 |
| T1-2 | **复核只给读数**：`review` 不改终态、不改等级、不进解出率与任何判定统计，不拦人看结果（`/work` 里等人看的 human 项照旧在）。状态视图的交付下多一个 `review`（读数由确定性代码数出，意见按叙述语域标） | `views.py`（`_review`、`_delivery`）、`wire_schema.py`（`Review`、`ReviewReadings`） | 守住开放道裁决：`delivered` 仍是“未经判定”；复核是增值项，不是门（open-lane §3.6） |
| T4-1 | 新租约种类 `verify`（只由司南申请，带 target = 交付编号）。`/work` 只在开题时抄入了 `review: true` 的开放道题上派：每次 answered、partial 的交付各派一次，已经为它领过 verify 租约（不论有没有交回读数）的不再派，受阻的交付与叫停之后不派 | `reducer/lease.py`、`work.py`（`review_wanted`） | 复核要有自己的会话与账；“领过就不再派”让复核挂掉不会无限重试 |
| T4-2 | verify 租约**花验证份额**：与判官租约同一个池子（`work.VERIFY_POOL`），预留与花费都算进 `verify_spent`，超出 `verify_share × cap` 即 `over_budget`。开题时由图服务从 `Config.review_open` 抄入 `review: true`（缺省关，由组装根按设置打开），提交体给不了 | `work.py`（`budget_view`）、`reducer/lease.py`、`reducer/common.py`（`Config.review_open`）、`reducer/problem.py` | 开放道裁决第 4 条：花费限在验证份额内；开关进事件，重放不读设置 |

权能矩阵只多一格：verify 席位多一个 `review`（`fenjue/…/tables.py` 的 `SEATS["verify"]`，`tests/fenjue/test_tables.py` 照过）。`ROLES`、`REQUEST_ROLES` 不变：verify 会话不能申请扩权，不能交付，不能写 Fact 与 Intent。信封不升版。

## 二、体质修炼的三问（01 §7 第 2 条）

| 问 | 答 |
| --- | --- |
| 比现有的强制点更严在哪里 | 复核读数原本无处可放；现在它只能由一个特定的会话（核这一次交付的 verify 租约）交回，内核逐条机械校验，并且读数被明文排除在终态、等级与判定统计之外。没有放宽任何一条：verify 席位的其余权能为零，复核的钱在验证份额内封顶 |
| 哪些既有路径会因此被拒 | 没有。`review` 与 `verify` 租约是新种类；没有抄入 `review` 的题（全部既有题）不派复核，`review` 一律 `forbidden_op` |
| 旧事件回放是否逐字节不变 | 是。旧事件没有 `review` 与 verify 租约，`apply` 不为它们推任何值；`verify_spent` 只多算 verify 租约，旧日志里没有；状态视图的 `review` 只在有复核时出现。十份冻结的黄金日志逐字节回放（`tests/fenjue/test_t4_zhang.py`）；`Config.review_open` 缺省关，所有既有测试台与组装根新写的事件体与改动前相同 |

## 三、证据

| 检 | 测试 |
| --- | --- |
| 开关关着：不派复核，`review` 被拒，视图不变；开关只抄进开放道 | `graph/tests/test_open_lane_review.py::test_without_the_switch_nothing_is_reviewed`、`test_the_switch_is_copied_only_into_open_lane_problems` |
| 一次交付复核一次；只给读数，终态与待办不变；读数过 wire schema | `test_a_delivery_is_reviewed_once_and_only_gets_readings`、`test_review_does_not_change_the_problems_list_or_levels` |
| 追问之后的新交付另有一次复核；复核会话没交回读数不重试；受阻与叫停不派 | `test_a_follow_up_delivery_gets_its_own_review`、`test_a_verify_session_that_ends_without_readings_is_not_retried`、`test_blocked_deliveries_and_halted_problems_are_not_reviewed` |
| 花验证份额 | `test_verify_leases_draw_on_the_verify_share` |
| 只有核这一次交付的复核会话能提交；复核会话不能交付 | `test_only_the_verify_session_for_this_delivery_can_review` |
| 体的机械校验逐项变异 | `test_review_bodies_are_checked_mechanically` |
| 新事件形状录为第十二份黄金日志 `open_lane_review.json` | `tests/fenjue/record_goldens.py`、`test_t4_zhang.py` |
| 权能矩阵 | `tests/fenjue/test_tables.py` |

## 四、不在本表里的（功法，另一个 PR）

复核会话怎么做（提示词、工具面、只读、重跑哪些自检）、司南怎么给它预留、设置项 `lanes.review` 与结果页、读数页的一节，都是功法与工作台的事，在 L3b 的第二个 PR 里（H1 新形态绑定 verify 席位、H2 编排加一类事项、H6、H7）。本表合入之后、第二个 PR 合入之前，`Config.review_open` 保持关，不会派出没有形态可跑的复核。

## 五、体质改动行数

本次是体质修炼，改动行数不为 0：`graph/` 下 9 个文件，见 PR 的 diff。读数表（Q35，`/v1/readings/open`）是只读投影，随同一 PR 提交，但它不是体质增强，不在本表里裁。

## 六、裁决

待 cz 逐条裁 T1-1、T1-2、T4-1、T4-2。
