"""吞噬引擎（焚决 v0.2，docs/design/fenjue/08-algorithms.md、09-engine.md）：识火、萃意，走到闸点 2。

最小版本（实现线 E1 + E3/E4 的流程骨架，cz 2026-11-21）：

- 量具（归药鼎，引擎改不到）：`schema`（10 的 Schema 原样搬入与校验器）、`data`（能力剖面、火位签名、机制原语、
  冲突探针、拒收表、注入模式、词表、通用产品名与通用词）、`formulas`（差距、价值、置信、难度、风险、优先级、火序）、`checks`（K1–K8、V1–V12）、
  `decision`（闸点决定块）、`budget`（预算先验占位表）、`text`（分词与模式匹配）；
- 流程：`survey`（摄入与勘察）、`shihuo`（识火）、`cuiyi`（萃意）、`run`（工作流、run.json 检查点、续做）；
- 丹：`dan`（模型调用接口；CI 回放录好的输出）。

还没有做的：接进内核（分析实例、`h1.tunshi` 形态与 `h3.tunshi-tools` 工具面、真模型适配器经端点代理）、
入位与火序的 S5、交接 S6、试算模式、异火榜的写入（`lianhua.py bang`）。
"""
