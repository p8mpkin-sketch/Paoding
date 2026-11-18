# eval/：评测台

规格：v1.4 §7 D14、§8。M0 做 baseline 与 full 两种模式：同一模型、同一 Goal 判据、同一端点代理与价目表计量（红线 5）。

## 官的声明

| 结构 | 官 | 标签 | 启用条件 | 说明 |
| --- | --- | --- | --- | --- |
| 对照臂运行器 | 量具 | T-0 | 常开 | 只产生读数，不驱动行为 |
| 归因表 | 量具 | T-0 | 常开 | 日志上的投影（M1） |

## 两种模式

| 模式 | 形态 | 工具面 | 终态由谁定 | 读数来源 | 需要 Docker |
| --- | --- | --- | --- | --- | --- |
| `baseline`（单 CLI 直连，规格里的 B1） | 单个 CLI 会话，直连端点代理 | 原生工具面（不挂代理工具） | 本地 exact_match：答案的 sha256 与判据相等 | 端点代理计量（进程内计量账）；`events` = CLI 回合数 | 否（干跑）；真题要能连到题目容器 |
| `full`（全栈流程，M0 报告里的 B1b） | `scripts/run.py` 整套系统，人经 HTTP 开题后旁观 | 代理工具 exec / submit / show，执行层沙箱 | 判官独立裁决，图服务写终态 | 图服务的 `/budget` 与事件日志；`events` = 本题事件数 | 是 |

说明：规格 §8.3 里的 B1b 原指“瘦基线换用代理工具面”的单会话；M0 报告与本运行器里的 `full` 是全栈（司南 + 代理工具 + 沙箱 + 判官），
即庖丁本身的最简形态。两者的差别、以及 Bk（等成本重试）与 Bn（共享笔记），在 M1 的四臂对照里补。

## 记录格式（每条运行一条）

```json
{"mode": "full", "problem": "q1-login", "run": 1, "model": "deepseek-chat",
 "duration_s": 42, "terminal": "solved", "cost_usd": 0.011, "events": 33,
 "log_dir": "runs/20261118T100000Z-full-q1-login-1/"}
```

`terminal` 取 `solved | unsolved | failed`（failed：CLI 出错、超时，或全栈没跑到终态）。`log_dir` 是
`<产物根目录名>/<时间戳>-<模式>-<题目>-<次>/`，产物根缺省 `runs/`。目录里有 `record.json`，以及 baseline 的
`cli.stream-json`、`workspace/`，full 的 `stack.log`、`events.json`、`home/`。

## 用法

```
uv run python -m paoding_eval baseline --dryrun                                  # 干跑，无 Docker、无密钥
uv run python -m paoding_eval baseline --problem eval/problems.d/<题>.yaml \
    --program claude --upstream https://api.deepseek.com/anthropic \
    --api-key-env DEEPSEEK_API_KEY --model deepseek-chat --run 1
uv run python -m paoding_eval full --problem eval/problems.d/<题>.yaml --config <栈配置.yaml> --run 1
```

题目清单的字段见 `src/paoding_eval/spec.py` 与 `problems.d/TEMPLATE.yaml`。答案由启动题目容器的一方填写，填了答案的清单不入库。

## 依赖

`paoding_graph.contract`、`paoding_adapter.contract`。full 模式以子进程起 `scripts/run.py`，经 HTTP 与图服务说话。
