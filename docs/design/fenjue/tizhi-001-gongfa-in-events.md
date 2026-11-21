# 体质修炼 001：功法摘要与会话形态进事件账（焚决 F3）

> 焚决唯一一次体质修炼（[06 §2](./06-migration.md#2-分期) 的 F3，[01 §9](./01-boundary.md#9-功法怎么进事件又怎么不影响回放)）。按 [01 §7](./01-boundary.md#7-体质修炼不经吞噬协议) 走规格变更表，不经吞噬协议。方向已由 FJ5 裁决（a，2026-11-20）；本表的两条逐条可否决，待 cz 裁决后并入规格 v1.6。

## 一、变更表

| # | 变更 | 位置（代码） | 理由 |
| --- | --- | --- | --- |
| T4-1 | `open_problem` 的事件体多一个可选字段 `gongfa: {jie, digest}`：开在哪一阶、哪一套功法之下。由图服务从配置 `Config.gongfa` 抄入，提交体里给了就拒（`schema_error`，与 `settings`、`profile` 同一条）。`apply` 原样存进题的记录，不进等级、消费门与画像 | `graph/…/reducer/common.py`（`Config.gongfa`）、`reducer/problem.py`、`state.py`、`views.py`（状态视图有就给）、`wire_schema.py` | 不入事件，一道题是用哪套功法做的就无从审计，开放道吞噬前后的对照也没法从日志分组（04 §4） |
| T4-2 | `lease` 的事件体多一个可选字段 `form: "id@ver"`：这次会话用哪个形态。由图服务按席位从配置 `Config.forms` 抄入，提交体里给的不认。`apply` 原样存进租约记录 | `reducer/common.py`（`Config.forms`）、`reducer/lease.py`、`state.py`、`views.py`（租约一行有就给）、`wire_schema.py` | 席位与形态分开之后（FJ4），同一个席位上可能有不止一个形态；不记下来，事后分不清某个会话是按哪种做法跑的 |

两条都是只加不改：信封不升版（`SCHEMA_VERSION` 仍为 1，`FIELDS` 不变），权能矩阵不变（`_who`、`ROLES`、`REQUEST_ROLES` 一格未动，`tests/fenjue/test_tables.py` 照过）。

内核不认识任何一团火：`Config.gongfa` 与 `Config.forms` 是两个不透明的值，由组装根（`scripts/stack.py`）从 `paoding_fenjue.kernel_config()` 取来。内核只抄不解释，`graph` 依旧不依赖任何组件。

## 二、体质修炼的三问（01 §7 第 2 条）

| 问 | 答 |
| --- | --- |
| 比现有的强制点更严在哪里 | 多了两样审计记录，没有放宽任何一条：两个字段都只由图服务写，会话、司南、人都写不进去（提交 `gongfa` 被拒，提交 `form` 被丢弃） |
| 哪些既有路径会因此被拒 | 没有。提交体带 `gongfa` 的开题本来就因字段白名单被拒，现在照旧；`lease` 本来就只取已知字段 |
| 旧事件回放是否逐字节不变 | 是。旧事件没有这两个字段，`apply` 不为它们推任何值；八份按道冻结的黄金日志逐字节回放（`tests/fenjue/test_t4_zhang.py`）；配置不给时（所有既有测试台的缺省）新写的事件体与改动前逐字节相同 |

## 三、读端的缺省（纯函数，不写回日志）

`paoding_fenjue.contract` 的两个函数，供工作台、评测与读数分组用：

- `gongfa_of(problem)`：没有 `gongfa` 的题读作 `{jie: 0, digest: null}`，即第 0 阶（旧法）；
- `form_of(lease)`：没有 `form` 的租约按席位推：bootstrap、reason、explore 推为 `h1.triad`，solve 推为 `h1.solo`，recall 推为 `h1.recall`；判官的租约没有形态。

两个函数放在功法组件而不是内核里：火的名字是功法的事，内核不该知道。

## 四、证据

| 检 | 测试 |
| --- | --- |
| 配置不给时事件体不变、读端读作第 0 阶与按席位推 | `tests/fenjue/test_f3_gongfa.py::test_without_config_the_events_are_what_they_were` |
| 配置给了：开题与租约抄入，状态视图给出，过 wire schema；画像、等级与没有功法的同一道题相同 | `test_config_is_stamped_on_open_and_lease_and_shown_in_the_views` |
| 提交体选不了功法与形态 | `test_submitters_cannot_choose_the_gongfa_or_the_form` |
| R3：新旧事件混放在同一份日志里，从头重放与在线状态相同；旧题的状态视图与功法上线前相同 | `test_old_and_new_events_replay_together` |
| R1：八份黄金日志逐字节回放 | `tests/fenjue/test_t4_zhang.py` |
| R5：信封不升版、权能矩阵不变 | `tests/fenjue/test_tables.py` |
| 全栈：F2 录下的零差剧本，把 `open_problem.gongfa` 与 `lease.form` 拿掉之后与 F3 之前相同 | `uv run python tests/fenjue/zero_diff.py --check --ignore open_problem.gongfa,lease.form` |

## 五、体质改动行数

本次是体质修炼，改动行数不为 0，单列在这里，不算进任何一次吞噬：`graph/` 下 6 个文件，见 PR 的 diff。之后的吞噬照旧以 0 行为目标。

## 六、裁决

2026-11-20 cz 合入 #120（main 59b0f68），T4-1、T4-2 两条随之生效，并入规格 v1.6。
