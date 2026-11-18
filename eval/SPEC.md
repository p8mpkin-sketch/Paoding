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
| `baseline`（单 CLI 直连，规格里的 B1） | 单个 CLI 会话，在执行层同款沙箱里跑，经中继直连端点代理 | 原生工具面原样（Bash、Read、Write、Edit、Glob、Grep；不挂代理工具） | 本地 exact_match：工作区 answer.txt 的 sha256 与判据相等 | 端点代理计量（进程内计量账）；`events` = CLI 回合数 | 真题是（`--image`）；干跑可在宿主上 |
| `full`（全栈流程，M0 报告里的 B1b） | `scripts/run.py` 整套系统，人经 HTTP 开题后旁观 | 代理工具 exec / submit / show，执行层沙箱 | 判官独立裁决，图服务写终态 | 图服务的 `/budget` 与事件日志；`events` = 本题事件数 | 是 |

说明：规格 §8.3 里的 B1b 原指“瘦基线换用代理工具面”的单会话；M0 报告与本运行器里的 `full` 是全栈（司南 + 代理工具 + 沙箱 + 判官），
即庖丁本身的最简形态。两者的差别、以及 Bk（等成本重试）与 Bn（共享笔记），在 M1 的四臂对照里补。

## 两臂环境对等（baseline 的沙箱）

M1 第一批读数里 baseline 三次全败、full 三次全解，原因不是能力差距：baseline 的 CLI 在宿主上跑，
解析不了题目容器的名字；原生工具面里也没有 Bash；提示没说要把答案写进 answer.txt。三处都已修，见 `src/paoding_eval/box.py`。

- **网络**：baseline 借执行层建沙箱（`compile_spec` + `DockerExecutor.launch`，风险上限 r1、r2 不批准），
  与 full 里执行容器面对的是同一套东西：内部网络，每台授权主机一个出站闸门，只放行 scope 里 actions 含 connect
  的 host:port。授权外的端口、外网都连不上（`tests/test_box.py`）。闸门的逐连接记录写到 `log_dir/gate.jsonl`。
- **计量**：沙箱网络上放一个端点中继（别名 `pd-endpoints`），CLI 经它连宿主回环上的端点代理，计量与 full 同一套（红线 5）。
  Linux 上中继走挂进去的 Unix 套接字；macOS（Docker Desktop）上 Unix 套接字挂不进容器，中继另接默认网桥、经
  `host.docker.internal` 连宿主（`--transport tcp`，按平台自动选）。tcp 通路本仓库的 CI 上没有验证过，第一次在 macOS 上跑时请留意。
- **工具集**：沙箱镜像 = full 的执行层基础镜像（`bases.basic`）+ CLI，见 `images/cli/Dockerfile`。两臂能用的命令因此相同。
- **提示**：题面后加一句交付方式（`spec.py` 的 `DELIVERY`）；full 里同一件事由 `claim_done` 承担。
- **前提**：与 full 相同，题目容器的容器名要等于 scope 里的主机名（如 scope 写 `q1:8080`，容器就叫 `q1`）。

真题 baseline 不给 `--image` 时直接拒跑：在宿主上跑的 baseline 量到的是网络差异。

## 记录格式（每条运行一条）

```json
{"mode": "full", "problem": "q1-login", "run": 1, "model": "deepseek-chat",
 "duration_s": 42, "terminal": "solved", "cost_usd": 0.011, "events": 33,
 "log_dir": "runs/20261118T100000Z-full-q1-login-1/"}
```

`terminal` 取 `solved | unsolved | failed`（failed：CLI 出错、超时，或全栈没跑到终态）。`log_dir` 是
`<产物根目录名>/<时间戳>-<模式>-<题目>-<次>/`，产物根缺省 `runs/`。目录里有 `record.json`，以及 baseline 的
`cli.stream-json`、`workspace/`、`gate.jsonl`，full 的 `stack.log`、`events.json`、`home/`。

每个运行目录另有 `meta.json`（不改 record 的字段）：运行器提交号（`runner_commit`，工作树有改动时带 `-dirty`）、
题目清单摘要（`manifest`，去掉 answer 后的 sha256 前 16 位）、baseline 的沙箱镜像与工具面、闸门上接通的连接数。

## 读数入库

一批运行跑完后，把原始记录收进仓库（只拷 record.json 与 meta.json，两者都不含答案与密钥）：

```
uv run python -m paoding_eval collect --out runs --into docs/m1/readings/<日期>-<批次>/records
```

每条运行一个 `<运行目录名>.json`，外加 `summary.md`（按题目与模式汇总：解出数、平均耗时与成本、是否沙箱、
运行器提交、清单摘要）。读数文档引用这张表；修正读数时写明前一版错在哪里。

## 用法

```
uv run python -m paoding_eval baseline --dryrun                                  # 干跑，无 Docker、无密钥
docker build -t paoding-cli eval/images/cli                                      # baseline 的沙箱镜像（一次）
uv run python -m paoding_eval baseline --problem eval/problems.d/<题>.yaml --image paoding-cli \
    --program claude --upstream https://api.deepseek.com/anthropic \
    --api-key-env DEEPSEEK_API_KEY --model deepseek-chat --run 1
uv run python -m paoding_eval full --problem eval/problems.d/<题>.yaml --config <栈配置.yaml> --run 1
```

题目清单的字段见 `src/paoding_eval/spec.py` 与 `problems.d/TEMPLATE.yaml`。答案由启动题目容器的一方填写，填了答案的清单不入库。

## 依赖

`paoding_graph.contract`、`paoding_adapter.contract`、`paoding_executor.contract`（baseline 的沙箱）。full 模式以子进程起 `scripts/run.py`，经 HTTP 与图服务说话。
