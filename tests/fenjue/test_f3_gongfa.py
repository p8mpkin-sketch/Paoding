"""焚决 F3（FJ5，焚决唯一一次体质修炼）：功法摘要与会话形态进事件账。

- open_problem 多一个可选 gongfa {jie, digest}、lease 多一个可选 form，都由 validate 从配置抄入，提交体里给的不认；
- apply 原样存，不进等级、消费门与画像；
- 配置不给（今天所有既有部署与测试台的缺省）时事件体与 F3 之前逐字节相同；
- 新旧事件混放在同一份日志里（R3）：从头重放与在线状态相同，旧题读作第 0 阶、旧租约按席位推形态。
"""

import dataclasses
import hashlib

from paoding_fenjue.contract import form_of, gongfa, gongfa_of, kernel_config
from paoding_graph import views, wire_schema
from paoding_graph.contract import Config, GraphService, TokenRegistry, replay, state_hash
from paoding_graph.reducer import apply, empty_state

JUDGES = {"exact_match": {"version": "1", "grade": "decisive", "kind": "builtin", "max_cost": 0.0}}


def service(tmp_path, **cfg):
    reg = TokenRegistry()
    reg.issue({"kind": "human", "id": "cz"}, "tok-human")
    reg.issue({"kind": "sinan", "id": "sn1"}, "tok-sinan")
    t = [1000]

    def tick():
        t[0] += 1
        return t[0]

    return GraphService(tmp_path / "g.sqlite", Config(judges=JUDGES, **cfg), reg, tick)


def open_problem(svc, pid, extra=None):
    st = f"statement {pid}".encode()
    body = {
        "title": "t",
        "origin": {"statement_ref": "$0", "materials": []},
        "goal": {"statement": "g", "check": {"judge_id": "exact_match"}, "max_attempts": 3, "accept": "judge"},
        "scope": [{"resource": "target", "pattern": "*", "actions": ["read"], "risk": "r0"}],
        "budget": {"usd_milli": 5000, "wall_s": 3600, "verify_share": 0.2, "bootstrap_share": 0.3},
        "env": {"base": "basic", "baseline_ref": "base@1"},
        "judges": ["exact_match"],
        **(extra or {}),
    }
    art = {"hash": hashlib.sha256(st).hexdigest(), "size": len(st), "media_type": "text/plain", "class": "input"}
    ops = [{"op": "register_artifact", "body": art}, {"op": "open_problem", "body": body}]
    return svc.submit("tok-human", pid, f"open-{pid}", ops)


def lease(svc, pid, extra=None):
    body = {"kind": "bootstrap", "holder": "sn1", "reserve": {"usd_milli": 500, "wall_s": 600}, "ttl_s": 600}
    return svc.submit("tok-sinan", pid, f"lease-{pid}", [{"op": "lease", "body": {**body, **(extra or {})}}])


def body_of(svc, pid, kind):
    return next(e["body"] for e in svc.events(pid) if e["kind"] == kind)


def test_without_config_the_events_are_what_they_were(tmp_path):
    svc = service(tmp_path)
    assert open_problem(svc, "p1")["ok"] and lease(svc, "p1")["ok"]
    assert "gongfa" not in body_of(svc, "p1", "open_problem")
    assert "form" not in body_of(svc, "p1", "lease")
    p = svc.state["problems"]["p1"]
    assert gongfa_of(p) == {"jie": 0, "digest": None}  # 读端：第 0 阶（旧法）
    assert form_of(next(iter(svc.state["leases"].values()))) == "h1.triad"  # 读端按席位推
    assert "gongfa" not in views.status(svc.state, "p1")["problem"]


def test_config_is_stamped_on_open_and_lease_and_shown_in_the_views(tmp_path):
    kc = kernel_config()
    svc = service(tmp_path, **kc)
    assert open_problem(svc, "p1")["ok"] and lease(svc, "p1")["ok"]
    g = gongfa()
    assert body_of(svc, "p1", "open_problem")["gongfa"] == {"jie": g["jie"], "digest": g["digest"]}
    assert body_of(svc, "p1", "lease")["form"] == "h1.triad@1"
    p = svc.state["problems"]["p1"]
    assert gongfa_of(p) == {"jie": g["jie"], "digest": g["digest"]}
    st = views.status(svc.state, "p1")
    assert st["problem"]["gongfa"] == {"jie": g["jie"], "digest": g["digest"]}
    env = {"as_of": svc.state["seq"], "head": svc.state["seq"], "view_hash": "0" * 64}
    assert wire_schema.validate("StatusView", {**env, **st}) == []
    # 不进等级、消费门与画像：同一道题有没有功法，画像与等级一样
    (tmp_path / "plain").mkdir()
    plain = service(tmp_path / "plain")
    assert open_problem(plain, "p1")["ok"]
    assert plain.state["problems"]["p1"]["profile"] == p["profile"]
    bare = views.status(plain.state, "p1")
    # 等级、预算、Intent 状态……都一样（plain 没领租约，租约一栏不比）
    assert {**bare, "problem": None, "leases": None} == {**st, "problem": None, "leases": None}
    assert {k: v for k, v in st["problem"].items() if k not in ("gongfa", "now_ts")} == {
        k: v for k, v in bare["problem"].items() if k != "now_ts"
    }


def test_submitters_cannot_choose_the_gongfa_or_the_form(tmp_path):
    svc = service(tmp_path)
    out = open_problem(svc, "p1", {"gongfa": {"jie": 9, "digest": "f" * 64}})
    assert not out["ok"] and out["results"][-1]["code"] == "schema_error"
    assert open_problem(svc, "p2")["ok"] and lease(svc, "p2", {"form": "h1.solo@9"})["ok"]
    assert "form" not in body_of(svc, "p2", "lease")  # 提交体里的不认，配置没给就不写


def test_old_and_new_events_replay_together(tmp_path):
    """R3：同一份日志里先有焚决之前的题，再有焚决之后的题。"""
    svc = service(tmp_path)
    assert open_problem(svc, "old")["ok"] and lease(svc, "old")["ok"]
    before = views.status(svc.state, "old")
    svc.cfg = dataclasses.replace(svc.cfg, **kernel_config())  # 组装根换上功法（与设置层热更新同一做法）
    assert open_problem(svc, "new")["ok"] and lease(svc, "new")["ok"]
    evs = svc.events()
    again = replay(evs, apply, empty_state())
    assert state_hash(again) == state_hash(svc.state)
    assert (
        gongfa_of(again["problems"]["old"])["jie"] == 0
        and gongfa_of(again["problems"]["new"])["jie"] == gongfa()["jie"]
    )
    forms = {l["problem_id"]: l.get("form") for l in again["leases"].values()}
    assert forms == {"old": None, "new": "h1.triad@1"}
    after = views.status(again, "old")
    assert {k: v for k, v in after.items() if k != "problem"} == {k: v for k, v in before.items() if k != "problem"}
    assert {k: v for k, v in after["problem"].items() if k != "now_ts"} == {
        k: v for k, v in before["problem"].items() if k != "now_ts"
    }
