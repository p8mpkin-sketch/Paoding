# 庖丁网页前端

React 18 + TypeScript + Vite。规格与官类见 [SPEC.md](SPEC.md)。

## 跑起来

```sh
cd web
npm ci
npm run dev          # http://127.0.0.1:5173 ，连内置的假后端，三道示例题，其中一道每 1.5 秒往前走一步
```

假后端的线格式与图服务相同，令牌已预置，不需要任何外部服务。

## 连真图服务

同源（推荐）：图服务直接托管构建产物。

```sh
(cd web && npm run build)
uv run python -m paoding_graph.httpapi --home .paoding --port 8787 --static web/dist
```

打开 http://127.0.0.1:8787/ 。读不需要令牌；要写（开题、Hint、审批）就把 `.paoding/human.token` 的内容填到页面右上角。

开发服务器加代理：

```sh
PAODING_API=http://127.0.0.1:8787 npm run dev
```

连整套系统（图服务 + 判官 + 司南 + 哮天犬，会话是假 CLI）：

```sh
(cd web && npm run build)
uv run python scripts/run.py --home /tmp/paoding-run --port 8100 --config scripts/e2e/config.yaml
# 或者开发服务器：PAODING_API=http://127.0.0.1:8100 npm run dev （run.py 缺省放行 http://127.0.0.1:5173）
uv run python scripts/e2e/drive.py --url http://127.0.0.1:8100 --token-file /tmp/paoding-run/human.token
```

打开 `/p/e2e` 能看到节点、判定刻度与花费随 SSE 一条条到。

只看界面、不跑会话的话，用演示脚本起一个带数据的真图服务（没有模型调用，事件按固定脚本经 HTTP 提交）：

```sh
(cd web && npm run build)
uv run python web/tools/live_demo.py --port 8787     # 令牌 tok-human
```

`p1` 已走完，`p2` 停在一条等人审批的 Intent，`p3` 每两秒走一步。

## 检查

```sh
npm run typecheck
npm test             # HT 验收、契约、边界
npm run build
```

契约测试用的应答录自真图服务：`uv run python web/tools/record_fixtures.py web/tests/fixtures/real`。图服务的线格式有变化时重录，测试会指出前端哪里要跟着改。

## 本机开关

都在浏览器的 `localStorage` 里，不影响任何派生量。

| 键 | 作用 |
| --- | --- |
| `paoding.api_base` | 图服务基址；同源部署留空 |
| `paoding.human_token` | 人的令牌 |
| `paoding.graph_view` | `always`：节点不足 50 也显示图 |
| `paoding.usage` | `off`：不记界面使用读数 |
