# adapter/：契约 4 Worker Adapter（会话边界）

规格：v1.3 §3.4；不变量 I2、I6。

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
| `proxy.py` | 端点代理：任务令牌换真实密钥（`x-api-key` 或 `Bearer` 都收，转发时只带真实密钥）；非流式 JSON 与 SSE 两种计量；`cost` 事件 `source=proxy`，幂等键 `cost:<租约>:<第几个请求>`；三道 429（任务预留、题上限、全局上限，默认 500 美元）；作废令牌 401；先入账再写响应结束块 |
| `tools.py` | `exec` / `submit` / `show` 三个代理工具与 Op 翻译；`*_path` 登记为 authored；`claim_done` = 登记候选 + `request_judge`；`tmp_id`；同一操作连拒 3 次不再转发 |
| `mcp.py` | 工具端点：MCP 的 HTTP 传输最小子集；每会话一个随机路径，一个进程并行托管多个会话 |
| `package.py` | 任务包①–⑦渲染与留档；黄金文件 `tests/golden/reason_package.txt` |
| `backend.py` | 十项绑定的命令构造、`--mcp-config` 内容、模型容器的 `docker run` 命令；都不运行 |
| `fakecli.py` | 脚本化假 CLI：接受同一组参数，经代理发请求、经工具端点调工具、输出 stream-json |
| `session.py` | 会话运行器：状态机、续租、停滞判定、回合上限、收尾轮、`failed(no_output)`、会话记录留档、释放与令牌作废 |

### 实现取值（待红队确认）

1. **计量取整**：每个请求按价目表折成毫美元后向上取整；价目表里没有的模型按最贵档计。cache 写入按输入价的 1.25 倍（价目表 `cache_write` 字段，密钥到位后与官网核对）。cost 事件没有 cache 写入的 token 字段，它只体现在 `usd_milli` 里。
2. **单请求超额**：额度在请求开始时检查、结束时入账，一个请求最多越过预留一次请求的花费。要逐 token 截断须在代理里改写流，M0 不做。
3. **续租**：不改 TTL，沿用司南领租约时定的值（规格写 TTL 120 秒，那是司南领租约时的取值）。
4. **`add_intent` 缺省预算**：Op 的 `budget_hint` 可省，内核的 `budget` 必填；省略时填 500 毫美元、600 秒。
5. **终局映射**：`final.outcome` 的 found→done，nothing 与 unsolved→nothing，failed→failed；交过 submit 而没给 final→done。
6. **幂等键**带工具宿主的实例号：同一租约换了宿主也不会撞上旧结果（测试里真撞上过一次，返回了前一个宿主的缓存结果）。
7. **⑤状态**只列非 open 的 Intent 与论断等级，让⑤随图增长得慢一些。

### 已知缺口

1. **3.4.5 的 5 后半（缓存读 > 0）与 7 的真机部分**要真模型，D4 真机验。假 CLI 对 `--tools`、`--restricted` 的模拟只证明绑定参数被传到了，不证明真 CLI 照做。
2. **判官 30 秒内的裁决随 submit 返回**：判官运行器还没有（D10），`submit` 目前只返回 id。
3. **3.4.5 的 3**（中途杀 CLI → 租约到期 → Intent 重开）的 reducer 侧已在 graph 测试里；端到端要哮天犬，下一个 PR。
4. **`check.inputs`** 暂拒，见异议报告 002 第 1 项。
