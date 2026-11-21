# 12 交接协议：引擎、`lianhua.py` 与实现线

> 焚决设计 v0.2 的第十二篇（待裁决）。回答“引擎交出什么、实现线接收什么”，以及引擎的产物怎么进炼档、后三步怎么照旧跑。

## 1. 分界

```
        引擎（分析实例）                       实现线（主仓库）                         lianhua.py（确定性）
 ① 识火  ② 萃意  ③ 入位  火序           导入 → 设计 PR → 写代码与测试                ④ 验体  ⑤ 融火  定阶  ⑥ 散火
 └──────── 交接包 handoff.json ────────▶ lianhua.py import ──▶ 炼档 placed ──▶ approve ──▶ yanti → ronghuo → jue →（sanhuo）
          只有设计与结构化数据               只有这里写仓库、开 PR、写代码               一行不加模型
```

| | 引擎交出 | 实现线接收并负责 |
| --- | --- | --- |
| 形式 | 交接包 `handoff.json`（[10 §9](./10-schemas.md#9-交接包-handoff)）与一页人读报告，都是分析实例里的 authored 类 Artifact，按 sha256 取 | 把交接包拷进主仓库的工作分支，跑 `lianhua.py import` |
| 内容 | 每个交实现线的候选：炼档种子、萃意八栏与火意全文、入位方案全文（清单草稿、火组、替换谁、各臂、预登记读数、冲突报告、实现步骤、体质影响预判）；火序；异火榜更新提议；剖面修订提议；校验结果 | 炼档 JSON 与 `.md`、包里的清单草稿、异火榜写入；设计 PR；代码、测试、资产 |
| 谁裁决 | 交出之前：cz 在三个闸点 | 设计 PR：cz（`lianhua.py approve`）；定阶：cz（`lianhua.py jue`） |
| 不做 | 写代码、推 PR、改功法、改火位注册表、改剖面与量具表、导入资料库、分配档号 | 改引擎的产物内容（要改就退回引擎重跑入位，或在设计 PR 上由 cz 改并记下） |

一句话：**引擎的产出止于“入位方案经 cz 裁决”；炼档从“入位”状态起由实现线与 `lianhua.py` 接手，与今天手写前三节之后的流程完全相同。**

## 2. 导入

### 2.1 `lianhua.py import`（实现线新增的子命令）

```
uv run python scripts/lianhua.py import <handoff.json> [--only C2] [--queue]
```

做的事，全部确定性：

1. **校验**：用与引擎同一套校验器（V1–V12，`paoding_fenjue.engine.check`）再跑一遍；另核对交接包的 `basis.gongfa_digest` 与当前 `gongfa.json` 的摘要相同，不同就做入位复核（第 3 步），复核不过拒导入。
2. **火位锁**：候选的火位（含火组成员）已有在途炼档（`placed` 到 `readings_ready`）时拒导入；带 `--queue` 则只写异火榜“已交实现线（排队）”。
3. **入位复核**：按当前功法重算原子归属与冲突。被替换的火、原子的拥有者、兼及火位都没变才继续。
4. **开档**：调既有的纯函数，顺序与手工完全相同：
   - `lianhua.new(next_no(), seed.name, seed.title, seed.identified, seed.shihuo)` → `identified`
   - `lianhua.cuiyi(d, cuiyi)` → `distilled`（八栏见 §2.2）
   - `lianhua.ruwei(d, placement.fire, placement.replaces, placement.arms, placement.readings, preregistered)` → `placed`；`placement.fire.lineage.dossier` 填上新档号；清单草稿写进 `fenjue/src/paoding_fenjue/fires/<id>.json`（还不在功法里）
5. **存引擎块**：炼档 JSON 加可选键 `engine`：`{run, candidate, artifacts, essence, placement_extra, provenance}`，其中 `placement_extra` 是 `ruwei()` 不收的那几栏（原子、火组、冲突报告、实现步骤、体质影响预判、拆分、新火位提议）。
6. **写异火榜**：按 `bang_updates` 写 `yihuobang.json`，并把新档号填进条目。
7. **原子写入**：先写临时文件，全部成功再改名；任何一步失败不留半份。

导入之后，炼档在 `placed` 状态，与手写前三节后的状态完全相同。下一步照旧：开设计 PR，cz 裁决后 `lianhua.py approve`。

### 2.2 萃意八栏的渲染规则

`lianhua.cuiyi()` 收八栏字符串。火意（[10 §5](./10-schemas.md#5-火意-essence)）按下面的固定规则渲染，引擎在交接包里给出渲染结果，导入命令再渲染一遍核对相同：

| 栏 | 渲染 |
| --- | --- |
| `yi` | `masked.statement` |
| `premise` | 每条：`{statement}（{成立/部分成立/不成立}：{why}；替代：{replaced_by}）`，以“；”连接 |
| `cost` | 每条 `cost`，以“；”连接 |
| `overlap` | 每条：`{fire}（{dims 以“、”连接}，{relation}）` |
| `conflict` | 每条：`{with}：{statement} → {how，没有则 resolution}` |
| `hypothesis` | `fusion.statement` + “。新生维：” + 各新生维名以“、”连接 |
| `split` | 每条：`{part} → {kernel}（{to}）`；空为“无” |
| `masked` | “机器检验 K1–K5、K7、K8 全过（K6 …）；闸点 2 由 cz 确认遮住出处成立”；有 cz 坚持的未过项时如实写出 |

`render()` 生成的 `.md` 第二节因此与手写的炼档同形；结构化的全文留在 `engine.essence`，界面与审计都读它。

### 2.3 火组

跨火位、行为有变的模式在入位时拆成火组（[08 §5.2](./08-algorithms.md#52-十二步) 第 4 步）。`lianhua.py` 今天一份炼档一团火。实现线的扩展（EN6）：

- 炼档 JSON 的 `fire` 仍是主火；新增可选键 `group`：其余成员的清单草稿与各自的 `replaces`；
- `ruwei` 校验每个成员（形状、火位、`lineage.dossier`、`replaces` 在 `lineage.from` 里）；
- `yanti` 的候选功法装上整个火组再跑 T1–T5；体质改动行数按整组算；
- `jue` 收下时整组一起装进功法、各自被替换的一起进常设留出，品阶只加一；`sanhuo` 整组一起散；
- `test_dossiers.py` 核对火组成员都在同一份炼档里，功法里不存在只装了半组的状态。

### 2.4 炼档模板与 CI 检查的改动

| 改动 | 为什么 |
| --- | --- |
| `TEMPLATE.json` 加可选键 `engine`、`group` | 存引擎的结构化产物与火组 |
| `test_dossiers.py` 容许这两个键；`engine` 存在时核对 `artifacts` 的 sha256 形状、`engine.essence` 能按 §2.2 渲染出第二节 | 引擎产物与 `.md` 一致 |
| `test_dossiers.py` 的“包里不留孤儿”放宽为“在任一份提交进包的功法文件里” | 引擎的两团火只在 `gongfa.engine.json` 里（[09 §1.3](./09-engine.md#13-为什么要单独的分析实例)） |
| `render()` 在第三节后加两小节“冲突报告”“实现步骤”（有 `engine` 时） | 设计 PR 里 cz 能直接看到 |

## 3. 设计 PR 与实现

1. **谁开**：实现线（人，或一个专做实现的 Claude 线程），不是引擎。PR 只含导入产生的文件：炼档 JSON 与 `.md`、清单草稿、异火榜。
2. **PR 正文**：炼档前三节、火序里的位置、体质影响预判（空）、许可证状态与实现线的参考规则（§4）、待 cz 定的〔占位〕参数。
3. **cz 裁决**：值得炼 → `lianhua.py approve <档号> --by cz`；不值得 → 关 PR（等于回滚，炼档只随 PR 进 `main`），异火榜由实现线记“已排除（理由）”。
4. **写代码**：按入位方案的实现步骤。实现中发现设计缝隙：
   - 只是实现细节（文件位置、函数拆法）：直接做，PR 里写一句；
   - 动到预登记读数：**读数登记之后不能改**（`lianhua.ruwei` 已强制），只能关掉这份、开下一份炼档（照旧的规则：赛后不许移动球门）；可以请引擎以“重新入位”模式只重跑 S5；
   - 发现要动体质：停下，拆出体质修炼的变更表，照旧走 [01 §7](./01-boundary.md#7-体质修炼不经吞噬协议)。
5. **后三步照旧**：`yanti`（体质改动行数、静态验体、换上这团火跑 T1–T5）、`ronghuo`（填读数、判结局）、`jue`（定阶）、`sanhuo`（散火）。**一行不改、不加模型。**唯一的扩展是火组（§2.3）。

## 4. 许可证与出处

快照勘察时探测许可证（[08 §3.1](./08-algorithms.md#31-输入的四种形态)），之后每份产物带着它。实现线按下表参考：

| 许可证状态 | 引擎的产物 | 实现线能不能打开原码参考 | 炼档里写什么 |
| --- | --- | --- | --- |
| 宽松（MIT、BSD、Apache-2.0、ISC 等） | 只含火意（火意本来就不含代码） | 可以参考，不复制；若有借鉴的片段，按原许可证要求保留署名并在炼档写明 | 来源、许可证、借鉴了什么 |
| 弱 copyleft（MPL、LGPL 等） | 同上 | 不打开；只借思想 | 来源、许可证、“只借思想” |
| 强 copyleft（GPL、AGPL 等） | 同上 | 不打开；只借思想 | 同上 |
| 专有、没找到许可证、不明 | 同上 | 不打开；只借思想（没找到许可证即保留所有权利） | 同上 |
| 服务条款（只观察行为） | 同上；探测计划经 cz 逐条批准 | 不适用 | 条款页地址、探测计划的 sha256 |
| cz 的描述 | 同上 | 不适用 | “出自 cz 的描述” |

本仓库是 Apache-2.0：与它不兼容的一律只借思想（[02 §4](./02-lianhua.md#4-第二步萃意提炼火意) 的原则不变）。

## 5. 结局回写

| 事件 | 回写 |
| --- | --- |
| `lianhua.py jue` 收下（火莲、合炼） | 异火榜条目 → 已吞噬，填品阶 |
| `lianhua.py jue` 不收（并火、反噬） | 异火榜条目 → 不收，`lessons` 抄炼档的 `outcome_why` |
| `lianhua.py sanhuo` | 异火榜条目 → 已散火 |
| 同一外部系统的下一团火在等 | 前一团定阶后，`lianhua.py status` 提示对它做入位复核（[09 §9](./09-engine.md#9-并发)） |

回写由 `lianhua.py` 的这几个子命令顺手做（实现线），不由引擎做。

## 6. 不变式

| 不变式 | 怎么保证 |
| --- | --- |
| 已有事件回放逐字节不变 | 引擎在分析实例里用既有事件；主实例的事件账在整个交接里一条不写；导入只改仓库文件 |
| 体质改动 0 行 | 引擎、导入、火组扩展都在功法组件、适配层的非体质文件、脚本与测试里；`kernel_forecast` 恒为空 |
| 后三步无模型 | `yanti`、`ronghuo`、`jue`、`sanhuo` 不调任何模型；引擎的丹全部在 S5 之前 |
| 预登记不可改 | 沿用 `lianhua.ruwei` 的强制 |
| 量具不随吞噬改 | 校验器、表、夹具在量具路径；引擎炼档的体质影响预判把量具路径也列为禁区 |

## 7. 实现线要做的事（建议的 PR 切分）

全部体质改动 0 行。顺序按依赖：

| # | PR | 内容 | 依赖 |
| --- | --- | --- | --- |
| E1 | 量具：表与校验器 | `paoding_fenjue.engine`：Schema（本目录 `engine/schemas/` 原样搬入）、能力剖面、火位签名、决策原子与原子归属、机制原语、冲突探针、拒收表、通用专名表；校验器 V1–V12 与 K1–K5/K7/K8；公式与火序；决定块解析 | — |
| E2 | `lianhua.py` 扩展 | `import`、`bang` 子命令；火组；炼档 `engine` 键；`test_dossiers.py` 的三处放宽；`render()` 两小节；结局回写；异火榜首批条目（`engine/examples/yihuobang.seed.json`） | E1 |
| E3 | 引擎工具面 | `h3.tunshi-tools`：`intake`、`probe`、`read_excerpt`（读丹、定界包裹）、`probe_service`、`obs`、`profile`、`check`；`request_access` 的来源比对 | E1 |
| E4 | 引擎形态与分析实例 | `h1.tunshi`、提示资产、`gongfa.engine.json`、`scripts/stack.py` 起分析实例的参数、预算先验的键与占位表 | E3 |
| E5 | 验收夹具 | `fenjue/tests/engine_fixtures/` 四个夹具 × 四种形态、录好的丹输出、CI 里的确定性验收 | E1–E4 |
| E6 | 界面 | 新建分析、三个确认卡（生成决定块）、报告页、候选方案页（排进界面线，EN16） | E4 |
| E7 | 首次真跑 | 测试方用真模型跑验收（[11 §7](./11-acceptance.md#7-怎么跑)），读数回填 | E5 |

**进度（2026-11-21，cz：先做能在夹具上过线的最小版本，识火与萃意走到闸点 2）**：E1 的量具除决策原子表（随入位做）之外都已落地（`paoding_fenjue.engine`：Schema 原样搬入、九张表、公式与火序、K1–K8、V1–V12、决定块解析、预算先验占位表）；E3/E4 先做流程骨架而不接内核（`run.Engine`：立项、快照、勘察、识火、闸点 1、萃意、闸点 2，`run.json` 检查点与续做；交付与决定块的形状就是将来 `deliver` 与 `follow_up` 的内容）；E5 的夹具先做小号（四个合成夹具，各一两百行，13 次识火的丹输出录在 `fenjue/tests/engine_fixtures/recorded/`）。没做的：分析实例与 `h1.tunshi`、`h3.tunshi-tools` 接入内核，真模型适配器，入位与交接，试算模式，E2 的 `lianhua.py import`、`bang`。

**进度（2026-11-21，第二期：入位与闸点 3、交接协议、试算模式）**：

- **入位**（`engine/ruwei.py`，[08 §5](./08-algorithms.md) 的 12 步）：决策原子表 `tables/atoms.json`（35 个原子、各自的归属火位、端口与规则族，参数键到原子的映射）补齐了 E1；位丹只拆原子（只能从表里选，或选“其他”写理由），主丹只写各臂、读数与实现步骤，各最多三次、带着错误重试；归属、主火位、`also_touches` 与火组、席位、端口、冲突种类与默认化解、替换谁、必登读数、体质影响预判、难度全是确定性代码。候选之间的互斥、先后、依赖与火序（含挂起：等新火位、等体质拆分、等互斥定夺、成环；在途炼档的火位锁）也是确定性的。三个单例夹具与组合夹具的入位、火序与设计样例（`engine/examples/case-*.expected.json`、`case-d.order.expected.json`）对上。
- **闸点 3**：每个候选交实现线、搁置（写理由）或排除（写理由），可退回某个候选重新入位（轮次加一），或退回闸点 2；火意没变的候选退回闸点 2 再确认时复用原来的入位，不重花预算。
- **交接**（`engine/handoff.py`）：交接包按 §2.2 生成萃意八栏，异火榜更新提议里首次出现的条目在 `note` 记“候选 Cx”，导入时据此把档号填回。`lianhua.py import <交接包> [--only Cx] [--queue]` 先校验交接包与入位复核，火位被在途炼档占着时拒导入（`--queue` 只记进异火榜排队），全部写入一次原子提交；`lianhua.py bang show|apply`；火组成员随炼档一起定阶与散火；`render()` 加了冲突报告与实现步骤两小节；`test_dossiers.py` 的三处放宽已做。**结局回写**（§5）：`jue` 与 `sanhuo` 顺手改异火榜上对应条目（已吞噬并填品阶、不收并抄教训、已散火）；`status` 提示排队的条目火位已空出、可以先复核再导入。
- **试算模式**：读预算与花费份额各减半，自动取火序前三，萃意单稿（不出第二稿与盲评；K8 有指令痕迹时仍重写），入位只做骨架不调主丹；产物 `dry_run.json` 与异火榜更新提议。转正式时 `start(intake, reuse=试算工作区)` 复用快照、勘察、精读与候选，核对快照一致，不再调模型。
- **界面要用的两项**（E-U4、E-U5）：界面会显示的所有自由文本（候选、火意、入位、试算、交接包）都过一遍内部词校验（V5），词表加了十个词；每次交付的回答末尾附“产物对照”表（产物｜Artifact id｜sha256），Artifact id 缺省 `local:<sha256 前 16 位>`，接内核后由 `Config.artifact_id` 换成真 id。
- 验收录音 14 份（含组合夹具的试算一份）重录；体质改动 0 行。还没做的：分析实例与 `h1.tunshi`、`h3.tunshi-tools` 接入内核，真模型适配器。
