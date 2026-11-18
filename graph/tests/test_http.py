"""图服务 HTTP 绑定：只读端点、as_of 回放、SSE 事件流、提议通道（HMI §11；规格 §3.1.2、§3.2.2）。

验收：3.1.5 的 18（回放：as_of 的返回值与当时在链头读到的相同，冷启动两次相同）；
HT-2、HT-3（画像不可填、预览同源）；HT-5（四语域由出处决定）；HT-6（三步到证据根，本地哈希校验）；
HT-10（视图模型哈希）；HT-16（Last-Event-ID 续流无缺无重）；§13.1 第 5 条与 §13.3（下载不执行、只对本机、拒绝跨源）。
"""
import hashlib
import http.client
import json
import threading
import time
import urllib.parse

import pytest
from conftest import CFG
from http_rig import R, Api, drive

from paoding_graph import views
from paoding_graph.envelope import verify_chain
from paoding_graph.replay import state_hash
from paoding_graph.service import GraphService
from paoding_graph.tokens import TokenRegistry


@pytest.fixture
def api(tmp_path):
    a = Api(tmp_path)
    yield a
    a.close()


def strip(body):
    return {k: v for k, v in body.items() if k not in ("as_of", "head", "view_hash", "state_hash")}


# ---------- 只读端点 ----------

def test_problem_list_terminal_and_cost_per_solve(api):
    drive(api, "p1")
    api.open("p2")
    out = api.get("/v1/problems")
    assert [p["id"] for p in out["items"]] == ["p1", "p2"]
    p1, p2 = out["items"]
    assert p1["terminal"] == "solved" and p1["terminal_badge"]["label"] == "exact_match@1"   # HT-4：终态带判据徽章
    assert p2["terminal"] is None and not p2["closed"]                                      # 未关题没有终态
    assert out["totals"] == {"problems": 2, "solved": 1, "spent_usd_milli": 70, "cost_per_solve_usd_milli": 70}


def test_status_is_structured_twin_of_pd_status(api):
    ids = drive(api)
    st = api.get("/v1/problems/p1/status")
    assert st["problem"]["terminal"] == "solved" and st["goal"]["predicate"]["level"] == "E3"
    assert st["goal"]["predicate"]["attempts_used"] == 1 and st["goal"]["predicate"]["max_attempts"] == 3
    assert [v["result"] for v in st["goal"]["predicate"]["verdicts"]] == ["pass"]
    assert [f["id"] for f in st["facts"]] == [ids["fact"]]
    assert [i["id"] for i in st["intents"]] == [ids["intent"], ids["intent2"]]      # 按创建 seq 排
    i = st["intents"][0]
    assert i["status"] == "done" and i["gate"] is True and i["attempts"] == 1
    assert i["expected_gain"] == {"src": "estimate", "register": "估", "value": 0.7}
    assert st["hints"][0]["text"]["register"] == "人" and st["hints"][0]["about"] == ids["intent"]
    assert [l["kind"] for l in st["leases"]] == ["bootstrap", "reason", "reason", "explore", "judge"]
    assert all(not l["active"] for l in st["leases"])


def test_view_layers_cursor_and_frontier(api):
    ids = drive(api, result="fail")                                  # 候选失败：题仍在进行
    v = api.get("/v1/problems/p1/view?layer=title")
    assert [n["id"] for n in v["items"]] == [ids["fact"], ids["intent"], ids["intent2"]]
    assert all("summary" not in n for n in v["items"])               # 标题层不带摘要
    page = api.get("/v1/problems/p1/view?layer=summary&limit=2")
    assert len(page["items"]) == 2 and page["next_after_seq"] == page["items"][-1]["seq"] and page["total"] == 3
    rest = api.get(f"/v1/problems/p1/view?layer=summary&after_seq={page['next_after_seq']}")
    assert [n["id"] for n in rest["items"]] == [ids["intent2"]] and rest["next_after_seq"] is None
    fr = v["frontier"]
    assert fr["hints"] == [ids["hint"]] and ids["intent2"] in fr["intents"] and ids["fact"] in fr["facts"]
    st, body, _ = api.req("GET", "/v1/problems/p1/view?layer=full")
    assert st == 404 and body["code"] == "not_enabled"               # T-1 开关默认关
    st, body, _ = api.req("GET", "/v1/problems/p1/view?layer=bogus")
    assert st == 400 and body["code"] == "schema_error"


def test_view_full_dump_switch(tmp_path):
    a = Api(tmp_path, view_full_dump=True)
    try:
        drive(a)
        full = a.get("/v1/problems/p1/view?layer=full")
        assert full["items"][0]["grounds"][0]["class"] == "exec"
    finally:
        a.close()


def test_drilldown_reaches_evidence_root_with_local_hash_check(api):
    """HT-6：论断 → 证据根 → Artifact → Blob，三步；浏览器侧本地计算的 sha256 与登记值一致。"""
    ids = drive(api)
    n = api.get(f"/v1/nodes/{ids['fact']}?layer=evidence")                       # 1
    [g] = n["grounds"]
    assert g["class"] == "exec" and g["register"] == "证据" and n["no_evidence_root"] is False
    assert n["predicate"]["label"] == "replay@1" and n["predicate"]["fail_means"] == "refuted"
    a = api.get(f"/v1/artifacts/{g['id']}")                                      # 2
    assert a["exec"]["command"] == "cat /etc/hostname" and a["exec"]["exit_code"] == 0
    st, data, hs = api.req("GET", f"/v1/blobs/{a['hash']}", raw=True)            # 3
    assert st == 200 and hashlib.sha256(data).hexdigest() == a["hash"] == g["hash"] and len(data) == a["size"]
    assert hs["Content-Disposition"].startswith("attachment") and hs["X-Content-Type-Options"] == "nosniff"
    st, part, _ = api.req("GET", f"/v1/blobs/{a['hash']}?range=0-8", raw=True)
    assert part == b"hostname"
    goal = api.get("/v1/problems/p1/status")["goal"]["predicate"]
    ev = api.get(f"/v1/artifacts/{goal['verdicts'][0]['evidence'][0]}")
    assert ev["class"] == "judge" and ev["register"] == "证据"
    intent = api.get(f"/v1/nodes/{ids['intent']}?layer=evidence")
    assert intent["leases"] == [ids["explore"]] and intent["type"] == "intent"
    assert api.get(f"/v1/nodes/{ids['hint']}")["type"] == "hint"


def test_inference_has_no_evidence_root_marker(api):
    api.open()
    st, b = api.lease("p1", "bootstrap")
    s = api.session(b["lease"]["id"], "bootstrap")
    out = api.propose_with(s, "p1", [{"op": "register_artifact", "body": api.art_op(b"x", "exec", "exec")["body"]}])
    assert not out["ok"] and out["results"][0]["code"] == "forbidden_op"        # 任务令牌登记不了 exec 类
    ex = api.one("p1", "register_artifact", api.art_op(b"x", "exec", "exec")["body"], "exec")
    f1 = api.propose_with(s, "p1", [{"op": "add_fact", "body": {
        "title": "a", "summary": "", "claim_type": "observation", "check": {"judge_id": "replay"},
        "premises": [], "grounds": [ex]}}])["results"][0]["id"]
    f2 = api.propose_with(s, "p1", [{"op": "add_fact", "body": {
        "title": "b", "summary": "", "claim_type": "inference", "premises": [f1], "grounds": []}}])["results"][0]["id"]
    n = api.get(f"/v1/nodes/{f2}?layer=evidence")
    assert n["no_evidence_root"] is True and n["predicate"] is None and n["premises"] == [f1]


def test_unknown_refs_are_404(api):
    drive(api)
    for path in ("/v1/problems/nope/status", "/v1/nodes/f_999", "/v1/artifacts/a_999", "/v1/hints/h_999/trace",
                 "/v1/problems/p1/cards/approval/i_999", "/v1/problems/p1/cards/bogus/x",
                 "/v1/problems/p1/invalidations?node=f_999", "/v1/blobs/" + "0" * 64, "/v1/nothing"):
        st, body, _ = api.req("GET", path)
        assert st == 404 and body["code"] == "unknown_ref", (path, st, body)
    st, body, _ = api.req("GET", "/v1/problems/p1/cards/extension/p1")
    assert st == 404 and body["code"] == "not_enabled"
    st, body, _ = api.req("GET", "/v1/blobs/zz")
    assert st == 400
    st, body, _ = api.req("POST", "/v1/problems/p1/status", {})
    assert st == 405


def test_corrupt_blob_reported(api):
    """3.2.5 的 4 的 HTTP 形态：改动 Blob 的一个字节，读取时报 corrupt。"""
    h = api.put(b"evidence bytes")
    p = api.blobs.path(h)
    p.chmod(0o644)
    p.write_bytes(b"Evidence bytes")
    st, body, _ = api.req("GET", f"/v1/blobs/{h}")
    assert st == 500 and body["code"] == "corrupt"


def test_budget_view_matches_ledger(api):
    """HT-11 的服务端一半：仪表读的 /budget 与账本投影逐字段一致。"""
    drive(api)
    b = api.get("/v1/problems/p1/budget")
    assert b["spent"]["usd_milli"] == 70 and b["by_kind"]["explore"]["usd_milli"] == 40
    assert b["cap"]["usd_milli"] == 5000 and b["mark_lines"] == [50, 80] and b["marks"] == []
    assert b["percent"] == {"spent": 1, "committed": 1} and b["wall"]["cap_s"] == 3600
    assert {k: b[k] for k in ("cap", "spent", "reserved", "by_kind", "verify_spent", "marks")} == api.svc.budget("p1")


def test_budget_marks_appear(api):
    api.open(usd_milli=100)
    st, b = api.lease("p1", "bootstrap", reserve={"usd_milli": 30, "wall_s": 60})
    lid = b["lease"]["id"]
    api.cost("p1", lid, 55, api.session(lid, "bootstrap"))
    bud = api.get("/v1/problems/p1/budget")
    assert bud["marks"] == [50] and len(bud["mark_seqs"]) == 1 and bud["percent"]["spent"] == 55
    evs = api.get("/v1/problems/p1/events?after=0")["events"]
    assert evs[-1]["kind"] == "budget_mark" and evs[-1]["actor"]["kind"] == "graph"       # 时间轴刻度只来自事件


def test_work_and_human_items(api):
    api.open(risks=("r0", "r2"))
    assert api.get("/v1/problems/p1/work")["items"] == [{"kind": "bootstrap"}]
    st, b = api.lease("p1", "bootstrap")
    api.release(b["lease"]["id"], "nothing")
    st, b = api.lease("p1", "reason")
    s = api.session(b["lease"]["id"], "reason")
    iid = api.propose_with(s, "p1", [{"op": "add_intent", "body": {
        "title": "改配置", "premises": [], "risk": "r2", "budget": R}}])["results"][0]["id"]
    api.release(b["lease"]["id"])
    items = api.get("/v1/problems/p1/work")["items"]
    assert {"kind": "human", "target": iid, "why": "needs_human"} in items
    assert {"kind": "explore", "target": iid} not in items                      # 3.1.5 的 7：未批准的 r2 不出现
    card = api.get(f"/v1/problems/p1/cards/approval/{iid}")
    assert card["card"]["fields"]["risk"] == "r2" and card["display"]["rollback_declared"] is False
    assert card["display"]["status"] == "needs_human"
    assert {"kind": "human", "target": iid, "why": "needs_human"} in api.get("/v1/problems/p1/view")["frontier"]["human"]


# ---------- 回放（H3；3.1.5 的 18；HT-10） ----------

PATHS = ("/v1/problems/p1/status", "/v1/problems/p1/budget", "/v1/problems/p1/work",
         "/v1/problems/p1/view?layer=summary", "/v1/problems/p1/cards/closeout/p1")


def _sep(path):
    return "&" if "?" in path else "?"


def test_as_of_equals_what_was_read_live(api):
    """对每个序号 s：带 as_of=s 的返回值与当时在链头读到的逐字节相同。"""
    live = {}
    orig = api.svc.submit

    def recording(token, pid, idem, ops):
        out = orig(token, pid, idem, ops)
        if "p1" in api.svc.state["problems"]:
            live[api.svc.head()] = {p: api.get(p) for p in PATHS}
        return out
    api.svc.submit = recording
    drive(api)
    api.svc.submit = orig
    assert len(live) >= 15
    for s, seen in live.items():
        for p in PATHS:
            now = api.get(f"{p}{_sep(p)}as_of={s}")
            assert now["as_of"] == s == seen[p]["as_of"]
            assert now["view_hash"] == seen[p]["view_hash"], (s, p)
            assert strip(now) == strip(seen[p])


def test_cold_start_twice_same_view_hashes(api, tmp_path):
    """HT-10：任意序号冷启动两次，视图模型哈希相同，并等于实时服务给出的值；状态哈希与重放一致。"""
    ids = drive(api)
    head = api.svc.head()
    paths = PATHS + (f"/v1/nodes/{ids['fact']}?layer=evidence", f"/v1/hints/{ids['hint']}/trace",
                     f"/v1/problems/p1/cards/approval/{ids['intent']}", "/v1/problems")
    want = {(s, p): api.get(f"{p}{_sep(p)}as_of={s}&state_hash=1") for s in range(2, head + 1) for p in paths
            if not (("hints" in p and s < int(ids["hint"][2:])) or ("nodes" in p and s < int(ids["fact"][2:]))
                    or ("approval" in p and s < int(ids["intent"][2:])))}
    for _ in range(2):
        cold = Api.__new__(Api)
        cold.reg = TokenRegistry()
        cold.svc = GraphService(api.path, CFG, cold.reg)
        from paoding_graph.httpapi import GraphHttp
        cold.blobs, cold.http = api.blobs, GraphHttp(cold.svc, api.blobs)
        cold.url = cold.http.serve()
        try:
            for (s, p), seen in want.items():
                got = cold.get(f"{p}{_sep(p)}as_of={s}&state_hash=1")
                assert got["view_hash"] == seen["view_hash"] and got["state_hash"] == seen["state_hash"], (s, p)
            assert cold.get("/v1/problems/p1/status?state_hash=1")["state_hash"] == state_hash(api.svc.state)
        finally:
            cold.http.close()


def test_as_of_bounds(api):
    drive(api)
    head = api.svc.head()
    st, body, _ = api.req("GET", f"/v1/problems/p1/status?as_of={head + 1}")
    assert st == 400 and body["code"] == "schema_error"
    st, body, _ = api.req("GET", "/v1/problems/p1/status?as_of=1")              # 开题之前：题还不存在
    assert st == 404 and body["code"] == "unknown_ref"
    st, body, _ = api.req("GET", "/v1/problems/p1/status?as_of=abc")
    assert st == 400
    assert api.get("/v1/problems/p1/status?as_of=2")["facts"] == []
    assert api.get(f"/v1/problems/p1/events?as_of=5")["events"][-1]["seq"] == 5


def test_state_at_cache_is_consistent(api):
    drive(api)
    head = api.svc.head()
    forward = [state_hash(api.svc.state_at(s)) for s in range(1, head + 1)]
    api.svc._snaps.clear()
    backward = [state_hash(api.svc.state_at(s)) for s in range(head, 0, -1)][::-1]
    assert forward == backward and forward[-1] == state_hash(api.svc.state)


# ---------- 事件：长轮询与 SSE ----------

def test_events_are_the_audit_log(api):
    drive(api)
    out = api.get("/v1/problems/p1/events?after=0")
    evs = out["events"]
    assert [e["seq"] for e in evs] == sorted(e["seq"] for e in evs) and out["head"] == evs[-1]["seq"]
    verify_chain(evs)                                               # 按题哈希链可离线校验
    assert evs[0]["kind"] == "register_artifact" and evs[1]["kind"] == "open_problem"
    kinds = [e["kind"] for e in evs]
    assert kinds.index("judge_verdict") < kinds.index("close_problem")
    page = api.get("/v1/problems/p1/events?after=0&limit=3")
    assert len(page["events"]) == 3 and page["next_after"] == page["events"][-1]["seq"]
    assert api.get(f"/v1/problems/p1/events?after={out['head']}") == {"events": [], "head": out["head"],
                                                                     "next_after": out["head"]}


def test_long_poll_wakes_on_new_event(api):
    api.open()
    head = api.svc.head()
    got = {}
    t = threading.Thread(target=lambda: got.update(api.get(f"/v1/problems/p1/events?after={head}&wait=5")))
    t0 = time.monotonic()
    t.start()
    time.sleep(0.2)
    hid = api.one("p1", "hint", {"text": "看看配置"})
    t.join(5)
    assert not t.is_alive() and time.monotonic() - t0 < 4
    assert [e["kind"] for e in got["events"]] == ["hint"] and got["events"][0]["seq"] == int(hid[2:])
    t0 = time.monotonic()
    assert api.get(f"/v1/problems/p1/events?after={api.svc.head()}&wait=0.3")["events"] == []
    assert time.monotonic() - t0 >= 0.25                             # 没有新事件：等满再空手而回


class Sse:
    """最小 SSE 客户端：按帧读，记录 id、event、data。"""

    def __init__(self, api, path, last_event_id=None):
        u = urllib.parse.urlsplit(api.url)
        self.conn = http.client.HTTPConnection(u.hostname, u.port, timeout=5)
        hs = {"Accept": "text/event-stream"}
        if last_event_id is not None:
            hs["Last-Event-ID"] = str(last_event_id)
        self.conn.request("GET", path, headers=hs)
        self.resp = self.conn.getresponse()
        self.comments = 0

    def frame(self):
        f = {}
        while True:
            line = self.resp.readline().decode().rstrip("\n")
            if line == "":
                if f:
                    return f
                continue
            if line.startswith(":"):
                self.comments += 1
                continue
            k, _, v = line.partition(": ")
            f[k] = v

    def frames(self, n):
        out = []
        while len(out) < n:
            f = self.frame()
            if "data" in f:
                out.append({"id": int(f["id"]), "event": f.get("event"), "data": json.loads(f["data"])})
        return out

    def close(self):
        self.conn.close()


def test_sse_stream_ids_are_seqs_and_same_source_as_events(api):
    api.open()
    s = Sse(api, "/v1/problems/p1/stream?after=0")
    try:
        assert s.resp.status == 200 and s.resp.getheader("Content-Type").startswith("text/event-stream")
        first = s.frames(2)
        hid = api.one("p1", "hint", {"text": "换个入口"})
        [live] = s.frames(1)
    finally:
        s.close()
    log = api.get("/v1/problems/p1/events?after=0")["events"]
    assert [f["data"] for f in first + [live]] == log                # 与 /events 同源，逐条相同
    assert [f["id"] for f in first + [live]] == [e["seq"] for e in log] and live["id"] == int(hid[2:])


def test_sse_default_cursor_is_head_and_heartbeats(api):
    api.open()
    s = Sse(api, "/v1/problems/p1/stream")
    try:
        time.sleep(0.5)
        api.one("p1", "hint", {"text": "a"})
        [f] = s.frames(1)
        assert f["data"]["kind"] == "hint" and s.comments >= 1        # 不补发历史；空闲时有心跳
    finally:
        s.close()


def test_sse_resume_with_last_event_id_no_gap_no_dup(api):
    """HT-16：断连后用 Last-Event-ID 续上，事件序列无缺无重。"""
    api.open()
    s = Sse(api, "/v1/problems/p1/stream?after=0")
    seen = s.frames(2)
    s.close()                                                        # 断连
    for n in range(5):
        api.one("p1", "hint", {"text": f"h{n}"})
    s2 = Sse(api, "/v1/problems/p1/stream", last_event_id=seen[-1]["id"])
    try:
        seen += s2.frames(5)
    finally:
        s2.close()
    log = api.get("/v1/problems/p1/events?after=0")["events"]
    assert [f["id"] for f in seen] == [e["seq"] for e in log]
    assert [f["data"]["hash"] for f in seen] == [e["hash"] for e in log]


def test_sse_snapshot_when_backlog_exceeds_window(tmp_path):
    """§13.2：补发窗口超过阈值时改发一个 as_of 快照，再从快照的 seq 续流。"""
    a = Api(tmp_path, replay_window=3)
    try:
        a.open()
        for n in range(6):
            a.one("p1", "hint", {"text": f"h{n}"})
        head = a.svc.head()
        s = Sse(a, "/v1/problems/p1/stream", last_event_id=1)
        try:
            [snap] = s.frames(1)
            assert snap["event"] == "snapshot" and snap["id"] == head and snap["data"]["as_of"] == head
            assert strip(snap["data"]["status"]) == strip(a.get(f"/v1/problems/p1/status?as_of={head}"))
            a.one("p1", "hint", {"text": "之后"})
            [nxt] = s.frames(1)
            assert nxt["event"] is None and nxt["id"] == head + 1
        finally:
            s.close()
    finally:
        a.close()


def test_sse_only_carries_own_problem(api):
    api.open("p1")
    api.open("p2")
    s = Sse(api, "/v1/problems/p1/stream")
    try:
        api.one("p2", "hint", {"text": "别题"})
        api.one("p1", "hint", {"text": "本题"})
        [f] = s.frames(1)
        assert f["data"]["problem_id"] == "p1" and f["data"]["body"]["text"] == "本题"
    finally:
        s.close()
    st, body, _ = api.req("GET", "/v1/problems/nope/stream")
    assert st == 404


# ---------- 写：与 pd 同一条提议通道 ----------

def test_writes_need_a_known_token(api):
    api.open()
    n = api.svc.head()
    st, body, _ = api.req("POST", "/v1/problems/p1/proposals", {"idem_key": "x", "ops": [{"op": "hint", "body": {"text": "a"}}]})
    assert st == 401 and body["code"] == "forbidden_op"
    st, body, _ = api.req("POST", "/v1/problems/p1/proposals", {"idem_key": "x", "ops": [{"op": "hint", "body": {"text": "a"}}]},
                          token="not-a-token")
    assert st == 403 and body["code"] == "forbidden_op"
    st, body, _ = api.req("PUT", "/v1/blobs", b"x")
    assert st == 401
    assert api.svc.head() == n                                       # 一条都没进日志


def test_human_token_can_only_submit_human_ops(api):
    """HT-12 的服务端一半：人的令牌提交不了模型侧操作；身份只来自令牌，请求体里自称无效。"""
    api.open()
    for op, body in (("add_fact", {"title": "t", "summary": "", "claim_type": "inference", "premises": [], "grounds": []}),
                     ("judge_verdict", {"request": "j_1", "result": "pass", "version": "1", "evidence": []}),
                     ("lease", {"kind": "bootstrap", "holder": "cz", "reserve": R, "ttl_s": 60}),
                     ("expire_lease", {"lease": "l_1"}), ("budget_mark", {"mark": 50, "axis": "usd_milli"}),
                     ("cost", {"task_id": "l_1", "source": "proxy", "usd_milli": 1, "price_table": "t"})):
        out = api.propose("p1", [{"op": op, "body": body, "actor": {"kind": "adapter", "role": "reason"}}])
        assert not out["ok"] and out["results"][0]["code"] == "forbidden_op", (op, out)
    ex = api.art_op(b"fake output", "exec")["body"]
    out = api.propose("p1", [{"op": "register_artifact", "body": ex}])
    assert out["results"][0]["code"] == "forbidden_op"               # 3.2.5 的 2：人的令牌登记不了 exec 类


def test_open_rejects_profile_and_malformed_batches(api):
    """HT-2：提交体带 profile 被拒。"""
    art = api.art_op(b"stmt")
    problem = {"title": "t", "origin": {"statement_ref": "$0", "materials": []},
               "goal": {"statement": "g", "check": {"judge_id": "exact_match"}, "max_attempts": 3, "accept": "judge"},
               "scope": [{"resource": "target", "pattern": "*", "actions": ["read"], "risk": "r0"}],
               "budget": {"usd_milli": 5000, "wall_s": 3600, "verify_share": 0.2, "bootstrap_share": 0.3},
               "env": {"base": "basic", "baseline_ref": "base@1"}, "judges": ["exact_match"]}
    bad = {**problem, "profile": {"info": "complete", "judge": "hard", "reversibility": "r0"}}
    st, body, _ = api.req("POST", "/v1/problems", {"id": "p1", "idem_key": "o1", "ops": [art, {"op": "open_problem", "body": bad}]},
                          token="tok-human")
    assert st == 200 and not body["ok"] and body["results"][1]["code"] == "schema_error"
    assert "p1" not in api.svc.state["problems"] and api.svc.head() == 0          # 整批原子：材料也没登记
    for ops in ([{"op": "hint", "body": {"text": "x"}}], [art], [{"op": "open_problem", "body": problem}, art]):
        st, body, _ = api.req("POST", "/v1/problems", {"id": "p1", "idem_key": "o2", "ops": ops}, token="tok-human")
        assert st == 400 and body["code"] == "schema_error"
    st, body, _ = api.req("POST", "/v1/problems", {"id": "../x", "idem_key": "o3", "ops": [art, {"op": "open_problem", "body": problem}]},
                          token="tok-human")
    assert st == 400
    st, body, _ = api.req("POST", "/v1/problems", {"id": "p1", "ops": [art, {"op": "open_problem", "body": problem}]},
                          token="tok-human")
    assert st == 400 and "idem_key" in body["detail"]
    ghost = {"op": "register_artifact", "body": {**art["body"], "hash": "1" * 64}}
    st, body, _ = api.req("POST", "/v1/problems", {"id": "p1", "idem_key": "o4", "ops": [ghost, {"op": "open_problem", "body": problem}]},
                          token="tok-human")
    assert st == 404 and body["code"] == "unknown_ref"               # Blob 不在仓库里：登记前就拒绝
    st, body, _ = api.req("POST", "/v1/problems", {"id": "p1", "idem_key": "o5", "ops": [art, {"op": "open_problem", "body": problem}]},
                          token="tok-human")
    assert st == 201 and body["ok"] and body["id"] == "p1"
    assert api.svc.state["problems"]["p1"]["profile"] == {"info": "complete", "judge": "hard", "reversibility": "r0"}


def test_idempotent_replay_over_http(api):
    api.open()
    a = api.propose("p1", [{"op": "hint", "body": {"text": "一次"}}], idem="same")
    n = api.svc.head()
    b = api.propose("p1", [{"op": "hint", "body": {"text": "一次"}}], idem="same")
    c = api.propose("p1", [{"op": "hint", "body": {"text": "换了内容也返回首次结果"}}], idem="same")
    assert a == b == c and api.svc.head() == n
    assert len(api.get("/v1/problems/p1/status")["hints"]) == 1


def test_lease_endpoints_require_idem_key(api):
    """缺幂等键的租约请求返回 schema_error，不替调用方生成键；什么也不落盘。"""
    api.open()
    lease = {"kind": "bootstrap", "holder": "sn1", "reserve": R, "ttl_s": 120}
    head = api.svc.head()
    st, body, _ = api.req("POST", "/v1/problems/p1/leases", lease, token="tok-sinan")
    assert (st, body["code"]) == (400, "schema_error") and api.svc.head() == head
    st, body, _ = api.req("POST", "/v1/problems/p1/leases", {**lease, "idem_key": ""}, token="tok-sinan")
    assert (st, body["code"]) == (400, "schema_error") and api.svc.head() == head
    st, b = api.lease("p1", "bootstrap")
    lid, head = b["lease"]["id"], api.svc.head()
    for verb, extra in (("renew", {"ttl_s": 300}), ("release", {"outcome": "nothing"})):
        st, body, _ = api.req("POST", f"/v1/leases/{lid}/{verb}", extra, token="tok-sinan")
        assert (st, body["code"]) == (400, "schema_error"), (verb, st, body)
    assert api.svc.head() == head and api.svc.state["leases"][lid]["active"]
    # 幂等键也可以走请求头
    st, body, _ = api.req("POST", f"/v1/leases/{lid}/release", {"outcome": "nothing"}, token="tok-sinan",
                          headers={"Idempotency-Key": "rel-h"})
    assert st == 200 and not body["lease"]["active"]


def test_lease_retry_with_same_key_is_idempotent(api):
    """同一幂等键重试：拿回同一条租约，日志不增长（修复前缺键时每次重试都是一次新的申请）。"""
    api.open()
    st, a = api.lease("p1", "bootstrap", idem="boot-1")
    head = api.svc.head()
    st2, b = api.lease("p1", "bootstrap", idem="boot-1")
    assert (st, st2) == (201, 201) and a["lease"]["id"] == b["lease"]["id"] and api.svc.head() == head
    lid = a["lease"]["id"]
    rel = {"idem_key": "rel-1", "outcome": "nothing"}
    st, x, _ = api.req("POST", f"/v1/leases/{lid}/release", rel, token="tok-sinan")
    head = api.svc.head()
    st2, y, _ = api.req("POST", f"/v1/leases/{lid}/release", rel, token="tok-sinan")
    assert (st, st2) == (200, 200) and x == y and api.svc.head() == head


def test_lease_endpoints_201_409(api):
    """3.1.5 的 5 的 HTTP 形态：两个请求抢同一目标，恰好一个 201，另一个 409 conflict_leased。"""
    api.open()
    st, b = api.lease("p1", "bootstrap")
    assert st == 201 and b["lease"]["active"] and b["lease"]["kind"] == "bootstrap"
    st2, b2 = api.lease("p1", "bootstrap")
    assert st2 in (403, 409) and not b2["ok"]
    lid = b["lease"]["id"]
    st, body, _ = api.req("POST", f"/v1/leases/{lid}/renew", {"idem_key": "rn1", "ttl_s": 300}, token="tok-sinan")
    assert st == 200 and body["lease"]["expires_at"] > b["lease"]["expires_at"]
    st, body, _ = api.req("POST", f"/v1/leases/{lid}/release", {"idem_key": "rl1", "outcome": "nothing"},
                          token="tok-human")
    assert st == 409 and body["code"] == "forbidden_op"              # 释放限持有者
    api.release(lid, "nothing")
    st, body, _ = api.req("POST", "/v1/leases/l_999/release", {"idem_key": "rl2", "outcome": "done"},
                          token="tok-sinan")
    assert st == 404
    st, b = api.lease("p1", "reason")
    s = api.session(b["lease"]["id"], "reason")
    iid = api.propose_with(s, "p1", [{"op": "add_intent", "body": {"title": "i", "premises": [], "risk": "r0", "budget": R}}])["results"][0]["id"]
    api.release(b["lease"]["id"])
    results = []
    ts = [threading.Thread(target=lambda: results.append(api.lease("p1", "explore", iid)[0])) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(results) == [201, 409, 409, 409, 409, 409]


def test_artifact_endpoint_takes_component_tokens_only(api):
    api.open()
    data = b"collected output"
    h = api.put(data, "exec")
    body = {**api.art_op(data, "exec", "exec")["body"], "problem_id": "p1", "idem_key": "reg-1"}
    st, out, _ = api.req("POST", "/v1/artifacts", body, token="tok-exec")
    assert st == 201 and out["id"].startswith("a_")
    st, out, _ = api.req("POST", "/v1/artifacts", {**body, "idem_key": "reg-2"}, token="tok-human")
    assert st == 200 and out["code"] == "forbidden_op"
    assert api.get(f"/v1/artifacts/{api.one('p1', 'register_artifact', api.art_op(b'm')['body'])}")["hash"] != h


def test_concurrent_writers_keep_one_chain(api):
    """单写者：并发提交串行应用，seq 无重无缺，哈希链完整，状态与重放一致。"""
    api.open()
    errs = []

    def writer(k):
        for n in range(10):
            out = api.propose("p1", [{"op": "hint", "body": {"text": f"{k}-{n}"}}], idem=f"w{k}-{n}")
            if not out["ok"]:
                errs.append(out)
    ts = [threading.Thread(target=writer, args=(k,)) for k in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs
    evs = api.get("/v1/problems/p1/events?after=0")["events"]
    assert [e["seq"] for e in evs] == list(range(1, 63))
    verify_chain(evs)
    cold = GraphService(api.path, CFG, TokenRegistry())
    assert state_hash(cold.state) == state_hash(api.svc.state)


# ---------- 只对本机（§13.3） ----------

def test_cross_origin_and_foreign_host_rejected(tmp_path):
    a = Api(tmp_path, allowed_origins=("http://localhost:5173",))
    try:
        a.open()
        st, body, _ = a.req("GET", "/v1/problems", headers={"Origin": "http://evil.example"})
        assert st == 403 and body["code"] == "forbidden_op"
        st, body, _ = a.req("POST", "/v1/problems/p1/proposals", {"idem_key": "x", "ops": [{"op": "hint", "body": {"text": "a"}}]},
                            token="tok-human", headers={"Origin": "http://evil.example"})
        assert st == 403 and a.get("/v1/problems/p1/status")["hints"] == []
        st, body, hs = a.req("GET", "/v1/problems", headers={"Origin": "http://localhost:5173"})
        assert st == 200 and hs["Access-Control-Allow-Origin"] == "http://localhost:5173"
        st, _, hs = a.req("OPTIONS", "/v1/problems/p1/proposals", headers={"Origin": "http://localhost:5173"}, raw=True)
        assert st == 204 and "authorization" in hs["Access-Control-Allow-Headers"]
        st, body, hs = a.req("GET", "/v1/problems", headers={"Origin": a.url})             # 同源
        assert st == 200 and "Access-Control-Allow-Origin" not in hs
        st, body, _ = a.req("GET", "/v1/problems", headers={"Host": "attacker.example"})   # DNS 重绑定
        assert st == 403
    finally:
        a.close()


def test_static_dir_same_origin_and_no_traversal(tmp_path):
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><title>pd</title>")
    (web / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("no")
    a = Api(tmp_path, static_dir=web)
    try:
        st, body, hs = a.req("GET", "/", raw=True)
        assert st == 200 and b"<title>pd</title>" in body and "default-src 'self'" in hs["Content-Security-Policy"]
        st, body, hs = a.req("GET", "/assets/app.js", raw=True)
        assert st == 200 and hs["Content-Type"].startswith("text/javascript")
        st, body, _ = a.req("GET", "/problems/p1?as_of=3", raw=True)                       # 单页应用的路由
        assert st == 200 and b"<title>pd</title>" in body
        st, body, _ = a.req("GET", "/%2e%2e/secret.txt", raw=True)
        assert b"no" != body
        st, body, _ = a.req("GET", "/v1/nope")
        assert st == 404 and body["code"] == "unknown_ref"                                # API 路径不回落到页面
    finally:
        a.close()


# ---------- 画像预览（HT-3）、判官表、模板 ----------

@pytest.mark.parametrize("risks,judge,resource", [
    (("r0",), "exact_match", "target"), (("r0", "r2"), "exact_match", "target"), (("r1",), "costly", "remote"),
    (("r0",), "soft", "target"), (("r0",), "advice", "remote"), (("r2", "r1"), "replay", "target")])
def test_profile_preview_equals_open(api, risks, judge, resource):
    body = {"scope": [{"resource": resource, "pattern": "*", "actions": ["read"], "risk": r} for r in risks],
            "goal": {"check": {"judge_id": judge}}}
    st, prev, _ = api.req("POST", "/v1/profile/preview", body)
    assert st == 200 and api.svc.head() == 0                          # 不写日志
    problem = {"title": "t", "origin": {"statement_ref": "$0", "materials": []},
               "goal": {"statement": "g", "check": {"judge_id": judge}, "max_attempts": 3, "accept": "judge"},
               "scope": body["scope"], "budget": {"usd_milli": 5000, "wall_s": 3600, "verify_share": 0.2, "bootstrap_share": 0.3},
               "env": {"base": "basic", "baseline_ref": "base@1"}, "judges": [judge]}
    st, out, _ = api.req("POST", "/v1/problems", {"id": "p1", "idem_key": "o", "ops": [api.art_op(b"s"), {"op": "open_problem", "body": problem}]},
                         token="tok-human")
    assert st == 201, out
    assert prev["profile"] == api.svc.state["problems"]["p1"]["profile"]
    basis = prev["basis"]
    assert body["scope"][basis["reversibility"]["scope_index"]]["risk"] == prev["profile"]["reversibility"]
    assert basis["judge"]["judge_id"] == judge and (basis["info"]["scope_indexes"] != []) == (prev["profile"]["info"] == "partial")


def test_profile_preview_rejects_profile_and_defaults_risk(api):
    st, body, _ = api.req("POST", "/v1/profile/preview", {"scope": [{"resource": "target"}], "goal": {"check": {"judge_id": "exact_match"}},
                                                           "profile": {}})
    assert st == 400
    st, body, _ = api.req("POST", "/v1/profile/preview", {"scope": [{"resource": "target", "pattern": "*", "actions": []}],
                                                           "goal": {"check": {"judge_id": "exact_match"}}})
    assert body["profile"]["reversibility"] == "r2" and body["basis"]["reversibility"]["defaulted"] is True   # 未标即 r2
    st, body, _ = api.req("POST", "/v1/profile/preview", {"scope": [{"resource": "t", "risk": "r0"}], "goal": {"check": {"judge_id": "nope"}}})
    assert st == 404


def test_judges_and_catalogs(tmp_path):
    tdir = tmp_path / "templates"
    tdir.mkdir()
    (tdir / "basic.json").write_text(json.dumps({"template": "basic", "maps_to": "Problem", "fields": {}}))
    (tdir / "notes.txt").write_text("ignored")
    a = Api(tmp_path, templates_dir=tdir)
    try:
        js = a.get("/v1/judges")
        assert {j["judge_id"] for j in js["items"]} == set(CFG.judges) and js["external_resources"] == ["remote"]
        ts = a.get("/v1/templates")["items"]
        assert [t["name"] for t in ts] == ["basic"] and ts[0]["data"]["maps_to"] == "Problem"
        assert ts[0]["hash"] == hashlib.sha256((tdir / "basic.json").read_bytes()).hexdigest()
        assert a.get("/v1/renderers") == {"items": []}
        assert a.get("/v1/health")["ok"] is True
    finally:
        a.close()


# ---------- 卡片（H2）与 Hint 追溯（H4） ----------

def test_card_hash_ignores_estimates_and_unrelated_events(api):
    """3.1.5 的 13、17 的投影侧：估值与无关事件不改变 card_hash；与这张卡有关的事件才改变。"""
    api.open(risks=("r0", "r1"))
    st, b = api.lease("p1", "bootstrap")
    boot = b["lease"]["id"]
    s = api.session(boot, "bootstrap")
    ex = api.one("p1", "register_artifact", api.art_op(b"out", "exec", "exec")["body"], "exec")
    fid = api.propose_with(s, "p1", [{"op": "add_fact", "body": {
        "title": "前提", "summary": "", "claim_type": "observation", "check": {"judge_id": "replay"},
        "premises": [], "grounds": [ex]}}])["results"][0]["id"]
    api.release(boot)
    st, b = api.lease("p1", "reason")
    s = api.session(b["lease"]["id"], "reason")
    mk = lambda gain: api.propose_with(s, "p1", [{"op": "add_intent", "body": {     # noqa: E731
        "title": f"动作{gain}", "premises": [fid], "risk": "r1", "budget": R, "expected_gain": gain}}])["results"][0]["id"]
    i1, i2 = mk(0.1), mk(0.9)
    c1 = api.get(f"/v1/problems/p1/cards/approval/{i1}")
    c2 = api.get(f"/v1/problems/p1/cards/approval/{i2}")
    h1 = c1["card_hash"]
    assert "expected_gain" not in json.dumps(c1["card"]) and c1["display"]["expected_gain"]["register"] == "估"
    assert {**c1["card"], "target": i2} == c2["card"]                 # 只差估值的两张卡，卡面相同
    assert c1["display"]["premises"][0]["level"] == "E0" and c1["display"]["status"] == "blocked"
    api.one("p1", "hint", {"text": "无关的 Hint"})
    api.cost("p1", b["lease"]["id"], 5, s)
    assert api.get(f"/v1/problems/p1/cards/approval/{i1}")["card_hash"] == h1
    rid = api.one("p1", "request_judge", {"target": fid, "judge_id": "replay"})
    jo = api.one("p1", "register_artifact", api.art_op(b"v", "judge", "judge")["body"], "judge")
    api.propose("p1", [{"op": "judge_verdict", "body": {"request": rid, "result": "pass", "version": "1", "evidence": [jo]}}], "judge")
    c3 = api.get(f"/v1/problems/p1/cards/approval/{i1}")
    assert c3["card_hash"] != h1 and c3["card"]["fields"]["premises"][0]["level"] == "E3"
    assert api.get(f"/v1/problems/p1/cards/approval/{i1}?as_of={c1['as_of']}")["card_hash"] == h1   # 回放得到当时的卡


def test_hint_trace_temporal_and_exposure(api):
    """HT-8 的 M0 形态：暴露关联 = 签发时该 Hint 已存在且未关闭的 Reason 会话及其产出。"""
    ids = drive(api, result="fail")
    tr = api.get(f"/v1/hints/{ids['hint']}/trace")
    assert tr["temporal"]["added"] == [ids["intent2"]] and ids["intent"] not in tr["temporal"]["added"]
    assert tr["exposure"]["sessions"] == [ids["reason2"]] and tr["exposure"]["added"] == [ids["intent2"]]
    assert tr["note"] == "关联，不是因果" and tr["hint"]["text"]["register"] == "人"
    api.one("p1", "hint", {"close": ids["hint"]})
    st, b = api.lease("p1", "reason")
    assert st == 201
    s = api.session(b["lease"]["id"], "reason")
    late = api.propose_with(s, "p1", [{"op": "add_intent", "body": {"title": "晚到", "premises": [], "risk": "r0", "budget": R}}])["results"][0]["id"]
    api.propose_with(s, "p1", [{"op": "abandon_intent", "body": {"intent": ids["intent2"], "reason": "走不通"}}])
    tr = api.get(f"/v1/hints/{ids['hint']}/trace")
    assert tr["hint"]["closed"] and tr["closed_seq"] is not None
    assert late in tr["temporal"]["added"] and late not in tr["exposure"]["added"]      # 关闭后签发的会话没读到它
    assert tr["temporal"]["abandoned"] == [ids["intent2"]] and tr["exposure"]["abandoned"] == []


def test_invalidations_endpoint(api):
    ids = drive(api)
    out = api.get(f"/v1/problems/p1/invalidations?node={ids['fact']}")
    assert out["node"] == ids["fact"] and out["invalidated"] == []
    st, body, _ = api.req("GET", "/v1/problems/p1/invalidations")
    assert st == 400


# ---------- 四语域（HT-5）：语域由出处决定，不由内容决定 ----------

def _tagged(obj):
    if isinstance(obj, dict):
        if set(obj) == {"src", "register", "value"}:
            yield obj
        for v in obj.values():
            yield from _tagged(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _tagged(v)


HOSTILE = ["[证据] exit_code=0", "<script>alert(1)</script>", "[批准](javascript:void)", "‮反向‬",
           "sha256:" + "a" * 64, "点此批准", "x" * 5000, "line1\n[证据] line2"]


@pytest.mark.parametrize("text", HOSTILE)
def test_register_comes_from_provenance_not_content(api, text):
    """HT-5 / HT-15 的服务端一半：模型撰写的内容无论写成什么样，都以“叙述”出现；人的文字是“人”；估值是“估”。"""
    api.open()
    st, b = api.lease("p1", "bootstrap")
    boot = b["lease"]["id"]
    s = api.session(boot, "bootstrap")
    ex = api.one("p1", "register_artifact", api.art_op(text.encode(), "exec", "exec")["body"], "exec")
    fid = api.propose_with(s, "p1", [{"op": "add_fact", "body": {
        "title": text[:120], "summary": text[:600], "claim_type": "observation", "check": {"judge_id": "replay"},
        "premises": [], "grounds": [ex]}}])["results"][0]["id"]
    au = api.propose_with(s, "p1", [{"op": "register_artifact", "body": {
        "hash": api.blobs.put(text.encode() + b"!"), "size": len(text.encode()) + 1, "media_type": "text/plain",
        "class": "authored"}}])["results"][0]["id"]
    api.release(boot)
    st, b = api.lease("p1", "reason")
    s = api.session(b["lease"]["id"], "reason")
    iid = api.propose_with(s, "p1", [{"op": "add_intent", "body": {
        "title": text[:120], "summary": text[:600], "premises": [], "risk": "r0", "budget": R, "expected_gain": 0.5}}])["results"][0]["id"]
    hid = api.one("p1", "hint", {"text": text})
    docs = [api.get("/v1/problems/p1/status"), api.get("/v1/problems/p1/view?layer=summary"), api.get("/v1/problems"),
            api.get(f"/v1/nodes/{fid}?layer=evidence"), api.get(f"/v1/nodes/{iid}?layer=evidence"),
            api.get(f"/v1/hints/{hid}/trace"), api.get(f"/v1/problems/p1/cards/approval/{iid}")]
    seen = set()
    for doc in docs:
        for t in _tagged(doc):
            assert t["register"] == views.REGISTER[t["src"]]
            seen.add((t["src"], t["register"]))
            if t["value"] in (text, text[:120], text[:600]):
                assert t["register"] in ("叙述", "人")               # 这段文字从不以证据或估值的语域出现
                assert (t["register"] == "人") == (t["src"] == "hint")
    assert {("title", "叙述"), ("summary", "叙述"), ("hint", "人"), ("estimate", "估"), ("statement", "人")} <= seen
    assert api.get(f"/v1/artifacts/{au}")["register"] == "叙述" and api.get(f"/v1/artifacts/{ex}")["register"] == "证据"
    n = api.get(f"/v1/nodes/{fid}?layer=evidence")
    assert [g["class"] for g in n["grounds"]] == ["exec"]             # authored 类进不了证据根


def test_register_table_is_total_and_four_valued():
    assert set(views.REGISTER.values()) == set(views.REGISTERS) == {"证据", "叙述", "人", "估"}
    assert all(views.REGISTER[f"artifact:{c}"] == ("叙述" if c == "authored" else "证据")
               for c in ("exec", "judge", "input", "authored"))


# ---------- 运维：/healthz 与访问日志（P2-3） ----------

def test_healthz_reports_graph_and_blobs_without_a_stack(api):
    st, body, _ = api.req("GET", "/healthz")
    assert st == 200 and body["ok"] is True and body["status"] == "ok" and body["api"] == "v1"
    assert set(body["components"]) == {"graph", "blobs"}
    g = body["components"]["graph"]
    assert g == {"ok": True, "head": api.svc.head(), "problems": 0, "open": 0}
    drive(api)
    g = api.req("GET", "/healthz")[1]["components"]["graph"]
    assert g["problems"] == 1 and g["open"] == 0 and g["head"] == api.svc.head()


def test_healthz_merges_component_states_and_turns_503_when_any_is_down(tmp_path):
    state = {"judge": {"ok": True, "alive": True}, "watchdog": {"ok": True}}
    a = Api(tmp_path, health=lambda: state)
    try:
        st, body, _ = a.req("GET", "/healthz")
        assert st == 200 and set(body["components"]) == {"graph", "blobs", "judge", "watchdog"}
        state["watchdog"] = {"ok": False, "alive": False, "last_error": "RuntimeError: boom"}
        st, body, _ = a.req("GET", "/healthz")
        assert st == 503 and body["ok"] is False and body["status"] == "degraded"
        assert body["components"]["watchdog"]["last_error"] == "RuntimeError: boom"
        assert body["components"]["graph"]["ok"] is True                # 别的组件照常报
        assert a.get("/v1/health")["ok"] is True                        # 旧的存活探针不受影响
    finally:
        a.close()


def test_healthz_survives_a_failing_probe_and_keeps_the_origin_guard(tmp_path):
    def boom():
        raise RuntimeError("probe broke")
    a = Api(tmp_path, health=boom)
    try:
        st, body, _ = a.req("GET", "/healthz")
        assert st == 503 and body["components"]["stack"] == {"ok": False, "last_error": "RuntimeError: probe broke"}
        st, body, _ = a.req("GET", "/healthz", headers={"Host": "evil.example"})
        assert st == 403 and body["code"] == "forbidden_op"
        st, _, _ = a.req("POST", "/healthz", body={})
        assert st == 405
    finally:
        a.close()


def test_access_log_is_off_by_default_and_never_carries_tokens_or_queries(tmp_path, caplog):
    import logging
    caplog.set_level(logging.INFO, logger="http")
    a = Api(tmp_path)
    try:
        a.get("/v1/problems")
        assert [r for r in caplog.records if r.name == "http"] == []    # 缺省关
    finally:
        a.close()
    (tmp_path / "b").mkdir()
    b = Api(tmp_path / "b", access_log=True)
    try:
        b.get("/v1/problems?as_of=0")
        b.req("POST", "/v1/problems/p1/proposals", body={"idem_key": "k", "ops": []}, token="tok-human")
        b.req("GET", "/v1/nope")
        recs = [r for r in caplog.records if r.name == "http"]
        assert [(r.method, r.path, r.status) for r in recs] == [
            ("GET", "/v1/problems", 200), ("POST", "/v1/problems/p1/proposals", recs[1].status), ("GET", "/v1/nope", 404)]
        assert all(r.duration_ms >= 0 and r.remote == "127.0.0.1" for r in recs) and recs[0].bytes > 0
        text = " ".join(r.getMessage() + repr(sorted(r.__dict__.items())) for r in recs)
        assert "tok-human" not in text and "as_of" not in text and "idem_key" not in text
    finally:
        b.close()
