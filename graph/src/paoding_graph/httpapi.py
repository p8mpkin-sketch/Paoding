"""图服务的 HTTP 绑定（规格 §3.1.2、§3.2.2 的端点；HMI §11 方案 A：图服务直出 HTTP 与事件流）。

- 读：HTTP GET，全部是 views.py 里状态的纯函数；每个只读端点可带 `as_of=<seq>`（H3），回放由唯一的 reducer 重放。
- 推：SSE（`/stream`），`id` 就是事件 seq，断连用 `Last-Event-ID` 续上；补发窗口超过阈值时先发一个 as_of 快照（§13.2）。
- 写：HTTP POST，一律落到 `GraphService.submit`，与 `pd` 是同一条提议通道；身份只来自 `Authorization: Bearer <令牌>`。
- 只监听本机回环（§13.3 的 M1 形态）：Host 头不是回环名的请求拒绝；跨源请求一律拒绝，除非来源在显式白名单里。
- 文本一律按纯数据返回；Blob 下载带 `Content-Disposition: attachment` 与 `nosniff`（§13.1 第 5 条）。

异常的去向（分发处只认这几种，不再宽接 ValueError、KeyError、TypeError）：
- `HttpError`：本层对请求形状的判断（参数、请求头、请求体）。
- `views.NotFound`、`views.NotEnabled`：视图说“没有这个东西”“这个开关没开”。
- `parse.BadBody`：解析层说请求体或参数不合形状，转成 400 `schema_error`。
- 其余一律是服务端自己的缺陷：回 500 `internal`，栈打到标准错误，不伪装成调用方的输入错误。

只用标准库。这里做 IO、读时钟（只用于长轮询与心跳的等待，不进任何视图）；reducer 与 views 仍是纯函数。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import threading
import time
import traceback
import urllib.parse
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import views
from .blobs import BlobError, BlobNotFound, BlobStore, CorruptBlob
from .jcs import canonicalize
from .parse import BadBody
from .replay import state_hash
from .service import GraphService
from .state import Actor, Body, Event, JudgeEntry, State
from .tokens import UnknownToken

MAX_BODY = 8 * 1024 * 1024  # JSON 请求体上限
MAX_BLOB = 256 * 1024 * 1024  # 单个 Blob 上限（§3.2.2）
MAX_VAULT = 64 * 1024  # 保密库单条上限：答案与期望输出，不是文件
LOOPBACK = ("127.0.0.1", "localhost", "[::1]")
_ACCESS = logging.getLogger("http")  # 访问日志；格式由组装根决定，这里只给字段
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass
class HttpConfig:
    host: str = "127.0.0.1"
    port: int = 0  # 0：由系统分配，测试用
    allowed_origins: tuple[str, ...] = ()  # 显式放行的跨源来源（开发服务器）；默认一个不放
    view_full_dump: bool = False  # T-1 开关：三层视图的满量导出（graph/SPEC.md）
    replay_window: int = 5000  # SSE 补发窗口；超过则先发快照（§13.2）
    heartbeat_s: float = 15.0
    longpoll_max_s: float = 30.0
    static_dir: Path | None = None  # 前端构建产物；与 API 同源，不需要跨源
    templates_dir: Path | None = None  # 开题模板（随锦囊发布的数据，前端只解释字段映射）
    renderers_dir: Path | None = None
    extra_hosts: tuple[str, ...] = field(default_factory=tuple)
    health: Callable[[], dict[str, Doc]] | None = None  # 组装根给出的其它组件状态：{组件名: {ok, …}}（/healthz）
    access_log: bool = False  # HTTP 访问日志（logging 的 "http"），缺省关
    # 保密库的只写入口（一句话开题设计 §2.5）：组装根注入 fn(内容) → VaultRef。图服务不依赖保密库的实现，
    # 也读不到库里的内容；没有注入时 PUT /v1/vault 返回 404。
    vault_put: Callable[[bytes], dict[str, Any]] | None = None


class HttpError(Exception):
    def __init__(self, status: int, code: str, detail: str = "") -> None:
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


class MountError(Exception):
    """挂载端点的业务拒绝（如设置的 base_digest 过期 → 409）。extra 并进应答体，不得含密钥。"""

    def __init__(self, status: int, code: str, detail: str = "", **extra: Any) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail, self.extra = status, code, detail, extra


class Handler(BaseHTTPRequestHandler):
    """一次请求。cors_origin 由来源检查写入：放行的跨源来源，同源或无 Origin 时为 None。"""

    protocol_version = "HTTP/1.1"
    cors_origin: str | None = None
    started = False  # 应答头是否已经发出
    sent_status: int | None = None  # 访问日志用：发出的状态码
    sent_bytes = 0  # 访问日志用：发出的应答体字节数

    def send_response(self, code: int, message: str | None = None) -> None:
        self.sent_status = code
        super().send_response(code, message)

    def log_message(self, format: str, *args: Any) -> None:
        pass


Params = dict[str, str]  # 路径参数或查询参数
Doc = dict[str, Any]  # 应答的 JSON 对象
Route = Callable[[Handler, Params, Params], None]
ViewFn = Callable[[State, Params, Params], Doc]
WriteFn = Callable[[str, Params, Body, Handler], tuple[int, Doc]]


def _length(h: Handler, default: int) -> int:
    raw = h.headers.get("Content-Length")
    if raw is None or not raw.strip():
        return default
    try:
        n = int(raw)
    except ValueError:
        raise HttpError(400, "schema_error", "Content-Length 须为整数") from None
    if n < 0:
        raise HttpError(400, "schema_error", "Content-Length 不得为负")
    return n


def _int(q: Params, name: str, default: int | None = None, lo: int = 0) -> int | None:
    if name not in q:
        return default
    try:
        v = int(q[name])
    except ValueError:
        raise HttpError(400, "schema_error", f"{name} 须为整数") from None
    if v < lo:
        raise HttpError(400, "schema_error", f"{name} 不得小于 {lo}")
    return v


class GraphHttp:
    def __init__(self, svc: GraphService, blobs: BlobStore, cfg: HttpConfig | None = None) -> None:
        self.svc, self.blobs, self.cfg = svc, blobs, cfg or HttpConfig()
        self.server: ThreadingHTTPServer | None = None
        self.url = ""
        self._closing = threading.Event()
        self._snap_lock = threading.Lock()
        # (题, 序号) → 四份投影与各自的 view_hash
        self._snap_cache: OrderedDict[tuple[str, int], dict[str, Doc]] = OrderedDict()
        g, p = self._get, self._post
        R = re.compile
        self.routes: list[tuple[str, re.Pattern[str], Route]] = [
            ("GET", R(r"/v1/health"), self.r_health),
            ("GET", R(r"/healthz"), self.r_healthz),
            ("GET", R(r"/v1/problems"), g(lambda st, m, q: views.problems(st, self._ts_of))),
            ("GET", R(r"/v1/problems/(?P<pid>[^/]+)/status"), g(lambda st, m, q: views.status(st, m["pid"]))),
            ("GET", R(r"/v1/problems/(?P<pid>[^/]+)/view"), g(self.v_view)),
            ("GET", R(r"/v1/problems/(?P<pid>[^/]+)/budget"), g(lambda st, m, q: views.budget(st, m["pid"]))),
            ("GET", R(r"/v1/problems/(?P<pid>[^/]+)/work"), g(lambda st, m, q: views.work(st, m["pid"]))),
            ("GET", R(r"/v1/problems/(?P<pid>[^/]+)/snapshot"), self.r_snapshot),
            ("GET", R(r"/v1/problems/(?P<pid>[^/]+)/ticks"), self.r_ticks),
            ("GET", R(r"/v1/problems/(?P<pid>[^/]+)/invalidations"), g(self.v_invalidations)),
            (
                "GET",
                R(r"/v1/problems/(?P<pid>[^/]+)/cards/(?P<kind>[^/]+)/(?P<id>[^/]+)"),
                g(lambda st, m, q: views.card(st, m["pid"], m["kind"], m["id"], self.svc.cfg)),
            ),
            ("GET", R(r"/v1/problems/(?P<pid>[^/]+)/events"), self.r_events),
            ("GET", R(r"/v1/problems/(?P<pid>[^/]+)/stream"), self.r_stream),
            (
                "GET",
                R(r"/v1/nodes/(?P<id>[^/]+)"),
                g(lambda st, m, q: views.node(st, m["id"], q.get("layer", "summary"))),
            ),
            ("GET", R(r"/v1/hints/(?P<id>[^/]+)/trace"), g(self.v_hint_trace)),
            ("GET", R(r"/v1/artifacts/(?P<id>[^/]+)"), g(lambda st, m, q: views.artifact(st, m["id"]))),
            ("GET", R(r"/v1/blobs/(?P<hash>[^/]+)"), self.r_blob_get),
            ("GET", R(r"/v1/judges"), lambda h, m, q: self._json(h, 200, views.judges(self.svc.cfg))),
            ("GET", R(r"/v1/templates"), lambda h, m, q: self._json(h, 200, _catalog(self.cfg.templates_dir))),
            ("GET", R(r"/v1/renderers"), lambda h, m, q: self._json(h, 200, _catalog(self.cfg.renderers_dir))),
            ("PUT", R(r"/v1/blobs"), self.r_blob_put),
            ("PUT", R(r"/v1/vault"), self.r_vault_put),
            ("POST", R(r"/v1/profile/preview"), self.r_profile_preview),
            ("POST", R(r"/v1/problems"), p(self.w_open)),
            ("POST", R(r"/v1/problems/(?P<pid>[^/]+)/proposals"), p(self.w_proposals)),
            ("POST", R(r"/v1/problems/(?P<pid>[^/]+)/leases"), p(self.w_lease)),
            ("POST", R(r"/v1/leases/(?P<id>[^/]+)/(?P<verb>renew|release)"), p(self.w_lease_verb)),
            ("POST", R(r"/v1/artifacts"), p(self.w_artifact)),
        ]

    def mount(
        self, method: str, pattern: str, fn: Callable[[Params, Body | None], Doc], *, human: bool = False
    ) -> None:
        """组装根挂上别的组件的端点（v1.5 起通鉴的 /v1/memory/…）：fn(查询参数, 请求体) → 应答对象。
        身份、来源检查与错误应答沿用本服务的外壳；fn 抛 BadBody 即 400 schema_error，抛 MountError 即其状态码。
        human=True：只认人的令牌（设置与密钥端点，宪章 03 §4、§7），别的组件令牌一律 403。"""
        if method not in ("GET", "POST", "PUT", "DELETE"):
            raise ValueError(f"挂载端点只支持 GET/POST/PUT/DELETE，不是 {method}")

        def route(h: Handler, m: Params, q: Params) -> None:
            if human and self._actor(h).get("kind") != "human":
                raise HttpError(403, "forbidden_op", "只接受人的令牌")
            body = self._body(h) if method in ("POST", "PUT") else None
            self._json(h, 200, fn({**q, **m}, body))

        self.routes.append((method, re.compile(pattern), route))

    # ---------- 生命周期 ----------

    def serve(self) -> str:
        app = self

        class H(Handler):
            def do_GET(self) -> None:
                app.dispatch(self, "GET")

            def do_POST(self) -> None:
                app.dispatch(self, "POST")

            def do_PUT(self) -> None:
                app.dispatch(self, "PUT")

            def do_DELETE(self) -> None:
                app.dispatch(self, "DELETE")

            def do_OPTIONS(self) -> None:
                app.dispatch(self, "OPTIONS")

        class Server(ThreadingHTTPServer):
            daemon_threads = True

        self.server = Server((self.cfg.host, self.cfg.port), H)
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.url = "http://%s:%d" % (self.cfg.host, self.server.server_address[1])
        return self.url

    def close(self) -> None:
        self._closing.set()
        with self.svc._cond:
            self.svc._cond.notify_all()
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()

    # ---------- 分发、来源检查 ----------

    def dispatch(self, h: Handler, method: str) -> None:
        if not self.cfg.access_log:
            return self._dispatch(h, method)
        t0 = time.monotonic()
        h.sent_status, h.sent_bytes = None, 0
        try:
            self._dispatch(h, method)
        finally:
            # 只记方法、路径（不含查询串）、状态、耗时、字节数。请求头与请求体不进日志：令牌在头里。
            # 长连接（SSE、长轮询）在连接结束时记一条，耗时就是连接时长。
            _ACCESS.info(
                "%s %s → %s",
                method,
                h.path.split("?", 1)[0],
                h.sent_status or "-",
                extra={
                    "method": method,
                    "path": h.path.split("?", 1)[0],
                    "status": h.sent_status,
                    "duration_ms": round((time.monotonic() - t0) * 1000, 1),
                    "bytes": h.sent_bytes,
                    "remote": h.client_address[0],
                },
            )

    def _dispatch(self, h: Handler, method: str) -> None:
        try:
            self._guard(h)
            if method == "OPTIONS":
                return self._send(h, 204, b"", "text/plain")
            url = urllib.parse.urlsplit(h.path)
            q = {k: v[-1] for k, v in urllib.parse.parse_qs(url.query, keep_blank_values=True).items()}
            path = urllib.parse.unquote(url.path).rstrip("/") or "/"
            known = False
            for meth, pat, fn in self.routes:
                m = pat.fullmatch(path)
                if m:
                    known = True
                    if meth == method:
                        fn(h, m.groupdict(), q)
                        return
            if known:
                raise HttpError(405, "schema_error", f"{path} 不支持 {method}")
            if method == "GET" and self.cfg.static_dir and not path.startswith("/v1/"):
                return self._static(h, path)
            raise HttpError(404, "unknown_ref", f"没有端点 {path}")
        except HttpError as e:
            self._json(h, e.status, {"ok": False, "code": e.code, "detail": e.detail})
        except MountError as e:
            self._json(h, e.status, {"ok": False, "code": e.code, "detail": e.detail, **e.extra})
        except views.NotFound as e:
            self._json(h, 404, {"ok": False, "code": "unknown_ref", "detail": str(e)})
        except views.NotEnabled as e:
            self._json(h, 404, {"ok": False, "code": "not_enabled", "detail": str(e)})
        except BadBody as e:
            self._json(h, 400, {"ok": False, "code": "schema_error", "detail": str(e)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # noqa: BLE001  进程边界：见模块说明
            # 到这里的都是服务端自己的缺陷：留下栈，回 500，不说成是调用方的输入错误。
            # 应答可能已经发出一半（事件流），那就只关连接。
            traceback.print_exc(file=sys.stderr)
            h.close_connection = True
            if not h.started:
                try:
                    self._json(h, 500, {"ok": False, "code": "internal", "detail": type(e).__name__})
                except OSError:
                    pass

    def _guard(self, h: Handler) -> None:
        """只对本机服务（§13.3）：Host 须为回环名（防 DNS 重绑定）；跨源一律拒绝，除非来源在白名单。"""
        host = (h.headers.get("Host") or "").strip().lower()
        name = host.rsplit(":", 1)[0] if not host.endswith("]") else host
        if name not in LOOPBACK and name not in self.cfg.extra_hosts:
            raise HttpError(403, "forbidden_op", "只接受发往本机回环地址的请求")
        origin = h.headers.get("Origin")
        h.cors_origin = None
        if origin and origin != f"http://{host}":
            if origin not in self.cfg.allowed_origins:
                raise HttpError(403, "forbidden_op", "跨源请求一律拒绝")
            h.cors_origin = origin

    # ---------- 应答 ----------

    def _send(self, h: Handler, status: int, data: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
        h.started = True
        h.send_response(status)
        h.send_header("Content-Type", ctype)
        h.send_header("Content-Length", str(len(data)))
        h.send_header("Cache-Control", "no-store")
        h.send_header("X-Content-Type-Options", "nosniff")
        self._cors(h)
        for k, v in (extra or {}).items():
            h.send_header(k, v)
        h.end_headers()
        h.sent_bytes = len(data)
        h.wfile.write(data)

    def _cors(self, h: Handler) -> None:
        if h.cors_origin:
            h.send_header("Access-Control-Allow-Origin", h.cors_origin)
            h.send_header("Vary", "Origin")
            h.send_header("Access-Control-Allow-Headers", "authorization, content-type, last-event-id, idempotency-key")
            h.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
            h.send_header("Access-Control-Expose-Headers", "X-Blob-Hash, X-Blob-Size")

    def _json(self, h: Handler, status: int, obj: Any) -> None:
        self._send(h, status, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _body(self, h: Handler) -> Body:
        n = _length(h, 0)
        if n > MAX_BODY:
            raise HttpError(413, "schema_error", "请求体过大")
        try:
            obj = json.loads(h.rfile.read(n) or b"{}")
        except ValueError:
            raise HttpError(400, "schema_error", "请求体须为 JSON") from None
        if not isinstance(obj, dict):
            raise HttpError(400, "schema_error", "请求体须为 JSON 对象")
        return obj

    def _token(self, h: Handler) -> str:
        auth = h.headers.get("Authorization") or ""
        if not auth.startswith("Bearer ") or not auth[7:].strip():
            raise HttpError(401, "forbidden_op", "写操作须带 Authorization: Bearer <令牌>")
        return auth[7:].strip()

    # ---------- 读：as_of 回放 ----------

    def _state(self, q: Params) -> tuple[State, int]:
        head = self.svc.head()
        as_of = _int(q, "as_of")
        if as_of is not None and as_of > head:
            raise HttpError(400, "schema_error", f"as_of={as_of} 超过链头 {head}")
        return self.svc.state_at(as_of), head

    def _get(self, fn: ViewFn) -> Route:
        """视图端点的统一外壳：{as_of, head, view_hash, …视图}。view_hash 是视图模型的规范化哈希（HT-10）。"""

        def handler(h: Handler, m: Params, q: Params) -> None:
            state, head = self._state(q)
            doc = fn(state, m, q)
            out = {
                "as_of": state["seq"],
                "head": head,
                "view_hash": hashlib.sha256(canonicalize(doc)).hexdigest(),
                **doc,
            }
            if q.get("state_hash") in ("1", "true"):
                out["state_hash"] = state_hash(state)
            self._json(h, 200, out)

        return handler

    def _ts_of(self, pid: str, seq: int) -> int | None:
        """某题第 seq 条事件的 ts（题目列表的 closed_ts 用；状态里不存关题时刻）。"""
        evs = self.svc.events(pid, seq - 1, limit=1, upto=seq)
        return evs[0]["ts"] if evs and evs[0]["seq"] == seq else None

    def v_view(self, st: State, m: Params, q: Params) -> Doc:
        return views.view(
            st,
            m["pid"],
            q.get("layer", "title"),
            _int(q, "after_seq", 0) or 0,
            _int(q, "limit", None, 1),
            self.cfg.view_full_dump,
        )

    def v_invalidations(self, st: State, m: Params, q: Params) -> Doc:
        if not q.get("node"):
            raise HttpError(400, "schema_error", "需要 node 参数")
        return views.invalidations(st, m["pid"], q["node"])

    def v_hint_trace(self, st: State, m: Params, q: Params) -> Doc:
        h = st["hints"].get(m["id"])
        if h is None:
            raise views.NotFound(f"没有 Hint {m['id']}")
        return views.hint_trace(st, self.svc.events(h["problem_id"], 0, upto=st["seq"]), m["id"])

    # ---------- 合并读与刻度（P2-1） ----------

    SNAPSHOT_PARTS = ("status", "view", "budget", "work")

    def _parts(self, pid: str, seq: int | None) -> tuple[int, dict[str, Doc]]:
        """某序号上四份投影的外壳与各自的 view_hash。按 (题, 序号) 缓存：日志只追加、视图是状态的纯函数，
        所以缓存永不失效。事件流的 view 帧与随后的 snapshot 请求共用这份缓存，同一序号只算一次。"""
        state = self.svc.state_at(seq)
        key = (pid, state["seq"])
        with self._snap_lock:
            hit = self._snap_cache.get(key)
            if hit is not None:
                self._snap_cache.move_to_end(key)
                return state["seq"], hit
        self._known(pid, state)
        docs = views.snapshot(state, pid, views.view(state, pid, "title", 0, None, self.cfg.view_full_dump))
        parts = {k: {"view_hash": hashlib.sha256(canonicalize(d)).hexdigest(), "doc": d} for k, d in docs.items()}
        with self._snap_lock:
            self._snap_cache[key] = parts
            while len(self._snap_cache) > 64:
                self._snap_cache.popitem(last=False)
        return state["seq"], parts

    def r_snapshot(self, h: Handler, m: Params, q: Params) -> None:
        """GET /v1/problems/{pid}/snapshot?as_of=&parts=：一次给 status、view（layer=title）、budget、work。
        每份与单独的端点同形（`{as_of, head, view_hash, …}`），所以前端拿来就能拼视图模型；
        `parts=status,budget` 只要其中几份（事件流的 view 帧说哪几份变了）。`state_hash=1` 加在 status 上。"""
        pid = m["pid"]
        self._known(pid)
        _, head = self._state(q)
        seq, parts = self._parts(pid, _int(q, "as_of"))
        want = [p for p in (q.get("parts") or ",".join(self.SNAPSHOT_PARTS)).split(",") if p]
        bad = set(want) - set(self.SNAPSHOT_PARTS)
        if bad or not want:
            raise HttpError(400, "schema_error", f"parts 只取 {','.join(self.SNAPSHOT_PARTS)}")
        out: Doc = {
            "as_of": seq,
            "head": head,
            "view_hash": hashlib.sha256(canonicalize({k: v["view_hash"] for k, v in parts.items()})).hexdigest(),
            "parts_hash": {k: v["view_hash"] for k, v in parts.items()},
        }
        for k in self.SNAPSHOT_PARTS:
            if k in want:
                out[k] = {"as_of": seq, "head": head, "view_hash": parts[k]["view_hash"], **parts[k]["doc"]}
        if "status" in want and q.get("state_hash") in ("1", "true"):
            out["status"]["state_hash"] = state_hash(self.svc.state_at(seq))
        self._json(h, 200, out)

    def r_ticks(self, h: Handler, m: Params, q: Params) -> None:
        """GET /v1/problems/{pid}/ticks?as_of=：时间轴只要每条事件的 seq、ts、种类
        （判官裁决另带 result，预算标记另带 mark），不要事件体。`head_hash` 是这道题到 as_of 为止
        最后一条事件的哈希，前端拿它核对随后从流里接上的第一条（prev_hash）。"""
        pid = m["pid"]
        state, head = self._state(q)
        self._known(pid, state)
        ticks: list[Doc] = []
        last: Event | None = None
        for ev in self.svc.events(pid, 0, upto=state["seq"]):
            t: Doc = {"seq": ev["seq"], "ts": ev["ts"], "kind": ev["kind"]}
            b = ev.get("body") or {}
            if ev["kind"] == "judge_verdict" and "result" in b:
                t["result"] = b["result"]
            if ev["kind"] == "budget_mark" and "mark" in b:
                t["mark"] = b["mark"]
            if ev["kind"] == "grant_scope":  # 时间轴分出人批、人拒、自动批准（runtime-grants §7.2）
                t["decision"] = b.get("decision")
                if "via" in b:
                    t["via"] = b["via"]
                if "version" in (b.get("policy") or {}):
                    t["policy_version"] = b["policy"]["version"]
            ticks.append(t)
            last = ev
        self._json(
            h,
            200,
            {
                "as_of": state["seq"],
                "head": head,
                "ticks": ticks,
                "last_seq": last["seq"] if last else 0,
                "head_hash": last["hash"] if last else None,
            },
        )

    def r_health(self, h: Handler, m: Params, q: Params) -> None:
        self._json(h, 200, {"ok": True, "head": self.svc.head(), "api": "v1"})

    def r_healthz(self, h: Handler, m: Params, q: Params) -> None:
        """各组件的状态。全部正常 200，任何一项不正常 503；应答体形状相同，所以探针只看状态码也行。
        图服务的一项在这里算（日志读得到、Blob 目录写得进）；其余由组装根的 health() 给，没有组装根就只有图服务。"""
        comps: dict[str, Doc] = {}
        try:
            head = self.svc.head()
            problems = self.svc.state["problems"]
            comps["graph"] = {
                "ok": True,
                "head": head,
                "problems": len(problems),
                "open": sum(1 for p in problems.values() if not p.get("closed")),
            }
        except (OSError, KeyError, ValueError) as e:  # 探针不能因为被探的东西坏了而自己抛
            comps["graph"] = {"ok": False, "last_error": f"{type(e).__name__}: {e}"[:300]}
        root = getattr(self.blobs, "root", None)
        if root is not None:
            comps["blobs"] = {"ok": os.path.isdir(root) and os.access(root, os.W_OK)}
        if self.cfg.health is not None:
            try:
                for name, st in self.cfg.health().items():
                    comps.setdefault(name, st)
            except Exception as e:  # noqa: BLE001  组装根的探针是外部回调，坏了只能如实报 503，不能让探针自己抛
                comps["stack"] = {"ok": False, "last_error": f"{type(e).__name__}: {e}"[:300]}
        ok = all(bool(c.get("ok")) for c in comps.values())
        self._json(
            h, 200 if ok else 503, {"ok": ok, "status": "ok" if ok else "degraded", "api": "v1", "components": comps}
        )

    def _known(self, pid: str, state: State | None = None) -> None:
        if pid not in (state or self.svc.state)["problems"]:
            raise views.NotFound(f"题目 {pid} 不存在")

    def r_events(self, h: Handler, m: Params, q: Params) -> None:
        """长轮询，同时就是审计日志：有 seq > after 的事件立刻返回，否则最多等 wait 秒。带 as_of 时不等。"""
        state, head = self._state(q)
        self._known(m["pid"])
        after, limit = _int(q, "after", 0) or 0, _int(q, "limit", 1000, 1)
        if "as_of" in q:
            evs = self.svc.events(m["pid"], after, limit, upto=state["seq"])
        else:
            try:
                wait = float(q.get("wait") or 0)
            except ValueError:
                raise HttpError(400, "schema_error", "wait 须为秒数") from None
            wait = min(wait, self.cfg.longpoll_max_s) if wait == wait else 0.0
            evs = (
                self.svc.wait_events(m["pid"], after, wait, limit)
                if wait > 0
                else self.svc.events(m["pid"], after, limit)
            )
            head = self.svc.head()
        self._json(h, 200, {"events": evs, "head": head, "next_after": evs[-1]["seq"] if evs else after})

    def r_stream(self, h: Handler, m: Params, q: Params) -> None:
        """SSE：每条事件一帧，`id` 即 seq。游标取 Last-Event-ID 头或 ?after=；都没有时从当前链头之后开始。"""
        pid = m["pid"]
        self._known(pid)
        cursor = h.headers.get("Last-Event-ID") or q.get("after")
        try:
            after = int(cursor) if cursor else self.svc.head()
        except ValueError:
            raise HttpError(400, "schema_error", "Last-Event-ID 须为事件序号") from None
        h.started = True
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream; charset=utf-8")
        h.send_header("Cache-Control", "no-store")
        h.send_header("X-Accel-Buffering", "no")
        h.send_header("Connection", "close")
        self._cors(h)
        h.end_headers()
        h.close_connection = True
        try:
            h.wfile.write(b"retry: 1000\n\n")
            backlog = self.svc.events(pid, after, self.cfg.replay_window + 1)
            if len(backlog) > self.cfg.replay_window:  # 落后太多：给一个 as_of 快照，再从快照处续流
                state = self.svc.state
                snap = {
                    "as_of": state["seq"],
                    "skipped_after": after,
                    "status": views.status(state, pid),
                    "budget": views.budget(state, pid),
                }
                after = state["seq"]
                self._frame(h, snap, after, "snapshot")
            while not self._closing.is_set():
                evs = self.svc.wait_events(pid, after, self.cfg.heartbeat_s, 500)
                if self._closing.is_set():
                    break
                if not evs:
                    h.wfile.write(b": hb\n\n")
                for ev in evs:
                    self._frame(h, ev, ev["seq"])
                    after = ev["seq"]
                if evs and not self._closing.is_set():
                    # 一批事件之后跟一帧 view：最后那个序号上四份投影各自的 view_hash。前端据此只取变了的那几份，
                    # 一份都没变就不发请求（P2-1）。具名帧，只用 onmessage 的客户端看不见它，事件帧仍等于日志。
                    seq, parts = self._parts(pid, after)
                    self._frame(
                        h, {"as_of": seq, "parts_hash": {k: v["view_hash"] for k, v in parts.items()}}, after, "view"
                    )
                h.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    @staticmethod
    def _frame(h: Handler, obj: Any, seq: int, event: str | None = None) -> None:
        data = json.dumps(obj, ensure_ascii=False)  # JSON 不含裸换行，一帧一行 data
        head = f"id: {seq}\n" + (f"event: {event}\n" if event else "")
        h.wfile.write((head + f"data: {data}\n\n").encode())
        h.wfile.flush()

    # ---------- Blob ----------

    def r_blob_get(self, h: Handler, m: Params, q: Params) -> None:
        bh = m["hash"]
        if not _HEX64.match(bh):
            raise HttpError(400, "schema_error", "hash 须为 sha256")
        start: int = 0
        end: int | None = None
        if q.get("range"):
            mm = re.fullmatch(r"(\d+)-(\d*)", q["range"])
            if not mm:
                raise HttpError(400, "schema_error", "range 形如 <起>-<止>，左闭右开")
            start, end = int(mm[1]), int(mm[2]) if mm[2] else None
        try:
            data = self.blobs.get(bh, start, end)
        except CorruptBlob as e:
            raise HttpError(500, "corrupt", str(e)) from None
        except BlobNotFound:
            raise HttpError(404, "unknown_ref", "没有这个 Blob") from None
        # 一律当作不可执行的下载：不在页面内解释（§13.1 第 5 条）
        self._send(
            h,
            200,
            data,
            "application/octet-stream",
            {
                "Content-Disposition": f'attachment; filename="{bh[:16]}.bin"',
                "X-Blob-Hash": bh,
                "X-Blob-Size": str(len(data)),
            },
        )

    def r_blob_put(self, h: Handler, m: Params, q: Params) -> None:
        actor = self._actor(h)
        n = _length(h, -1)
        if n < 0:
            raise HttpError(411, "schema_error", "需要 Content-Length")
        if n > MAX_BLOB:
            raise HttpError(413, "schema_error", "单个 Blob 上限 256 MB")
        try:
            bh = self.blobs.put(h.rfile.read(n))
        except BlobError as e:
            raise HttpError(413, "schema_error", str(e)) from None
        self._json(h, 201, {"hash": bh, "size": n, "by": actor["kind"]})

    def r_vault_put(self, h: Handler, m: Params, q: Params) -> None:
        """只写：人的令牌，内容是一份含密级判官资产（如答案），返回 {vault, digest}。没有读的端点。"""
        if self.cfg.vault_put is None:
            raise HttpError(404, "unknown_ref", "本部署没有保密库入口")
        actor = self._actor(h)
        if actor["kind"] != "human":
            raise HttpError(403, "forbidden_op", "只有人的令牌能写保密库")
        n = _length(h, -1)
        if n < 0:
            raise HttpError(411, "schema_error", "需要 Content-Length")
        if n == 0 or n > MAX_VAULT:
            raise HttpError(413, "schema_error", f"保密库条目须为 1 到 {MAX_VAULT} 字节")
        self._json(h, 201, self.cfg.vault_put(h.rfile.read(n)))

    def _actor(self, h: Handler) -> Actor:
        token = self._token(h)
        try:
            return self.svc.tokens.resolve(token)
        except UnknownToken:
            raise HttpError(403, "forbidden_op", "未知令牌") from None

    # ---------- 写：全部落到 GraphService.submit（与 pd 同一条提议通道） ----------

    def _post(self, fn: WriteFn) -> Route:
        def handler(h: Handler, m: Params, q: Params) -> None:
            token, body = self._token(h), self._body(h)
            self._actor(h)  # 未知令牌：403，不进日志
            status, out = fn(token, m, body, h)
            self._json(h, status, out)

        return handler

    @staticmethod
    def _idem(body: Body, h: Handler) -> str:
        k = body.get("idem_key") or h.headers.get("Idempotency-Key")
        if not isinstance(k, str) or not k:
            raise HttpError(400, "schema_error", "写操作须带 idem_key")
        return k

    @staticmethod
    def _ops(body: Body) -> list[Body]:
        """每条提议是 {op: 字符串, body: 对象}；body 可缺。形状在这里验一次，后面按这个形状用。"""
        ops = body.get("ops")
        if (
            not isinstance(ops, list)
            or not ops
            or not all(
                isinstance(o, dict) and isinstance(o.get("op"), str) and isinstance(o.get("body", {}), dict)
                for o in ops
            )
        ):
            raise HttpError(400, "schema_error", "ops 须为非空数组，每条带 op；body 须为对象")
        return ops

    def _blobs_exist(self, ops: list[Body]) -> None:
        """登记前 Blob 必须已在仓库里（IO 前置条件在服务层检查，不进内核）。"""
        for o in ops:
            if o["op"] == "register_artifact":
                bh = str(o.get("body", {}).get("hash", ""))
                if _HEX64.match(bh) and not self.blobs.exists(bh):
                    raise HttpError(404, "unknown_ref", f"Blob {bh[:12]}… 不存在，先 PUT /v1/blobs")

    def w_open(self, token: str, m: Params, body: Body, h: Handler) -> tuple[int, Doc]:
        """POST /v1/problems：{id, idem_key, ops}。ops 以若干条 input 类登记开头，最后一条是 open_problem，
        Origin 用批内引用 "$<下标>" 指向前面登记的材料。整批原子。"""
        pid, ops = body.get("id"), self._ops(body)
        if not isinstance(pid, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", pid):
            raise HttpError(400, "schema_error", "id 须为 1–64 位的字母、数字、点、横线、下划线")
        if ops[-1]["op"] != "open_problem" or any(
            o["op"] != "register_artifact" or o.get("body", {}).get("class") != "input" for o in ops[:-1]
        ):
            raise HttpError(400, "schema_error", "ops 只能是若干条 input 类 register_artifact 加最后一条 open_problem")
        self._blobs_exist(ops)
        out = self.svc.submit(token, pid, self._idem(body, h), ops)
        return (201 if out["ok"] else 200), {**out, "id": pid}

    def w_proposals(self, token: str, m: Params, body: Body, h: Handler) -> tuple[int, Doc]:
        ops = self._ops(body)
        self._blobs_exist(ops)
        out = self.svc.submit(token, m["pid"], self._idem(body, h), ops)
        return 200, out  # 被拒也是 200：结果逐条在 results 里

    def w_lease(self, token: str, m: Params, body: Body, h: Handler) -> tuple[int, Doc]:
        idem = self._idem(body, h)  # 缺幂等键即拒：自动生成的键让重试不再幂等
        lease = {k: body[k] for k in ("kind", "target", "holder", "reserve", "ttl_s") if k in body}
        out = self.svc.submit(token, m["pid"], idem, [{"op": "lease", "body": lease}])
        r = out["results"][0]
        if out["ok"]:
            return 201, {"ok": True, "lease": self.svc.state["leases"].get(r["id"], {"id": r["id"]})}
        return (
            409
            if r.get("code") in ("conflict_leased", "over_budget")
            else 400
            if r.get("code") == "schema_error"
            else 403
            if r.get("code") == "forbidden_op"
            else 409
        ), {"ok": False, **r}

    def w_lease_verb(self, token: str, m: Params, body: Body, h: Handler) -> tuple[int, Doc]:
        lease = self.svc.state["leases"].get(m["id"])
        if lease is None:
            raise views.NotFound(f"没有租约 {m['id']}")
        idem = self._idem(body, h)
        keys = ("ttl_s",) if m["verb"] == "renew" else ("outcome", "transcript_ref", "suggestions")
        op = {"op": m["verb"], "body": {"lease": m["id"], **{k: body[k] for k in keys if k in body}}}
        out = self.svc.submit(token, lease["problem_id"], idem, [op])
        return (200 if out["ok"] else 409), (
            {"ok": True, "lease": self.svc.state["leases"][m["id"]]}
            if out["ok"]
            else {"ok": False, **out["results"][0]}
        )

    def w_artifact(self, token: str, m: Params, body: Body, h: Handler) -> tuple[int, Doc]:
        """POST /v1/artifacts：登记（register_artifact）。类别与令牌的匹配由内核判定。"""
        pid = body.get("problem_id")
        if not isinstance(pid, str):
            raise HttpError(400, "schema_error", "需要 problem_id")
        art = {k: v for k, v in body.items() if k not in ("problem_id", "idem_key")}
        self._blobs_exist([{"op": "register_artifact", "body": art}])
        out = self.svc.submit(token, pid, self._idem(body, h), [{"op": "register_artifact", "body": art}])
        r = out["results"][0]
        return (201 if out["ok"] else 200), (
            {"ok": True, "id": r["id"], "seq": r["seq"]} if out["ok"] else {"ok": False, **r}
        )

    def r_profile_preview(self, h: Handler, m: Params, q: Params) -> None:
        self._json(h, 200, views.profile_preview(self._body(h), self.svc.cfg))

    # ---------- 前端静态文件（同源） ----------

    def _static(self, h: Handler, path: str) -> None:
        assert self.cfg.static_dir is not None
        root = self.cfg.static_dir.resolve()
        p = (root / path.lstrip("/")).resolve()
        if p != root and root not in p.parents:
            raise HttpError(404, "unknown_ref", "没有这个文件")
        if not p.is_file():
            p = root / "index.html"  # 单页应用：其余路径回到入口
            if not p.is_file():
                raise HttpError(404, "unknown_ref", "没有这个文件")
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".ico": "image/x-icon",
            ".woff2": "font/woff2",
            ".map": "application/json",
        }.get(p.suffix, "application/octet-stream")
        self._send(
            h,
            200,
            p.read_bytes(),
            ctype,
            {"Content-Security-Policy": "default-src 'self'; connect-src 'self'; frame-src 'none'; object-src 'none'"},
        )


def _catalog(d: Path | None) -> Doc:
    """配置目录里的条目，带内容哈希。条目是数据：前端只解释字段映射，不执行其中任何东西。签名校验随 M3。"""
    items = []
    if d and Path(d).is_dir():
        for f in sorted(Path(d).iterdir()):
            if not f.is_file() or f.suffix not in (".json", ".yaml", ".yml"):
                continue
            raw = f.read_bytes()
            data: Any = None
            try:  # 解析不了就只给原文：条目是数据，坏条目不该拖垮目录
                if f.suffix == ".json":
                    data = json.loads(raw)
                else:
                    import yaml  # 可选依赖：没有就只给原文

                    try:
                        data = yaml.safe_load(raw)
                    except yaml.YAMLError:
                        data = None
            except (ValueError, ImportError):  # JSON 不合法（含编码错误），或没装 yaml
                data = None
            items.append(
                {
                    "name": f.stem,
                    "hash": hashlib.sha256(raw).hexdigest(),
                    "size": len(raw),
                    "signature": None,
                    "data": data,
                    "text": raw.decode("utf-8", "replace"),
                }
            )
    return {"items": items}


# ---------- 进程入口：python -m paoding_graph.httpapi ----------


def main(argv: list[str] | None = None) -> int:
    import argparse
    import secrets

    from .reducer import Config
    from .tokens import TokenRegistry

    ap = argparse.ArgumentParser(prog="paoding-graph", description="图服务：HTTP 只读端点、事件流与提议通道")
    ap.add_argument("--home", default=".paoding", help="数据目录：g.sqlite 与 blobs/")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--judges", help="判官注册表（JSON 文件：judge_id → {version, grade, kind, max_cost}）")
    ap.add_argument("--human", default="human", help="人的身份（actor.id）")
    ap.add_argument("--token-file", help="人的令牌存放处；缺省 <home>/human.token（权限 600）")
    ap.add_argument("--allow-origin", action="append", default=[], help="放行的跨源来源（开发服务器）")
    ap.add_argument("--static", help="前端构建产物目录（同源提供）")
    ap.add_argument("--templates")
    ap.add_argument("--renderers")
    a = ap.parse_args(argv)
    home = Path(a.home)
    home.mkdir(parents=True, exist_ok=True)
    judges: dict[str, JudgeEntry] = (
        json.loads(Path(a.judges).read_text(encoding="utf-8"))
        if a.judges
        else {
            "replay": {"version": "1", "grade": "decisive", "kind": "builtin", "max_cost": 0.01},
            "exact_match": {"version": "1", "grade": "decisive", "kind": "builtin", "max_cost": 0.0},
        }
    )
    tf = Path(a.token_file) if a.token_file else home / "human.token"
    if not tf.exists():
        tf.write_text(secrets.token_urlsafe(32), encoding="utf-8")
        tf.chmod(0o600)
    reg = TokenRegistry()
    reg.issue({"kind": "human", "id": a.human}, tf.read_text(encoding="utf-8").strip())
    svc = GraphService(home / "g.sqlite", Config(judges=judges), reg)
    app = GraphHttp(
        svc,
        BlobStore(home / "blobs"),
        HttpConfig(
            port=a.port,
            allowed_origins=tuple(a.allow_origin),
            static_dir=Path(a.static) if a.static else None,
            templates_dir=Path(a.templates) if a.templates else None,
            renderers_dir=Path(a.renderers) if a.renderers else None,
        ),
    )
    print(f"图服务 {app.serve()}（链头 seq={svc.head()}；人的令牌在 {tf}）", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        app.close()
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
