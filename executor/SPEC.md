# executor/：契约 6 执行层（信任根）

规格：v1.3 §3.6；不变量 I2、I5。

## 实现的契约接口

- 授权编译 `compile(scope, risk) → 容器能力`：能力 ≤ Intent 风险 ≤ 授权范围；`scope_violation` 事件。
- 执行容器、出站白名单（出站闸门，放行到 host:port）与访问摘要 `touched`。
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
- `runtime.py`：Docker 实现。每个沙箱一张 `--internal` 网络，唯一出口是出站闸门（见下）；`--cap-drop ALL`、`no-new-privileges`、pids/内存/CPU 上限，不传任何凭据类环境变量。判官的洁净容器不挂 Worker 工作区。exec 合并 stdout 与 stderr（保序），容器外采集，写 Blob，用执行层令牌登记为 exec 类；判官模式只交回出处字段，由判官运行器登记。回显超过 8 KB 只回头尾。
- 依赖：`paoding_graph.contract` 的 `GraphPort` 与 `BlobPort`。

## 容器生命周期（创建、销毁、重置、清理）

| 动作 | 接口 | 保证 |
| --- | --- | --- |
| 创建 | `DockerExecutor.launch(spec, lease_id)` | 一张内部网络加一个执行容器，有授权目标时另加上游网络与每台主机一个闸门；任一步失败把已建的拆掉，不留半成品。容器带 `paoding.sandbox`、`paoding.owner`、`paoding.lease`、`paoding.role=sandbox` 四个标签；到 `limits.wall_s` 自己退出 |
| 销毁 | `destroy(sid)`、`destroy_lease(lease_id)`、`close()`（也是上下文管理器的出口） | 幂等。按 `paoding.sandbox=<sid>` 标签拆掉执行容器、闸门与两张网络，本实例不认识的 sid（进程重启之后）同样拆得掉；目标容器只摘网不删；不带本层标签的容器一律不碰 |
| 重置 | `reset(sid)` | 销毁后从同一镜像重建，**沙箱 id 不变**，白名单照旧；工作区是共享挂载，不重置 |
| 清理 | `reap(在途租约集合)`、`sweep_orphans()` | 前者回收本实例名下租约已结束的沙箱；后者回收属主进程已死的容器与网络（含题目环境容器），网络上还接着目标容器也删得掉 |
| 状态 | `sandboxes()` | 本实例名下的沙箱：sid、租约、目标、是否仍在运行 |

沙箱已停止或不存在时 `exec` 抛 `SandboxGone`，不采集、不登记。

`EnvManager` 管题目环境容器（执行容器的出站目标）：`start(name, image, env, command, ready_port)` 等端口就绪，`reset(name)` 删除后按同一参数重建，`stop(name)` 幂等且只删本层建的。启动参数（含环境变量）只留在本进程内存里，不写日志、不进 Blob、不进任何沙箱。

## 出站闸门（P0-4，2026-11-18）

```
执行容器 ──<sid>-net（internal）── 闸门 <sid>-gate-N ──<sid>-up-net（internal）── 题目容器
                                   别名 = 目标主机名
```

- 每台授权主机一个闸门容器（`gate.py`，只用标准库，源码经 `python -c` 传入，不需要另建镜像；镜像由 `DockerExecutor(gate_image=…)` 指定，缺省 `python:3.12-slim`，部署机上要先拉好）。
- **名字解析**：闸门在 `<sid>-net` 上以目标主机名为别名，Docker 的内置 DNS 把这个名字解析到闸门；内部网络上别的名字解析不出来。
- **端口级放行**：闸门只在授权规则写明的端口上监听并转发到目标的同一端口；同一目标的其他端口没有监听，连接被直接拒绝。目标容器不在 `<sid>-net` 上，绕过名字直连它的地址也不通。
- **`actions` 由闸门执行**：规则连同 `actions` 原样交给闸门（`ExecSpec.egress_rules`）。含 `connect`（或 `*`）的端口才开；只写了别的动作的规则不开通路。同一地址有多条规则时动作取并集。
- **只认执行容器**：闸门只接受源地址是执行容器的连接，别的容器即使接进 `<sid>-net` 也过不了闸门。
- **闸门自身**：`--cap-drop ALL`、`no-new-privileges`、只读根、非 root、不挂任何卷、不带任何环境变量；两只脚都在内部网络上，自己也出不了外网。带 `paoding.sandbox`、`paoding.owner`、`paoding.lease`、`paoding.role=gate` 标签，随沙箱销毁，孤儿清扫同样覆盖。
- **逐连接记录**：闸门每接一条连接在标准输出记一行 JSON（`connect`：目的地与上游是否接通；`deny`：来源不对），执行层用 `gate_log()` 在容器之外读。
- **访问摘要 `touched`（P0-3）**：每次 `exec` 结束后，执行层取这次运行起止时刻之间闸门记下的 `connect`，写成 `net:host:port`（去重、排序）填进出处字段，Worker 租约与判官租约下都一样。来源只有闸门的记录，命令输出里怎么说都不算；白名单外的连接到不了闸门，不会出现；目标端口没开、上游没接通的连接也算（它确实去碰了授权范围内的地址）。同一沙箱里并发的两次 `exec` 时间重叠时，重叠时段的连接两边都会记上。
- `net` 规则的 `pattern` 必须是 `host:port`；没写端口的在授权编译时报 `ScopeError`，不默认成"整台主机"（异议报告 006 第 1 项）。

## 已知缺口

1. **`scope_violation` 尚未产生。** 白名单外的端口与地址在网络层被拒（没有监听、没有路由），闸门看不到这些连接，所以 3.6.4 的 1 只验了"连接被拒"，没验"日志里出现 `scope_violation`"。闸门看得到的只有来源不对的连接（记 `deny`）。要看到全部越界连接需要在闸门里做包过滤与记录，留给后续。
2. **只支持本机容器作为目标。** M0 的题目都是本机题目容器，够用；外部地址要把闸门的上游一侧接到有出站路由的网络上，尚未做。
3. **闸门是 TCP 转发，不是透明路由。** 目标端口没在监听时，执行容器的 `connect()` 仍然成功（接它的是闸门），随后连接被立刻重置、拿不到任何字节。只看 `connect` 是否成功的端口探测会把"服务没起"看成"端口开着"；读写一个字节就能分辨。闸门记录里 `ok=false` 如实记下上游没接通（异议报告 006 第 2 项）。
4. **只转发 TCP。** UDP 与 ICMP 不通。

## 评审方 #14 必修项（已修）

1. **资源种类登记表单一事实源**：`graph/src/paoding_graph/resources.py` 的 `RESOURCE_EXTERNAL`（`net` 为外部资源，`workspace` 不是）。画像推导的 `Config.external_resources` 默认取自它；执行层的 `RESOURCE_KINDS` 只挂编译行为，external 取自同一张表，键集合不一致时导入即失败。原先这里把 `net` 登记为 `external=False`，与 §6.1 走查（CTF 题画像为 partial）矛盾；当时画像侧另持一份（缺省为空），两边都错且互不相干。
2. **孤儿清扫查属主**：沙箱容器与网络打 `paoding.owner=<主机名>:<pid>:<进程启动时刻>` 标签；`sweep_orphans` 只清本机属主确定已死的（pid 不在或启动时刻不符，防 pid 复用）。别的主机的、标签缺失或格式不明的一律不动。
