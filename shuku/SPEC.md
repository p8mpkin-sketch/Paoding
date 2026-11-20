# 书库（paoding_shuku）规格：资料库第一期

设计稿：《庖丁知识库后端设计（v5 第四期）》。这一期做书库组件、文字类导入、混合检索、HTTP 端点与知识页的资料一栏；
K1–K3 cz 2026-11-20 裁决：全部采纳推荐项（knowledge 类可作开放道依据、与执行记录分开写、判定道不认；默认 hash 向量器；新建任务知识默认“自动”）。
第二期（执行中检索、knowledge 类别与内核改动、引用进依据、新建任务的知识选项）见文末；pdf / docx、onnx / local_http、网址抓取在第三期。

## 组件

- 书库有自己的只增日志 `shuku.sqlite`（与图服务、通鉴同一种 EventLog 基质），是唯一的事实。
- 本地索引 `shuku-index.sqlite`（段落表、FTS5、向量表）可以整个删掉，`Shuku.rebuild()` 按日志重建。
- 原文与解析出的纯文本都进 Blob 库，日志里只记哈希。
- 依赖方向：shuku → graph（只经 `paoding_graph.contract`）。别的组件只许 import `paoding_shuku.contract`。

## 日志事件（problem_id = `shuku`）

| 事件 | 谁写 | 体 |
|---|---|---|
| `source_put` | 人 | `{source: {id, name, origin, scope}, file}`：新资料，版本 1 进入解析 |
| `revision_put` | 人 | `{source, file}`：新版本；上一个版本还在导入（未失败）时拒绝 |
| `stage_done` | 书库 | `{source, revision, stage: parse\|chunk, info}` |
| `revision_ready` | 书库 | `{source, revision, chunks, embedder}` |
| `stage_failed` | 书库 | `{source, revision, stage, reason, code, count?}`：停住，等人重试或取消。code ∈ secrets / unsupported / empty / error |
| `job_retry` | 人 | `{source, revision, mask?}`：mask 只对 code=secrets 有效，遮盖认出的串后往下走 |
| `job_cancel` | 人 | `{source, revision}` |
| `source_set` | 人 | `{source, disabled}` |
| `source_curate` | 人 | `{source, action: delete\|restore}`：软删进回收站 30 天 |
| `source_purged` | 书库 | `{source}`：到期清掉索引，日志不动 |

`file = {hash, size, media_type, name}`；`origin ∈ {file, folder, url, text}`；`scope ∈ {all, pick}`。

## 五阶段

上传（`source_put` / `revision_put` 时已完成）→ 解析 → 切分 → 建索引 → 可用（`revision_ready`）。
`tick()` 每次给每个在导入的版本推进一步，进程重启后从日志里的那一步接着做。可检索的版本是最新一个 ready 的版本：
新版本导入中，旧版本照常服务；停用、在回收站、已清掉的资料不参与检索。

- 解析：md / txt / 源码 / html / json / csv 等文字类；utf-8，不行再试 gb18030；二进制与 pdf / docx 明确拒绝（第三期）。
  解析出来是空的也算失败。
- 凭据扫描（`creds.py`，与 adapter/creds.py 同一套形状，另加 PEM 私钥块）：解析后、写 Blob 之前扫一遍。认出像密钥的串就停在解析，
  原因里只写处数（不写串本身）；人选“遮盖后导入”（`job_retry` 带 `mask`）后逐字换成占位符再往下走，或取消。
  原文 Blob 是人交来的字节，不改；纯文本 Blob、索引、日志、检索结果里都只有占位符。
- 切分（`c1`）：按标题与空行分块，相邻块并到约 500 字，不超过 800；段落 id = `k_` + sha256(切分器版本、文本哈希、起止)。
  同一文本、同一切分器得到同一组 id，重建索引不改 id。
- 检索：词法（FTS5，拉丁词原样、汉字二元）与向量（默认 `hash-512-v1`）各取前 50，RRF（k = 60）融合；k 至多 20。

## HTTP（scripts/knowledge_hub.py，挂在图服务上）

写只认人的令牌。只收网页或 pd 命令交来的字节：请求体带 `path` / `dir` / `folder` 即 400 `forbidden_op`，
`url` 即 400 `not_supported`（cz 2026-11-19 硬规则：本地题库与校准目录不进资料库、不进会话）。

| 方法与路径 | 说明 |
|---|---|
| `GET /v1/knowledge/sources` | `{sources, embedder, note, as_of}` |
| `POST /v1/knowledge/sources` | `{name, scope?, text, file_name?}` 或 `{name, scope?, origin?, file}`（先 `PUT /v1/blobs`，核对大小） |
| `POST /v1/knowledge/sources/{id}/revisions` | `{text}` 或 `{file}` |
| `POST /v1/knowledge/sources/{id}/disable\|enable\|delete\|restore` | |
| `GET /v1/knowledge/jobs` | 正在导入（含失败）的版本与所在阶段 |
| `POST /v1/knowledge/jobs/{id}/{rev}/retry\|cancel` | retry 可带 `{mask: true}` |
| `POST /v1/knowledge/search` | `{q, k?, pick?}` → `{hits, via, embedder, note}` |
| `GET /v1/knowledge/chunks/{id}` | 一段的原文、标题路径、起止位置、是否有更新的版本 |

错误码：`unknown_ref` 404、`conflict` 409、`forbidden_op` 403 / 400、其余 400。

配置：`knowledge.embedder.kind ∈ {hash, onnx, local_http}`，后两种这一期退回 hash 并在 `note` 里说明。
`/healthz` 的 `knowledge` 一项：循环状态、向量模型、可检索的资料数、在导入数、失败数。

## 验收（cz 2026-11-20）

- 设计稿“测试”一节：单元与集成在 `shuku/tests/`、`tests/integration/test_knowledge_endpoints.py`；全栈与隐私的第二期部分随第二期。
- ① 金丝雀：`shuku/tests/test_canary.py`（书库目录全部文件、纯文本 Blob、检索结果与单段原文、资料与作业列表）与
  `test_knowledge_endpoints.py::test_canary_stays_out_of_index_logs_and_responses`（经 HTTP 全栈一轮，另查运行日志的每条记录）。
- ② 切分确定性单独一轮：`uv run --frozen pytest -q shuku/tests/test_chunk_determinism.py`（重复调用、换进程换哈希种子、
  调用顺序打乱、重建索引与同字节再导入）。

## 第二期：执行中检索与引用（cz 2026-11-20 开工）

- 内核（`graph/src/paoding_graph/reducer/knowledge.py`）：
  - `register_artifact` 认 `class = knowledge`，只由书库的组件令牌 `graph:shuku` 登记，体带
    `knowledge: {source, revision, chunk, locator}`；别的类别带这个字段、别的令牌登记这一类都拒。
  - `kb_query`（新事件，`graph:shuku`）：`{lease, query, hits: [段落 id]}`，不改状态；过程一栏显示为“查资料”。
    查询词先遮盖凭据（原话里的与查询词里认得出的），命中只记段落 id。
  - 能不能当依据：只有开放道交付的**主张**可以引用 knowledge；自检、判定道事实的 grounds、人工验收清单一律
    `inadmissible_class`（cz 验收附加条件 2，`graph/tests/test_knowledge_class.py`）。
  - `prefs.knowledge = {mode: auto | pick | off, pick?}`；缺省按 auto。
- 读法：交付视图每条主张带 `supported`（有执行留档或材料）与 `cited`（引用了资料），分开算；
  “N 条里 M 条有执行记录”的 M 不含只引资料的主张，另标“K 条引用了资料”（cz 验收附加条件 1）。pd 文本同一规则。
- 会话工具（`paoding_adapter.tools`，经 `KnowledgePort` 注入，不 import 书库）：`kb_search(query, k ≤ 20)`、
  `kb_read(chunk)`；每会话至多 40 / 200 次。任务没有可查的资料（选“不用”或范围里没有可用资料）不挂这两个工具。
  判定道的会话也能查，但提示词与返回里写明资料段落不能当 grounds。
- 端口实现（`scripts/knowledge_hub.py` 的 `SessionKnowledge`）：范围 auto = 所有 scope=all 的可用资料，
  pick = 点名的几份（不论 scope）；`kb_read` 只读范围内当前可用版本的段落，原文进 Blob 后登记。资料列表多一个 `cited`（被几个任务引用过）。
- 新建任务：起草校验的 `overrides.knowledge`；auto 不写进任务，pick / off 写进 `prefs.knowledge`，出处记“人”。
- 网页：输入框旁“知识”（自动 / 指定 / 不用）；结果页分开标示；证据抽屉给资料名、位置、当时的原文、
  “这是你给的资料里的话，没有在这次任务里验证”，资料之后有新版本时提示但不替换原文；文件一栏的“引用的资料”。
- 测试：`graph/tests/test_knowledge_class.py`、`tests/integration/test_knowledge_session.py`（假 CLI 全栈：
  kb_search → kb_read → deliver 引用）、`qicao/tests/test_qicao_service.py::test_knowledge_option_goes_into_prefs`、
  web `task.test.tsx` / `kaiti.test.tsx` 与 e2e。
