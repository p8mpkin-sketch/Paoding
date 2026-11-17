# graph/：契约 1 解牛图服务 + 契约 2 Artifact 仓库 + 契约 5 预算账本投影

规格：v1.3 §3.1、§3.2、§3.5；不变量 I1、I3、I4、I7、I8。

## 实现的契约接口

- 事件信封 `Event`（§3.1.2），JCS（RFC 8785）规范化，按题哈希链 `prev_hash → hash`。
- 内核函数 `validate(state, actor, op)` 与 `apply(state, event)`：纯函数，不读时钟、不做 IO、不调用模型（I1）。
- 等级函数、消费门、Intent 状态：**从参考模型搬运，不重写**（`src/paoding_graph/refmodel.py` 是 `docs/design/reference-model/kernel.py` 的逐字节副本，CI 比对）。参考模型与规格不一致时以规格为准，并写异议报告。
- 端点（M0 走本机 Unix socket）：§3.1.2 端点表与 §3.2.2 Blob/Artifact 端点。
- Blob 仓库：本地目录按 sha256 寻址，写入不可变，读取校验哈希（`corrupt`）。
- 对外契约（`paoding_graph.contract`）：事件信封、拒绝码、Artifact/Check/VaultRef 类型、客户端。

## 官的声明（附录 B 三类制）

| 结构 | 官 | 标签 | 启用条件 | 退役信号 / 长存依据 |
| --- | --- | --- | --- | --- |
| 事件日志 + 确定性裁决 | 守门官 | T-0 | 常开 | 会话必死，跨会话的持久是系统的定义 |
| 出处类别与可采信检查 | 守门官 | T-0 | 常开 | 达成与否必须独立于模型自述（红线 2） |
| 画像推导 | 守门官 | T-0 | 常开（人可覆盖） | 授权与不可逆性由人和环境决定 |
| 估值不进等级（I8） | 守门官 | T-0 | 常开 | 估计不是事实；性质测试常驻 CI |
| 三层视图（`view?layer=`） | 感知官 | T-1 | 常开；开关 `view=full_dump` | 满量导出与下钻版解题率差 ≤1 题且成本不升 |
| 账本投影、归因记录 | 量具 | T-0 | 常开 | 永不退役，也永不守门 |

## 依赖

不依赖任何其它组件。其它组件经 `paoding_graph.contract` 与本机 socket 访问它。

## 实现取值（规格未定、在此钉死）

- 哈希链创世值：每题第一条事件的 `prev_hash` 为 64 个 `0`。
- 日志表只追加：SQLite 触发器拒绝 UPDATE 与 DELETE；`(problem_id, idem_key)` 唯一，重放返回首次事件。
- 状态哈希：`sha256(JCS(state))`，reducer 的状态必须是 JSON 值。
- Blob 写入后文件权限置只读；range 读取也先校验全文哈希。
- 新对象 id 由事件 seq 派生：`a_<seq>`、`f_<seq>`、`i_<seq>`、`j_<seq>`。
- `validate` 返回规范化事件体，含派生字段（画像、判官快照 `judge_snapshot`、`producer`、内容键）；cfg（判官注册表等）只在 validate 时读，重放不依赖它。
- 判官裁决的 `grade` 取开题时的判官快照，不取裁决方自报。
- `request_judge` 的判官必须是登记判据时的那一个（I4 判据先行的字面推论）；推断类论断在 M0 没有判据，不能请求判定。
- `input` 类 Artifact 可以在 `open_problem` 之前登记（Origin 要引用它们）；其它类别要求题目已开。
- M0 拒绝 `accept=human`、`check.control`、`done.tests` 与 `follows`/`executor`/`rollback`/`delegate`，返回 `schema_error`，待对应里程碑启用。
- Blob 是否存在由服务层在 validate 之前检查（IO 不进内核）。

## 进度

| 日 | 内容 | 验收 |
| --- | --- | --- |
| D1（预备） | `jcs.py`、`envelope.py`、`eventlog.py`、`replay.py`、`blobs.py` | 3.1.5 的 1；3.2.5 的 1、4；RFC 8785 附录 B 向量 |
| D2（预备） | `reducer.py`（六种操作）、`levels.py`、`refmodel.py`（逐字节副本）、`tokens.py` | 迟滞（一败回 E0、两败为 X）；3.1.5 的 4（M0 形态）、6、8、9；3.2.5 的 2 前四种 |
