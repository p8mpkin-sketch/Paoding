"""试算暴露的三个引擎问题（落位预检 / 产物登记自愈 / 尝试之间的反馈与耗尽终局）的回归。

红线：内核与全部验证器零改动。这里的测试只证明提议侧与重试侧：预检用的就是现行验证器（单一事实源）；登记被拒
会按原因重产再登记（有上限，写明重试史）；会话崩了不会原样重来、重试耗尽一定有一次 blocked 交付。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "engine_fixtures"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cases  # noqa: E402
from test_engine_kernel import ByKey, Host, brief_for  # noqa: E402
from test_engine_phase2 import _cand, _essence, _organ  # noqa: E402

from paoding_fenjue import shapes  # noqa: E402
from paoding_fenjue.engine import checks, kernel, pills, ruwei  # noqa: E402
from paoding_fenjue.engine.dan import Reply  # noqa: E402
from paoding_fenjue.engine.run import Engine  # noqa: E402

# ---------------------------------------------------------------- 修复一：落位预检


# trial-b-2 里让引擎崩掉的提议的形状：params.forms 的值写成了形态编号（字符串），工具另写在 params.tools 里
B2_PROPOSAL = {
    "atoms": [{"atom": "session.prompt", "params": {"prompt": {"layers": ["stable"]}}, "emergent": True}],
    "fire": {
        "id": "h1.layered",
        "seats": ["solve", "verify"],
        "params": {
            "forms": {"solve": "h1.solo@2", "verify": "h1.review@1"},
            "tools": {"solve": ["exec", "show", "deliver"], "verify": ["exec", "show", "review"]},
        },
        "organ": _organ(),
    },
}


def test_trial_b2_proposal_no_longer_crashes_and_the_error_says_what_to_write():
    assert ruwei._tool_ports(B2_PROPOSAL["fire"]["params"]) == set()  # 原来是 AttributeError: 'str' has no 'get'
    sk, advice = ruwei.precheck(_cand("H1"), _essence(), B2_PROPOSAL)
    shape = [a for a in advice if "forms.solve 须是形态对象" in a["problem"]]
    assert shape and shape[0]["rule"] == "shape"
    assert "tools" in shape[0]["fix"] and "h1.solo" in shape[0]["fix"]  # 现行形态的写法，不是空话
    assert len(sk.problems) == len(advice)


@pytest.mark.parametrize(
    "bad",
    [
        {"atoms": "session.prompt"},
        {"atoms": ["session.prompt"]},
        {"atoms": [{"atom": "session.end", "mechanism_steps": 3}], "fire": {"id": "h1.x", "seats": ["solve"]}},
        {"atoms": [{"atom": "session.end"}], "fire": "h1.x"},
        {"atoms": [{"atom": "session.end"}], "fire": {"id": "h1.x", "seats": "solve", "assets": {"a": 1}}},
        {"atoms": [{"atom": "session.end"}], "fire": {"id": "h1.x", "seats": ["solve"], "params": ["tools"]}},
        {"atoms": [{"atom": "session.end"}], "fire": {"id": "h1.x", "seats": ["solve"], "params": {"forms": ["x"]}}},
        {"atoms": [{"atom": "session.end"}], "fire": {"id": "h1.x", "seats": ["solve"]}, "group": "H2"},
        {"atoms": [{"atom": "session.end"}], "fire": {"id": "h1.x", "seats": ["solve"]}, "group": ["H2"]},
        {"atoms": [{"atom": "session.end"}], "fire": {"id": "h1.x", "seats": ["solve"]}, "resolutions": "replace"},
        {"atoms": [{"atom": "session.end"}], "fire": {"id": "h1.x", "seats": ["solve"]}, "depends_on": "C2"},
        {"atoms": [{"atom": "session.end"}], "fire": {"id": "h1.x", "seats": ["solve"], "params": {
            "forms": {"solve": {"tools": "deliver"}}}}},
    ],
)  # fmt: skip
def test_any_wrong_shape_becomes_a_problem_never_a_crash(bad):
    sk, advice = ruwei.precheck(_cand("H1"), _essence(), bad)
    assert sk.problems and all(a["fix"] for a in advice)


# 校验器各条的原文（cz 的单子里逐条摘出来的）→ 预检给出的是针对性的改法，不是通用提示
QUOTED = [
    ("席位 verify 不能提交 deliver（经脉越过席位上限）", "seat_rule", "review"),
    ("席位 solve 不能提交 review（经脉越过席位上限）", "seat_rule", "deliver"),
    ("清单 id 'h2.plan_gate' 要以 h2. 开头、只用小写字母数字与连字符", "id_rule", "h2.<"),
    ("h3.base@2 的 tool.grant 是semantic冲突，不能用 coexist 化解", "conflict_rule", "replace"),
    ("H1 的行为有变（原子 session.end），要一团火组成员", "group_rule", "group"),
    ("H1 上要同时替换 ['h1.review', 'h1.solo']：一团火只能顶替一团", "replace_rule", "h1.solo"),
    ("火组成员 H2 上没有任何决策原子：只读的写进兼及火位", "group_rule", "兼及火位"),
]


@pytest.mark.parametrize(("msg", "rule", "must"), QUOTED)
def test_each_quoted_validator_message_gets_a_specific_fix(msg, rule, must):
    a = ruwei.explain(msg)
    assert a["problem"] == msg and a["rule"] == rule and must in a["fix"]


def test_precheck_is_the_validator_not_a_second_copy():
    """预检的错误 = 入位校验（skeleton）的错误，一条不多一条不少；清单体检（V8）也是同一个函数。"""
    for prop in (B2_PROPOSAL, {"atoms": [{"atom": "report.magic"}], "fire": {"id": "h1.demo", "seats": ["solve"]}}):
        sk, advice = ruwei.precheck(_cand("H1"), _essence(), prop)
        again = ruwei.skeleton(_cand("H1"), _essence(), prop)
        assert [a["problem"] for a in advice] == again.problems
    # 过了入位校验的清单再过 V8（shapes.check + 预算绝对值）：预算数字提交前就拦下，不等闸点 3
    ok = {
        "atoms": [{"atom": "report.claim_link", "params": {"show": "x"}, "emergent": True}],
        "fire": {"id": "h7.demo-y", "params": {"budget_usd": 3}, "organ": _organ()},
    }
    assert ruwei.skeleton(_cand(), _essence(), ok).problems == []
    sk, advice = ruwei.precheck(_cand(), _essence(), ok)
    assert [a["problem"] for a in advice] == checks.v8(sk.placement) and advice


def test_a_valid_proposal_passes_the_precheck_clean():
    ok = {
        "atoms": [{"atom": "report.claim_link", "params": {"show": "x"}, "emergent": True}],
        "fire": {"id": "h7.demo-y", "params": {}, "organ": _organ()},
    }
    sk, advice = ruwei.precheck(_cand(), _essence(), ok)
    assert sk.problems == [] and advice == []


def test_the_rules_card_is_read_from_the_live_tables(monkeypatch):
    card = ruwei.rules_card()
    assert card["seats"]["verify"] == list(ruwei.SEATS["verify"]) and "deliver" not in card["seats"]["verify"]
    assert card["tool_events"]["deliver"] == ["deliver"]
    assert all(i in card["id_rule"] for i in shapes.fire_ids())
    assert card["replace_rule"]["seat_forms"] == ruwei.seat_forms()
    assert "forms.solve" in card["form_shape"] and "tools" in card["form_shape"]
    # 规则变了卡跟着变：改一格权能，卡里就是新的（不是写死的一份）
    monkeypatch.setitem(ruwei.SEATS, "verify", (*ruwei.SEATS["verify"], "deliver"))
    assert "deliver" in ruwei.rules_card()["seats"]["verify"]
    p = ruwei.placer_payload(_cand("H1"), _essence(), [], ruwei.ownership())
    assert p["rules"]["seats"]["solve"] and "errors" not in p


class Scripted:
    """按次序给出位丹的回答，记下每次收到的载荷。"""

    def __init__(self, *outputs):
        self.outputs, self.seen = list(outputs), []

    def call(self, role, key, payload):
        self.seen.append((key, dict(payload)))
        return Reply(self.outputs.pop(0), 10, 5)


def test_chain_violation_is_caught_by_the_precheck_fixed_and_passes():
    """提案违规 → 预检拦下（带规则与改法）→ 位丹照着改 → 通过。"""
    good = {
        "atoms": [{"atom": "report.claim_link", "params": {"show": "x"}, "emergent": True}],
        "fire": {"id": "h7.demo-y", "params": {}, "organ": _organ()},
    }
    bad = {**good, "fire": {**good["fire"], "id": "h7_Demo"}}
    dan = Scripted(bad, good)
    res = ruwei.place(dan, _cand(), _essence(), full=False)
    assert res.problems == [] and len(dan.seen) == 2
    first, second = dan.seen
    assert "rules" in first[1] and "errors" not in first[1]
    (err,) = second[1]["errors"]
    assert "要以 h7. 开头" in err and "规则 id_rule" in err and "怎么改：id 改成 h7." in err
    assert res.placement["fire"]["id"] == "h7.demo-y"


def test_the_precheck_gives_up_after_the_attempts_with_the_problems_listed():
    bad = {"atoms": [{"atom": "report.magic"}], "fire": {"id": "h7.demo-y", "params": {}, "organ": _organ()}}
    res = ruwei.place(Scripted(bad, bad, bad), _cand(), _essence(), full=False)
    assert res.problems and "没有这个决策原子：report.magic" in res.problems[0]


# ---------------------------------------------------------------- 修复二：产物登记自愈


class Strict(Host):
    """宿主 check 的替身：读工作区里的文件，按真宿主一样先过 kernel.product_errors（须是 JSON 对象、合 Schema）。"""

    def __init__(self, brief, ws, refuse=None):
        super().__init__(brief)
        self.ws, self.refuse, self.paths, self.by_id = ws, refuse, [], {}

    def call(self, name, args):
        if name != "check":
            return super().call(name, args)
        self.calls.append((name, dict(args)))
        self.paths.append(args["path"])
        obj = json.loads((self.ws / args["path"]).read_text(encoding="utf-8"))
        errs = kernel.product_errors(args["name"], obj) or ([self.refuse] if self.refuse else [])
        if errs:
            return {"ok": False, "code": "schema_error", "detail": "；".join(errs), "errors": errs}
        self.n += 1
        self.by_id[f"a_{100 + self.n}"] = args["path"]
        return {"ok": True, "artifact": f"a_{100 + self.n}"}


def _bare_list_artifact(ws: Path, obj) -> str:
    sha = shapes.digest(obj)
    (ws / "analysis" / "artifacts").mkdir(parents=True, exist_ok=True)
    (ws / "analysis" / "artifacts" / f"{sha}.json").write_text(json.dumps(obj) + "\n", encoding="utf-8")
    return sha


def test_a_refused_product_is_reproduced_and_registered_again(tmp_path):
    brief = brief_for(tmp_path)
    host = Strict(brief, tmp_path)
    s = kernel.Session(tmp_path, brief, ByKey(cases.recording("alpha", "code")), host)
    sha = _bare_list_artifact(tmp_path, [{"op": "add"}])  # trial-a-2 / c-2：bang_updates.json 是个列表
    aid = s.artifact_id("bang_updates.json", sha)
    assert aid == "a_101" and len(host.paths) == 2 and host.paths[0].endswith(f"{sha}.json")
    again = json.loads((tmp_path / host.paths[1]).read_text(encoding="utf-8"))
    assert again == {"v": 1, "name": "bang_updates.json", "bang_updates": [{"op": "add"}]}
    assert s.artifact_id("bang_updates.json", sha) == "a_101" and len(host.paths) == 2  # 已登记的不再问宿主
    assert json.loads((tmp_path / "analysis" / "registered.json").read_text(encoding="utf-8"))[sha] == "a_101"


def test_the_refusal_is_fed_back_as_expected_and_actual_not_just_invalid(tmp_path):
    info = kernel.refusal_info(
        "bang_updates.json", [1, 2, 3], {"code": "schema_error", "errors": ["产物须是 JSON 对象"]}
    )
    assert (
        info["expected"] == "JSON 对象"
        and info["got"] == "JSON 列表（3 项）"
        and info["errors"] == ["产物须是 JSON 对象"]
    )
    info = kernel.refusal_info("candidates.json", {"v": 1}, {"detail": "缺 basis"})
    assert (
        info["expected"] == "JSON 对象，合 candidates Schema" and "v" in info["got"] and info["errors"] == ["缺 basis"]
    )


def test_reproduction_stops_after_two_retries_and_the_blocked_delivery_tells_each_try(tmp_path, monkeypatch):
    n = []

    def never_right(name, obj, info):  # 每次都重产一份不同的，但宿主一直不收
        n.append(1)
        return {"v": 1, "try": len(n)}

    monkeypatch.setattr(kernel, "reproduce_product", never_right)
    brief = brief_for(tmp_path)
    host = Strict(brief, tmp_path, refuse="产物里带着原话里的凭据")
    s = kernel.Session(tmp_path, brief, ByKey(cases.recording("alpha", "code")), host)
    out = s.run()
    (d,) = host.delivered()
    checks_made = [c for c in host.calls if c[0] == "check"]
    assert len(checks_made) == 1 + kernel.REGISTER_RETRIES == 3 and len(n) == 2  # 同一产物至多重试 2 次
    assert out.status == "delivered" and d["outcome"] == "blocked" and d["artifacts"] == []
    needs = "\n".join(d["needs"])
    assert "没有登记成" in d["needs"][0] and "登记 3 次，重试 2 次" in d["needs"][0]
    for i in (1, 2, 3):
        assert f"第 {i} 次：期望 JSON 对象，合 candidates Schema，实际 JSON 对象" in needs
    assert "凭据" in needs and "已重产为" in needs


def test_an_error_that_cannot_be_reproduced_stops_at_once_with_the_history(tmp_path):
    brief = brief_for(tmp_path)
    host = Strict(brief, tmp_path, refuse="产物里带着原话里的凭据")
    s = kernel.Session(tmp_path, brief, ByKey(cases.recording("alpha", "code")), host)
    s.run()
    (d,) = host.delivered()
    assert d["outcome"] == "blocked" and "重试 0 次" in d["needs"][0] and "没有自动重产的办法" in "\n".join(d["needs"])


def test_chain_registration_refused_then_reproduced_then_accepted_in_a_whole_dry_run(tmp_path, monkeypatch):
    """注册拒收 → 回喂 → 重产 → 通过：把引擎改回当初的写法（更新列表直接当产物），整个试算会话照样交付。"""
    put = Engine.put

    def old_put(self, name, obj):
        return put(self, name, obj["bang_updates"] if name == "bang_updates.json" else obj)

    monkeypatch.setattr(Engine, "put", old_put)
    brief = brief_for(tmp_path, fx="delta", intake=cases.intake("delta", "code", "dry_run"))
    host = Strict(brief, tmp_path)
    s = kernel.Session(tmp_path, brief, ByKey(cases.recording("delta", "code", ".dry")), host)
    out = s.run()
    (d,) = host.delivered()
    assert out.status == "delivered" and d["outcome"] == "answered" and len(d["artifacts"]) == 2
    refused = [p for p in host.paths if p.endswith(".json")]
    assert len(refused) == len({p for p in refused}) and len(host.paths) == 3  # dry_run、bang 列表（被拒）、重产的 bang
    doc = json.loads((tmp_path / "analysis" / "run.json").read_text(encoding="utf-8"))
    sha = doc["artifacts"]["bang_updates.json"]  # 引擎的检查点也改认了重产的那份
    assert json.loads((tmp_path / "analysis" / "artifacts" / f"{sha}.json").read_text(encoding="utf-8"))["name"]
    # 交付里的“产物对照”：每行的 sha256 都是那个 Artifact id 实际登记内容的哈希；重产过的有说明行
    answer = (tmp_path / "analysis" / "answer.md").read_text(encoding="utf-8")
    rows = {
        c[0]: (c[1], c[2])
        for c in (r.strip("| ").split(" | ") for r in answer.splitlines() if r.startswith("| ") and ".json" in r)
    }
    for name, (aid, row_sha) in rows.items():
        assert host.by_id[aid] == f"analysis/artifacts/{row_sha}.json", name
    bang_id, bang_sha = rows["bang_updates.json"]
    rejected = host.paths[1].rsplit("/", 1)[1][:-5]
    assert bang_sha == sha and bang_sha != rejected
    assert f"bang_updates.json：原 {rejected[:12]} 被拒，已按原因重产（{sha[:12]}）" in answer
    assert "原 " not in "".join(r for r in answer.splitlines() if r.startswith("| dry_run.json"))


# ---------------------------------------------------------------- 修复三：尝试之间的反馈与耗尽终局


class Spy(ByKey):
    def __init__(self, path, fail=None):
        super().__init__(path, fail)
        self.seen = []

    def call(self, role, key, payload):
        self.seen.append((key, dict(payload)))
        return super().call(role, key, payload)


def _dry_brief(ws, **kw):
    return brief_for(ws, fx="delta", intake=cases.intake("delta", "code", "dry_run"), **kw)


def test_an_engine_defect_is_a_relay_with_a_reason_not_a_crash_and_the_next_try_carries_it(tmp_path, monkeypatch):
    real = ruwei.skeleton
    boom = {"left": 1}

    def flaky(*a, **kw):
        if boom["left"]:
            boom["left"] -= 1
            raise AttributeError("'str' object has no attribute 'get'")
        return real(*a, **kw)

    monkeypatch.setattr(ruwei, "skeleton", flaky)
    rec = cases.recording("delta", "code", ".dry")
    spy1 = Spy(rec)
    s1 = kernel.Session(tmp_path, _dry_brief(tmp_path, relays_left=4), spy1, h := Host(_dry_brief(tmp_path)))
    out = s1.run()
    assert out.status == "relay" and h.delivered() == []  # 以前：整个进程崩，会话 outcome=nothing
    (row,) = json.loads((tmp_path / "analysis" / "attempts.json").read_text(encoding="utf-8"))["rows"]
    assert row["attempt"] == 1 and row["kind"] == "defect" and row["unit"] == "ruwei:C1"
    assert "AttributeError" in row["reason"] and "ruwei:C1" in row["reason"]
    assert not any("prior_failures" in p for _, p in spy1.seen)

    spy2 = Spy(rec)
    s2 = kernel.Session(tmp_path, _dry_brief(tmp_path, relays_left=3), spy2, h2 := Host(_dry_brief(tmp_path)))
    assert s2.attempt_no == 2
    out2 = s2.run()
    assert out2.status == "delivered" and len(h2.delivered()) == 1
    carried = [(k, p["prior_failures"]) for k, p in spy2.seen if "prior_failures" in p]
    assert carried and all(k.startswith("ruwei:C1:") for k, _ in carried)  # 只给出事的那个单元，别的调用的输入不变
    assert "AttributeError" in carried[0][1][0] and "形状" in carried[0][1][0]


def test_b2_regression_every_try_fails_then_the_last_one_ends_in_a_blocked_delivery(tmp_path, monkeypatch):
    """trial-b-2：五次尝试同一处崩；以前无交付、无终局、题悬着。现在最后一次一定交一份写明各次原因的 blocked。"""

    def always(*a, **kw):
        raise AttributeError("'str' object has no attribute 'get'")

    monkeypatch.setattr(ruwei, "skeleton", always)
    rec = cases.recording("delta", "code", ".dry")
    results = []
    for left in (4, 3, 2, 1, 0):
        brief = _dry_brief(tmp_path, relays_left=left)
        host = Host(brief)
        out = kernel.Session(tmp_path, brief, ByKey(rec), host).run()
        results.append((out.status, host.delivered()))
    assert [r[0] for r in results[:4]] == ["relay"] * 4 and all(r[1] == [] for r in results[:4])
    status, (d,) = results[4]
    assert status == "delivered" and d["outcome"] == "blocked" and d["artifacts"] == []
    assert "共尝试 5 次" in d["needs"][0] and "继续" in d["needs"][0]
    lines = [x for x in d["needs"] if x.startswith("第 ")]
    assert [x[:5] for x in lines] == [f"第 {i} 次" for i in range(1, 6)] and all("程序出错" in x for x in lines)
    assert "AttributeError" in lines[0] and "共尝试 5 次" in (tmp_path / "analysis" / "answer.md").read_text("utf-8")


def test_a_defect_in_the_last_try_is_reported_even_when_it_is_the_first_try(tmp_path, monkeypatch):
    monkeypatch.setattr(ruwei, "skeleton", lambda *a, **kw: 1 / 0)
    brief = _dry_brief(tmp_path, relays_left=0)
    host = Host(brief)
    kernel.Session(tmp_path, brief, ByKey(cases.recording("delta", "code", ".dry")), host).run()
    (d,) = host.delivered()
    assert d["outcome"] == "blocked" and "共尝试 1 次" in d["needs"][0] and "ZeroDivisionError" in "\n".join(d["needs"])


def test_a_defect_while_reading_a_fragment_is_fed_back_to_that_slots_reads_only(tmp_path, monkeypatch):
    from paoding_fenjue.engine import shihuo

    real, boom = shihuo._parse_reader, {"left": 1}

    def flaky(*a, **kw):
        if boom["left"]:
            boom["left"] -= 1
            raise KeyError("observations")
        return real(*a, **kw)

    monkeypatch.setattr(shihuo, "_parse_reader", flaky)
    rec = cases.recording("delta", "code", ".dry")
    s1 = kernel.Session(tmp_path, _dry_brief(tmp_path, relays_left=4), ByKey(rec), Host(_dry_brief(tmp_path)))
    assert s1.run().status == "relay"
    (row,) = json.loads((tmp_path / "analysis" / "attempts.json").read_text(encoding="utf-8"))["rows"]
    assert row["unit"].startswith("read:H") and "KeyError" in row["reason"]
    slot = row["unit"].partition(":")[2]
    spy = Spy(rec)
    s2 = kernel.Session(tmp_path, _dry_brief(tmp_path, relays_left=3), spy, Host(_dry_brief(tmp_path)))
    assert s2.run().status == "delivered"
    carried = [k for k, p in spy.seen if "prior_failures" in p]
    assert carried and all(k.startswith("read:") and k.split(":")[-2] == slot for k in carried)
    assert not any(  # 别的调用的输入不变：这个火位的读丹调用一次不漏地带了，别的一次不带
        k.startswith("read:") and k.split(":")[-2] == slot for k, p in spy.seen if "prior_failures" not in p
    )
    assert not any(not k.startswith("read:") for k in carried)


def test_the_call_stack_of_a_defect_goes_to_a_debug_file_only(tmp_path, monkeypatch):
    def boom(*a, **kw):
        raise AttributeError("secret-detail")

    monkeypatch.setattr(ruwei, "skeleton", boom)
    brief = _dry_brief(tmp_path, relays_left=0)
    host = Host(brief)
    kernel.Session(tmp_path, brief, ByKey(cases.recording("delta", "code", ".dry")), host).run()
    log = (tmp_path / "analysis" / "defects.log").read_text(encoding="utf-8")
    assert "Traceback" in log and "in boom" in log and "secret-detail" in log
    assert "Traceback" not in json.dumps(host.delivered()) and "Traceback" not in (
        tmp_path / "analysis" / "attempts.json"
    ).read_text(encoding="utf-8")


def test_prior_failures_reach_the_model_prompt_and_only_for_the_unit_that_failed():
    payload = {"template": "ruwei/place/v1", "candidate": {"id": "C1"}, "prior_failures": ["上次崩在 forms 的形状"]}
    req = pills.render("placer", "ruwei:C1:r1:place:1", payload, "h1.tunshi@1")
    assert "前几次尝试在这一步没做成" in req.user and "上次崩在 forms 的形状" in req.user
    assert '"prior_failures"' not in req.user  # 只在专栏里出现一次，不再混进“输入”的 JSON
    assert kernel._unit_owns("ruwei:C1", "ruwei:C1:r1:design:2") and not kernel._unit_owns("ruwei:C1", "ruwei:C10:r1:x")
    assert kernel._unit_owns("candidates", "shihuo:patterns:1")
    # 片段阅读：按键里倒数第二段的火位认（片段键里也有冒号）
    assert kernel._unit_owns("read:H1", "read:s1:README.md:1-14:H1:1")
    assert not kernel._unit_owns("read:H1", "read:s1:README.md:1-14:H2:1")
    assert not kernel._unit_owns("read:H1", "ruwei:C1:r1:place:1")


def test_the_unit_that_was_doing_when_it_crashed_is_what_the_ledger_names(tmp_path):
    brief = _dry_brief(tmp_path)
    s = kernel.Session(tmp_path, brief, ByKey(cases.recording("delta", "code", ".dry")), Host(brief))
    (tmp_path / "analysis").mkdir(exist_ok=True)
    (tmp_path / "analysis" / "run.json").write_text(
        json.dumps({"step": "S5", "units": [{"id": "ruwei:C1", "state": "doing"}, {"id": "x", "state": "done"}]}),
        encoding="utf-8",
    )
    assert s._doing_unit() == "ruwei:C1"
