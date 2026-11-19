# qicao/：起草（一句话开题）

设计：[`docs/design/kaiti/README.md`](../docs/design/kaiti/README.md)（cz 2026-11-19 裁决：九条全部采纳）。本组件是迁移表第一期。

## 三层里的位置

| 层 | 模块 | 确定性 |
| --- | --- | --- |
| ① 前置抽取 | `extract.py`：答案标签行剪出（`答案：X`、`答案是X`、`Answer: X`）；地址、网址、域名（纯展示，不给起草模型）、时长、金额（`$N`、`N美元`、`N元` 按 intake.yaml 换算）、代码块、文件名、句子 → 区间表；形态用例见 `tests/test_extract_forms.py` | 是 |
| ② 起草 | `draft.py`：模型只指认区间，严格 Schema；经端点代理（`MessagesClient` 拿"开题"账户的任务令牌，不拿密钥） | 否 |
| ③ 校验 | `vet.py`：出处账、答案外泄、判据映射、风险表、预算先验与裁剪、分道 | 是（纯函数） |
| 批次 | `ops.py`：Vetted → 登记 + `open_problem`（`origin.draft = {record: 出处账, lane}`）；答案先进保密库（`vaultio.py`），批次里只有 VaultRef | 是 |
| 服务 | `service.py`（第二期）：`POST /v1/drafts/extract` 与 `POST /v1/drafts` 的实现；`override()`（`vet.py`）收确认卡上人改的风险与预算 | 起草之外是 |

写入路径上没有本组件：开题仍由人的令牌提交（`pd kaiti`，二期网页同一条 `app/submit.ts`）。图服务不调用本组件。

## 数据（`kaiti.d/`，领域词只许写在这里）

- `intake.yaml`：答案标签、URL 缺省端口、模板缺省、零确认开关 `zero_confirm`（**缺省 false**：放行由人按离线读数决定）。
- `practice.yaml`：练习道信封的资源、地址白名单与判官；金额与时长上限取设置层 `caps.practice_*`。
- `priors.placeholder.yaml`：预算先验的占位表。真实的"档位 → 默认预算"表由测试方注入（`--priors`），本仓库不读取任何题库或校准目录。

## 接口

- `PriorSource`：`lookup(tier, signature) → Prior | None`、`version()`；`TablePriors` 是注入表的实现。
- `Settings.from_doc`：读 `/v1/settings` 的形状（生命周期地图 PR #84）：`caps`、`risk`（顺序匹配，未命中 r2）、`models`（起草档案取 `routes.draft`，可按档案名覆盖，不许填端点或密钥）。
- `Settings.grants_runtime`：读设置快照的 `grants.runtime`（运行时扩权，`docs/design/runtime-grants/` §3.1、§12 第四步），没有 `grants` 节即关。开着时 `vet` 的授权恒为工作区一条（`workspace r0`，零出站），起草模型标的入口与参考地址只进 `Vetted.mentions`（`{value, span}`）与 `scope.mention` 出处行（注"执行时如需访问，会按需申请"），不生成规则、不查风险表、不影响道别；`overrides.risk` 无行可改。关着时走旧分支（入口地址即授权），保留作回退与对照臂。
- `offline.py`：§10 第 3 条的离线读数；练习道判定精确率达到 1.0 是零确认放行的前提。

## 起草服务（第二期）

组装根（`scripts/kaiti_hub.py`）把 `KaitiService` 挂在图服务的 `/v1/drafts` 前缀上，只接受人的令牌；图服务不认识它。

- `POST /v1/drafts/extract {text}` → `{text, spans, answers}`：前置抽取，不调模型。答案只报个数。
- `POST /v1/drafts {text, answer?, draft?, model?, nonce?, overrides?}` → 校验结果、区间表（UTF-16 下标）、待登记的材料（正文与 sha256）、带 `"$answer"` 占位的批次。交回 `draft` 即不调模型，只重新校验；`overrides` 是确认卡上的人改（`risk`、`usd_milli`、`wall_s`），改过的出处记"人"，不再是练习道候选，超过单题硬顶直接 400，不替人裁剪。
- 零确认一律关（第三期信封已进内核但休眠，开关的打开等测试方的精确率读数）：`lane` 只有 `confirm` 与 `refuse`。答案来自原文答案行时回传一次（`secret`），前端只拿它写保密库；答案栏里的不回传。
- 不持有令牌、不写图服务、不写保密库：前端用人的令牌依次 `PUT /v1/blobs`（三方核对哈希）、`PUT /v1/vault`、`POST /v1/problems`。
- 起草模型：`kaiti.draft` 取 `heuristic`（演示起草，不调模型；假 CLI 后端的缺省）、`messages` 或 `off`。`messages` 的令牌只从环境变量读（`kaiti.token_env`，缺省 `PD_DRAFT_TOKEN`），配置文件里写密钥即报错。经端点代理的"开题"账户与钥匙环归生命周期地图线程；接上之前请求直接打到 `kaiti.url`（缺省同上游）。
- 设置快照：全栈组装读设置存储（`/v1/settings`）的当前快照，与内核的单题硬顶同源；`kaiti.settings` 文件只用于没有设置存储的独立部署。`KaitiService` 收的是取快照的函数。

## 还没有做的

零确认开关的打开（等测试方的精确率读数放行）；端点代理的"开题"账户与钥匙环（同上）。
