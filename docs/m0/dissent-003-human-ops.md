# M0 异议报告 003：内核补齐 M0 的两项人的操作

> 状态：**已授权并落实**（2026-11-17，PR #18 评审方评审）｜性质：规格落实，不是增项。两项本就在规格 §3.1.2 操作表与 §3.2（pd 命令清单）里，M0 内核漏实现。

## 1. `profile_override`：画像事后覆盖

- 依据：裁决 A7“三轴是派生的画像……人只能事后覆盖并留痕”；§3.1.2 操作表把它列为 human 操作；§3.2 `pd profile <pid> --override <轴>=<值> --reason`。
- 实现：事件体 `{axis, value, reason, derived}`。轴与取值按画像定义查表（info、judge、reversibility），理由必填，只许人提交。apply 后 `profile` 取覆盖值，`derived_profile` 保留推出值，`profile_overrides` 逐条留痕（谁、何时、推出值、覆盖值、理由）。重放稳定。
- pd：`[证据] judge = costly（推出值 hard，已由人覆盖）`，理由按 `[人]` 语域单列。

## 2. `deny` 带理由

- 依据：§3.2 `pd deny <intent> --reason "<文本>"`；§3.2 输出约定把“裁决与拒绝的理由”归入 `[人]` 语域。
- 实现：`approve` 事件体加可选 `reason`；`decision=deny` 时必填（空白也拒）。apply 记入 `decision_reasons`，`pd status` 在该 Intent 下以 `[人]` 显示。

## 其余人的操作

`rule`、`accept`、`extend`、`judge_revoke`、`intent_done` 按变更 #41 的里程碑走，M0 不做。`--scope-amend`、`--waive-premise` 同理。
