# 内核语义的参考模型

[基座规格 v1.3](../base-layer-spec-v1.md) 里"由日志派生"的那部分语义，写成可以运行的纯函数，用来检验规格自己的定义是否自洽、是否写得出来。它不是 M0 的代码库：没有事件日志、存储、租约、预算和容器。M0 的 D2 可以把它当作等级函数的对照实现。

```
cd docs/design/reference-model
python3 -m unittest test_kernel        # 88 条测试，Python 3.10 以上，只用标准库
python3 market_walkthrough.py          # 规格 6.3 榷场走查的逐步复算，打印资本列
```

三个文件：`kernel.py` 是模型，`test_kernel.py` 是测试，`market_walkthrough.py` 是榷场走查的记账脚本（测试会导入它，逐格核对走查表）。

## 覆盖范围

| 规格条目 | 模型里的函数 | 测试类 |
| --- | --- | --- |
| 3.1.2 裁决序列、有效裁决、`unstable`、自动复判至多补到 4 次；3.3.5 的 2、7 | `sequence`、`effective`、`rejudge_wanted` | `Hysteresis` |
| 3.1.5 的 3 坏事实注入（完整形态与 M0 形态）、`/invalidations` | `compute`、`invalidations` | `BadFactInjection` |
| 3.1.5 的 4 环状引用（完整形态与 M0 形态） | `compute`、`validate_add_fact` | `CyclicSupport` |
| 3.1.3 的 `independent`、`heterogeneous`、`strength`；5.2 场景 1 | `compute` | `EchoChamber` |
| 3.1.3 消费门表、带判据的 Intent 作前提、r2 的批准只管一次租约；3.1.5 的 7、9 | `gate`、`intent_state` | `ConsumptionGate` |
| 3.1.4 的 E3d；相符性判官的失败只产生争议 | `compute` | `ConsistentJudge` |
| Goal 按候选分别计且没有 X；判据的有效期；撤销判官版本；人的裁决 | `compute` | `GoalValidityAndRulings` |
| 6.1、6.2 两个走查里每一步的等级与状态 | 全部 | `WalkthroughCtf`、`WalkthroughOps` |
| 3.2.5 的 2 的前四种伪造形态；3.4.5 的 4 | `validate_add_fact`、`validate_register` | `ForgedReferences` |
| 最小不动点唯一且终止；信任不超过前提；M0 是完整版的特例 | `compute`、`gate_m0` | `Properties` |
| 3.3.3 对照判据进消费门与续期门的进展：r2 的观察类前提要带对照或由人豁免；3.5.2 | `premises_ok`、`gate`、`counts_as_progress` | `ControlledPredicates` |
| 3.1.7 难点标记、只看最近一次结果、换缝计数、两次换缝后强制升档、认领规则；3.1.5 的 13 到 16 | `failed_last`、`reroutes`、`must_escalate`、`knot`、`escalated`、`claimable`、`validate_follow` | `Knot` |
| 3.1.7 关节度 | `unlocks` | `Unlocks` |
| 3.3.2 判官资产两级：结构级到处只读挂载，含密级只到判官；`vault:` 引用不是 Artifact；3.3.5 的 6、9 | `mountable`、`can_deref`、`show_body` | `JudgeAssets` |
| 2.4 题界与封存：摘录只由图在重放之后登记，等级不出题，`seal_check`，封存撤销；3.1.5 的 10 到 12 | `validate_register_excerpt`、`seal_check`、`compute` | `Seals` |
| 3.1.2 终态三值：`solved` 只来自判定性判官，人验收是 `accepted` | `terminal` | `Terminal` |
| 3.5.3 预测账：按家族与角色结算 Brier 分 | `calibration` | `ForecastLedger` |
| 8.6 常设留出的互斥分配 | `holdout` | `Holdout` |
| 2.2 不变量 I8：任意改动估值类事件，等级、消费门、Intent 状态、审批卡哈希逐例不变 | 全部 | `ValuationsStayOutOfLevels` |
| 3.1.9 人的决策与所见绑定（`seen`、`stale_view`）、r2 的回退声明；3.1.5 的 17、19 | `approval_card`、`card_hash`、`validate_decision`、`validate_rollback` | `SeenBinding` |
| 6.4 Lean 接入走查里每一步的等级与状态 | 全部 | `WalkthroughLean` |
| 6.3 榷场走查的资本列，逐步守恒 | `market_walkthrough.py` | `WalkthroughMarket` |

`Properties` 在 400 个随机状态上逐条检查（固定种子，允许复审的前提成环）：

1. 任意打乱迭代顺序，重算结果相同。
2. 靠复审得到 E1 或 E2 的论断，等级不高于它任何一个前提。
3. 追加一条复审支持，不会让任何论断的等级下降。
4. 去掉一个节点的证伪，不会让其它论断的等级下降。这是 `invalidations` 定义的依据。
5. 只有判定性判官支持时，等级只取 X、E3、E0，完整版消费门与 3.1.2 的 M0 消费门逐例相同。完整版消费门比 M0 多的唯一一项，是 r2 的观察类前提要带对照（M1 才启用）。

`ValuationsStayOutOfLevels` 是 I8 的性质测试：在随机状态上任意增、删、改估值类记录（预测、报价、行情、名额、结算），逐例比较等级、消费门、Intent 状态和审批卡哈希，全部不变。同一批改动确实会改变预测账的读数，由第二条测试确认，免得第一条测的是没人读的字段。

测试的敏感度用变异检查过：对模型逐一做 90 处语义破坏（去掉迟滞、让过期裁决继续计入、不并入目标论断的前提、去掉独立性或异构要求、r2 批准永久有效、让估值进入审批卡、让任务会话能解引用含密级的判官资产、让人验收也算 `solved` 等），每一处都至少让一条测试失败。

## 实测

`compute` 连注释约 80 行，规格 3.1.1 里"百行内可写完"成立。未做优化的 Python 实现全量重算一次的耗时（本机单核，5 次取最小）：

| 论断数 | 裁决数 | 复审数 | 耗时 |
| --- | --- | --- | --- |
| 1000 | 420 | 1160 | 约 6 毫秒 |
| 5000 | 2049 | 5902 | 约 42 毫秒 |
| 10000 | 4066 | 11868 | 约 72 毫秒 |

## 建模时澄清并写回规格的几处

1. 人的裁决如何"优先于判官"：`--refuted` 直接给出 X；`--upheld` 把该论断现有的反证（含判官的失败裁决）标为已驳回，被驳回的裁决不再计入裁决序列。
2. `done.tests` 以 Intent 是否达成为准：达成给相符性支持；判定给出失败而未达成，给相符性判官的反证。
3. `/invalidations` 的定义：把该节点的证伪去掉重算，等级因此变高的其它节点。
4. `grounds` 只收 exec、judge、input 三类；authored 类只作正文、重放规格与候选。
5. 难点标记只看一个 Intent 最近一次租约的结果，之后有观察达成或显式升档就清除；它和关节度都不进等级与消费门。
6. 审批卡的哈希按卡片范围计算：只含该 Intent 的风险、预算、判据、回退声明和各前提的等级与状态。别的对象上的事件和一切估值类事件都不让一次批准过期。
7. 榷场走查的两处行情：两家报价、κ 为 2、先验 0.5 时行情的下界是 0.25，蓝图原表的 0.2 与 0.15 按公式算不出来，改为 0.30 与 0.27，名额归属与每一步的资本不变。

另有两处照规格字面实现，记在这里备查：

- 迟滞按（目标、判官版本）分别计。同一论断上换了判官版本，新版本的第一条失败裁决直接给出 X，即使旧版本的通过裁决仍在。判官升级是因为旧版本有缺陷时，应当先撤销旧版本。
- 序列里只有一条裁决时取该条，所以第一次判定就失败的论断直接是 X。一次请求之内的抖动由判官运行器的 `flake.reruns` 处理，不靠迟滞。

## 没有覆盖的

事件日志与哈希链、`validate` 的其余规则（权限、配额、租约冲突、幂等）、预算与续期门、租约生命周期（`leased`、`done`、重试计数）、争议裁决任务的派生、消费时验证的去重键、写假文件后读出这一种伪造形态（需要真实的执行层）。这些留给 M0。

v1.3 新增而模型没有覆盖的：`as_of` 回放与另外三种卡片（closeout、extension、dispute）的投影、通鉴管线（判例封存、Playbook 抽取、随机留出退役的统计）、闲人协议的触发与吸收率、托管（`escrow_out`、`escrow_in`）与多节点、榷场的在线分配（脚本只复算走查里那一局）。它们分别在 M1、M3、M4、M5 随实现补测试。
