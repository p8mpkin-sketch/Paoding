"""一句话开题一期：前置抽取、起草解析、校验（设计 docs/design/kaiti §10 第 1 条的性质测试）。"""

from __future__ import annotations

import dataclasses
import json
import random
import string

import pytest

from paoding_qicao.contract import (
    ANSWER_SLOT,
    DraftError,
    Intake,
    Settings,
    TablePriors,
    batch,
    blobs,
    derivation_bytes,
    draft,
    extract,
    parse_draft,
    placeholder_priors,
    render_card,
    vet,
)
from paoding_qicao.extract import cn_number, norm

INTAKE = Intake.load()
SETTINGS = Settings.from_doc(
    {
        "version": "s1",
        "settings": {
            "caps": {
                "open_usd_milli": 20_000,
                "open_wall_s": 14_400,
                "practice_usd_milli": 500,
                "practice_wall_s": 1800,
            },
            "risk": [
                {"resource": "net", "pattern": "q*:*", "actions": ["connect"], "risk": "r0"},
                {"resource": "net", "pattern": "*.prod.example:*", "actions": ["*"], "risk": "r2"},
            ],
            "models": {
                "profiles": [
                    {"name": "cheap", "endpoint": "e", "model": "m", "family": "f", "tier": "t", "key_slot": "k"}
                ],
                "routes": {"draft": "cheap"},
            },
        },
    }
)
PRIORS = placeholder_priors()

T1 = (
    "练习题：目标在 q1:8080，是个登录页，登录后页面会显示一个答案串，把它交出来写进 answer.txt。"
    "只许访问这个地址，半小时内搞定。答案：PD-7Q2M9XKD"
)
T2 = (
    "仓库在 git.lab:8443，修好 svc 的构建失败。完成标准：在仓库根目录跑 `make test` 全部通过。"
    "可以参考 https://docs.lab/x 上的文档。预算 $50，2 小时。另外也允许访问 paste.example:443 上传日志"
)


def sid(ext, kind, text=None):
    return next(s.id for s in ext.spans if s.kind == kind and (text is None or text in s.text))


def d1(ext):
    return {
        "title": "取得登录后显示的答案串",
        "goal_sentence": [sid(ext, "sentence", "目标在")],
        "entries": [{"span": sid(ext, "addr"), "role": "entry"}],
        "deliverable": {"span": sid(ext, "file")},
        "check": {"form": "answer"},
        "deadline": sid(ext, "duration"),
        "spend": None,
        "tier_guess": None,
        "materials": [],
    }


class FakeModel:
    def __init__(self, out: str):
        self.out, self.calls = out, []

    def complete(self, system, user, max_tokens):
        self.calls.append(user)
        return self.out


# ---------- 抽取 ----------


def test_answer_cut_and_spans():
    e = extract(T1, INTAKE.labels)
    assert e.answers == ("PD-7Q2M9XKD",)
    assert "PD-7Q2" not in e.text and "答案：" not in e.text
    kinds = {s.kind: s.value for s in e.spans if s.kind != "sentence"}
    assert kinds == {"addr": "q1:8080", "file": "answer.txt", "duration": 1800}
    for s in e.spans:
        assert e.text[s.start : s.end] == s.text


def test_kinds_t2():
    e = extract(T2, INTAKE.labels)
    vals = {(s.kind, s.value) for s in e.spans if s.kind != "sentence"}
    assert ("addr", "git.lab:8443") in vals and ("url", "docs.lab:443") in vals
    assert ("code", "make test") in vals and ("money", 50_000) in vals and ("duration", 7200) in vals
    assert ("addr", "paste.example:443") in vals


@pytest.mark.parametrize(
    ("s", "n"), [("3", 3), ("十", 10), ("十五", 15), ("二十", 20), ("两", 2), ("半", 0.5), ("一半", 1.5), ("x", None)]
)
def test_cn_number(s, n):
    assert cn_number(s) == n


def test_no_false_durations_or_addrs():
    e = extract("这件事十分重要，版本 v1.5 h 无关，会议 12:30 开始。", INTAKE.labels)
    assert not e.of("duration") and not e.of("addr")


def test_fenced_code_and_multiple_answers():
    e = extract("跑下面的检查：\n```\npython check.py out.md\n```\n答案：a\nanswer: b", INTAKE.labels)
    assert e.of("code")[0].value == "python check.py out.md"
    assert e.answers == ("a", "b") and "multiple_answers" in e.notes


# ---------- 起草解析 ----------


def test_parse_strict():
    e = extract(T1, INTAKE.labels)
    assert parse_draft(d1(e), e).title.startswith("取得")
    bad = [
        {**d1(e), "scope": []},
        {**d1(e), "title": "x" * 41},
        {**d1(e), "entries": [{"span": "s99", "role": "entry"}]},
        {**d1(e), "entries": [{"span": sid(e, "file"), "role": "entry"}]},
        {**d1(e), "check": {"form": "command", "spans": []}},
        {**d1(e), "goal_sentence": []},
        {**d1(e), "deadline": sid(e, "addr")},
        {**d1(e), "tier_guess": "huge"},
    ]
    for b in bad:
        with pytest.raises(DraftError):
            parse_draft(b, e)


def test_model_never_sees_answer():
    e = extract(T1, INTAKE.labels)
    m = FakeModel("好的：" + json.dumps(d1(e), ensure_ascii=False))
    d = draft(e, True, m, "cheap")
    assert d.model == "cheap"
    assert "PD-7Q2M9XKD" not in m.calls[0] and "人已另外给出" in m.calls[0]


def test_model_garbage():
    e = extract(T1, INTAKE.labels)
    for out in ("没有 JSON", "{bad json}"):
        with pytest.raises(DraftError):
            draft(e, True, FakeModel(out))


# ---------- 校验 ----------


def run(text, dd, answer=None, **kw):
    e = extract(text, INTAKE.labels)
    d = parse_draft(dd(e) if callable(dd) else dd, e, "cheap") if dd is not None else None
    return e, vet(e, answer, d, INTAKE, SETTINGS, PRIORS, **kw)


def test_practice_candidate_goes_confirm_while_switch_off():
    _, v = run(T1, d1)
    assert v.eligible and v.lane == "confirm"
    assert [n.code for n in v.notes] == ["zero_confirm_off"]
    p = v.input
    assert p["goal"]["check"] == {"judge_id": "exact_match", "sealed": [ANSWER_SLOT]}
    assert p["scope"] == [{"resource": "net", "pattern": "q1:8080", "actions": ["connect"], "risk": "r0"}]
    assert p["budget"]["usd_milli"] == 500 and p["budget"]["wall_s"] == 1800
    assert "profile" not in p


def test_practice_lane_when_switch_on():
    _, v = run(T1, d1, zero_confirm=True)
    assert v.lane == "practice" and not v.notes


def test_runtime_grants_open_with_zero_egress():
    """扩权第四步（runtime-grants §3.1）：开着时授权只有工作区一条，原文地址只作展示；道别判断不再看授权。"""
    import dataclasses

    on = dataclasses.replace(SETTINGS, grants_runtime=True)
    e = extract(T1, INTAKE.labels)
    v = vet(e, None, parse_draft(d1(e), e, "cheap"), INTAKE, on, PRIORS, zero_confirm=True)
    assert v.input["scope"] == [{"resource": "workspace", "pattern": "", "actions": ["read", "write"], "risk": "r0"}]
    assert [m["value"] for m in v.mentions] == ["q1:8080"] and v.public()["mentions"] == v.mentions
    assert v.lane == "practice" and not v.notes
    rows = [d for d in v.public()["derivation"] if d["field"] == "scope.mention"]
    assert rows and rows[0]["note"] == "执行时如需访问，会按需申请"
    # 原文地址没有风险表命中（r2）也不再挡道：旧路这里会是 risk_unmatched
    e2 = extract(T1.replace("q1:8080", "z9.prod.example:443"), INTAKE.labels)
    v2 = vet(e2, None, parse_draft(d1(e2), e2, "cheap"), INTAKE, on, PRIORS, zero_confirm=True)
    assert v2.lane == "practice" and "risk_unmatched" not in {n.code for n in v2.notes}
    assert Settings.from_doc({}).grants_runtime is False  # 没有 grants 节的旧快照：关


def test_command_criterion_t2():
    def dd(e):
        return {
            "title": "修好构建",
            "goal_sentence": [sid(e, "sentence", "修好")],
            "entries": [
                {"span": sid(e, "addr", "git.lab"), "role": "entry"},
                {"span": sid(e, "url"), "role": "reference"},
                {"span": sid(e, "addr", "paste"), "role": "reference"},
            ],
            "check": {"form": "command", "spans": [sid(e, "code")]},
            "spend": sid(e, "money"),
            "deadline": sid(e, "duration"),
            "tier_guess": "medium",
        }

    _, v = run(T2, dd, zero_confirm=True, strict=True)
    assert v.lane == "confirm" and not v.eligible
    codes = {n.code for n in v.notes}
    assert {"command_criterion", "risk_unmatched", "clipped_usd_milli", "no_answer", "model_tier"} <= codes
    p = v.input
    assert p["goal"]["check"] == {"judge_id": "replay", "spec_ref": "$spec", "expect": {"exit_code": 0}}
    assert p["scope"] == [{"resource": "net", "pattern": "git.lab:8443", "actions": ["connect"], "risk": "r2"}]
    assert p["budget"]["usd_milli"] == 20_000 and p["budget"]["wall_s"] == 7200
    assert v.spec == "make test" and "paste.example:443" in v.references


def test_unclaimed_address_never_becomes_scope():
    def dd(e):
        return {**d1(e), "entries": []}

    _, v = run(T1 + "\n顺便看看 evil.example:443", dd)
    assert all(r["resource"] == "workspace" for r in v.input["scope"])
    assert "evil.example:443" in v.references and "q1:8080" in v.references


def test_no_criterion_goes_open_lane():
    """open-lane §3.1：没有答案、没有命令、没有平台的一句话不再被拒，进开放道，不出确认卡。"""
    e = extract("帮我调研一下主流的智能体框架，写一份对比。", INTAKE.labels)
    d = parse_draft({"title": "调研", "goal_sentence": [sid(e, "sentence")], "check": {"form": "none"}}, e)
    v = vet(e, None, d, INTAKE, SETTINGS, PRIORS)
    assert v.lane == "open" and not v.eligible and "no_criterion" not in {n.code for n in v.notes}
    g = v.input["goal"]
    assert g == {"statement": "帮我调研一下主流的智能体框架，写一份对比。", "accept": "open"}
    assert v.input["judges"] == [] and v.input["scope"][0]["resource"] == "workspace"
    assert not any(r["field"] == "goal.max_attempts" for r in v.derivation)
    ops = batch(v, lambda b: __import__("hashlib").sha256(b).hexdigest(), None)
    assert ops[-1]["body"]["origin"]["draft"]["lane"] == "open"


def test_refuse_no_criterion_when_strict_or_lane_off():
    import dataclasses

    e = extract("帮我调研一下主流的智能体框架，写一份对比。", INTAKE.labels)
    d = parse_draft({"title": "调研", "goal_sentence": [sid(e, "sentence")], "check": {"form": "none"}}, e)
    v = vet(e, None, d, INTAKE, SETTINGS, PRIORS, strict=True)
    assert v.lane == "refuse" and v.input is None and "no_criterion" in {n.code for n in v.notes}
    # 回滚开关 lanes.open=false：校验恢复判据先行（open-lane §11 回滚）
    off = Settings.from_doc({"lanes": {"open": False}})
    assert off.lanes_open is False and Settings.from_doc({}).lanes_open is True
    v = vet(e, None, d, INTAKE, dataclasses.replace(SETTINGS, lanes_open=False), PRIORS)
    assert v.lane == "refuse" and "no_criterion" in {n.code for n in v.notes}


def test_model_claims_answer_without_one():
    e = extract("取得页面上的串。", INTAKE.labels)
    d = parse_draft({"title": "x", "goal_sentence": [sid(e, "sentence")], "check": {"form": "answer"}}, e)
    v = vet(e, None, d, INTAKE, SETTINGS, PRIORS, strict=True)
    assert v.lane == "refuse" and "answer_missing" in {n.code for n in v.notes}
    v = vet(e, None, d, INTAKE, SETTINGS, PRIORS)  # 开放道：去把它找出来
    assert v.lane == "open" and "answer_missing" in {n.code for n in v.notes}


def test_answer_field_and_conflict_and_leak():
    _, v = run(T1, d1, answer="PD-7Q2M9XKD")
    assert v.lane == "confirm" and v.secret == "PD-7Q2M9XKD"
    _, v = run(T1, d1, answer="other")
    assert v.lane == "refuse" and "answer_conflict" in {n.code for n in v.notes}
    text = T1.replace("。答案：PD-7Q2M9XKD", "，提示：串长得像 pd-7q2m9xkd")
    _, v = run(text, d1, answer="PD-7Q2M9XKD")
    assert v.lane == "refuse" and "answer_leak" in {n.code for n in v.notes}


def test_title_leak():
    def dd(e):
        return {**d1(e), "title": "交出 PD-7Q2M9XKD"}

    _, v = run(T1, dd)
    assert v.lane == "refuse"


def test_bad_draft_refuses_when_the_task_needs_the_draft():
    """起草不可用时，有答案（要判官比对）、有验收清单、选了严格判定、关了开放道的题照旧拒绝（D14 只放开放道）。"""
    e = extract(T1, INTAKE.labels)
    v = vet(e, None, None, INTAKE, SETTINGS, PRIORS, draft_error="超时")
    assert v.lane == "refuse" and "超时" in v.notes[0].text and v.notes[0].code == "bad_draft"
    e2 = extract(RAW, INTAKE.labels)
    for kw in ({"strict": True}, {"acceptance": [{"text": "列出三个框架"}]}):
        v = vet(e2, None, None, INTAKE, SETTINGS, PRIORS, draft_error="超时", **kw)
        assert v.lane == "refuse" and [n.code for n in v.notes] == ["bad_draft"], kw
    closed = dataclasses.replace(SETTINGS, lanes_open=False)
    assert vet(e2, None, None, INTAKE, closed, PRIORS, draft_error="超时").lane == "refuse"
    assert vet(e2, "42", None, INTAKE, SETTINGS, PRIORS, draft_error="超时").lane == "refuse"
    blank = extract("   ", INTAKE.labels)
    assert [n.code for n in vet(blank, None, None, INTAKE, SETTINGS, PRIORS).notes] == ["empty_text", "bad_draft"]


RAW = (
    "对比 LangGraph、AutoGen、CrewAI 三个框架的状态持久化方式，崩溃后能恢复到哪一步。"
    "参考 https://github.com:443 上的文档，预算 2 美元。"
)


def test_without_a_draft_an_open_task_opens_on_the_raw_statement():
    """地图 Q38（D14）：起草不可用、未选严格判定时，用原话直开开放道：题面与目标是原话，题名取原话开头，
    地址只当材料，金额与时长不认（默认预算），出处账里没有一行来自模型。"""
    e = extract(RAW, INTAKE.labels)
    v = vet(e, None, None, INTAKE, SETTINGS, PRIORS, draft_error="起草模型超时")
    assert v.lane == "open" and v.statement == e.text
    assert [n.code for n in v.notes] == ["draft_unavailable"] and "起草模型超时" in v.notes[0].text
    g = v.input["goal"]
    assert g["accept"] == "open" and "self_checks" not in g
    assert g["statement"] == "".join(str(sp.value) for sp in e.of("sentence"))
    first = str(e.of("sentence")[0].value)
    assert v.input["title"] == first[:39] + "…" and len(v.input["title"]) == 40  # 第一句超过 40 字：截断加省略号
    assert v.input["scope"] == [{"resource": "workspace", "pattern": "", "actions": ["read", "write"], "risk": "r0"}]
    assert v.references == ["https://github.com:443"]
    assert v.input["budget"]["usd_milli"] == PRIORS.lookup(INTAKE.defaults["tier"], None).usd_milli  # 不认原文的金额
    assert all(r["source"] != "model" for r in v.derivation)
    assert next(r for r in v.derivation if r["field"] == "title")["source"] == "span"
    again = vet(e, None, None, INTAKE, SETTINGS, PRIORS, draft_error="起草模型超时")
    assert again.public() == v.public()  # 确定性：同一段原文恒得同一份


def test_raw_open_with_runtime_grants_says_access_is_asked_for():
    rt = dataclasses.replace(SETTINGS, grants_runtime=True)
    e = extract(RAW, INTAKE.labels)
    v = vet(e, None, None, INTAKE, rt, PRIORS)
    assert v.lane == "open" and "按需申请" in v.notes[0].text and "没有草案" in v.notes[0].text


def test_priors_pluggable_and_fallback():
    injected = TablePriors.from_doc(
        {"source": "tester", "version": "t1", "tiers": {"medium": {"usd_milli": 900, "wall_s": 999}}}
    )
    e = extract("跑 `make test` 通过即可", INTAKE.labels)
    d = parse_draft(
        {"title": "x", "goal_sentence": [sid(e, "sentence")], "check": {"form": "command", "spans": [sid(e, "code")]}},
        e,
    )
    v = vet(e, None, d, INTAKE, SETTINGS, injected)
    assert v.input["budget"]["usd_milli"] == 900 and v.priors_version == "tester:t1"
    hard = parse_draft(
        {
            "title": "x",
            "goal_sentence": [sid(e, "sentence")],
            "check": {"form": "command", "spans": [sid(e, "code")]},
            "tier_guess": "hard",
        },
        e,
    )
    v = vet(e, None, hard, INTAKE, SETTINGS, injected)
    assert v.input["budget"]["usd_milli"] == 2000  # 查不到 → 模板缺省


def test_priors_table_validation():
    from paoding_qicao.contract import PriorTableError

    for doc in (
        {},
        {"tiers": {"a": {"usd_milli": 0, "wall_s": 1}}},
        {"tiers": {"a": 3}},
        {"tiers": {"a": {"usd_milli": 1, "wall_s": 1, "bootstrap_share": 2}}},
    ):
        with pytest.raises(PriorTableError):
            TablePriors.from_doc(doc)
    assert PRIORS.placeholder and PRIORS.version().startswith("placeholder")


def test_settings_profiles():
    assert SETTINGS.draft_profile(None)["name"] == "cheap"
    with pytest.raises(ValueError):
        SETTINGS.draft_profile("nope")
    assert Settings.from_doc({}).draft_profile(None) is None
    with pytest.raises(ValueError):
        Settings.from_doc({"risk": [{"resource": "net", "pattern": "*", "risk": "r9"}]})


def test_batch_and_card():
    _, v = run(T1, d1)
    store = {}

    def put(b):
        import hashlib

        h = hashlib.sha256(b).hexdigest()
        store[h] = b
        return h

    ref = {"vault": "kt-x", "digest": "d" * 64}
    ops = batch(v, put, ref)
    assert [o["op"] for o in ops] == ["register_artifact", "register_artifact", "open_problem"]
    body = ops[-1]["body"]
    assert body["origin"]["statement_ref"] == "$0" and body["goal"]["check"]["sealed"] == [ref]
    for b in store.values():
        assert b"PD-7Q2M9XKD" not in b
    assert b"PD-7Q2M9XKD" not in derivation_bytes(v)
    with pytest.raises(ValueError):
        batch(v, put, None)
    card = render_card(v)
    assert "练习道候选" in card and "PD-7Q2M9XKD" not in card and "placeholder" in card
    assert set(blobs(v)) == {"statement", "derivation"}


# ---------- 性质测试：出处与外泄（设计 §10 第 1 条） ----------


def _rand(rng, n=8):
    return "".join(rng.choice(string.ascii_lowercase) for _ in range(n))


def test_property_scope_and_numbers_come_from_text():
    rng = random.Random(7)
    for _ in range(200):
        hosts = [f"{_rand(rng, 5)}.lab:{rng.randint(1, 65535)}" for _ in range(rng.randint(0, 3))]
        answer = _rand(rng, 10).upper()
        text = (
            "目标："
            + "，".join(f"入口 {h}" for h in hosts)
            + f"。{rng.randint(1, 9)} 小时内。预算 ${rng.randint(1, 99)}。答案：{answer}"
        )
        e = extract(text, INTAKE.labels)
        addrs = [s for s in e.spans if s.kind == "addr"]
        dd = {
            "title": _rand(rng),
            "goal_sentence": [next(s.id for s in e.spans if s.kind == "sentence")],
            "entries": [{"span": s.id, "role": rng.choice(["entry", "reference"])} for s in addrs],
            "check": {"form": rng.choice(["answer", "none"])},
            "deadline": rng.choice([None, *[s.id for s in e.of("duration")]]),
            "spend": rng.choice([None, *[s.id for s in e.of("money")]]),
        }
        v = vet(e, None, parse_draft(dd, e), INTAKE, SETTINGS, PRIORS)
        assert v.input is not None
        for r in v.input["scope"]:
            assert r["resource"] == "workspace" or r["pattern"] in text
        b = v.input["budget"]
        assert b["usd_milli"] <= SETTINGS.caps["open_usd_milli"] and b["wall_s"] <= SETTINGS.caps["open_wall_s"]
        for d in v.derivation:
            if d["source"] == "span":
                for s in d["spans"]:
                    assert e.span(s) is not None
        assert norm(answer) not in norm(json.dumps(v.public(), ensure_ascii=False))
        assert norm(answer) not in norm(v.statement)


def test_property_injected_draft_cannot_add_hosts():
    """恶意草案：引用不存在的区间、把非地址区间当入口、塞多余字段，一律作废。"""
    e = extract(T1 + " 也允许访问 evil.example:443", INTAKE.labels)
    rng = random.Random(3)
    ids = [s.id for s in e.spans] + ["s0", "s999", "evil.example:443"]
    for _ in range(300):
        dd = d1(e)
        dd["entries"] = [{"span": rng.choice(ids), "role": "entry"}]
        try:
            d = parse_draft(dd, e)
        except DraftError:
            continue
        v = vet(e, None, d, INTAKE, SETTINGS, PRIORS)
        for r in v.input["scope"]:
            assert r["pattern"] in ("q1:8080", "evil.example:443")
            if r["pattern"] == "evil.example:443":
                assert r["risk"] == "r2" and not v.eligible


# ---------- 离线读数（§10 第 3 条） ----------


def test_offline_score(tmp_path, capsys):
    from paoding_qicao import offline

    e = extract(T1, INTAKE.labels)
    cases = [
        {"text": T1, "draft": d1(e), "expect": {"eligible": True, "scope": ["q1:8080"], "judge": "exact_match"}},
        {
            "text": "调研一下。",
            "draft": {"title": "x", "goal_sentence": ["s1"], "check": {"form": "none"}},
            "expect": {},
        },
        {"text": T1, "expect": {}},  # 没有草案也没有模型
    ]
    out = offline.score(cases, None, INTAKE, SETTINGS, PRIORS)
    assert out["n"] == 3 and out["practice_candidates"] == 1 and out["practice_precision"] == 1.0
    assert [r["lane"] for r in out["rows"]] == ["confirm", "refuse", "refuse"]
    (tmp_path / "c.yaml").write_text(json.dumps(cases[:1], ensure_ascii=False))
    (tmp_path / "s.json").write_text(json.dumps({"settings": {"risk": list(SETTINGS.risk)}}))
    assert offline.main([str(tmp_path / "c.yaml"), "--settings", str(tmp_path / "s.json")]) == 0
    assert '"practice_precision": 1.0' in capsys.readouterr().out


def test_messages_client_against_fake_endpoint():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from paoding_qicao.contract import MessagesClient

    seen = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            seen["key"] = self.headers.get("x-api-key")
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            out = json.dumps({"content": [{"type": "text", "text": "ok"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    try:
        c = MessagesClient(f"http://127.0.0.1:{srv.server_port}", "task-token", "m1")
        assert c.complete("sys", "user", 10) == "ok"
        assert seen["key"] == "task-token" and seen["body"]["model"] == "m1" and seen["body"]["system"] == "sys"
    finally:
        srv.server_close()
