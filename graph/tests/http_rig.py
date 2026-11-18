"""HTTP 测试台：真图服务（SQLite 临时文件）+ Blob 仓库 + 本机 HTTP 绑定。客户端只用标准库。

`drive()` 走一条完整的题：开题 → Bootstrap（观察）→ Reason（Intent、Hint）→ Explore → 候选 → 判官裁决 → 自动关题。
全部经 HTTP 提交（令牌决定身份），所以同一条日志既验写通道，也供只读端点与回放用。
"""
import hashlib
import json
import urllib.error
import urllib.request

from conftest import CFG

from paoding_graph.blobs import BlobStore
from paoding_graph.httpapi import GraphHttp, HttpConfig
from paoding_graph.service import GraphService
from paoding_graph.tokens import TokenRegistry

TOKENS = {"human": {"kind": "human", "id": "cz"}, "sinan": {"kind": "sinan", "id": "sn1"},
          "exec": {"kind": "executor", "id": "ex1"}, "judge": {"kind": "judge", "id": "jr1"},
          "watchdog": {"kind": "watchdog", "id": "wd"}}
R = {"usd_milli": 100, "wall_s": 60}


class Api:
    def __init__(self, tmp_path, **cfg):
        self.reg = TokenRegistry()
        for name, actor in TOKENS.items():
            self.reg.issue(actor, f"tok-{name}")
        t = [1000]

        def tick():
            t[0] += 1
            return t[0]
        self.clock = t
        self.path = tmp_path / "g.sqlite"
        self.svc = GraphService(self.path, CFG, self.reg, tick)
        self.blobs = BlobStore(tmp_path / "blobs")
        self.http = GraphHttp(self.svc, self.blobs, HttpConfig(heartbeat_s=0.2, **cfg))
        self.url = self.http.serve()
        self.n = 0

    def close(self):
        self.http.close()

    # ---------- 原始请求 ----------

    def req(self, method, path, body=None, token=None, headers=None, raw=False):
        data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
        hs = {"Content-Type": "application/json", **(headers or {})}
        if token:
            hs["Authorization"] = f"Bearer {token}"
        r = urllib.request.Request(self.url + path, data=data, method=method, headers=hs)
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                payload = resp.read()
                return resp.status, (payload if raw else json.loads(payload)), dict(resp.headers)
        except urllib.error.HTTPError as e:
            payload = e.read()
            return e.code, (payload if raw else json.loads(payload or b"null")), dict(e.headers)

    def get(self, path, **kw):
        st, body, _ = self.req("GET", path, **kw)
        assert st == 200, (st, body)
        return body

    def propose(self, pid, ops, who="human", idem=None):
        self.n += 1
        st, body, _ = self.req("POST", f"/v1/problems/{pid}/proposals",
                               {"idem_key": idem or f"k{self.n}", "ops": ops}, token=f"tok-{who}")
        assert st == 200, (st, body)
        return body

    def one(self, pid, op, body, who="human"):
        out = self.propose(pid, [{"op": op, "body": body}], who)
        assert out["ok"], out
        return out["results"][0].get("id") or "ok"

    def session(self, lease_id, role):
        """Adapter 为租约签的会话令牌（进程内签发，与真 Adapter 相同）。"""
        tok = f"tok-s-{lease_id}"
        self.reg.issue({"kind": "adapter", "id": "ad1", "session": lease_id, "role": role}, tok)
        return tok

    # ---------- 便捷操作 ----------

    def put(self, data: bytes, who="human"):
        st, body, _ = self.req("PUT", "/v1/blobs", data, token=f"tok-{who}",
                               headers={"Content-Type": "application/octet-stream"})
        assert st == 201 and body["hash"] == hashlib.sha256(data).hexdigest(), (st, body)
        return body["hash"]

    def art_op(self, data: bytes, cls="input", who="human"):
        body = {"hash": self.put(data, who), "size": len(data), "media_type": "text/plain", "class": cls}
        if cls in ("exec", "judge"):
            body["exec"] = {"sandbox_id": "s", "base": "b", "baseline_ref": "r", "tool": "shell",
                            "command": "cat /etc/hostname", "cwd": "/", "exit_code": 0, "touched": [],
                            "started_at": 1, "ended_at": 2, "truncated": False}
        return {"op": "register_artifact", "body": body}

    def open(self, pid="p1", risks=("r0",), usd_milli=5000, resource="target"):
        self.n += 1
        problem = {
            "title": f"题 {pid}", "origin": {"statement_ref": "$0", "materials": []},
            "goal": {"statement": "取得答案并原样提交", "check": {"judge_id": "exact_match", "expect": {"digest": "ab"}},
                     "max_attempts": 3, "accept": "judge"},
            "scope": [{"resource": resource, "pattern": "*", "actions": ["read"], "risk": r} for r in risks],
            "budget": {"usd_milli": usd_milli, "wall_s": 3600, "verify_share": 0.2, "bootstrap_share": 0.3},
            "env": {"base": "basic", "baseline_ref": "base@1"}, "judges": ["exact_match", "replay"]}
        st, body, _ = self.req("POST", "/v1/problems", {"id": pid, "idem_key": f"open-{pid}", "ops": [
            self.art_op(b"statement " + pid.encode()), {"op": "open_problem", "body": problem}]}, token="tok-human")
        assert st == 201 and body["ok"], (st, body)
        return body

    def lease(self, pid, kind, target=None, who="sinan", reserve=R, ttl=120):
        st, body, _ = self.req("POST", f"/v1/problems/{pid}/leases", {
            "kind": kind, **({"target": target} if target else {}), "holder": TOKENS[who]["id"],
            "reserve": reserve, "ttl_s": ttl}, token=f"tok-{who}")
        return st, body

    def release(self, lease_id, outcome="done", who="sinan"):
        st, body, _ = self.req("POST", f"/v1/leases/{lease_id}/release", {"outcome": outcome}, token=f"tok-{who}")
        assert st == 200, (st, body)
        return body

    def cost(self, pid, lease_id, usd_milli, token):
        out = self.propose_with(token, pid, [{"op": "cost", "body": {
            "task_id": lease_id, "source": "proxy", "tokens_in": 10, "tokens_cached": 0, "tokens_out": 5,
            "usd_milli": usd_milli, "wall_s": 1, "price_table": "t1", "model": "m"}}])
        assert out["ok"], out

    def propose_with(self, token, pid, ops):
        self.n += 1
        st, body, _ = self.req("POST", f"/v1/problems/{pid}/proposals", {"idem_key": f"k{self.n}", "ops": ops},
                               token=token)
        assert st == 200, (st, body)
        return body


def drive(api: Api, pid="p1", result="pass") -> dict:
    """一条完整的题。返回过程中产生的各个 id。"""
    api.open(pid)
    ids = {}
    st, b = api.lease(pid, "bootstrap")
    assert st == 201, b
    boot = ids["boot"] = b["lease"]["id"]
    s = api.session(boot, "bootstrap")
    ids["exec"] = api.one(pid, "register_artifact", api.art_op(b"hostname-output\n", "exec", "exec")["body"], "exec")
    out = api.propose_with(s, pid, [{"op": "add_fact", "body": {
        "title": "主机名可读", "summary": "读取主机名成功", "claim_type": "observation",
        "check": {"judge_id": "replay", "expect": {"exit_code": 0}}, "premises": [], "grounds": [ids["exec"]]}}])
    assert out["ok"], out
    ids["fact"] = out["results"][0]["id"]
    api.cost(pid, boot, 30, s)
    api.release(boot, "done")

    st, b = api.lease(pid, "reason")
    assert st == 201, b
    rl = ids["reason"] = b["lease"]["id"]
    s = api.session(rl, "reason")
    out = api.propose_with(s, pid, [{"op": "add_intent", "body": {
        "title": "取回答案", "summary": "沿已知入口取回", "premises": [ids["fact"]], "risk": "r0", "budget": R,
        "expected_gain": 0.7}}])
    assert out["ok"], out
    ids["intent"] = out["results"][0]["id"]
    api.release(rl, "done")
    ids["hint"] = api.one(pid, "hint", {"text": "先看登录表单", "about": ids["intent"]})

    st, b = api.lease(pid, "reason")
    assert st == 201, b
    rl2 = ids["reason2"] = b["lease"]["id"]
    s = api.session(rl2, "reason")
    out = api.propose_with(s, pid, [{"op": "add_intent", "body": {
        "title": "核对表单字段", "summary": "", "premises": [], "risk": "r0", "budget": R}}])
    assert out["ok"], out
    ids["intent2"] = out["results"][0]["id"]
    api.release(rl2, "done")

    st, b = api.lease(pid, "explore", ids["intent"])
    assert st == 201, b
    el = ids["explore"] = b["lease"]["id"]
    s = api.session(el, "explore")
    cand = api.blobs.put(b"the-answer")
    out = api.propose_with(s, pid, [
        {"op": "register_artifact", "body": {"hash": cand, "size": 10, "media_type": "text/plain", "class": "authored"}},
        {"op": "request_judge", "body": {"target": "goal", "judge_id": "exact_match", "candidate": "$0"}}])
    assert out["ok"], out
    ids["candidate"], ids["request"] = out["results"][0]["id"], out["results"][1]["id"]
    api.cost(pid, el, 40, s)
    api.release(el, "done")

    st, b = api.lease(pid, "judge", ids["request"], who="judge")
    assert st == 201, b
    jl = ids["judge"] = b["lease"]["id"]
    ids["judge_out"] = api.one(pid, "register_artifact", api.art_op(b"verdict\n", "judge", "judge")["body"], "judge")
    out = api.propose(pid, [{"op": "judge_verdict", "body": {
        "request": ids["request"], "result": result, "version": "1", "evidence": [ids["judge_out"]]}}], "judge")
    assert out["ok"], out
    ids["verdict_seq"] = out["results"][0]["seq"]
    api.release(jl, "done", who="judge")
    return ids
