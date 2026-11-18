# eval/：评测台

规格：v1.4 §7 D14、§8、变更表 A2。瘦基线三臂（baseline、Bk、Bn）与 full：同一模型、同一 Goal 判据、同一端点代理与价目表计量（红线 5），瘦基线三臂都在执行层同款沙箱里跑。

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
即庖丁本身的最简形态。B1b 的单会话形态尚未单独做。

## 对照臂：Bk 与 Bn（`src/paoding_eval/arms.py`）

规格 A2：独立重试本身就能涨解题率，所以只和 B1 比会虚高。庖丁赢 Bk 才说明共享状态有价值，赢 Bn 才说明图和等级有价值。
三条瘦基线臂共用一个核心：若干轮，每轮若干个独立的 CLI 尝试，每个尝试一个新沙箱、新工作区（与 baseline 同一套闸门与中继），
同一个端点代理计量。

| 臂 | 每轮 | 轮数 | 尝试之间共享什么 | 何时停 |
| --- | --- | --- | --- | --- |
| `baseline`（B1） | 1 个尝试 | 1 | 无 | 跑完 |
| `bk`（等成本独立重试） | 1 个尝试 | 到预算，或 `--rounds`（缺省 20） | 无 | 任一次解出，或花费到预算 |
| `bn`（共享笔记） | `--workers` 个并行尝试（缺省 3） | 到预算，或 `--rounds`（缺省 10） | 一份只追加的 `NOTES.md` | 同上 |

- **等成本**：`--budget-usd` 取 full 臂在同一道题上的每题成本。预算在每轮开始前检查；轮内每个尝试的代理预留取剩余预算的均分，
  到额即被代理拒（429），所以一臂的总花费至多越过预算一次请求。bk、bn 不给预算也不给 `--rounds` 时拒跑。
- **Bn 的笔记**：每轮开始时把共享笔记拷进各工作区的 `NOTES.md`，提示里说明它是协作者共享的、只许追加；轮末收回每个 Worker
  在原内容之后追加的部分，按“`## w<序号> · 第 <轮> 轮`”接到共享笔记后面。改动了已有内容的那一份整个丢弃，记进 meta。
  同一轮里的 Worker 彼此看不到对方这一轮的追加（轮是同步点）；没有图、没有等级、没有判官，这正是 Bn 要隔离出来的变量。
- **终态**：任一尝试解出即 `solved`；全部尝试 `failed` 即 `failed`；否则 `unsolved`。`cost_usd` 是全部尝试的总花费，
  `events` 是全部尝试的回合数之和，`duration_s` 是整臂的墙钟。
- **产物**：`log_dir/r<轮>-w<序号>/` 是每个尝试（工作区、`cli.stream-json`、`gate.jsonl`），Bn 另有合并后的 `NOTES.md`；
  `meta.json` 多出 `arm`（workers、rounds_max、budget_usd、stopped_by）、`attempts`（逐次终态、花费、回合、到目标的连接数）
  与 Bn 的 `notes`（字节数、被丢弃的改写）。
- **未做**：尝试之间不重置题目容器（与 full 相同：一道题开着时环境不重建）。如果题目有会被尝试改坏的状态，这一点对 Bk、Bn 更不利。

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

`mode` 取 `baseline | full | bk | bn`。`terminal` 取 `solved | unsolved | failed`（failed：CLI 出错、超时，或全栈没跑到终态）。`log_dir` 是
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
uv run python -m paoding_eval bk --problem eval/problems.d/<题>.yaml --image paoding-cli \
    --program claude --upstream … --api-key-env … --model … --budget-usd <full 臂每题成本> --run 1
uv run python -m paoding_eval bn  …同上… --budget-usd <full 臂每题成本> --workers 3 --run 1
uv run python -m paoding_eval full --problem eval/problems.d/<题>.yaml --config <栈配置.yaml> --run 1
```

题目清单的字段见 `src/paoding_eval/spec.py` 与 `problems.d/TEMPLATE.yaml`。答案由启动题目容器的一方填写，填了答案的清单不入库。

## 依赖

`paoding_graph.contract`、`paoding_adapter.contract`、`paoding_executor.contract`（baseline 的沙箱）。full 模式以子进程起 `scripts/run.py`，经 HTTP 与图服务说话。
