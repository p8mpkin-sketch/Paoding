# 体质修炼 003：租约按题的功法版本抄形态；在途降一阶（已实现，待裁）

> 起因：FJ6 锁定（#129）只动了能力层。在跑的题每次派工、每个会话都按开题时记下的那一版功法取（`paoding_fenjue.for_problem`），留下两件要动内核的事。按 [01 §7](./01-boundary.md#7-体质修炼不经吞噬协议) 走规格变更表，不经吞噬协议；cz 2026-11-21 定先起草（决定卡“Draft 003 now”），#129–#130 合入时确认做。照 F3 的做法，变更表与代码放在同一个 PR 里逐条裁：T4-3、T4-4 一个提交，T4-5 单独一个提交，否决哪条就删哪个提交（T4-3 与 T4-4 可分开否决，见第七节）。

## 一、变更表

| # | 变更 | 位置（代码） | 理由 |
| --- | --- | --- | --- |
| T4-3 | `Config` 加 `gongfa_archive: ((摘要, 品阶, ((席位, "id@ver"), …)), …)`：功法存档里每一版的品阶与席位 → 形态表，由组装根从 `paoding_fenjue.kernel_config()` 取来，内核只查不解释。领租约时，`validate` 按**这道题生效的功法摘要**（见 T4-4；没有改钉就是开题时记下的）查表抄 `lease.form`；题没有摘要、或表里没有这个摘要，退回 `Config.forms`，即 F3 原样 | `graph/…/reducer/common.py`（Config）、`reducer/pin.py`（`form_for`）、`reducer/lease.py`（抄 `form` 的那一行改为调 `form_for`） | F3 的 `lease.form` 抄的是内核启动时的配置。H1 换过之后，在跑的老题领租约时事件里记的是新功法的形态，而会话按锁定的那一版跑（FJ6）：审计记录与实际不一致 |
| T4-4 | 新操作 `repin`，**只有人的令牌**能提交（与 `follow_up`、`halt` 同一格）：`{to: {jie, digest}, reason}`，把一道在跑的题改钉到另一版功法。`validate` 三条：题未关；`(to.digest, to.jie)` 在 `Config.gongfa_archive` 里；`to.jie` 低于这道题此刻生效的品阶（见 T4-5）。`apply` 追加到题的 `repins` 列表 `{to, reason, seq}`，**不改**开题时的 `gongfa`：两样都留着，审计看得到原来是哪一版、谁在什么时候为什么改了 | `reducer/__init__.py`（`_who` 一行、分派表两行）、`reducer/pin.py`（`effective`、`_v_repin`、`_a_repin`）、`state.py`、`views.py`（状态视图给出 `repins`）、`wire_schema.py` | FJ6a 的紧急操作：新火在真实任务上出事时，人可以让在跑的题从下一次派工起换回上一版。已经在跑的会话不被杀：它开始时取过功法，照那一版跑完这一轮（与 D12 叫停同一思路：先让它收尾） |
| T4-5 | 撤销改钉：`repin` 的 `to` 也可以是这道题**开题时记下的那一版**（即使它比此刻生效的高），用于误操作后改回来。除此之外只许往低改 | 同 T4-4 的 `_v_repin` | 改钉是人在紧急时做的，要能撤；但不许把在跑的题升到开题之后才上线的版本，那会破坏 FJ6“一题之内前后一致” |

读端（能力层，不算体质行数）：

- `paoding_fenjue.for_problem(题)` 先看 `repins` 的最后一条，再看开题时的 `gongfa`。司南与适配层不用改：它们已经只经 `for_problem` 取功法。
- `arm_of` 与进化读数页按“生效的那一版”分臂；改钉过的题在版本表里单列一行“改钉”，不混进任何一版的做成率（它前后用了两版）。
- `kernel_config()` 多给 `gongfa_archive`，由存档目录生成：每一版的席位 → 形态取主臂（不算留出）。组装根 `scripts/stack.py` 原样展开 `kernel_config()`，不用改。
- `GET /v1/evolution` 多给 `archive`：存档里每一版的品阶与摘要（`pd repin` 与以后的回滚弹窗按它把品阶解析成摘要）。

不做：H1 上的常设留出。分到留出的题要用另一个形态，而分配按 `sha256("H1:题号")` 算，那是功法的事，内核不该知道。此刻 H1 没有留出；H1 若要设留出，另提。

部署注意：`Config` 在组装根启动时装载。`lianhua.py jue / sanhuo` 改了功法之后，新开的题要等组装根重新装载才记新摘要（F3 起就是这样）；`gongfa_archive` 同理。散火之后要改钉在跑的题，先重新装载，表里才有散火后的那一版。

## 二、体质修炼的三问

| 问 | 答 |
| --- | --- |
| 比现有的强制点更严在哪里 | T4-3 只让审计记录更准，没有放宽任何一条，形态仍只由图服务写。T4-4、T4-5 加的是一个只有人能提交的操作；只许改到存档里有、且不高于开题那一版的版本；关过的题拒 |
| 哪些既有路径会因此被拒 | 没有。不给 `gongfa_archive` 时（所有既有测试台的缺省）领租约与 F3 逐字节相同；`repin` 是新操作 |
| 旧事件回放是否逐字节不变 | 是。旧日志里没有 `repin`。`lease.form` 的值由 `validate` 写进事件体，`apply` 原样存，重放时不查表（R2：`apply` 不读配置）。黄金日志加一道 `repin`，录法同 F3 的 gongfa 道 |

## 三、证据

| 检 | 测试 |
| --- | --- |
| 不给 `gongfa_archive` 时事件体与 F3 相同 | `graph/tests/test_repin.py::test_t4_3_without_the_archive_the_lease_is_what_f3_wrote`；`test_gongfa_fields.py` 原有各条不改照过 |
| 给了：老题领租约抄到开题那一版的形态，新题抄当前的；表里没有的摘要退回 `forms` | `test_repin.py::test_t4_3_a_task_opened_under_an_older_version_leases_that_versions_form` |
| 改钉后下一次领租约抄改钉的那一版，在跑的租约不动；状态视图给出 `repins`；开题时的 `gongfa` 不动；从头重放相同 | `test_repin.py::test_t4_4_a_human_moves_a_running_task_down_and_the_next_lease_follows` |
| `repin` 只认人的令牌；只许改到存档里有的、更低的一版；同一版、品阶对不上、焚决之前的题、关过的题拒；提交体字段白名单 | `test_repin.py::test_t4_4_who_and_where_a_task_can_be_repinned`；`test_malformed.py`（每种操作都有合法样例与畸形样例） |
| 能力层：`for_problem` 按最后一条改钉取功法（司南编排、会话形态、入账都只经它取，不用改）；`kernel_config` 带全部存档 | `fenjue/tests/test_pinning.py` 两条 |
| 读数：改钉过的题单列一行，不进常设留出的任何一臂；`archive` 一栏 | `fenjue/tests/test_readings.py::test_repinned_tasks_get_their_own_row_and_stay_out_of_both_arms` |
| `pd repin`：按品阶解析摘要、同阶几版要挑、经 HTTP 提议通道提交，被拒原样报出 | `pd/tests/test_pd_repin.py` |
| R1 黄金日志逐字节回放（新录 repin 道，4 份日志 19 条事件）、R3 新旧混放、R5 信封不升版（权能表 human 一行多 `repin`） | `tests/fenjue/test_t4_zhang.py`、`test_repin.py::test_r1_r3_tasks_with_and_without_repins_replay_together`、`tests/fenjue/test_tables.py` |

## 四、入口

- **pd**：`pd repin <题号> --to-jie N [--to-digest <摘要前缀>] --reason …`（人的令牌，走运行中的全栈：只有组装根装载了功法存档）。
- **网页**（fenjue-ui U4 推荐 a，界面第二期的写操作）：回滚弹窗里加勾选“正在跑的任务也从下一步起换回上一版”，默认不勾；勾上即对开在被撤版本下、还没关的每道题各提交一条 `repin`，一个批次。任务页显示“能力版本 v1（由 v2 改钉，原因…）”。

## 五、体质改动行数

`graph/src` 下 7 个文件，T4-3 与 T4-4 共 +88 −3 行（新文件 `reducer/pin.py` 67 行），T4-5 另 +4 −1 行。单列在这里，不算进任何一次吞噬。

## 六、待裁

| # | 问题 | 选项 | 推荐 |
| --- | --- | --- | --- |
| R1 | T4-3 按题的摘要抄形态 | a. 采纳；b. 不改，形态只作“启动时配置”的记录，读端另算 | a：审计记录要与会话实际一致 |
| R2 | T4-4 在途降一阶 | a. 采纳，只有人能提交，下一次派工起生效；b. 不做（即 FJ6b） | a：FJ6 已裁 a，包含这个紧急操作 |
| R3 | T4-5 允许改回开题那一版 | a. 允许；b. 只许往低改，误操作也不能撤 | a：紧急操作要能撤 |

## 七、此刻能不能用上

存档里此刻只有两版功法，都是第 2 阶（`9770a71f…` 是 #125 之前没有常设留出的那一版，`1d45a28d…` 是此刻的）。T4-4 只许往低改，所以**此刻没有哪道题能改钉**：要等下一次升阶（第 3 阶上线）之后，开在第 3 阶下的题才能改回第 2 阶。T4-3 此刻就生效：两版的 H1 形态相同，所以眼下抄出来的值与 F3 一样，H1 换过之后才会不同。

否决的做法：否决 R1（T4-3）就把 `lease.py` 改回 `dict(cfg.forms).get(kind)`；否决 R2（T4-4）就删 `repin` 的分派两行、`_who` 一行与 `_v_repin`、`_a_repin`，黄金日志的 repin 道一并删（它还没冻结进任何发布）；否决 R3（T4-5）就回退那一个提交。
