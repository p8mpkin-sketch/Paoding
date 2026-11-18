# executor/：契约 6 执行层（信任根）

规格：v1.3 §3.6；不变量 I2、I5。

## 实现的契约接口

- 授权编译 `compile(scope, risk) → 容器能力`：能力 ≤ Intent 风险 ≤ 授权范围；`scope_violation` 事件。
- 执行容器、出站白名单与访问摘要 `touched`。
- `exec` 的容器外采集与登记（`register_artifact`，class=exec，组件令牌不进任何容器）。
- r2 凭据按次注入（机制实现；M0 题目只含 r0）。

## 官的声明

| 结构 | 官 | 标签 | 启用条件 | 长存依据 |
| --- | --- | --- | --- | --- |
| 执行层采集登记 | 守门官 | T-0 | 常开 | 模型叙述的输出不在采集通路上 |
| 授权范围、按风险注入能力 | 守门官 | T-0 | 常开 | 授权由人和环境决定 |

## 依赖

`paoding_graph.contract`。

## M0 实现（预备，2026-11-17）

- `compile.py`：确定性授权编译。资源种类插件 `net`（host:port）与 `workspace`；没有插件解释的 resource 直接报错，不默认放行。
- `runtime.py`：Docker 实现。每个沙箱一张 `--internal` 网络，只接入白名单里的本机题目容器；`--cap-drop ALL`、`no-new-privileges`、pids/内存/CPU 上限，不传任何凭据类环境变量。判官的洁净容器不挂 Worker 工作区。exec 合并 stdout 与 stderr（保序），容器外采集，写 Blob，用执行层令牌登记为 exec 类；判官模式只交回出处字段，由判官运行器登记。回显超过 8 KB 只回头尾。
- 依赖：`paoding_graph.contract` 的 `GraphPort` 与 `BlobPort`。

## 容器生命周期（创建、销毁、重置、清理）

| 动作 | 接口 | 保证 |
| --- | --- | --- |
| 创建 | `DockerExecutor.launch(spec, lease_id)` | 一张内部网络加一个容器；任一步失败把已建的拆掉，不留半成品。容器带 `paoding.sandbox`、`paoding.owner`、`paoding.lease`、`paoding.role=sandbox` 四个标签；到 `limits.wall_s` 自己退出 |
| 销毁 | `destroy(sid)`、`destroy_lease(lease_id)`、`close()`（也是上下文管理器的出口） | 幂等。本实例不认识的 sid（进程重启之后）按标签找到网络与接入的目标再拆；不带本层标签的容器一律不碰 |
| 重置 | `reset(sid)` | 销毁后从同一镜像重建，**沙箱 id 不变**，白名单照旧；工作区是共享挂载，不重置 |
| 清理 | `reap(在途租约集合)`、`sweep_orphans()` | 前者回收本实例名下租约已结束的沙箱；后者回收属主进程已死的容器与网络（含题目环境容器），网络上还接着目标容器也删得掉 |
| 状态 | `sandboxes()` | 本实例名下的沙箱：sid、租约、目标、是否仍在运行 |

沙箱已停止或不存在时 `exec` 抛 `SandboxGone`，不采集、不登记。

`EnvManager` 管题目环境容器（执行容器的出站目标）：`start(name, image, env, command, ready_port)` 等端口就绪，`reset(name)` 删除后按同一参数重建，`stop(name)` 幂等且只删本层建的。启动参数（含环境变量）只留在本进程内存里，不写日志、不进 Blob、不进任何沙箱。

## 已知缺口（D3 正式日补齐，需要题目容器一起验）

1. **`scope_violation` 尚未产生。** `--internal` 网络对越界连接是静默丢弃，执行层看不到，所以 3.6.4 的 1 只验了"连接被拒"，没验"日志里出现 `scope_violation`"。计划：沙箱的唯一出口改为一个出站闸门容器（DNS 加 TCP 转发），白名单外的名字或地址在闸门处拒绝并上报，执行层据此追加事件；同一任务累计 3 次交哮天犬终止。
2. **访问摘要 `touched` 为空。** 同一个闸门可以记下实际连到过的授权目标，届时填入。
3. **端口粒度未强制。** 白名单写到 host:port，但目前整台目标容器可达。闸门落地后按端口放行。
4. **只支持本机容器作为目标。** M0 的题目都是本机题目容器，够用；外部地址要等闸门。

## 评审方 #14 必修项（已修）

1. **资源种类登记表单一事实源**：`graph/src/paoding_graph/resources.py` 的 `RESOURCE_EXTERNAL`（`net` 为外部资源，`workspace` 不是）。画像推导的 `Config.external_resources` 默认取自它；执行层的 `RESOURCE_KINDS` 只挂编译行为，external 取自同一张表，键集合不一致时导入即失败。原先这里把 `net` 登记为 `external=False`，与 §6.1 走查（CTF 题画像为 partial）矛盾；当时画像侧另持一份（缺省为空），两边都错且互不相干。
2. **孤儿清扫查属主**：沙箱容器与网络打 `paoding.owner=<主机名>:<pid>:<进程启动时刻>` 标签；`sweep_orphans` 只清本机属主确定已死的（pid 不在或启动时刻不符，防 pid 复用）。别的主机的、标签缺失或格式不明的一律不动。
