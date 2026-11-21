# adapter/：契约 4 Worker Adapter（会话边界）

规格：v1.4 §3.4；不变量 I2、I6。

## 实现的契约接口

- 模型容器：CLI 后端只有文件工具与三个代理工具 `exec` / `submit` / `show`，无命令执行能力。
- 端点代理：换密钥、逐请求计量、超额拒绝；50%/80% 预算标记（§3.5.2）。密钥只在容器外。
- 工具端点（MCP）与十项后端绑定；任务包渲染与留档（登记为 authored 类）。任务包前缀字节稳定（CI 黄金测试）。
- `exec` 回显 8KB 截断，返回 ArtifactId。

## 官的声明

| 结构 | 官 | 标签 | 启用条件 | 退役信号 / 长存依据 |
| --- | --- | --- | --- | --- |
| 双容器、密钥隔离、代理工具 | 守门官 | T-0 | 常开 | 对抗面来自环境与目标内容 |
| 端点代理的预算硬顶 | 守门官 | T-0 | 常开 | 资源有涯（I6） |
| 代理工具的输出截断 | 感知官 | T-1 | 常开 | 取消截断不伤成本与解题率 → 放宽直至移除 |
| 三层视图与缓存友好布局 | 感知官 | T-1 | 常开；`view=full_dump` | 见 graph/SPEC.md |

## 依赖

`paoding_graph.contract`、`paoding_executor.contract`。

## 实现（D4–D6 假 CLI 版，离线预备）

| 模块 | 内容 |
| --- | --- |
| `proxy.py` | 端点代理：任务令牌换真实密钥（`x-api-key` 或 `Bearer` 都收，转发时只带真实密钥）；非流式 JSON 与 SSE 两种计量；`cost` 事件 `source=proxy`，幂等键 `cost:<租约>:<代理实例号>:<第几个请求>`；三道 429（任务预留、题上限、全局上限，默认 500 美元）；启动时从账本投影（`/budget`）恢复全局与按题的累计花费（`restore`），重启后硬顶不归零；作废令牌 401；先入账再写响应结束块 |
| `tools.py` | `exec` / `submit` / `show` 三个代理工具与 Op 翻译；`*_path` 登记为 authored；`claim_done` = 登记候选 + `request_judge`；`tmp_id`；同一操作连拒 3 次不再转发 |
| `mcp.py` | 工具端点：MCP 的 HTTP 传输最小子集；每会话一个随机路径，一个进程并行托管多个会话 |
| `package.py` | 任务包①–⑦渲染与留档；黄金文件 `tests/golden/reason_package.txt` |
| `backend.py` | 十项绑定的命令构造、`--mcp-config` 内容、模型容器的 `docker run` 命令（由 `container.py` 执行） |
| `container.py` | 模型容器启动器 `ContainerLauncher`：每个会话一张内部网络、一个端点中继、一个模型容器；`UnixBridge`（Unix 套接字 → 本机回环上的端点） |
| `relay.py` | 端点中继：跑在中继容器里，把两个端口的字节流原样转给挂载进来的 Unix 套接字；只用标准库 |
| `fakeupstream.py` | 假模型端点：本机回环上的 `/v1/messages`，usage 定值，不生成内容；测试台与组装根（`scripts/run.py` 的空配置）共用 |
| `fakecli.py` | 脚本化假 CLI：接受同一组参数，经代理发请求、经工具端点调工具、输出 stream-json |
| `session.py` | 会话运行器：状态机、续租、停滞判定、回合上限、收尾轮、`failed(no_output)`、会话记录留档、释放与令牌作废 |

### 会话接管沙箱（组装）

`SessionRunner.run` 在带 `exec` 的会话（bootstrap、explore）开始时按租约编译授权并起执行容器，结束时销毁；reason 会话不起容器。上限取所服务 Intent 的 `risk`，Bootstrap 取 r0，r2 规则只在该 Intent 已获批准时编入（规格 §3.6.2）。调用方显式给 `sandbox_id` 时沿用旧行为（测试台的假执行层）。`Problem.env.base` 是基础规格名，经 `AdapterConfig.bases` 映射到镜像。

对外契约（`contract.py`）：`SessionPort`（司南按租约启动会话的入口）、`SessionRunner`、`AdapterConfig`、`SessionRecord`、`EndpointProxy`、`ProxyConfig`、`PriceTable`、`ToolEndpoint`、`CliBinding`、`fake_program`、`ContainerLauncher`、`local_launcher`。

集成测试 `tests/test_integration.py`（需要 Docker）：假 CLI 经端点代理与工具端点，落到真的执行层与真的图服务。`tests/test_container.py`（需要 Docker）：假 CLI 跑在模型容器里，验容器内到得了工具端点与端点代理、到不了外网、宿主、题目容器。

### 运行时扩权（`docs/design/runtime-grants/` §6，2026-11-19）

- `AdapterConfig.grants_runtime`（组装根给出读设置层 `grants.runtime` 的函数）为真时，会话多一个工具 `request_access {target: "host:port", why}`，系统提示在工具清单后补一段（`package.ACCESS_NOTE`）。入参只收这两个键，风险与动作不由申请方给。
- 工具转图服务的 `request_scope`（net、`connect`）。返回 `granted`（练习道白名单当场批下，或已在范围内；返回时闸门已对齐）、`pending`（进人的待办）、`denied`（人在本题拒过）。批下来但风险高于本任务上限、本会话没有执行容器、执行器不支持热对齐时，`granted` 附 `detail` 说明本沙箱里不开。
- 人批或拒之后，下一次 `exec` 的返回带 `access: [{request, status, target, reason?}]`，每个变化只报一次；`exec` 在运行命令之前先对齐，刚批下的地址这条命令就能用。
- 会话运行器 `SessionRunner.reconcile(lease_id)` 按当前 `Problem.scope` 重编授权交给执行器的 `reconcile`；会话循环看范围指纹（规则条数、已撤销下标），人批或撤销的那一刻就对齐，不等下一次工具调用。`AdapterConfig.grants_hot = False` 退回租约边界（设计 §12.2）。
- 测试：`tests/test_request_access.py`（真图服务、假执行层）、`tests/test_access_live.py`（Docker：练习道自动批下后紧接着的 `exec` 连得上；人在会话中途批准，闸门在下一次 `exec` 之前热加，执行容器不重建；撤销后下一次连接失败）。

### 模型容器（审计 P0-2）

真实后端（`backend.kind == "real"`）的 CLI 缺省在模型容器里起；假 CLI 也可以走同一条路径（配置 `"launcher": "container"`），集成测试就是这么跑的。`local_launcher`（宿主子进程）只留给假 CLI 的测试台与空配置。

每个会话三样东西，会话结束（`launcher.release`）一并拆掉：

| 名字 | 是什么 | 要点 |
| --- | --- | --- |
| `pd-model-<租约>-net` | 内部网络 | `--internal` 加隔离网关（`gateway_mode_ipv4=isolated`，Docker 27.1 起）：没有出站路由，也到不了宿主；老版本退回普通 `--internal` |
| `pd-model-<租约>-ep` | 端点中继 | 网络别名 `pd-endpoints`；8081 → 端点代理，8082 → 工具端点。连回 Adapter 进程的通路见下（`transport`），不持有任何密钥 |
| `pd-model-<租约>` | 模型容器 | CLI 镜像；`--read-only`、`--cap-drop ALL`、`no-new-privileges`、`--init`、与 Adapter 同一 uid；只挂工作区、会话目录（只读）、HOME |

- 中继到 Adapter 的通路（`backend.transport`，缺省按平台）：`unix`（Linux）经只读挂载的 Unix 套接字；`tcp`（macOS）——Docker Desktop 的容器在虚拟机里，挂进去的 Unix 套接字连不通——中继另接默认网桥，带 `--add-host host.docker.internal:host-gateway`，经它连宿主本机回环上的两个端点，与评测台 baseline 同法。模型容器只在内部网络上，两种通路下都到不了宿主。中继起来后先从中继里对两个上游各走一个 HTTP 来回，不通就在开会话前报错（说明要换通路），不留到会话里变成“Connection reset by peer”。
- 容器内环境变量：`ANTHROPIC_BASE_URL=http://pd-endpoints:8081`、`ANTHROPIC_API_KEY=任务令牌`。`--mcp-config` 里的地址是 `http://pd-endpoints:8082/mcp/<会话路径>`。真实密钥只在端点代理进程里。
- 模型容器不在执行容器的网络上：连不到授权范围内的目标；执行容器不在模型网络上：连不到中继，也就连不到模型端点（3.6.4 的 4）。端点代理与工具端点仍只监听本机回环。
- 软线与终止送进容器：`docker kill --signal INT` 与 `docker stop`，不是只给宿主上的 docker 客户端发信号。收尾轮在同一张网络上另起一个容器，HOME 与工作区沿用。
- 容器与网络带执行层的属主标签（`paoding.sandbox`、`paoding.owner`、`paoding.lease`，`paoding.role` 取 `model` / `endpoints`），进程异常退出后由哮天犬的孤儿清扫回收。
- 取值上的缝隙记在 `docs/m0/dissent-p0-2-model-container.md`。

### 实现取值（待评审方确认）

- 工具入参（模型写的 JSON）只经图服务契约里的解析层 `Obj` 读，形状不对是 `schema_error`。`ToolHost.call` 只接 `BadBody`；宿主或下游的其它异常不再说成入参错误，工具端点把它报成 JSON-RPC `-32603` 内部错误并留栈（审计 P1-4）。

1. **计量取整**：每个请求按价目表折成毫美元后向上取整；价目表里没有的模型按最贵档计。cache 写入按输入价的 1.25 倍（价目表 `cache_write` 字段，密钥到位后与官网核对）。cost 事件没有 cache 写入的 token 字段，它只体现在 `usd_milli` 里。
2. **单请求超额**：额度在请求开始时检查、结束时入账，一个请求最多越过预留一次请求的花费。要逐 token 截断须在代理里改写流，M0 不做。
3. **续租**：不改 TTL，沿用司南领租约时定的值（规格写 TTL 120 秒，那是司南领租约时的取值）。
4. **`add_intent` 缺省预算**：Op 的 `budget_hint` 可省，内核的 `budget` 必填；省略时填 500 毫美元、600 秒。
5. **终局映射**：`final.outcome` 的 found→done，nothing 与 unsolved→nothing，failed→failed；交过 submit 而没给 final→done。
6. **幂等键**带工具宿主的实例号：同一租约换了宿主也不会撞上旧结果（测试里真撞上过一次，返回了前一个宿主的缓存结果）。
7. **⑤状态**只列非 open 的 Intent 与论断等级，让⑤随图增长得慢一些。
8. **工作区权限**：执行容器丢了全部能力，容器内的 root 写不了别人的目录，所以会话起沙箱前把工作区目录置为 777。M0 单机单用户可接受；多用户时改为容器内固定 uid 加属主映射。
9. **会话边界**：`SessionRunner.run` 里任何没预料到的异常都杀掉 CLI、按 `failed` 释放租约（`status = failed(error)`，原因写进 `cli.stderr.log` 与 `release.why`），再照常卸端点、撤令牌、销毁自己起的执行容器；司南跑会话的线程池会吞掉异常，不接住就会让租约悬到过期。执行层编不了或起不了这道题的授权（`ScopeError`，例如范围里有 M0 连不了的外部主机）时：要 exec 干活的会话不起 CLI、按失败释放；驱动程序的会话没有沙箱照常跑，地址类来源如实报抓不了。会话中途对齐出站闸门被拒，`reconcile` 返回 `unsupported`，申请工具与 `fetch` 照实告诉模型。

### 已知缺口

1. **3.4.5 的 5 后半（缓存读 > 0）与 7 的真机部分**要真模型，D4 真机验。假 CLI 对 `--tools`、`--restricted` 的模拟只证明绑定参数被传到了，不证明真 CLI 照做。模型容器路径同理：容器、网络、中继都用假 CLI 验过，真 CLI 镜像（HOME 布局、只读根文件系统下它还要写哪里）没有验过。
2. **判官 30 秒内的裁决随 submit 返回**：判官运行器还没有（D10），`submit` 目前只返回 id。
3. **3.4.5 的 3**（中途杀 CLI → 租约到期 → Intent 重开）的 reducer 侧已在 graph 测试里；端到端要哮天犬，下一个 PR。
4. **`check.inputs`** 拒绝：按异议 002 裁决，inputs 属于 JudgeRequest（勘误 E1）。
