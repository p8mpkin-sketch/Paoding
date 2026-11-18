# judgebox/：契约 3 判官运行器 + 内建判官（信任根）

规格：v1.4 §3.3；不变量 I2。

## 实现的契约接口

- 判官注册表 = 配置目录（YAML），领域词只允许出现在判官配置里，不在本目录代码里。
- 内建判官只有领域中立的三个：`replay`、`exact_match`（M0），`seal_check`（M3）。`lean_check` 不是内建判官，M3 以 `judges.d/` 里的配置条目存在（异议报告 001 第 3 项，2026-11-17 裁决）。
- 洁净重放：从 `baseline_ref` 新建容器；抖动策略与次数上限。
- 保密库：含密级资产（`VaultRef`）只在判官容器内解引用；`show` 对其返回 `forbidden_op`。

## 已落地（M0）

| 模块 | 内容 |
| --- | --- |
| `registry.py` | `load_registry(dir)` 读 `judges.d/*.yaml`；`kernel_judges()` 给出图服务 `Config.judges` 的形状（version、grade、kind、max_cost 抄进题目快照） |
| `vault.py` | `Vault.put(key, content) → VaultRef{vault, digest}`，摘要加盐；`open(ref)` 校验摘要，资产被换过即拒。目录 0700、文件 0600，内容不进日志、Blob 与任何容器 |
| `builtin.py` | `exact_match`：答案取自 `Check.sealed`（保密库）或公开的 `expect.sha256`，输出只有候选摘要与结论；`replay`：洁净容器（不挂工作区、上限不超过 r1）里执行 `spec_ref`，没有规格时执行候选，按 `expect {exit_code, stdout_contains, stdout_regex}` 比对 |
| `runner.py` | `JudgeRunner.tick()`：从 `/work` 领 judge 租约 → 运行 → 输出登记为 judge 类 → `judge_verdict` → `cost(source=judge)` 计入验证池 → 释放。同一请求最多领 3 次租约 |

裁决取值：`pass`、`fail`、`flaky`（一次请求内 `1 + flake.reruns` 次不一致）、`inconclusive`（原因码 `timeout`、`env_error`、`unsupported`、`untouched`）。
`inconclusive` 在内核里只给请求结案，不进裁决序列，等级不变（§3.3.4）；成本照记。

拒绝运行的三种情况，都报 `inconclusive(env_error)`：注册表版本与开题快照不一致；规格 Blob 的哈希对不上；保密库内容与登记的摘要不符。

读过保密库的判官输出在出处里记 `touched: ["vault:<键>"]`，Adapter 的 `show` 据此返回 `forbidden_op`。

### 恒真谓词与 `require_touch`（P0-3，2026-11-18）

`replay` 重放的脚本与期望都是 Worker 写的，一条 `echo ok`、期望含 `ok` 的规格在洁净容器里永远"可复现"。`judges.d/replay.yaml` 现在默认 `require_touch: true`：

- **访问摘要从哪来**：执行层的出站闸门记下重放期间真实发生的连接（`net:host:port`）；判官另把挂入洁净容器、且自身有出处的候选记为 `artifact:<id>`（`runner._grounded`：`input` 类算；`exec`、`judge` 类里自身访问摘要非空的算；`authored` 类与访问摘要为空的 `exec` 输出不算）。规格脚本本身不算。
- **裁决**：访问摘要为空时裁决 `inconclusive(untouched)`，不论谓词成立与否，等级不变，成本照记。判官输出照常登记，`touched` 如实为空。
- **什么时候要求**：判官配置打开，且题目的授权范围里有外部资源（资源种类登记表里 `external` 的，如 `net`；没登记过的种类按外部算）。只有 `workspace` 规则的纯计算题没有可碰的东西，不要求。要对某类题彻底关闭，在判官配置里把 `require_touch` 设为 `false`。
- **挡不住的**：规格先连一下授权目标、再打印与它无关的内容。这是规格 §5.2 场景 2 承认的缺口，靠 Verify 反证、对照判据（M1）处理。

### 对照判据 N1（§3.3.3，2026-11-18 从 M1 提前）

恒真的谓词也能到 E3；对照给判据加一个负对照：同一份规格，换一组输入，结果必须相反。观察类论断的判据可带 `control: {inputs: [ArtifactId]}`。

- **怎么跑**：`replay` 先照常做主运行（含抖动重跑）。主运行通过后，在新的洁净容器里用同一份规格再跑一组，`control.inputs` 按序写到 `/workspace/inputs/1`、`2`、…。两组运行都建 `/workspace/inputs`，环境只差在输入上（主运行里它是空的）。
- **裁决**：

  | 主运行 | 对照运行 | 裁决 | `control_end` |
  | --- | --- | --- | --- |
  | 通过 | 不通过 | `pass`，裁决记录带 `controlled` | `fail` |
  | 不通过、抖动或无结论 | 不跑 | 照主运行 | `not_run` |
  | 通过 | 通过或抖动 | `inconclusive(no_contrast)`：结果不依赖输入 | `pass` / `flaky` |
  | 通过 | 超时、环境错误或 `untouched` | `inconclusive`，原因码照旧 | 同原因码 |

- 判官输出是两次运行的输出拼接（中间隔 `--- control ---`），登记为一条 judge 类 Artifact。
- 不认对照的判官（如 `exact_match`）遇到带对照的判据，运行器一律给 `inconclusive(unsupported)`，不能替对照说"不通过"。内核另外复核：带对照的目标，`pass` 必须带 `control_end=fail`。
- **挡不住的**：对照输入由提出者选，它证明的是"结果依赖输入"，不是"标题为真"；规格也可以按输入有没有来分支。M1 抽样审计里带与不带对照的 E3 观察在恒真谓词与标题夸大的比例上没有差别，就删掉它（§3.3.3 的证伪线）。
- Adapter 的 `add_fact` Op：`check.control.input_paths`（工作区文件，登记为 authored）或 `check.control.inputs`（ArtifactId / tmp_id）。

已知缺口：`seal_check`、评审团判官随 M1/M3。

## 验收对应（3.3.5）

| 编号 | 测试 |
| --- | --- |
| 1 超时 | `test_replay_timeout_is_inconclusive_and_still_costs`、`test_replay_timeout_kills_the_container`（Docker） |
| 2 抖动 | `test_replay_flaky_when_reruns_disagree`、`test_replay_majority_policy` |
| 3 伪造证据 | `test_forged_workspace_file_does_not_survive_replay`（Docker） |
| 4 错误候选与次数上限 | `test_wrong_candidate_does_not_raise_level`、`test_candidate_quota_is_enforced_by_the_kernel` |
| 5 任务令牌不能裁决 | `test_task_tokens_cannot_submit_verdicts`、`…_register_judge_class`、`…_take_judge_leases` |
| 6 规格被改 | `test_tampered_spec_is_refused` |
| 8 空谓词 | `test_echo_ok_observation_never_reaches_e3`、`test_echo_ok_does_not_reach_e3_on_a_real_sandbox`（Docker）、`test_a_spec_that_really_reads_the_target_reaches_e3`（Docker）、`test_mounted_candidate_counts_only_when_it_has_provenance`、`test_pure_computation_problems_are_not_asked_to_touch`、`test_replay_untouched_predicate`、`test_replay_touching_the_resource_counts` |
| N1 对照判据 | `test_control_judge.py` 全部（表格四行、输入只进对照运行、不认对照的判官、内核复核）、`test_control_separates_a_spec_that_reads_its_input_from_a_constant`（Docker） |
| 9 保密库不可见 | `test_judge_output_never_contains_the_answer`、`test_problem_carries_only_the_vault_reference`、adapter 的 `test_show_refuses_judge_output_that_read_the_vault` |

## 官的声明

| 结构 | 官 | 标签 | 启用条件 | 长存依据 |
| --- | --- | --- | --- | --- |
| Goal 判官、重放判官 | 守门官 | T-0 | 常开；开关为自动重放的成本阈值 | 达成与否独立于模型自述 |
| 判官资产的保密库 | 守门官 | T-0 | 题目有含密级资产 | 答案对解题者可见则判定不独立 |

## 依赖

`paoding_graph.contract`、`paoding_executor.contract`。
