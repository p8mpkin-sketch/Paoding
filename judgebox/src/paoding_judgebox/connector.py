"""外部裁决连接器（docs/design/external-verdict/ §5.1–§5.4，§11 二期）：判定权在外部平台时的判官运行器。

不起容器、不碰 Problem.scope、路径上没有模型。它只做三件确定性的事：
1. 交付：按档案的 submit 端点把候选交给平台（deliver: judge）。幂等键是（题、候选），提交号存在本地状态目录里，
   同一候选的复判只读回执、不重交。deliver: worker 时候选的正文就是智能体交来的提交号，判官只读回执并核对归属。
2. 读回执：按档案的 receipt 端点取回执，按 JSON 指针取状态，按映射表给裁决；表外的值 inconclusive(unsupported)。
3. 待定：映射为 pending 时给 inconclusive(pending) 与 recheck_at，间隔从 poll.first_s 起按次数翻倍，封顶 poll.max_s。

档案的领域词只在 connectors.d 里（红线 3）；凭据只写钥匙环槽位名，值经注入的 secret(slot) 取得，只放进请求头，
不进输出、不进状态目录、不进异常消息。开题时抄进判官快照的档案摘要，运行时与已加载的档案核对，不一致即拒绝运行。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .builtin import Ctx, Outcome

VERDICTS = ("pass", "fail", "pending")
ENDPOINTS = ("list", "brief", "submit", "receipt")
DELIVER = ("judge", "worker")
_PTR = re.compile(r"^(/[^/]*)*$")
_VAR = re.compile(r"\{(task|sid)\}")
_SLOT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")  # 与设置页的槽名同形

Secret = Callable[[str], "str | None"]


class ProfileError(ValueError):
    pass


def validate_profile(doc: Any, name: str = "") -> dict[str, Any]:
    """连接器档案的形状（§5.1）。只认结构；不合即 ProfileError，启动时就失败，不留到判题时。"""
    where = f"{name}：" if name else ""

    def need(cond: bool, msg: str) -> None:
        if not cond:
            raise ProfileError(where + msg)

    need(isinstance(doc, dict), "档案须是映射")
    need(isinstance(doc.get("id"), str) and bool(doc["id"]), "缺 id")
    need(bool(str(doc.get("version", ""))), "缺 version")
    allowed = {"id", "version", "base_url", "match", "task_ref", "credential", "endpoints", "fields", "verdict"}
    allowed |= {"deliver", "poll", "timeout_s"}
    need(set(doc) <= allowed, f"多余字段 {sorted(set(doc) - allowed)}")
    url = urllib.parse.urlsplit(str(doc.get("base_url", "")))
    need(url.scheme in ("http", "https") and bool(url.netloc), "base_url 须是 http(s) 地址")
    need(not url.username and not url.password, "base_url 里不许带凭据")
    cred = doc.get("credential")
    need(isinstance(cred, dict) and set(cred) <= {"key_slot", "header", "scheme"}, "credential 只写槽位名与请求头形状")
    need(
        isinstance(cred.get("key_slot"), str) and bool(_SLOT.match(cred["key_slot"])), "credential.key_slot 须是槽位名"
    )
    need(all(isinstance(cred.get(k, ""), str) for k in ("header", "scheme")), "credential.header、scheme 须是字符串")
    eps = doc.get("endpoints")
    need(isinstance(eps, dict) and {"submit", "receipt"} <= set(eps) <= set(ENDPOINTS), f"endpoints 取 {ENDPOINTS}")
    for k, e in eps.items():
        need(isinstance(e, dict) and e.get("method") in ("GET", "POST"), f"endpoints.{k}.method 取 GET 或 POST")
        need(isinstance(e.get("path"), str) and e["path"].startswith("/"), f"endpoints.{k}.path 须以 / 开头")
        need(set(e) <= {"method", "path", "body"}, f"endpoints.{k} 只有 method、path、body")
    fields = doc.get("fields")
    need(
        isinstance(fields, dict) and {"submission_id", "status"} <= set(fields), "fields 至少有 submission_id 与 status"
    )
    for k, p in fields.items():
        need(isinstance(p, str) and bool(_PTR.match(p)), f"fields.{k} 须是 JSON 指针")
    verdict = doc.get("verdict")
    need(isinstance(verdict, dict) and bool(verdict), "verdict 映射表不能空")
    need(all(v in VERDICTS for v in verdict.values()), f"verdict 的值取 {VERDICTS}")
    need(doc.get("deliver", "judge") in DELIVER, f"deliver 取 {DELIVER}")
    poll = doc.get("poll", {})
    need(isinstance(poll, dict) and set(poll) <= {"first_s", "max_s", "settle_s"}, "poll 只有 first_s、max_s、settle_s")
    need(all(type(v) is int and v > 0 for v in poll.values()), "poll 的值须为正整数（秒）")
    return dict(doc)


def pointer(doc: Any, ptr: str) -> Any:
    """RFC 6901 JSON 指针；取不到返回 None。"""
    cur = doc
    for raw in ptr.split("/")[1:]:
        key = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        elif isinstance(cur, list) and key.isdigit() and int(key) < len(cur):
            cur = cur[int(key)]
        else:
            return None
    return cur


class ConnectorCallError(RuntimeError):
    """平台调用失败。消息里只有端点名与状态码，不含请求头与凭据。"""

    def __init__(self, endpoint: str, status: int | None, why: str):
        super().__init__(f"{endpoint}: {status if status is not None else '-'} {why}")
        self.endpoint, self.status = endpoint, status


class Connector:
    """一份档案对应的平台客户端。凭据每次调用时现取，不缓存。"""

    def __init__(self, prof: Mapping[str, Any], secret: Secret):
        self.prof, self._secret = prof, secret

    def _url(self, ep: str, task: str = "", sid: str = "") -> str:
        vals = {"task": urllib.parse.quote(task, safe=""), "sid": urllib.parse.quote(sid, safe="")}
        path = _VAR.sub(lambda m: vals[m.group(1)], self.prof["endpoints"][ep]["path"])
        return str(self.prof["base_url"]).rstrip("/") + path

    def call(self, ep: str, *, task: str = "", sid: str = "", candidate: str | None = None) -> Any:
        if ep not in self.prof["endpoints"]:
            raise ConnectorCallError(ep, None, "档案没有这个端点")
        spec = self.prof["endpoints"][ep]
        cred = self.prof["credential"]
        key = self._secret(cred["key_slot"])
        if not key:
            raise ConnectorCallError(ep, None, f"钥匙环槽位 {cred['key_slot']} 没有设")
        headers = {"Accept": "application/json"}
        scheme = cred.get("scheme", "Bearer")
        headers[cred.get("header", "Authorization")] = f"{scheme} {key}" if scheme else key
        data = None
        if spec["method"] == "POST":
            body = _fill(spec.get("body", {}), candidate)
            data = json.dumps(body, ensure_ascii=False).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self._url(ep, task, sid), data=data, method=spec["method"], headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=int(self.prof.get("timeout_s", 20))) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raise ConnectorCallError(ep, e.code, "平台拒绝") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ConnectorCallError(ep, None, f"连不上平台（{type(e).__name__}）") from None
        try:
            return json.loads(raw or b"null")
        except ValueError:
            raise ConnectorCallError(ep, None, "应答不是 JSON") from None

    def field(self, doc: Any, name: str) -> Any:
        ptr = self.prof["fields"].get(name)
        return None if ptr is None else pointer(doc, ptr)

    # 入口（三期"从平台导入"）与资源公告用的两个读操作
    def tasks(self) -> Any:
        return self.call("list")

    def brief(self, task: str) -> Any:
        return self.call("brief", task=task)

    def notice(self, task: str) -> bytes:
        """资源公告（§5.5）：领题说明的规范化字节，含运行时分到的服务地址。开题时领题由人的令牌登记为 input 类；
        这里只取、不登记，不判断地址能不能出站（那是 #91 的事）。"""
        return _out(self.brief(task))


def _fill(tpl: Any, candidate: str | None) -> Any:
    if tpl == "$candidate":
        return candidate
    if isinstance(tpl, dict):
        return {k: _fill(v, candidate) for k, v in tpl.items()}
    if isinstance(tpl, list):
        return [_fill(v, candidate) for v in tpl]
    return tpl


class SubmissionStore:
    """（题、候选）→ 提交号与已读次数。本地状态目录，一键一个文件，原子替换；不存凭据、不存候选正文。"""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / (hashlib.sha256(key.encode()).hexdigest() + ".json")

    def get(self, key: str) -> dict[str, Any] | None:
        p = self._path(key)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def put(self, key: str, rec: Mapping[str, Any]) -> None:
        p = self._path(key)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(dict(rec), sort_keys=True), encoding="utf-8")
        os.replace(tmp, p)


def _out(doc: Any) -> bytes:
    return json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def connector_plugins(
    registry: Mapping[str, Mapping[str, Any]],
    connectors: Mapping[str, Mapping[str, Any]],
    secret: Secret,
    store: SubmissionStore,
) -> dict[str, Callable[[Ctx], Outcome]]:
    """注册表里 runner.type = connector 的条目各挂同一个运行器（档案按开题快照取，不按条目）。"""
    fn = connector_judge(connectors, secret, store)
    return {jid: fn for jid, s in registry.items() if (s.get("runner") or {}).get("type") == "connector"}


def connector_judge(
    connectors: Mapping[str, Mapping[str, Any]], secret: Secret, store: SubmissionStore
) -> Callable[[Ctx], Outcome]:
    """判官运行器的插件位（JudgeConfig.judges[jid]）。connectors 即 registry.load_connectors() 的结果。"""

    def fn(c: Ctx) -> Outcome:
        jid = str(c.spec.get("id", ""))
        snap = (c.problem.get("judge_snapshot", {}).get(jid) or {}).get("connector")
        if c.target != "goal":
            return Outcome("inconclusive", "unsupported", b"connector judges only the goal")
        if not snap:
            return Outcome("inconclusive", "env_error", b"judge snapshot has no connector")
        loaded = connectors.get(snap["id"])
        if loaded is None or loaded["digest"] != snap["digest"]:
            # 档案在开题之后改过或没加载：判定程序已不是登记的那一个（I4），拒绝运行
            return Outcome("inconclusive", "env_error", f"connector {snap['id']} differs from the snapshot".encode())
        prof = loaded["doc"]
        if not c.candidate:
            return Outcome("inconclusive", "unsupported", b"connector needs a candidate to deliver")
        binding = c.check.get("binding") or {}
        task = str(binding.get("task", ""))
        conn = Connector(prof, secret)
        key = f"{c.problem.get('id', '')}\x00{c.candidate_ref or ''}"
        rec = store.get(key) or {}
        try:
            if "sid" not in rec:
                if prof.get("deliver", "judge") == "judge":
                    ack = conn.call("submit", task=task, candidate=(c.candidate or b"").decode("utf-8", "replace"))
                    sid = conn.field(ack, "submission_id")
                    if not isinstance(sid, (str, int)) or str(sid) == "":
                        return Outcome("inconclusive", "env_error", _out({"submit": ack, "why": "no submission id"}))
                    rec = {"sid": str(sid), "polls": 0}
                else:  # deliver: worker——候选正文就是提交号；归属在读回执时核对
                    rec = {"sid": (c.candidate or b"").decode("utf-8", "replace").strip(), "polls": 0}
                store.put(key, rec)
            receipt = conn.call("receipt", task=task, sid=rec["sid"])
        except ConnectorCallError as e:
            return Outcome("inconclusive", "env_error", str(e).encode())
        rec = {**rec, "polls": int(rec.get("polls", 0)) + 1}
        store.put(key, rec)
        out = _out({"submission": rec["sid"], "receipt": receipt})
        owner = conn.field(receipt, "task")
        if "task" in prof["fields"] and str(owner) != task:
            return Outcome("inconclusive", "env_error", _out({"why": "receipt belongs to another task", "task": owner}))
        at = conn.field(receipt, "submitted_at")
        if "submitted_at" in prof["fields"] and not (isinstance(at, int) and at >= int(c.problem.get("opened_ts", 0))):
            # deliver: worker 时提交号由被判的一方给出：只认开题之后的提交（§5.4）
            return Outcome("inconclusive", "env_error", _out({"why": "submission predates the problem", "at": at}))
        status = conn.field(receipt, "status")
        v = prof["verdict"].get(str(status)) if status is not None else None
        if v is None:
            return Outcome("inconclusive", "unsupported", out)
        if v == "pending":
            poll = prof.get("poll", {})
            wait = min(int(poll.get("first_s", 10)) * 2 ** (rec["polls"] - 1), int(poll.get("max_s", 600)))
            return Outcome("inconclusive", "pending", out, recheck_at=c.now_ms + wait * 1000)
        return Outcome(v, "ok", out)

    return fn
