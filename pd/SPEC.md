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
