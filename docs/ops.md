# 运维说明（M0 单机）

> 对象：`scripts/run.py` 起的全栈（图服务、判官运行器、司南、哮天犬同在一个进程）。出处：质量提升第二阶段 P2-3。
> 本文只讲怎么看、怎么查、怎么备份；机制在各组件的 `SPEC.md`。

## 数据目录

`--home` 指的目录里有：

| 路径 | 内容 | 备份 |
| --- | --- | --- |
| `g.sqlite`（及 `-wal`、`-shm`） | 事件日志，唯一的事实源；所有状态由它重放得到 | 要 |
| `blobs/` | Blob 仓库，按 sha256 寻址，只增不改 | 要 |
| `vault/` | 保密库：含密级判官资产 | 自行决定，见下 |
| `sessions/` | 会话的工作目录；留档已登记进 Blob | 不用 |
| `logs/stack.log` | 结构化日志（轮转，10 MB × 5） | 不用 |
| `human.token` | 人的令牌（权限 600）；删掉后下次启动重新生成 | 不用 |
| `config.yaml` 或 `config.json` | 配置，可省 | 随你的配置管理 |

## 健康检查

```
curl -s http://127.0.0.1:8100/healthz
```

全部正常返回 200，任何一个组件不正常返回 503；两种情况应答体形状相同：

```json
{"ok": true, "status": "ok", "api": "v1",
 "components": {
   "graph":    {"ok": true, "head": 42, "problems": 1, "open": 1},
   "blobs":    {"ok": true},
   "events":   {"ok": true, "alive": true, "last_tick_age_s": 0.1},
   "judge":    {"ok": true, "alive": true, "last_tick_age_s": 0.2, "judges": 2},
   "sinan":    {"ok": true, "alive": true, "last_tick_age_s": 0.3, "problems_scheduled": 1},
   "watchdog": {"ok": true, "alive": true, "last_tick_age_s": 0.8},
   "adapter":  {"ok": true, "backend": "fake", "launcher": null, "sessions_in_flight": 1},
   "executor": {"ok": true, "kind": "docker"}}}
```

- 一个后台循环算正常的条件：线程活着，并且最近一轮没有抛异常。出过错的会带 `last_error` 与累计的 `failures`；下一轮成功后 `last_error` 消失，`failures` 保留。
- `last_tick_age_s` 只是读数，不参与判断：判官的一轮可能要等一次重放跑完。要按它告警，阈值由你按题目的判官耗时定。
- `executor` 的 `docker info` 探测结果缓存 10 秒。
- 只监听回环地址，`Host` 不是回环名的请求照样被拒（403）。不要令牌，也不返回任何题目内容。
- 旧的 `GET /v1/health`（`{ok, head, api}`）还在，它只说明 HTTP 服务活着。

## 日志

一行一个 JSON 对象，同时写 stderr 与 `<home>/logs/stack.log`：

```json
{"ts": "2026-11-18T06:20:31.512Z", "level": "info", "component": "graph", "msg": "#17 p1 lease ← sinan（explore → i_12，预留 300 毫美元）", "seq": 17, "problem_id": "p1", "kind": "lease", "actor": "sinan", "lease_id": "l_17"}
```

| 字段 | 含义 |
| --- | --- |
| `ts` | UTC，ISO 8601，毫秒 |
| `level` | `debug`、`info`、`warning`、`error` |
| `component` | `graph`（每条落盘事件一行）、`judge`、`sinan`、`adapter`、`watchdog`、`stack`（启停）、`http`（访问日志） |
| `msg` | 给人读的一句话 |
| 上下文 ID | 有则带：`problem_id`、`lease_id`、`request_id`（判定请求）、`seq`、`kind`、`actor`；访问日志另有 `method`、`path`、`status`、`duration_ms`、`bytes`、`remote` |
| `exc` | 异常回溯，只在带异常的记录上 |

常用查法（`jq`）：

```
jq -c 'select(.problem_id=="p1")' logs/stack.log                 # 一道题的全部记录
jq -c 'select(.lease_id=="l_17")' logs/stack.log                 # 一个租约从签发到释放
jq -c 'select(.level=="error" or .level=="warning")' logs/stack.log
```

配置（`config.yaml` 的 `log` 一节，都可省）：

```yaml
log:
  level: info            # debug | info | warning | error
  format: json           # stderr 的格式：json | text（text 是给人在终端看的单行格式；文件恒为 JSON）
  file: logs/stack.log   # 相对数据目录；写空串即不写文件
  access: false          # HTTP 访问日志，缺省关
```

命令行上 `--log-format text` 与 `--access-log` 覆盖配置。

**访问日志**缺省关，因为网页每到一条事件都要读投影，量大而信息少。打开后每个请求一条（`component: "http"`），只记方法、路径、状态码、耗时、字节数与对端地址；查询串、请求头、请求体都不记，所以令牌不会进日志。SSE 与长轮询在连接结束时记一条，耗时即连接时长。

日志里的审计信息不是事实源：事实以事件日志为准（`GET /v1/problems/{pid}/events`），结构化日志只是方便检索的副本。

## 备份与恢复

```
scripts/backup.sh --home /var/lib/paoding                     # 放到 <home>/backups/
scripts/backup.sh --home /var/lib/paoding --out /mnt/backup   # 或指定去处
scripts/backup.sh --home /var/lib/paoding --with-vault        # 连保密库一起
```

不用停机。脚本先用 SQLite 的在线备份（`sqlite3 .backup`；没有这个命令时用 Python 标准库的同一接口）取得一致的 `g.sqlite`，再把 `blobs/` 打成 `blobs.tar.gz`。次序是有意的：Blob 只增不改，且总是先写 Blob 再落事件，所以后打包的 Blob 一定覆盖先备份的日志引用到的全部内容。产出目录 `paoding-backup-<UTC 时间>/` 里另有 `MANIFEST`：链头序号、Blob 个数、各文件的 sha256。

不要直接 `cp g.sqlite`：服务在跑时 WAL 里有未合并的内容，拷出来的文件可能不完整。

保密库缺省不备份：备份的存放处未必配得上它的保密级别。没有保密库的备份恢复之后，结构级判官照常，含密级判官无法重判。

恢复（到一个新的数据目录，先停掉全栈）：

```
mkdir /var/lib/paoding-restored
cp  paoding-backup-<时间>/g.sqlite      /var/lib/paoding-restored/g.sqlite
tar -C /var/lib/paoding-restored -xzf paoding-backup-<时间>/blobs.tar.gz
tar -C /var/lib/paoding-restored -xzf paoding-backup-<时间>/vault.tar.gz   # 如果备份了
uv run python scripts/run.py --home /var/lib/paoding-restored --port 8100
```

启动即重放：图服务把整条日志重放一遍得到状态，哈希链在读取时校验；Blob 在读取时校验 sha256。启动日志里的“链头 seq”应等于 `MANIFEST` 的 `head_seq`。备份那一刻还在途的租约，恢复后由哮天犬按过期处理。

建议的节奏：每天一次，外加每次升级之前。备份目录的清理由你的保留策略决定，脚本不删旧备份。

## 测试覆盖率

```
uv run pytest --cov --cov-report=json:coverage.json --cov-report=
python ci/coverage_by_component.py coverage.json
```

CI 每次都跑，按组件的表在任务日志与任务摘要里。只显示，不设门槛。子进程里执行的代码（假 CLI、被测试起成子进程的 `run.py`）量不到，所以读数偏低而不偏高。
