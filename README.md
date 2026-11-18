# 庖丁 (Paoding)

> 通用问题求解智能体 —— 给定明确的起点（Origin）与可验证的目标（Goal），在未知状态空间中搜索路径。
>
> "依乎天理，批大郤，导大窾，因其固然。" ——《庄子·养生主》

## 核心设计目标

**设计不仅要满足眼前，更要兼容未来。**

> "方今之时，臣以神遇而不以目视，官知止而神欲行。"

感知官——为当前模型的缺陷而建的结构（视图、规划者、复核梯、控制器）——随模型成熟逐步退位；守门官——判官、预算、审批、审计、隔离——长存；量具——预测账、常设留出、归因表——只产生读数，越换代越有用。系统的成功终态是器官的逐步退位，而非无限增厚。详见 [官知止设计总纲](docs/design/paoding-allegory-mapping.md)。

## 当前状态

**规格。** 基座规格 v1.4 是当前权威：v1.3（v1.1 的裁决、v1.2 的三项补充与典故对账 D1 到 D6、蓝图 v2 的采纳项与评审附加条件、人机界面设计的裁决落地项）加上 M0 实施中裁决的四条勘误 E1 到 E4。参考模型 88 条测试全绿。

**代码（2026-11-18）。** M0 的机制层已经写完并合入 `main`：九个组件、图服务的 HTTP 绑定、网页前端 F1、全栈一键启动（`scripts/run.py`）。`uv run pytest` 369 条（含全部 Docker 测试）、`web` 的 `npm test` 53 条全绿。全程只用假 CLI（`adapter/src/paoding_adapter/fakecli.py`），没有调用过真实模型。

**还没有的。** 真实模型与题目环境上的实效验证（B1、B1b 与庖丁各臂的解题率和成本）尚未进行，规格里标 `[假设]` 的条目都还没有读数。质量提升两个阶段（安全与正确性加固；前端体验、运维基础、文档收口）的条目逐项以 PR 进行，进度见 [docs/m0/status.md](docs/m0/status.md)。

## 代码（M0，EDR-001 D-4）

| 目录 | 组件 | 规格 |
| --- | --- | --- |
| [pd/](pd/SPEC.md) | 人的通道 CLI，F0 四语域文本 | §3.1.2 人的操作、HMI F0 |
| [graph/](graph/SPEC.md) | 解牛图服务、Artifact 仓库、预算账本投影 | §3.1、§3.2、§3.5 |
| [adapter/](adapter/SPEC.md) | Worker Adapter、端点代理 | §3.4 |
| [executor/](executor/SPEC.md) | 执行层 | §3.6 |
| [judgebox/](judgebox/SPEC.md) | 判官运行器、内建判官、保密库 | §3.3 |
| [watchdog/](watchdog/SPEC.md) | 哮天犬 | §3.5 |
| [eval/](eval/SPEC.md) | 评测台（M0：B1、B1b） | §8 |
| [sinan/](sinan/SPEC.md) | 司南（调度，外壳） | §4.1 |
| [web/](web/SPEC.md) | 网页前端（F1）：前沿、检视与下钻、时间轴回放、成本仪表、开题向导、Hint、审批卡 | HMI §3、§4、§10、§11 |

全栈一键启动（假 CLI、空配置即可；执行层要本机 Docker）：

```
uv run python scripts/run.py --home /tmp/paoding-run --port 8100   # Ctrl+C 干净退出
scripts/test-e2e.sh                                                # 起全栈 → 开一道题 → 等 solved → 摘要 → 清理
```

配置（`<home>/config.json`，可省）的形状见 `scripts/e2e/config.json`；构建过 `web/dist` 的话，网页就在同一端口（`http://127.0.0.1:8100/`，人的令牌在 `<home>/human.token`）。图服务对外只有 HTTP（只监听回环地址），端点表见 [graph/SPEC.md](graph/SPEC.md) 的“HTTP 绑定”。

```
uv run pytest -q                      # 单元与对抗测试（没有 Docker 时相关测试自动跳过）
python ci/check_domain_words.py       # 红线 3
python ci/check_deps.py               # 依赖只走契约接口
(cd web && npm ci && npm run typecheck && npm test && npm run build)   # 前端
```

M0 进度见 [docs/m0/status.md](docs/m0/status.md)，实现中发现的规格缝隙见 `docs/m0/dissent-*.md`（下表“实施记录”）。

## 文档

| 文档 | 说明 |
| --- | --- |
| [docs/design/core-innovations.md](docs/design/core-innovations.md) | **核心创新与架构总览（项目名片 / 定盘星）**：信条、骨架一张图、创新账（出处+状态）、方法论出身、未证明清单、动工检查单 |
| [docs/research/agent-architecture-survey.md](docs/research/agent-architecture-survey.md) | 调研 v1（Claude 会话产出：六场景基准、高星生态、厂商观点、A/B/C 分级制度） |
| [docs/research/agent-architecture-survey-zcode.md](docs/research/agent-architecture-survey-zcode.md) | 调研 v1（ZCode 会话产出：国内攻防黑板谱系、通用框架演化、五层共识） |
| [docs/research/agent-architecture-survey-v2.md](docs/research/agent-architecture-survey-v2.md) | **调研 v2：两路合并版**（两范式 × 五层交叉表与四条张力） |
| [docs/research/paoding-design-implications.md](docs/research/paoding-design-implications.md) | 调研 → 设计启示（Claude 会话产出） |
| [docs/design/base-layer-spec-v1.md](docs/design/base-layer-spec-v1.md) | **基座规格 v1.4（当前权威）**：文首三张变更表逐条可否决（第三张是 M0 勘误 E1 到 E4）；约束审计、三层六契约与八条不变量、题界与封存、三个机制与前沿展开（榷场、闲人、子题）、四个走查、M0 清单、M1 目标与审计清单、未证明清单 20 条 |
| [docs/design/spec-v1.1-adjudication.md](docs/design/spec-v1.1-adjudication.md) | 规格 v1.1 裁决书：A1–A10 全部采纳，附三项补充（答案保密分级、终态三值、基质接口附录）与一项立场撤回 |
| [docs/design/paoding-allegory-mapping.md](docs/design/paoding-allegory-mapping.md) | **「官知止」设计总纲 v1.2**：典故-架构全文对应、感知官/守门官/量具三分类与启用条件、退役条款表、四个新提案 |
| [docs/design/paoding-jieniu-principles.md](docs/design/paoding-jieniu-principles.md) | 庖丁解牛逐句对账（Claude 会话产出）：12 条原理 × 规格对账 + D1–D6 设计点 |
| [docs/design/hmi-design-v1.md](docs/design/hmi-design-v1.md) | 人机交互设计 v1.1：十条原理逐条落实（四语域、判据卡、审批卡、回放、关题三步）、五场景矩阵、线框、API server 裁决（图服务直出）、模型接入全景；H1–H6 已采纳 |
| [docs/design/reference-model/](docs/design/reference-model/README.md) | 等级函数与消费门的可执行参考模型（规格的对照，不是实现） |
| [docs/design/architecture-blueprint-v2.md](docs/design/architecture-blueprint-v2.md) | 总架构蓝图 v2 与创新前沿：定盘审计（F1–F3、I7、I8）、题界与封存、榷场、通鉴、闲人、多节点、Lean 接入、N1–N3（已整体采纳，落地见规格 v1.3） |
| [docs/reviews/blueprint-v2-review.md](docs/reviews/blueprint-v2-review.md) | 蓝图 v2 对抗评审：P1、P2 附加条件 |
| [docs/design/blueprint-v2-adjudication.md](docs/design/blueprint-v2-adjudication.md) | 蓝图 v2 裁决书：整体采纳，官的三类化 |
| [docs/design/architecture-v0.md](docs/design/architecture-v0.md) | 架构 v0 首稿（归档） |
| [docs/design/architecture-v0.1.md](docs/design/architecture-v0.1.md) | 架构 v0.1（v0 + 七条评审修订，历史桥接文档） |
| [docs/design/greenfield-base-run.md](docs/design/greenfield-base-run.md) | 绿地对照运行：无预设独立推导的基座设计（TaskSpec/Judge/Evidence/Ledger/Executor） |
| [docs/design/coordination-substrates.md](docs/design/coordination-substrates.md) | 协调基质设计：黑板/阡陌(git)/榷场(市场) + 基质接口（M0 基质=事件日志，见裁决书 §四） |
| [docs/design/engineering-decisions.md](docs/design/engineering-decisions.md) | 工程决策记录 EDR-001：语言、前端、部署、仓库（monorepo 与组件目录的出处） |
| [docs/reviews/spec-v1.3-review.md](docs/reviews/spec-v1.3-review.md) | 规格 v1.3 终审 |
| [docs/reviews/hmi-v1-review.md](docs/reviews/hmi-v1-review.md) | HMI 设计 v1 对抗评审 |
| [docs/prompts/fable-v4-arbitration.md](docs/prompts/fable-v4-arbitration.md) | Fable 任务书 v4（仲裁+深化；历史：裁决已由裁决书完成） |

**实施记录（M0）**

| 文档 | 说明 |
| --- | --- |
| [docs/m0/kickoff.md](docs/m0/kickoff.md) | M0 开工指令：新会话读它恢复上下文 |
| [docs/m0/status.md](docs/m0/status.md) | 进度日志：逐日的落地内容、验收条目与测试数 |
| [docs/m0/errata-v1.4.md](docs/m0/errata-v1.4.md) | 勘误 E1 到 E4 的原清单（已并入规格 v1.4） |
| [docs/m0/dissent-001-skeleton.md](docs/m0/dissent-001-skeleton.md) | 异议 001：仓库骨架（已裁决，三项采纳） |
| [docs/m0/dissent-002-adapter.md](docs/m0/dissent-002-adapter.md) | 异议 002：Adapter（已裁决，四项采纳，即 E1 到 E4） |
| [docs/m0/dissent-003-human-ops.md](docs/m0/dissent-003-human-ops.md) | 异议 003：内核补齐两项人的操作（已落实） |
| [docs/m0/dissent-004-http-api.md](docs/m0/dissent-004-http-api.md) | 异议 004：HTTP 绑定的九处缝隙（待裁决） |
| [docs/m0/dissent-005-web-f1.md](docs/m0/dissent-005-web-f1.md) | 异议 005：网页前端 F1 的十二处缝隙（待裁决） |
| 各组件的 `SPEC.md` | 该组件实现了哪些契约、官的声明、与规格的偏差和进度（见上文代码表） |

## 命名体系

黑板 = 解牛图 · 技能包 = 锦囊 · 工具层 = 如意 · 验证 = 谛听 · 并行编队 = 八仙过海 · 反思 = 复盘 · 跨项目记忆 = 通鉴

## License

TBD
