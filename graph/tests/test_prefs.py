"""任务级模型偏好（宪章 03 §3.1、地图 Q12/Q14、AC0.5）：open_problem 的可选 prefs.model 只能取已登记的档案名。"""

import dataclasses

from conftest import CFG, HUMAN, Kernel

from paoding_graph import views

WITH = dataclasses.replace(CFG, model_profiles=frozenset({"default", "light"}))


def body(k, pid="p1", **extra):
    st = k.art(pid, "input", b"statement " + pid.encode())
    return {
        "title": "t",
        "origin": {"statement_ref": st, "materials": []},
        "goal": {"statement": "g", "check": {"judge_id": "exact_match"}, "max_attempts": 3, "accept": "judge"},
        "scope": [{"resource": "target", "pattern": "*", "actions": ["read"], "risk": "r0"}],
        "budget": {"usd_milli": 5000, "wall_s": 3600, "verify_share": 0.2, "bootstrap_share": 0.3},
        "env": {"base": "basic", "baseline_ref": "base@1"},
        "judges": ["exact_match"],
        **extra,
    }


def test_registered_profile_is_recorded_and_shown():
    k = Kernel(WITH)
    assert k.submit(HUMAN, "p1", "open_problem", body(k, prefs={"model": "light"})) == "ok"
    assert k.events[-1]["body"]["prefs"] == {"model": "light"}
    assert k.state["problems"]["p1"]["prefs"] == {"model": "light"}
    assert views.status(k.state, "p1")["problem"]["prefs"] == {"model": "light"}


def test_only_registered_profiles_and_only_a_name():
    k = Kernel(WITH)
    assert k.submit(HUMAN, "p1", "open_problem", body(k, prefs={"model": "custom"})) == "unknown_ref"
    assert k.submit(HUMAN, "p1", "open_problem", body(k, prefs={"endpoint": "https://x"})) == "schema_error"
    assert k.submit(HUMAN, "p1", "open_problem", body(k, prefs={"model": "light", "key": "sk"})) == "schema_error"
    assert k.submit(HUMAN, "p1", "open_problem", body(k, prefs={})) == "ok"  # 空偏好即按角色路由


def test_without_settings_layer_no_profile_is_accepted():
    k = Kernel()
    assert k.submit(HUMAN, "p1", "open_problem", body(k, prefs={"model": "default"})) == "unknown_ref"


def test_absent_prefs_leave_event_and_view_unchanged():
    k = Kernel(WITH)
    assert k.submit(HUMAN, "p1", "open_problem", body(k)) == "ok"
    assert "prefs" not in k.events[-1]["body"]
    assert "prefs" not in views.status(k.state, "p1")["problem"]
