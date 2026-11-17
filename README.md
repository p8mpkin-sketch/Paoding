# 庖丁 (Paoding)

> 通用问题求解智能体 —— 给定明确的起点（Origin）与可验证的目标（Goal），在未知状态空间中搜索路径。
>
> "依乎天理，批大郤，导大窾，因其固然。" ——《庄子·养生主》

## 核心设计目标

**设计不仅要满足眼前，更要兼容未来。**

> "方今之时，臣以神遇而不以目视，官知止而神欲行。"

感知官——为当前模型的缺陷而建的结构（视图、规划者、复核梯、控制器）——随模型成熟逐步退位；守门官——判官、预算、审批、审计、隔离——长存。系统的成功终态是器官的逐步退位，而非无限增厚。详见 [官知止设计总纲](docs/design/paoding-allegory-mapping.md)。

## 当前状态

调研完成（2026-11）。基座规格 v1.1 已裁决（十条异议全部采纳，附三项补充），参考模型与 M0 实施进行中。

## 文档

| 文档 | 说明 |
| --- | --- |
| [docs/research/agent-architecture-survey.md](docs/research/agent-architecture-survey.md) | 调研 v1（Claude 会话产出：六场景基准、高星生态、厂商观点、A/B/C 分级制度） |
| [docs/research/agent-architecture-survey-zcode.md](docs/research/agent-architecture-survey-zcode.md) | 调研 v1（ZCode 会话产出：国内攻防黑板谱系、通用框架演化、五层共识） |
| [docs/research/agent-architecture-survey-v2.md](docs/research/agent-architecture-survey-v2.md) | **调研 v2：两路合并版**（两范式 × 五层交叉表与四条张力） |
| [docs/research/paoding-design-implications.md](docs/research/paoding-design-implications.md) | 调研 → 设计启示（Claude 会话产出） |
| [docs/design/base-layer-spec-v1.md](docs/design/base-layer-spec-v1.md) | **基座规格 v1.1（当前权威）**：约束审计、六个契约、三个机制、两个走查、M0 清单与 M1 目标 |
| [docs/design/spec-v1.1-adjudication.md](docs/design/spec-v1.1-adjudication.md) | 规格 v1.1 裁决书：A1–A10 全部采纳，附三项补充（vault 分级、终态三值、基质接口附录）与一项立场撤回 |
| [docs/design/paoding-allegory-mapping.md](docs/design/paoding-allegory-mapping.md) | **「官知止」设计总纲**：典故-架构全文对应、感知官/守门官两分类、退役条款表、四个新提案 |
| [docs/design/reference-model/](docs/design/reference-model/README.md) | 等级函数与消费门的可执行参考模型（规格的对照，不是实现） |
| [docs/design/architecture-v0.md](docs/design/architecture-v0.md) | 架构 v0 首稿（归档） |
| [docs/design/architecture-v0.1.md](docs/design/architecture-v0.1.md) | 架构 v0.1（v0 + 七条评审修订，历史桥接文档） |
| [docs/design/greenfield-base-run.md](docs/design/greenfield-base-run.md) | 绿地对照运行：无预设独立推导的基座设计（TaskSpec/Judge/Evidence/Ledger/Executor） |
| [docs/design/coordination-substrates.md](docs/design/coordination-substrates.md) | 协调基质设计：黑板/阡陌(git)/榷场(市场) + 基质接口（M0 基质=事件日志，见裁决书 §四） |
| [docs/prompts/fable-v4-arbitration.md](docs/prompts/fable-v4-arbitration.md) | Fable 任务书 v4（仲裁+深化；历史：裁决已由裁决书完成） |

## 命名体系

黑板 = 解牛图 · 技能包 = 锦囊 · 工具层 = 如意 · 验证 = 谛听 · 并行编队 = 八仙过海 · 反思 = 复盘 · 跨项目记忆 = 通鉴

## License

TBD
