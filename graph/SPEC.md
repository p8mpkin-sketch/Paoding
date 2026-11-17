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

## 进度

| 日 | 内容 | 验收 |
| --- | --- | --- |
| D1（预备） | `jcs.py`、`envelope.py`、`eventlog.py`、`replay.py`、`blobs.py` | 3.1.5 的 1；3.2.5 的 1、4；RFC 8785 附录 B 向量 |
