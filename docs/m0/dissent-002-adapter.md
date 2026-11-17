# M0 异议报告 002：Adapter（D4–D6 假 CLI 版）的四处缝隙

> 状态：**已裁决，四项全部按实现侧采纳**（2026-11-17，PR #15 红队评审；勘误见 [errata-v1.4.md](errata-v1.4.md) E1–E4）｜提出方：M0 实施线程｜性质：实现中发现的规格缝隙，代码里未私改，按"暂行做法"先走，裁决后照改。

## 1. Op 的 `check.inputs` 在内核判据里没有对应字段

§3.4.2 的 `add_fact` Op 写着 `check?: { judge_id, spec_path, expect, inputs?: ArtifactId[], control? }`，而 §3.1.2 的判据（reducer `_check`）只收 `judge_id / spec_ref / expect / sealed / control`。Adapter 无处安放 `inputs`。

- **暂行做法**：带 `inputs` 的 Op 返回 `schema_error`，说明原因。没有塞进 `expect` 里，因为那会改变内容键（`content_key` 取 check 的规范化哈希）。
- **提议**：二选一。(a) 内核判据加 `inputs` 字段，参与内容键；(b) Op 去掉 `inputs`，判官输入一律走 `expect` 或 grounds。

## 2. 该 CLI 2.1.326 的帮助文本里没有 `--max-turns`

§3.4.2 十项表第 8 项写 `--max-turns`。读 `claude --help`（2.1.326，未运行会话）：有 `--max-budget-usd`、`--append-system-prompt[-file]`（在 `--bare` 的说明里出现）、`--tools`、`--restricted`、`--permission-prompts none`、`--strict-mcp-config`、`--session-id`、`--resume`，**没有** `--max-turns`。它可能是隐藏选项，也可能已移除。

- **暂行做法**：绑定默认不传 `--max-turns`（`CliBinding.max_turns_flag=False`）；回合上限由 Adapter 从事件流数 `assistant` 事件执行，超限按 `failed(max_turns)` 终止。
- **D4 真机核对**：传一次 `--max-turns 1` 看是否报未知选项。另外帮助文本里有 `--system-prompt-snapshot`（首个请求的系统提示录下后，后续请求与 resume 原样重发），与前缀稳定直接相关，D4 一并核对默认值。

## 3. 3.4.5 的 5 的"90%"取决于题面体量，不只取决于渲染

前缀稳定的结构保证已做到：后一个包以前一个包的①–④开头，分叉点在④末尾。但⑤–⑦是每次都变的固定开销（实测约 400 字节），①–④不足它的 9 倍时比例必然低于 90%。实测（同一角色提示，新增 3 个节点）：

| 题面 | 比例 |
| --- | --- |
| 0.45 KB | 0.860 |
| 0.9 KB | 0.882 |
| 1.8 KB | 0.910 |

- **暂行做法**：三档都断言结构保证；90% 只对 1.8 KB 档断言。
- **提议**：验收改成"①–④逐字节是后一个包的前缀"，比例只作读数；或者保留 90%，注明适用于题面 ≥ 2 KB。

## 4. 回合上限与花费上限的执行方

规格把 `--max-turns`、`--max-budget-usd` 写成 CLI 的机制，同时说"记账以端点代理为准"。按代理的事后计量，一个请求最多越过预留一次请求的花费；`--max-budget-usd` 按客户端估算，也可能略超。两者都不是硬顶。

- **暂行做法**：代理的三道 429 是唯一硬顶；CLI 的 `--max-budget-usd` 设为租约预留额，只作第二道。
- **提议**：确认"预留 = 软顶，越过不超过一个请求"可接受；否则代理要改写流、在 token 级截断，M0 不建议。

## 裁决（2026-11-17）

1. **check.inputs：采纳实现侧。** inputs 属于 JudgeRequest，Check 只有三字段；规格勘误 E1。Adapter 维持拒绝 `check.inputs`。
2. **无 `--max-turns`：采纳 Adapter 计数。** 规格勘误 E2。
3. **前缀 90%：改验收语义。** ①–④ 100% 字节前缀稳定，比例降为遥测读数；规格勘误 E3。渲染相应调整：段间空行移到下一段开头，使①–④恰好是后一包的字节前缀（黄金文件随之更新）。
4. **预留额软上限：采纳为实现语义。** 规格勘误 E4。
