# pd/：人的通道 CLI（F0 文本约定）

规格：v1.3 §3.1.2 人的操作、§4.1；HMI v1.1 的 F0（变更 #44，方案 α，M0 无网页）。

## 实现的契约接口

- `pd problem open | status | report | profile | hint | approve`。
- 文本输出四语域标记：`[证据]` `[叙述]` `[人]` `[估]`；等级词表；判据徽章。
- `pd report` 首行写终态（solved / accepted / unsolved）与根结论的等级上限；accepted 不呈现为"已证明"。
- 画像只能事后覆盖（`profile_override`），**不存在人填三轴的入口**。

## 官的声明

| 结构 | 官 | 标签 | 启用条件 | 长存依据 |
| --- | --- | --- | --- | --- |
| 人的决策通道（approve、四顾确认） | 守门官 | T-0 | 常开 | 验收属于委托人 |
| 四语域与判据徽章 | 守门官 | T-0 | 常开 | 叙述与证据必须可区分 |

## 依赖

`paoding_graph.contract`。

## 实现（骨架，离线预备）

- `cli.py`：`problem open`、`status`、`report`、`profile`、`hint add|close`、`approve`、`deny`。pid 取 `--pid` 或 `PD_PROBLEM`，数据目录取 `--home` 或 `PD_HOME`。
- `render.py`：渲染入口 `Out.add(出处类别, 文本)`，语域查 `REGISTER` 表得到，没有直接写语域的入口；模型撰写的文本压成单行，内容里伪造的行首标记不成行。等级词表 `LEVEL_WORDS` 固定；E3、E3d、X 带作出裁决的 `judge@version`；`solved` 带目标判官徽章；`accepted` 写“人验收，未经判官判定”。
- 观察类论断：首行是谓词（判官徽章、规格哈希、`expect`）与等级，第二行是证据根，标题与摘要在其后，按叙述。
- `pd status` 对每条 Hint 列出“之后新增的 Intent”，注明是时序关联，不是因果。
- `pd approve` 先打印审批卡文本，再要求输入 yes（`--yes` 跳过）；`deny` 理由必填。

### 实现取值（待红队确认）

1. **本机进程内打开图服务**：骨架直接打开 `PD_HOME/g.sqlite`。图服务独立成进程（司南循环在跑）时，两个进程各自持有状态，pd 的写入要等对方重放才看得见；D10 改走 HTTP/Unix socket 绑定，接口不变。
2. 内建判官表取异议 001 裁决的三个（replay、exact_match、seal_check）；配置判官随 judgebox 落地后从 `judges.d` 读。
3. `pd hint add` 需要 pid（规格命令表里没写），取 `--pid` 或 `PD_PROBLEM`。

### 已知缺口（内核 M0 未实现的人的操作）

1. `profile_override`（规格操作表列为 human 操作）：`pd profile --override` 目前直接报未实现。
2. `deny` 的理由：内核的 `approve` 事件体只有 `intent` 与 `decision`，理由打印在卡上但不入日志。
3. `--scope-amend`、`--waive-premise`、`pd extend`：内核 M0 没有对应字段或操作（范围修订与豁免、续期门属 M1/M4）。
4. r2 缺回退时“禁用批准”（HMI H1）：`rollback` 是 M4 字段，M0 卡面只写“未声明回退”，不禁用。
