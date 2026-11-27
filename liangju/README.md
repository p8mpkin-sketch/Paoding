# 量具（引擎之外）

三样只读工具，加上它们共用的输入形状。设计见《焚决分析引擎：现行设计（合并版）》第 5、7.2、13、14 节。

| 工具 | 做什么 | 入口 |
| --- | --- | --- |
| 盲判 | 同一个过线定义判所有臂：整理、判读、回原文抽样核对；每个不利的判断记成一条发现记录 | `python -m liangju.mangpan` |
| 汇总 | 从盲判的产出与花费记录生成汇总数（设计第 13 节的字段），没有需要人填的栏 | `python -m liangju.huizong` |
| 表项计数 | 数引擎里的词表条目、正则、门槛常量、提示词里的硬规则 | `python -m liangju.biaoxiang` |

另有两个打下手的：`liangju.tici`（把一条臂的导出整理成与臂无关的题次记录）、`liangju.pici`（批次头）。

## 它不碰引擎

- 不 import 任何组件，任何组件也不 import 它（`ci/check_deps.py` 第 4 条）。
- 只读运行结束之后的导出：工作区导出目录，以及这道题的事件、预算视图、交付的回答三个只读的 GET。
  不读运行中的状态，不往运行里写任何东西。
- 盲判自己的模型调用直接连人登记的端点，不经过引擎，也不经过引擎的端点代理与预算账；用量记在盲判自己的流水里。
- 碰了 `liangju/` 的改动，引擎、适配层、体质、提示词、表、Schema、夹具与录音、组装脚本必须改动零行，
  功法清单、火清单与提示词的摘要逐项相等（`ci/check_liangju.py`，CI 在合并请求上跑）。

## 尺子只有一把

一个题次过线，当且仅当三条都成立：

1. **答到**：每个子问都被判为答到。前提不成立、且讲清了实际情况的，算答到。
2. **属实**：回原文抽到的结论里，没有一条被原文否定，也没有一条找不到依据。
3. **在预算内完成**：运行正常结束，折算后的花费不超过每题上限（批次头里计划的数；没有计划时取这次运行自己的上限）。

盲判对每个题次看到的只有四样：题面、这道题的子问清单、交出的回答文本、定版快照。`BlindItem` 里没有臂名，
提示词里也就不可能出现；同一份回答标成哪条臂，判的是同一份（同一个盲号）。子问清单随题目一起定，不由任何一条臂拆。

**交给盲判的回答文本只有回答本身。** 每条臂的转换都一样：臂自己的过程产物（自己拆的子问、核对标注、读数、
候选评估）一律不进 `answer.md`。引擎这条臂（`tici.answer_only`）不是从交付的报告里往外删，而是从导出里结构化的
回答产物取每条结论的原文与出处，排成一条一行；每条都要逐字出现在交付的报告里，没出现的不算交出去了（个数记在
`own.undelivered_items`）。报告第一行的读法说明、每条旁边的核对标注、「没读到的」「核对记录」两节、后面整段预评估
都不在里面。没有按题读的运行交付的只有候选评估：运行算正常结束，交给盲判的回答是空的，汇总里单列一个数。

抽样量：每个子问抽 2 条承重结论、一份回答至多 8 条，某个子问不足 2 条就全查。抽哪几条由种子定，种子由计划哈希
（没有计划时用题集摘要）与题号派生。

盲判的模型**单独登记，必须与各臂的模型不同**，并且三份已知答案的自检样本（`canary/`：漏掉一个子问、写错一条承重
结论、前提不成立且说清了实际情况；两种文风各一份）都判对了才启用。下面三种情况 `judge` 拒绝启动，一份都不判：

- 登记不全（模型名、版本、线格式、端点、密钥所在的环境变量）；
- 盲判的模型与某条臂登记的或运行里读回的模型相同；
- 没有自检记录，或自检记录不是这个模型、这个版本、这版提示词的，或没有全部判对。

## 起点轮怎么用

题目内容留在本机，不进仓库。下面的文件都在仓库之外。

**题集** `questions.json`（每道题带子问清单与快照目录；`axes` 是分层用的五条轴，可缺）：

```json
{"v": 1, "code": "题集代号", "questions": [
  {"id": "q01", "text": "题面", "subquestions": ["子问一", "子问二"], "snapshot": "相对本文件的快照目录",
   "axes": {"language": "…", "size": "…", "ask": "…", "premise": "…", "where": "…"}}
]}
```

**各臂的登记** `arms.json`（任何一条臂的模型栏空着，批次不登记）：

```json
{"B":  {"role": "benhuo",  "model": "…", "version": "…", "endpoint": "端点代理", "sampling": {},
        "metering": "端点代理的计量事件", "price_table": "…"},
 "B2": {"role": "tonghuo", "model": "…", "version": "…", "endpoint": "端点代理", "sampling": {},
        "metering": "端点代理的计量事件", "price_table": "…"}}
```

**盲判的模型** `judge.json`（`wire` 取 `anthropic` 或 `openai`；密钥只放在环境变量里）：

```json
{"name": "…", "version": "…", "wire": "openai", "url": "https://…/v1", "key_env": "JUDGE_API_KEY"}
```

**步骤**（都在仓库根目录下跑）：

```bash
B=~/shihuo/S0-1                          # 批次目录
# 1. 跑之前登记批次头（记下提交号、工作区是否干净、配置摘要）
python -m liangju.pici start --batch $B --id S0-1 --purpose 起点轮 --arms arms.json \
    --config <引擎用的配置文件> --set-code <题集代号> --set-source 手出 --runs 2 --parallel 4
# 2. 用现在的引擎原样跑：每道题本火与同火对照各 2 次，并行 4 路，两条臂交替排队
# 3. 跑完再记一笔
python -m liangju.pici end --batch $B --config <引擎用的配置文件>
# 4. 把导出整理成题次记录。runs.json: [{"pid": "…", "arm": "B", "question": "q01", "rep": 1}, …]
python -m liangju.tici collect --runs runs.json --home ~/paoding-analysis --url http://127.0.0.1:8200 --out $B
# 5. 盲判：先自检，再判，再重判五分之一
python -m liangju.mangpan selfcheck --judge judge.json --out $B/selfcheck.json
python -m liangju.mangpan judge   --batch $B --questions questions.json --judge judge.json --jobs 4
python -m liangju.mangpan rejudge --batch $B --questions questions.json --judge judge.json
# 6. 汇总
python -m liangju.huizong --batch $B --questions questions.json
```

回传的只有 `$B/summary.md`（或 `summary.json`）。它里面只有计数、比例、代号与摘要；题面、子问、仓库名、文件路径、
引用内容、回答原文、发现记录里的那句自由文字与证据指针，都不在里面。发现记录（`findings.jsonl`）、盲判的逐份结果
（`verdicts/`）留在本机，第 1 步的归类器就位后补算新类别曲线的第一个点。

`judge` 可以接着上次做：判过的不重判，上次没做成的补上。

## 表项计数

```bash
python -m liangju.biaoxiang                                        # 现在的计数
python -m liangju.biaoxiang --check liangju/baseline/biaoxiang.json  # 哪一类比初值多了就非零退出
```

`baseline/biaoxiang.json` 是初值（数法第 1 版）。数法写在 `biaoxiang.py` 开头；改数法要换版本号，不同版本不放在一起比。

`--check` 接在 CI 里，推送与合并请求都跑：四类里哪一类比初值多了就红。要让它变绿只有两条路：把加的东西拿掉，
或者改 `baseline/biaoxiang.json` 这一个文件。初值文件在 `liangju/` 下，按上面「不碰引擎」那条，它不能和引擎的改动
放在同一个合并请求里：抬初值是单独的一个合并请求，审读的人看得见抬了哪一类、抬了多少。

## 回原文核对时的搜索

搜索的正则是盲判的模型给的。每次搜索在一个子进程里跑（`liangju.sousuo`），上限 10 秒：超了就停，按「没有搜到」
回给模型并注明是超时，次数记进这份回答的判的记录（`search_timeouts`），汇总的「量具自检」里有合计。

## 现在量不到的

- 各项检验的首次通过率：引擎的导出里没有逐项检验的首次通过记录，汇总里这一栏写「导出里没有」。
- 写入缓存的 token：端点代理的计量事件里只有新输入、命中缓存的输入、输出三个数，折算时写入缓存按零算
  （代理自己的账面数算了这一项，汇总里的折算数因此不大于账面数）。
- 导出的用量与服务商账单的对账：要人拿到账单后填进批次头的 `reconciliation`，没填时汇总写「未对账」。
- 整理这一段看得到回答原文，可能对不同文风摘得不一样。缓解办法是只许摘、逐字可核，以及自检样本用两种文风各做
  一份；不能完全消除。
