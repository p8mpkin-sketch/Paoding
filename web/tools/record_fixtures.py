"""用真图服务（后端分支的 http_rig）录一份端点应答，供前端的契约测试使用。"""
import json, pathlib, sys, tempfile
sys.path.insert(0, "graph/tests")
from http_rig import Api, drive, R

out = pathlib.Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
api = Api(pathlib.Path(tempfile.mkdtemp()))
ids = drive(api, "p1")
# 第二题：留一条待审批的 Intent（needs_scope）与一条活跃 Hint，不关题
api.open("p2", risks=("r0",))
st, b = api.lease("p2", "bootstrap"); boot = b["lease"]["id"]; s = api.session(boot, "bootstrap")
ex = api.one("p2", "register_artifact", api.art_op(b"out\n", "exec", "exec")["body"], "exec")
o = api.propose_with(s, "p2", [{"op": "add_fact", "body": {"title": "入口可读", "summary": "读到了入口", "claim_type": "observation", "check": {"judge_id": "replay", "expect": {"exit_code": 0}}, "premises": [], "grounds": [ex]}},
                              {"op": "add_fact", "body": {"title": "另有一处入口", "summary": "由上一条推出", "claim_type": "inference", "premises": ["$0"], "grounds": []}}])
assert o["ok"], o
f = o["results"][0]["id"]
api.cost("p2", boot, 30, s); api.release(boot, "done")
st, b = api.lease("p2", "reason"); rl = b["lease"]["id"]; s = api.session(rl, "reason")
o = api.propose_with(s, "p2", [{"op": "add_intent", "body": {"title": "扩大范围后再读", "summary": "需要第二个目标", "premises": [f], "risk": "r1", "budget": R, "expected_gain": 0.4,
     "needs_scope": [{"resource": "target", "pattern": "second", "actions": ["read"], "risk": "r1"}]}}])
assert o["ok"], o
i2 = o["results"][0]["id"]
api.release(rl, "done")
h2 = api.one("p2", "hint", {"text": "第二个目标更可能", "about": i2})

def save(name, path, **kw):
    st, body, _ = api.req("GET", path, **kw)
    (out / f"{name}.json").write_text(json.dumps({"path": path, "status": st, "body": body}, ensure_ascii=False, indent=1), encoding="utf-8")

save("health", "/v1/health"); save("problems", "/v1/problems"); save("judges", "/v1/judges"); save("templates", "/v1/templates")
for pid in ("p1", "p2"):
    for v in ("status", "budget", "work"):
        save(f"{pid}-{v}", f"/v1/problems/{pid}/{v}")
    save(f"{pid}-view", f"/v1/problems/{pid}/view?layer=summary")
    save(f"{pid}-events", f"/v1/problems/{pid}/events?after=0")
    save(f"{pid}-ticks", f"/v1/problems/{pid}/ticks")
    save(f"{pid}-snapshot", f"/v1/problems/{pid}/snapshot?state_hash=1")
    save(f"{pid}-closeout", f"/v1/problems/{pid}/cards/closeout/{pid}")
save("p1-status-asof", f"/v1/problems/p1/status?as_of={ids['verdict_seq']-3}&state_hash=1")
save("p1-fact-evidence", f"/v1/nodes/{ids['fact']}?layer=evidence")
save("p1-intent-evidence", f"/v1/nodes/{ids['intent']}?layer=evidence")
save("p1-hint", f"/v1/nodes/{ids['hint']}")
save("p1-hint-trace", f"/v1/hints/{ids['hint']}/trace")
save("p1-artifact-exec", f"/v1/artifacts/{ids['exec']}")
save("p1-artifact-judge", f"/v1/artifacts/{ids['judge_out']}")
save("p1-artifact-candidate", f"/v1/artifacts/{ids['candidate']}")
save("p2-approval", f"/v1/problems/p2/cards/approval/{i2}")
save("p2-extension", f"/v1/problems/p2/cards/extension/p2")
save("p2-hint-trace", f"/v1/hints/{h2}/trace")
save("missing", "/v1/problems/nope/status")
st, body, _ = api.req("POST", "/v1/profile/preview", {"scope": [{"resource": "target", "pattern": "*", "actions": ["read"], "risk": "r1"}, {"resource": "x", "pattern": "*", "actions": ["w"]}], "goal": {"check": {"judge_id": "exact_match"}}})
(out / "profile-preview.json").write_text(json.dumps({"status": st, "body": body}, ensure_ascii=False, indent=1), encoding="utf-8")
# 被拒的批次长什么样
st, body, _ = api.req("POST", "/v1/problems/p2/proposals", {"idem_key": "bad1", "ops": [{"op": "approve", "body": {"intent": i2, "decision": "deny"}}]}, token="tok-human")
(out / "proposal-rejected.json").write_text(json.dumps({"status": st, "body": body}, ensure_ascii=False, indent=1), encoding="utf-8")
st, body, _ = api.req("POST", "/v1/problems/p2/proposals", {"idem_key": "bad2", "ops": [{"op": "pause", "body": {}}]}, token="tok-human")
(out / "proposal-unknown-op.json").write_text(json.dumps({"status": st, "body": body}, ensure_ascii=False, indent=1), encoding="utf-8")
st, body, _ = api.req("POST", "/v1/problems/p2/proposals", {"idem_key": "x", "ops": [{"op": "hint", "body": {"text": "t"}}]})
(out / "proposal-no-token.json").write_text(json.dumps({"status": st, "body": body}, ensure_ascii=False, indent=1), encoding="utf-8")
api.close()
print(json.dumps(ids))
