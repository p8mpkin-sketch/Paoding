"""线格式的 schema 与真应答一致（HMI §14；P2-1 第 4 条）。

前端的 web/src/api/types.ts 由 wire_schema 生成；这里用同一份 schema 严格校验图服务的真应答：
缺键、类型不符、多出 schema 没列的键都算失败。于是 schema、服务、前端类型三方一致。
"""

import importlib.util
import json
from pathlib import Path

import pytest
from http_rig import Api, R, drive

from paoding_graph import wire_schema as ws

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def api(tmp_path):
    a = Api(tmp_path)
    yield a
    a.close()


def ok(name, value):
    errs = ws.validate(name, value)
    assert errs == [], f"{name}: {errs[:8]}"


def test_every_read_endpoint_matches_the_schema(api):
    ids = drive(api)
    api.open("p2", risks=("r0", "r1"))
    pid = "p1"
    for seq in (api.get(f"/v1/problems/{pid}/status")["problem"]["opened_seq"], None):
        q = f"?as_of={seq}" if seq else ""
        ok("StatusView", api.get(f"/v1/problems/{pid}/status{q}"))
        ok("GraphView", api.get(f"/v1/problems/{pid}/view{q}"))
        ok("BudgetResponse", api.get(f"/v1/problems/{pid}/budget{q}"))
        ok("WorkView", api.get(f"/v1/problems/{pid}/work{q}"))
        ok("SnapshotResponse", api.get(f"/v1/problems/{pid}/snapshot{q}{'&' if q else '?'}state_hash=1"))
        ok("TicksResponse", api.get(f"/v1/problems/{pid}/ticks{q}"))
    ok("SnapshotResponse", api.get(f"/v1/problems/{pid}/snapshot?parts=budget,work"))
    ok("ProblemsView", api.get("/v1/problems"))
    ok("EventsResponse", api.get(f"/v1/problems/{pid}/events"))
    for e in api.get(f"/v1/problems/{pid}/events")["events"]:
        ok("Event", e)
    for nid in (ids["fact"], ids["intent"], ids["hint"]):
        ok("NodeEvidence", api.get(f"/v1/nodes/{nid}?layer=evidence"))
    ok(
        "FactNode",
        {
            k: v
            for k, v in api.get(f"/v1/nodes/{ids['fact']}").items()
            if k not in ("as_of", "head", "view_hash", "state_hash", "problem_id")
        },
    )
    for aid in (ids["exec"], ids["candidate"], ids["judge_out"]):
        ok("ArtifactView", api.get(f"/v1/artifacts/{aid}"))
    ok("HintTrace", api.get(f"/v1/hints/{ids['hint']}/trace"))
    ok("JudgesResponse", api.get("/v1/judges"))
    ok("Catalog", api.get("/v1/templates"))
    ok("HealthResponse", api.get("/v1/health"))
    st, prev, _ = api.req(
        "POST",
        "/v1/profile/preview",
        {
            "scope": [{"resource": "target", "pattern": "*", "actions": ["read"], "risk": "r1"}],
            "goal": {"check": {"judge_id": "exact_match"}},
        },
    )
    assert st == 200
    ok("ProfilePreview", prev)


def test_cards_match_the_schema(api):
    ids = drive(api)
    card = api.get(f"/v1/problems/p1/cards/approval/{ids['intent']}")
    ok("CardResponse", card)
    ok("ApprovalFields", card["card"]["fields"])
    ok("ApprovalDisplay", card["display"])


def test_write_answers_and_errors_match_the_schema(api):
    api.open()
    out = api.propose("p1", [{"op": "hint", "body": {"text": "看一眼"}}])
    ok("ProposalResponse", out)
    bad = api.propose("p1", [{"op": "approve", "body": {"intent": "nope"}}])
    ok("ProposalResponse", bad)
    st, body, _ = api.req("GET", "/v1/nodes/nope")
    assert st == 404
    ok("ErrorBody", body)
    st, b = api.lease("p1", "bootstrap", reserve=R)
    assert st == 201


def test_the_open_problem_body_the_tests_use_matches_problem_input(api):
    """ProblemInput 是请求方向：拿测试实际提交的 open_problem 事件体对一遍。"""
    api.open()
    body = next(e["body"] for e in api.get("/v1/problems/p1/events")["events"] if e["kind"] == "open_problem")
    added = {"id", "profile", "judge_snapshot"}  # 内核写日志时补上的，提交方不给
    ok("ProblemInput", {k: v for k, v in body.items() if k not in added})


def test_validator_catches_extra_missing_and_wrong_keys():
    good = {"as_of": 1, "parts_hash": {"status": "a", "view": "b", "budget": "c", "work": "d"}}
    assert ws.validate("ViewFrame", good) == []
    assert ws.validate("ViewFrame", {**good, "extra": 1}) != []
    assert ws.validate("ViewFrame", {"as_of": 1}) != []
    assert ws.validate("ViewFrame", {**good, "as_of": "1"}) != []
    assert ws.validate("ViewFrame", {**good, "as_of": True}) != []
    assert ws.validate("ViewFrame", {**good, "extra": 1}, strict=False) == []
    t = {"src": "human", "register": "人", "value": "x"}
    assert ws.validate("Tagged", t) == [] and ws.validate("Tagged", {**t, "register": "别的"}) != []
    ok_res = {"ok": True, "id": None, "seq": 3}
    assert ws.validate("OpResult", ok_res) == [] and ws.validate("OpResult", {**ok_res, "ok": 1}) != []


def test_schema_is_plain_json_and_every_ref_resolves():
    text = json.dumps(ws.SCHEMA, ensure_ascii=False)
    refs = {r.rsplit("/", 1)[1] for r in __import__("re").findall(r'"\$ref": "([^"]+)"', text)}
    assert refs <= set(ws.D)


def test_generated_types_are_up_to_date():
    """与 CI 的 `scripts/gen-types.py --check` 同一件事，放进测试里让本地也能发现忘了重新生成。"""
    spec = importlib.util.spec_from_file_location("gen_types", ROOT / "scripts" / "gen-types.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert (ROOT / "web" / "src" / "api" / "types.ts").read_text(encoding="utf-8") == gen.render()


def test_scope_card_and_its_ticks_match_the_schema(api):
    import dataclasses

    api.svc.cfg = dataclasses.replace(api.svc.cfg, grants_runtime=True, external_resources=frozenset({"net"}))
    api.open()
    rule = {"resource": "net", "pattern": "q7.lab:8443", "actions": ["connect"]}
    rid = api.one("p1", "request_scope", {"rules": [rule], "why": "读接口"})
    card = api.get(f"/v1/problems/p1/cards/scope/{rid}")
    ok("CardResponse", card)
    ok("ScopeCardFields", card["card"]["fields"])
    ok("ScopeDisplay", card["display"])
    assert card["display"]["profile"]["after"]["info"] == "partial"  # 端点带上了图服务的配置
    seen = {"seq": card["as_of"], "card_hash": card["card_hash"]}
    api.one("p1", "grant_scope", {"request": rid, "decision": "approve", "seen": seen, "risk": ["r2"]})
    ok("ScopeDisplay", api.get(f"/v1/problems/p1/cards/scope/{rid}")["display"])
    ticks = api.get("/v1/problems/p1/ticks")
    ok("TicksResponse", ticks)
    [t] = [x for x in ticks["ticks"] if x["kind"] == "grant_scope"]
    assert t["decision"] == "approve" and "via" not in t


def test_status_with_granted_and_revoked_rules_matches_the_schema(api):
    import dataclasses

    api.svc.cfg = dataclasses.replace(api.svc.cfg, grants_runtime=True, external_resources=frozenset({"net"}))
    api.open()
    rule = {"resource": "net", "pattern": "q7.lab:8443", "actions": ["connect"]}
    rid = api.one("p1", "request_scope", {"rules": [rule], "why": "读接口"})
    card = api.get(f"/v1/problems/p1/cards/scope/{rid}")
    api.one(
        "p1",
        "grant_scope",
        {"request": rid, "decision": "approve", "seen": {"seq": card["as_of"], "card_hash": card["card_hash"]}},
    )
    api.one("p1", "revoke_scope", {"rule": 1, "reason": "用完了"})
    st = api.get("/v1/problems/p1/status")
    ok("StatusView", st)
    assert st["problem"]["scope"][1]["revoked"] > st["problem"]["scope"][1]["granted"]["seq"]
