# 方案分析试算：三个验收用例在真外部系统上跑一遍

引擎的第一次实战（cz 2026-11-21：在你自己的电脑上跑）。三道题都是**试算模式**：读预算与花费份额减半、自动取前三个候选、
不出第二稿与盲评，产物是 `dry_run.json`（结论、自动选中的候选、正式跑一次的估算）。全程不碰任何本机题库或校准目录。

## 0. 准备（一次）

- Docker 在跑（`docker info` 能通），先拉镜像：`docker pull python:3.12-slim`
- 仓库在 `main`（含 #139），`uv sync` 过
- 界面要看的话先构建一次前端：`npm --prefix web ci && npm --prefix web run build`
- 一个 Anthropic 的 API 密钥，只放在环境变量里

## 1. 起分析实例（单独的数据目录）

```bash
export ANTHROPIC_API_KEY=…            # 只在这个终端里
uv run python scripts/run.py --home ~/paoding-analysis --port 8200 --config scripts/trial/analysis.yaml
```

界面在 http://127.0.0.1:8200 。缺省三个档位都用 `claude-sonnet-5-5`；要分档（强档用更强的模型）就在设置页的模型档案里加
`heavy` / `mid` / `light` 档案（同端点、同密钥槽）。

## 2. 写一版设置（另开一个终端）

```bash
uv run python scripts/trial/trial.py setup --url http://127.0.0.1:8200 --token-file ~/paoding-analysis/human.token
```

做两件事：关开放道复核（你接受的建议）；把 `codeload.github.com:443` 的连接标成 r1（只在 `--via repo` 时用得上，见下）。

## 3. 开三道题

```bash
uv run python scripts/trial/trial.py open --url http://127.0.0.1:8200 --token-file ~/paoding-analysis/human.token
```

用例与仓库在 [`cases.json`](./cases.json)（可以改）：

| 题号 | 用例 | 仓库（候选） |
| --- | --- | --- |
| trial-a | 甲：多阶段目标的证据确认 | exiw-ai/proofloop |
| trial-b | 乙：长会话的上下文压缩与接力 | OpenHands/software-agent-sdk |
| trial-c | 丙：证据自动留档与关联 | dugarsumit/pydantic-ai-provenance |

每道题开之前，脚本先用 `git ls-remote` 钉住提交（写了 `ref` 就用它，没写取最新的标签，没有标签取默认分支此刻的提交），
再经 GitHub 的接口核对**这个提交**的许可证；许可证不清楚（没有、NOASSERTION、OTHER）的**不开题**，换一个仓库再开
（`--only trial-a` 只开一道）。

然后**在你这边**下载那个提交的源码归档（`codeload.github.com/<owner>/<repo>/tar.gz/<提交>`，至多 200 MB，放在当前目录的
`trial-cache/`，摘要对得上就不重下），随题上传开题；立项单上这份上传带着出处（仓库地址与提交），标题里也写着
`owner/repo@提交前 12 位`。钉住的提交、许可证、归档的 sha256 与字节数记在当前目录的 `trial-record.json`。

为什么不让分析会话自己去抓：执行层（M0）只能连本机的题目容器，连不了互联网上的主机。`--via repo` 仍保留那条路
（会话申请连 `codeload.github.com:443`、你在权限卡上批），但在 M0 上批了也开不了，会交付“受阻”并写明这一点。

**重跑**：题号不能重复，加 `--tag`，例如 `--tag 2` 开出 `trial-a-2`、`trial-b-2`、`trial-c-2`（之前的 `trial-a/b/c`
留在原处，不影响）。

## 4. 在界面上做的事

- 缺省（随题上传）不需要批任何访问申请，开题后直接跑。用 `--via repo` 时第一轮会申请连接 `codeload.github.com:443`
  （只下载、不执行），见上一节。
- 试算走完会交付一次（`answered`），报告里有结论、自动选中的三个候选、正式跑的估算、产物对照表（每份产物的出处与许可证在
  产物里）。试算不需要你在确认点上作决定；看完觉得值得，就照报告里的估算决定要不要对哪一道开正式分析。
- 会话卡住、端点调不通、预算用完、执行层开不了，都会交付并在“需要”里写明下一步；不用看日志。会话里出了没预料到的
  缺陷也会按失败结束、释放租约（原因在 `~/paoding-analysis/sessions/<会话>/cli.stderr.log`），不会一直显示在跑。

## 5. 收读数

```bash
uv run python scripts/trial/trial.py report --url http://127.0.0.1:8200 --home ~/paoding-analysis
```

写出 `trial-report.md`（每道题：钉住的提交与许可证、花费、事件计数、每次交付与“需要”、工作区走到哪一步、试算结论与估算、
产物里记的许可证）。把它贴回线程，我来整理成验收读数，对照 [11 §2](../../docs/design/fenjue/11-acceptance.md) 的预期。
`~/paoding-analysis/analyses/<题号>/` 是完整的工作区导出，有问题时我会请你再贴其中的某个文件。

## 花费

试算每道题的预算上限 20 美元〔占位〕，试算只用其中一半的份额；三道题合计不会超过 60 美元，实际花多少看 `report` 的读数。
