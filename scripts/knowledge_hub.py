"""全栈里的书库一角（v5 第四期，资料库第一期）：书库服务，以及挂在图服务 HTTP 上的资料端点。

    GET  /v1/knowledge/sources                              资料列表，带向量模型说明
    POST /v1/knowledge/sources                              新建：{name, scope, text} 或 {name, scope, origin?, file}
    POST /v1/knowledge/sources/{id}/revisions               新版本：{text} 或 {file}
    POST /v1/knowledge/sources/{id}/disable|enable|delete|restore
    GET  /v1/knowledge/jobs                                 正在导入的版本与五阶段进度
    POST /v1/knowledge/jobs/{id}/{rev}/retry|cancel        retry 可带 {mask: true}：遮盖认出的凭据后导入
    POST /v1/knowledge/search                               “试一下”：{q, k?, pick?}，与会话检索同一个函数
    GET  /v1/knowledge/chunks/{id}                          一段的原文与位置

写操作只认人的令牌。file 是先用 PUT /v1/blobs 传上去的 {hash, size, media_type, name}；这里核对 Blob 在、大小对。
硬规则（cz 2026-11-19）：只收网页或 pd 命令交来的字节。请求体里带本机路径（path、dir）一律拒绝，网址抓取在第三期。

配置（StackConfig.knowledge）：embedder（{kind: hash|onnx|local_http, ...}，缺省 hash）。

执行中检索（资料库第二期）：SessionKnowledge 是会话运行器的 KnowledgePort。范围按任务的 prefs.knowledge：
缺省与 auto 是所有“所有任务”可见的资料，pick 是点名的几份，off 不挂工具。kb_read 把段落文字放进 Blob，
用书库的组件令牌（graph:shuku）登记为本题的 knowledge 类；每次 kb_search 记一条 kb_query（查询词与命中的段落 id）。
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from paoding_graph.contract import (
    KNOWLEDGE_REGISTRAR,
    BadBody,
    BlobError,
    BlobStore,
    GraphHttp,
    GraphService,
    MountError,
    TokenRegistry,
)
from paoding_shuku.contract import EMBEDDERS, MAX_BYTES, Rejected, Shuku, ShukuConfig

DEFAULTS: dict[str, Any] = {"embedder": {"kind": "hash"}}
MAX_TEXT = 2 * 1024 * 1024  # 粘贴文字的上限（字节）；更大的走文件
STATUS = {"unknown_ref": 404, "conflict": 409, "forbidden_op": 403}


def knowledge_config(raw: object) -> dict[str, Any]:
    if raw is None:
        return {k: dict(v) for k, v in DEFAULTS.items()}
    if not isinstance(raw, dict) or set(raw) - set(DEFAULTS):
        raise ValueError(f"knowledge 只认 {sorted(DEFAULTS)} 这几项")
    emb = raw.get("embedder", DEFAULTS["embedder"])
    if not isinstance(emb, dict) or emb.get("kind", "hash") not in EMBEDDERS:
        raise ValueError(f"knowledge.embedder.kind 取 {EMBEDDERS}")
    return {"embedder": dict(emb)}


class KnowledgeHub:
    def __init__(
        self,
        home: Path,
        blobs: BlobStore,
        cfg: dict[str, Any],
        graph: GraphService | None = None,
        tokens: TokenRegistry | None = None,
    ):
        self.blobs, self.graph = blobs, graph
        self.sk = Shuku(home / "shuku", blobs, ShukuConfig(embedder=cfg["embedder"]))
        self.session: SessionKnowledge | None = None
        if graph is not None and tokens is not None:  # 书库的组件令牌只在本进程：登记 knowledge 类、记 kb_query
            self.session = SessionKnowledge(self.sk, blobs, graph, tokens.issue(dict(KNOWLEDGE_REGISTRAR)))

    def mount(self, http: GraphHttp) -> None:
        base = r"/v1/knowledge"
        sid = r"(?P<id>s_[a-z0-9]{6,32})"
        http.mount("GET", base + "/sources", lambda q, b: self._list())
        http.mount("POST", base + "/sources", self._put, human=True)
        http.mount("POST", f"{base}/sources/{sid}/revisions", self._revise, human=True)
        http.mount("POST", f"{base}/sources/{sid}/(?P<verb>disable|enable|delete|restore)", self._curate, human=True)
        http.mount("GET", base + "/jobs", lambda q, b: {"jobs": self.sk.jobs(), "as_of": self.sk.state["seq"]})
        http.mount("POST", f"{base}/jobs/{sid}/(?P<rev>[0-9]+)/(?P<verb>retry|cancel)", self._job, human=True)
        http.mount("POST", base + "/search", self._search)
        http.mount("GET", base + r"/chunks/(?P<id>k_[0-9a-f]{16})", self._chunk)

    # ---------- 读 ----------

    def _list(self) -> dict[str, Any]:
        e = self.sk
        cited = self.cited()
        sources = [{**s, "cited": cited.get(s["id"], 0)} for s in e.sources()]
        return {"sources": sources, "embedder": e.embedder.id, "note": e.embedder_note, "as_of": e.state["seq"]}

    def cited(self) -> dict[str, int]:
        """每份资料被多少个任务引用过（图服务里 knowledge 类登记所在的题数）。"""
        if self.graph is None:
            return {}
        seen: dict[str, set[str]] = {}
        for a in self.graph.state["artifacts"].values():
            kn = a.get("knowledge")
            if a["class"] == "knowledge" and kn:
                seen.setdefault(str(kn["source"]), set()).add(a["problem_id"])
        return {k: len(v) for k, v in seen.items()}

    def _search(self, q: dict[str, str], body: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(body, dict) or not isinstance(body.get("q"), str):
            raise BadBody("请求体是 {q, k?, pick?: [资料 id]}")
        pick = body.get("pick")
        if pick is not None and (not isinstance(pick, list) or not all(isinstance(x, str) for x in pick)):
            raise BadBody("pick 是资料 id 的列表")
        k = body.get("k", 8)
        if not isinstance(k, int) or isinstance(k, bool):
            raise BadBody("k 是整数")
        return self.sk.search(body["q"], k, pick)

    def _chunk(self, q: dict[str, str], body: dict[str, Any] | None) -> dict[str, Any]:
        c = self.sk.chunk(q["id"])
        if c is None:
            raise MountError(404, "unknown_ref", "没有这一段（资料可能已清掉，或索引在重建）")
        return c

    # ---------- 写 ----------

    def _file(self, body: dict[str, Any]) -> dict[str, Any]:
        """请求体里的字节来源 → file。只认 text 或已上传的 Blob；本机路径与网址明确拒绝。"""
        for k in ("path", "dir", "folder"):
            if k in body:
                raise MountError(400, "forbidden_op", "资料库不读本机目录：请在网页上选文件上传，或粘贴文字")
        if "url" in body:
            raise MountError(400, "not_supported", "网址导入在资料库第三期")
        if isinstance(body.get("text"), str):
            data = body["text"].encode("utf-8")
            if not data.strip():
                raise BadBody("text 不能是空的")
            if len(data) > MAX_TEXT:
                raise MountError(413, "schema_error", "粘贴的文字至多 2 MB，更大的请当文件上传")
            name = str(body.get("file_name") or "pasted.txt")
            return {"hash": self.blobs.put(data), "size": len(data), "media_type": "text/plain", "name": name}
        f = body.get("file")
        if not isinstance(f, dict) or not isinstance(f.get("hash"), str) or not isinstance(f.get("size"), int):
            raise BadBody("给 text，或 file: {hash, size, media_type, name}（先 PUT /v1/blobs）")
        if f["size"] > MAX_BYTES:
            raise MountError(413, "schema_error", "单个文件至多 200 MB")
        try:
            got = len(self.blobs.get(f["hash"]))
        except BlobError:
            raise MountError(404, "unknown_ref", "Blob 不在：先 PUT /v1/blobs 再导入") from None
        if got != f["size"]:
            raise BadBody(f"file.size 与 Blob 实际大小 {got} 不符")
        return {
            "hash": f["hash"],
            "size": f["size"],
            "media_type": str(f.get("media_type") or ""),
            "name": str(f.get("name") or ""),
        }

    def _put(self, q: dict[str, str], body: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(body, dict) or not isinstance(body.get("name"), str):
            raise BadBody("请求体是 {name, scope?, origin?, text | file}")
        f = self._file(body)
        origin = "text" if "text" in body else str(body.get("origin") or "file")
        sid = self._do(lambda: self.sk.put_source(body["name"], origin, str(body.get("scope") or "all"), f))
        return {"source": sid, "revision": 1, "sources": self.sk.sources(), "jobs": self.sk.jobs()}

    def _revise(self, q: dict[str, str], body: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise BadBody("请求体是 {text | file}")
        if q["id"] not in self.sk.state["sources"]:
            raise MountError(404, "unknown_ref", "资料不存在")
        f = self._file(body)
        n = self._do(lambda: self.sk.put_revision(q["id"], f))
        return {"source": q["id"], "revision": n, "jobs": self.sk.jobs()}

    def _curate(self, q: dict[str, str], body: dict[str, Any] | None) -> dict[str, Any]:
        verb = q["verb"]
        if verb in ("disable", "enable"):
            self._do(lambda: self.sk.act("source_set", {"source": q["id"], "disabled": verb == "disable"}))
        else:
            self._do(lambda: self.sk.act("source_curate", {"source": q["id"], "action": verb}))
        return {"ok": True, "sources": self.sk.sources()}

    def _job(self, q: dict[str, str], body: dict[str, Any] | None) -> dict[str, Any]:
        kind = "job_retry" if q["verb"] == "retry" else "job_cancel"
        act: dict[str, Any] = {"source": q["id"], "revision": int(q["rev"])}
        if kind == "job_retry" and isinstance(body, dict) and "mask" in body:
            act["mask"] = body["mask"]  # 遮盖认出的凭据再导入；校验在书库的 reducer 里
        self._do(lambda: self.sk.act(kind, act))
        return {"ok": True, "jobs": self.sk.jobs()}

    @staticmethod
    def _do(fn: Any) -> Any:
        try:
            return fn()
        except Rejected as e:
            raise MountError(STATUS.get(e.code, 400), e.code, e.detail) from None

    # ---------- 循环 ----------

    def tick(self) -> list[str]:
        return self.sk.tick()

    def health(self) -> dict[str, Any]:
        jobs = self.sk.jobs()
        return {
            "embedder": self.sk.embedder.id,
            "sources": sum(1 for s in self.sk.sources() if s["live_revision"] is not None),
            "importing": sum(1 for j in jobs if not j["failed"]),
            "failed": sum(1 for j in jobs if j["failed"]),
        }

    def close(self) -> None:
        self.sk.close()


class SessionKnowledge:
    """会话运行器的 KnowledgePort（paoding_adapter.contract.KnowledgePort 的结构实现）。"""

    def __init__(self, sk: Shuku, blobs: BlobStore, graph: GraphService, token: str):
        self.sk, self.blobs, self.graph, self.token = sk, blobs, graph, token

    def _pick(self, pid: str) -> list[str] | None | bool:
        """None：auto（所有“所有任务”可见的资料）；列表：点名的几份；False：不用。"""
        p = self.graph.state["problems"].get(pid)
        pref = ((p or {}).get("prefs") or {}).get("knowledge") or {"mode": "auto"}
        if p is None or pref["mode"] == "off":
            return False
        return list(pref.get("pick") or []) if pref["mode"] == "pick" else None

    def _live(self, pid: str) -> list[tuple[str, int]]:
        pick = self._pick(pid)
        return [] if pick is False else self.sk.live(pick if isinstance(pick, list) else None)

    def available(self, pid: str) -> bool:
        return bool(self._live(pid))

    def _submit(self, pid: str, what: str, op: dict[str, Any]) -> dict[str, Any]:
        return self.graph.submit(self.token, pid, f"shuku:{what}:{secrets.token_hex(8)}", [op])

    def search(self, pid: str, lease: str, query: str, k: int) -> dict[str, Any]:
        pick = self._pick(pid)
        if pick is False:
            return {"ok": False, "code": "forbidden_op", "detail": "本任务的知识选项是“不用”"}
        res = self.sk.search(query, k, pick if isinstance(pick, list) else None)
        hits = [
            {
                "chunk": h["id"],
                "source_name": h["source_name"],
                "locator": _locator(h),
                "snippet": h["text"][:200],
                "score": h["score"],
            }
            for h in res["hits"]
        ]
        body = {"lease": lease, "query": query, "hits": [h["chunk"] for h in hits]}
        self._submit(pid, "kb_query", {"op": "kb_query", "body": body})  # 记不上（题已关）不影响这次检索
        return {"hits": hits, "via": res["via"]}

    def read(self, pid: str, lease: str, chunk: str) -> dict[str, Any]:
        live = dict(self._live(pid))
        c = self.sk.chunk(chunk)
        if c is not None and live.get(c["source"]) not in (None, c["revision"]):
            c = self.sk.chunk(chunk, live[c["source"]]) or c  # 同一段在当前可检索的版本里也在
        if c is None or live.get(c["source"]) != c["revision"]:
            return {"ok": False, "code": "unknown_ref", "detail": f"{chunk} 不在本任务能查的资料里（先 kb_search）"}
        data = c["text"].encode("utf-8")
        names = {sid: s["name"] for sid, s in self.sk.state["sources"].items()}
        loc = _locator(c)
        body = {
            "hash": self.blobs.put(data),
            "size": len(data),
            "media_type": "text/plain; charset=utf-8",
            "class": "knowledge",
            "knowledge": {"source": c["source"], "revision": c["revision"], "chunk": c["id"], "locator": loc},
        }
        out = self._submit(pid, "read", {"op": "register_artifact", "body": body})
        if not out["ok"]:
            r = out["results"][0]
            return {"ok": False, "code": r.get("code", "schema_error"), "detail": r.get("detail", "")}
        return {
            "artifact": out["results"][0]["id"],
            "text": c["text"],
            "source_name": names.get(c["source"], c["source"]),
            "locator": loc,
            "revision": c["revision"],
        }


def _locator(c: dict[str, Any]) -> str:
    """资料里的位置：文件名 / 标题路径。"""
    return " / ".join(str(x) for x in (c.get("doc"), c.get("heading")) if x)[:300]
