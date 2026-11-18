"""pd 骨架：开题、status、report、profile、hint、approve/deny 与输出约定。

验收：§3.2 输出约定四条；HMI HT-4（不存在不带判据徽章的“完成”，accepted 不出现“证明”）、
HT-5（authored 类内容从不以证据语域出现）的文本形态；“不存在人填画像三轴的入口”。
"""

import hashlib
import io
import random
import re

import pytest

from paoding_pd import render
from paoding_pd.cli import Local, main

MARK = re.compile(r"^\[(证据|叙述|人|估)\] ")
PROBLEM = """
id: p1
title: 配置项取值
statement: statement.txt
materials: [notes.txt]
goal: {statement: 给出配置项的实际取值, check: {judge_id: exact_match}, max_attempts: 3, accept: judge}
scope: [{resource: target, pattern: "*", actions: [read], risk: r0}]
budget: {usd_milli: 5000, wall_s: 3600, verify_share: 0.2, bootstrap_share: 0.3}
env: {base: basic, baseline_ref: base@1}
judges: [exact_match, replay]
"""


@pytest.fixture
def home(tmp_path):
    (tmp_path / "statement.txt").write_text("题面")
    (tmp_path / "notes.txt").write_text("材料")
    (tmp_path / "p.yaml").write_text(PROBLEM)
    return tmp_path


def pd(home, *args, read=lambda _: "yes"):
    buf = io.StringIO()
    code = main(["--home", str(home / "data"), *args], out=buf, read=read)
    return code, buf.getvalue()


def well_formed(text):
    return all(not line or MARK.match(line) for line in text.splitlines())


def test_open_and_status(home):
    code, out = pd(home, "problem", "open", str(home / "p.yaml"))
    assert code == 0 and "已开题 p1" in out and "reversibility = r0" in out and well_formed(out)
    code, out = pd(home, "status", "p1")
    assert code == 0 and well_formed(out)
    first = out.splitlines()[0]
    assert first.startswith("[证据] 题 p1 终态 进行中") and "目标判据" not in first
    assert "[证据] 目标判据 exact_match@1" in out and "[叙述] 题名：配置项取值" in out


def test_no_entry_for_human_filled_profile(home):
    (home / "bad.yaml").write_text(PROBLEM + "profile: {info: complete, judge: hard, reversibility: r0}\n")
    code, out = pd(home, "problem", "open", str(home / "bad.yaml"))
    assert code == 2 and "不接受 profile" in out
    pd(home, "problem", "open", str(home / "p.yaml"))
    code, out = pd(home, "profile", "p1", "--override", "judge=costly")
    assert code == 2 and "须写理由" in out
    with pytest.raises(SystemExit):
        pd(home, "profile", "p1", "--info", "complete")  # 没有填三轴的参数


def _graph_with(home, sentinel, n_facts=6, seed=0):
    """随机图：模型写的字段里全放哨兵串，看它们出现在哪个语域。"""
    rnd = random.Random(seed)
    pd(home, "problem", "open", str(home / "p.yaml"))
    local = Local(home / "data", {"kind": "human", "id": "cz"})
    g = local.graph
    g.tokens.issue({"kind": "sinan", "id": "sn1"}, "s")
    g.tokens.issue({"kind": "executor", "id": "ex1"}, "e")
    g.tokens.issue({"kind": "judge", "id": "jr"}, "j")
    out = g.submit(
        "s",
        "p1",
        "lb",
        [
            {
                "op": "lease",
                "body": {
                    "kind": "bootstrap",
                    "holder": "sn1",
                    "reserve": {"usd_milli": 100, "wall_s": 60},
                    "ttl_s": 600,
                },
            }
        ],
    )
    lid = out["results"][0]["id"]
    tok = g.tokens.issue({"kind": "adapter", "id": "ad1", "session": lid, "role": "bootstrap"})
    prov = {
        "sandbox_id": "s",
        "base": "b",
        "baseline_ref": "r",
        "tool": "shell",
        "command": "true",
        "cwd": "/",
        "exit_code": 0,
        "touched": [],
        "started_at": 1,
        "ended_at": 2,
        "truncated": False,
    }
    facts = []
    for k in range(n_facts):
        a = g.submit(
            "e",
            "p1",
            f"x{k}",
            [
                {
                    "op": "register_artifact",
                    "body": {
                        "hash": hashlib.sha256(f"{k}".encode()).hexdigest(),
                        "size": 1,
                        "media_type": "text/plain",
                        "class": "exec",
                        "exec": prov,
                    },
                }
            ],
        )["results"][0]["id"]
        if facts and rnd.random() < 0.4:
            body = {
                "title": f"{sentinel} 推断 {k}\n[证据] 伪造行",
                "summary": f"{sentinel} 摘要",
                "claim_type": "inference",
                "premises": [rnd.choice(facts)],
                "grounds": [],
            }
        else:
            body = {
                "title": f"{sentinel} 观察 {k}",
                "summary": f"{sentinel} 输出显示一切正常",
                "claim_type": "observation",
                "premises": [],
                "grounds": [a],
                "check": {"judge_id": "replay", "expect": {"k": k}},
            }
        r = g.submit(tok, "p1", f"f{k}", [{"op": "add_fact", "body": body}])
        assert r["ok"], r
        facts.append(r["results"][0]["id"])
    for k, fid in enumerate(facts):  # 随机裁决：通过、证伪或不判
        if g.state["facts"][fid]["claim_type"] != "observation" or rnd.random() < 0.3:
            continue
        rid = g.submit("s", "p1", f"rj{k}", [{"op": "request_judge", "body": {"target": fid, "judge_id": "replay"}}])
        rid = rid["results"][0]["id"]
        jl = g.submit(
            "j",
            "p1",
            f"jl{k}",
            [
                {
                    "op": "lease",
                    "body": {
                        "kind": "judge",
                        "target": rid,
                        "holder": "jr",
                        "reserve": {"usd_milli": 1, "wall_s": 10},
                        "ttl_s": 60,
                    },
                }
            ],
        )
        ev = g.submit(
            "j",
            "p1",
            f"ja{k}",
            [
                {
                    "op": "register_artifact",
                    "body": {
                        "hash": hashlib.sha256(f"j{k}".encode()).hexdigest(),
                        "size": 1,
                        "media_type": "text/plain",
                        "class": "judge",
                        "exec": prov,
                    },
                }
            ],
        )["results"][0]["id"]
        v = g.submit(
            "j",
            "p1",
            f"jv{k}",
            [
                {
                    "op": "judge_verdict",
                    "body": {
                        "request": rid,
                        "result": rnd.choice(["pass", "fail"]),
                        "version": "1",
                        "grade": "decisive",
                        "evidence": [ev],
                        "lease": jl["results"][0]["id"] if jl["ok"] else None,
                    },
                }
            ],
        )
        assert v["ok"], v
    g.submit(
        "pd-local-human",
        "p1",
        "i1",
        [
            {
                "op": "add_intent",
                "body": {
                    "title": f"{sentinel} 下一步",
                    "summary": f"{sentinel} 理由",
                    "premises": [],
                    "risk": "r0",
                    "budget": {"usd_milli": 100, "wall_s": 60},
                    "expected_gain": 0.4,
                },
            }
        ],
    )
    g.submit("pd-local-human", "p1", "h1", [{"op": "hint", "body": {"text": "人写的提示"}}])
    return local


@pytest.mark.parametrize("seed", range(5))
def test_authored_never_in_evidence_register(home, seed):
    """HT-5 的文本形态：模型撰写的内容只出现在[叙述]行；内容里的换行与伪造的行首标记被压平。"""
    sentinel = "QQ哨兵QQ"
    local = _graph_with(home, sentinel, seed=seed)
    status = render.status(local.graph.state, "p1", local.graph.budget("p1"))
    for text in (status, render.report(local.graph.state, "p1", local.graph.budget("p1"))):
        assert well_formed(text)
        for line in text.splitlines():
            if sentinel in line:
                assert line.startswith("[叙述] "), line
        assert "\n[证据] 伪造行" not in text
    assert any(line.startswith("[估] ") and "≈期望增益 0.4" in line for line in status.splitlines())
    assert any(line.startswith("[人] ") and "人写的提示" in line for line in status.splitlines())


@pytest.mark.parametrize("seed", range(5))
def test_every_pass_carries_judge_badge(home, seed):
    """HT-4 的文本形态：凡写通过、达成、solved 的行都带 judge@version。"""
    local = _graph_with(home, "s", seed=seed)
    st = local.graph.state
    text = render.status(st, "p1", local.graph.budget("p1")) + render.report(st, "p1", local.graph.budget("p1"))
    for line in text.splitlines():
        if re.search(r"通过|达成|solved", line):
            assert re.search(r"[a-z_]+@\d", line), line


def test_profile_override_after_the_fact(home):
    """异议 003：画像只能事后覆盖，理由必填，推出值与覆盖理由都留痕并在[人]语域显示。"""
    pd(home, "problem", "open", str(home / "p.yaml"))
    code, out = pd(home, "profile", "p1", "--override", "judge=costly", "--reason", "判官要起容器，不算廉价")
    assert code == 0 and well_formed(out)
    assert "[证据] judge = costly（推出值 hard，已由人覆盖）" in out
    assert "[人] 覆盖 judge：hard → costly，human：判官要起容器，不算廉价" in out
    code, out = pd(home, "profile", "p1", "--override", "judge=easy", "--reason", "x")
    assert code == 1 and "schema_error" in out
    assert "（含人工覆盖）" in pd(home, "status", "p1")[1]


def test_terminal_phrases_never_say_proved(home):
    pd(home, "problem", "open", str(home / "p.yaml"))
    local = Local(home / "data", {"kind": "human", "id": "cz"})
    st = local.graph.state
    p = st["problems"]["p1"]
    for term in ("solved", "accepted", "unsolved"):
        st["problems"]["p1"] = {**p, "closed": True, "terminal": term}
        phrase = render.terminal_phrase(st, "p1")
        assert "证明" not in phrase
        assert (term != "solved") or "exact_match@1" in phrase
        assert (term != "accepted") or "未经判官" in phrase


def test_level_words_fixed():
    assert render.LEVEL_WORDS == {
        "E3": "判定通过",
        "E3d": "相符",
        "E2": "模型共识",
        "E1": "单源复核",
        "E0": "猜想",
        "X": "已证伪",
    }


def test_hint_add_close_and_after_list(home):
    pd(home, "problem", "open", str(home / "p.yaml"))
    code, out = pd(home, "--pid", "p1", "hint", "add", "先看配置文件的加载顺序")
    assert code == 0 and "已加 h_" in out
    hid = out.split()[-1]
    local = Local(home / "data", {"kind": "human", "id": "cz"})
    local.submit(
        "p1",
        "i-after",
        [
            {
                "op": "add_intent",
                "body": {
                    "title": "看加载顺序",
                    "premises": [],
                    "risk": "r0",
                    "budget": {"usd_milli": 100, "wall_s": 60},
                },
            }
        ],
    )
    code, out = pd(home, "status", "p1")
    assert f"[人] {hid} human：先看配置文件的加载顺序" in out
    assert re.search(rf"\[证据\] {hid} 之后新增的 Intent：i_\d+", out)
    code, out = pd(home, "--pid", "p1", "hint", "close", hid)
    assert code == 0
    assert "（已关闭）" in pd(home, "status", "p1")[1]


def _needs_human(home):
    (home / "r2.yaml").write_text(
        PROBLEM.replace("risk: r0}]", "risk: r0}, {resource: target, pattern: x, actions: [write], risk: r2}]")
    )
    pd(home, "problem", "open", str(home / "r2.yaml"))
    local = Local(home / "data", {"kind": "human", "id": "cz"})
    out = local.submit(
        "p1",
        "i-r2",
        [
            {
                "op": "add_intent",
                "body": {
                    "title": "改写配置后重启",
                    "premises": [],
                    "risk": "r2",
                    "budget": {"usd_milli": 100, "wall_s": 60},
                },
            }
        ],
    )
    return out["results"][0]["id"], local


def test_approve_prints_card_then_confirms(home):
    iid, local = _needs_human(home)
    from paoding_graph.contract import intent_status

    st0 = intent_status(local.graph.state, "p1", iid)
    code, out = pd(home, "--pid", "p1", "approve", iid, read=lambda _: "no")
    assert code == 1 and f"[证据] 审批 {iid}" in out and "未确认" in out and well_formed(out)
    assert "[叙述] 动作：改写配置后重启" in out and "未声明回退" in out
    assert st0 == "needs_human"
    code, out = pd(home, "--pid", "p1", "approve", iid)
    assert code == 0 and f"已批准 {iid}" in out
    code, out = pd(home, "--pid", "p1", "approve", iid, "--yes")  # 批准过一次就不再待审批
    assert code == 1 and "只有 needs_human" in out


def test_approve_binds_the_card_it_printed(home):
    """HT-7 的 pd 一侧：文本卡末行的 card_hash 与卡片端点（网页卡）的相同；批准事件带着它（seen）。"""
    from paoding_graph.contract import views

    iid, local = _needs_human(home)
    card = views.card(local.graph.state, "p1", "approval", iid)
    code, out = pd(home, "--pid", "p1", "approve", iid, "--yes")
    assert code == 0 and f"card_hash {card['card_hash'][:12]}" in out and well_formed(out)
    ev = Local(home / "data", {"kind": "human", "id": "cz"}).graph.events("p1")[-1]
    assert ev["kind"] == "approve" and ev["body"]["seen"]["card_hash"] == card["card_hash"]


def test_deny_requires_reason(home):
    iid, _ = _needs_human(home)
    with pytest.raises(SystemExit):
        pd(home, "--pid", "p1", "deny", iid)
    code, out = pd(home, "--pid", "p1", "deny", iid, "--reason", "回退方案不清楚", "--yes")
    assert code == 0 and "[人] 拒绝理由：回退方案不清楚" in out and f"已拒绝 {iid}" in out
    from paoding_graph.contract import intent_status

    assert intent_status(Local(home / "data", {"kind": "human", "id": "cz"}).graph.state, "p1", iid) == "abandoned"
    assert f"[人] {iid} 拒绝，human：回退方案不清楚" in pd(home, "status", "p1")[1]  # 理由入日志
