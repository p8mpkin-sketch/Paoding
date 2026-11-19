# 通鉴（paoding_tongjian）

规格 v1.5 第 50、51 条与内核增量 8、9、10；机制设计见 `docs/design/m2-capabilities/01-memory.md`。本组件只依赖 `paoding_graph.contract`。

| 模块 | 内容 | 官 |
| --- | --- | --- |
| `reducer.py` | 通鉴日志的 validate 与 apply：`case_sealed`、`mem_derived`、`mem_pin`、`mem_forget`；记忆状态 `mem_state` 是派生量 | 守门官 T-0 |
| `project.py` | 判例投影（解题链、链头封存、切口、分角色花费、召回结果）与记忆条目（环境事实、排除路径、花费画像）；封存过滤 | 守门官 T-0 |
| `match.py` | 开题前匹配：环境键精确、签名包含、BM25 | 感知官 T-1 |
| `recall.py` | 开题人一侧：按 `memory=off\|recall\|noverify` 把召回清单写进开题批次 | 感知官 T-1 |
| `runner.py` | 召回运行器：领 `recall` 租约，以 `recall` 角色原样提交召回判据并请求判定。不含模型 | 守门官载体 |
| `service.py` | 通鉴服务：通鉴日志的唯一写入者（复用图服务的 `EventLog`），关题即封存 | 守门官 T-0 |

不变量：

1. 写入没有模型：封存、投影、匹配、召回全是确定性代码。
2. 通鉴日志与题日志是同一种基质：同一套信封、JCS、哈希链，单写者；状态由重放得出，重启后与之前逐字段相同。
3. 记忆状态的唯一更新入口是 `case_sealed` 带回的召回结果（以及 `mem_derived` 的新一次在链 E3）；人只能钉住与遗忘，带 `seen`。
4. 等级不过界（I7）：召回事实在新题里是新节点，等级只由新题判官的裁决决定；没通过的不能作可采信前提。
5. `case_seal=off` 时判例照常封存，判例往下的投影（记忆条目）不写，因而没有召回。

全栈里由 `scripts/memory_hub.py` 组装：一个循环先跑召回运行器、再封存已关的题；HTTP 上挂 `GET /v1/memory` 与 `POST /v1/memory/match`。最小版本没做的：召回判官墙钟 60 秒上限、`/v1/memory/proposals` 写端点与 `pd memory` 命令、前端呈现（留泳道期）。
