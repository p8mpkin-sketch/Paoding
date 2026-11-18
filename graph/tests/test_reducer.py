"""D2：reducer 最小集、等级函数与迟滞、组件令牌。

验收：等级函数单元测试（一次失败回到 E0，连续两次失败为 X）；3.1.5 的 4（M0 形态）；
3.2.5 的 2 的前四种形态；3.1.5 的 8（画像与 risk 上限）。
"""
import ast
import pathlib
import random

import pytest
from conftest import ADAPTER, CFG, EXECUTOR, HUMAN, JUDGE, Kernel, explore, reason

from paoding_graph import levels as lv
from paoding_graph.replay import replay, state_hash
from paoding_graph.reducer import apply, empty_state
from paoding_graph.tokens import TokenRegistry, UnknownToken

ROOT = pathlib.Path(__file__).resolve().parents[2]


# ---------- 搬运不重写 ----------

def test_refmodel_is_verbatim_copy():
    """等级函数与消费门从参考模型搬运，不重写：两份文件逐字节相同。"""
    a = (ROOT / "docs/design/reference-model/kernel.py").read_bytes()
    b = (ROOT / "graph/src/paoding_graph/refmodel.py").read_bytes()
    assert a == b, "graph/refmodel.py 与参考模型分叉；改等级语义须两边一起改（以规格为准）"


def test_reducer_is_pure():
    """I1：reducer、等级桥接与参考模型不 import 时钟、IO、随机数、网络、子进程。"""
    banned = {"time", "datetime", "os", "random", "socket", "sqlite3", "subprocess", "pathlib",
              "urllib", "http", "requests", "asyncio", "secrets", "io", "shutil", "tempfile"}
    for name in ("reducer.py", "levels.py", "refmodel.py", "jcs.py", "envelope.py", "work.py"):
        tree = ast.parse((ROOT / "graph/src/paoding_graph" / name).read_text())
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                mods = [node.module]
            for m in mods:
                assert m.split(".")[0] not in banned, f"{name} import 了 {m}"
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("open", "eval", "exec", "input"):
                pytest.fail(f"{name} 调用了 {node.func.id}")


def test_apply_does_not_mutate(k):
    k.open()
    before = state_hash(k.state)
    snapshot = k.state
    k.obs()
    assert state_hash(snapshot) == before


# ---------- 等级与迟滞 ----------

def test_hysteresis(k):
    """一次失败回到 E0（带 unstable），连续两次失败为 X。"""
    k.open()
    f = k.obs()
    assert lv.levels(k.state, "p1")[f] == "E0"
    k.verdict("p1", f, "pass")
    assert lv.levels(k.state, "p1")[f] == "E3"
    k.verdict("p1", f, "fail")
    _, res = lv.compute(k.state, "p1")
    assert res.levels[f] == "E0" and f in res.unstable
    k.verdict("p1", f, "fail")
    assert lv.levels(k.state, "p1")[f] == "X"


def test_single_fail_is_x(k):
    """序列只有一条时取该条：首判失败即证伪。"""
    k.open()
    f = k.obs()
    k.verdict("p1", f, "fail")
    assert lv.levels(k.state, "p1")[f] == "X"


def test_flaky_is_inconclusive(k):
    k.open()
    f = k.obs()
    k.verdict("p1", f, "pass")
    k.verdict("p1", f, "flaky")
    assert lv.levels(k.state, "p1")[f] == "E0"


def test_consistent_judge_cannot_reach_e3(k):
    k.open()
    f = k.obs(judge="soft")
    k.verdict("p1", f, "pass", judge="soft")
    assert lv.levels(k.state, "p1")[f] != "E3"


def test_goal_candidates_and_attempts(k):
    k.open()
    cands = [k.art("p1", "authored", f"c{i}".encode()) for i in range(4)]
    k.verdict("p1", "goal", "fail", judge="exact_match", candidate=cands[0])
    assert lv.levels(k.state, "p1")["goal"] == "E0"          # 目标没有 X
    k.verdict("p1", "goal", "fail", judge="exact_match", candidate=cands[1])
    k.verdict("p1", "goal", "pass", judge="exact_match", candidate=cands[2])
    assert lv.levels(k.state, "p1")["goal"] == "E3"
    assert k.submit(HUMAN, "p1", "request_judge",
                    {"target": "goal", "judge_id": "exact_match", "candidate": cands[3]}) == "quota_exceeded"


def test_judge_must_be_registered_check(k):
    """判据先行（I4）：只能用登记判据时的判官。"""
    k.open()
    f = k.obs(judge="replay")
    assert k.submit(HUMAN, "p1", "request_judge", {"target": f, "judge_id": "costly"}) == "schema_error"


def test_premise_downgrade_and_inference(k):
    k.open()
    a = k.obs(title="a")
    k.verdict("p1", a, "pass")
    b = k.submit(explore(), "p1", "add_fact", {"title": "b", "claim_type": "inference", "premises": [a], "grounds": []})
    assert b.startswith("f_")
    k.verdict("p1", a, "fail"); k.verdict("p1", a, "fail")
    assert lv.levels(k.state, "p1")[a] == "X"
    assert k.submit(explore(), "p1", "add_fact",
                    {"title": "c", "claim_type": "inference", "premises": [a], "grounds": []}) == "stale_premise"


# ---------- 3.1.5 的 4，M0 形态 ----------

def test_unknown_ref_cycle_impossible(k):
    k.open()
    assert k.submit(explore(), "p1", "add_fact",
                    {"title": "x", "claim_type": "inference", "premises": ["f_999"], "grounds": []}) == "unknown_ref"


def test_random_logs_terminate_and_replay(k):
    """随机操作序列：重算总在有限步内结束，重放状态哈希一致。"""
    rng = random.Random(11)
    for trial in range(30):
        kk = Kernel()
        kk.open()
        facts, observed = [], []
        for step in range(40):
            r = rng.random()
            if r < 0.35 or not facts:
                prem = rng.sample(facts, min(len(facts), rng.randint(0, 2)))
                if prem and rng.random() < 0.5:
                    out = kk.submit(explore(f"L{step}"), "p1", "add_fact",
                                    {"title": f"n{step}", "claim_type": "inference", "premises": prem, "grounds": []})
                else:
                    out = kk.obs(title=f"n{step}", actor=explore(f"L{step}"), premises=prem)
                    if out.startswith("f_"):
                        observed.append(out)
                if out.startswith("f_"):
                    facts.append(out)
            elif observed:
                kk.verdict("p1", rng.choice(observed), rng.choice(["pass", "pass", "fail", "flaky"]))
            lv.compute(kk.state, "p1")
        final = state_hash(kk.state)
        assert state_hash(replay(kk.events, apply, empty_state())) == final


# ---------- 3.2.5 的 2，前四种形态 ----------

def test_forged_unknown_ref(k):
    k.open()
    assert k.obs(grounds=["a_999"]) == "unknown_ref"
    assert k.obs(grounds=["vault:answer"]) == "unknown_ref"        # 保密库引用不是 Artifact


def test_forged_authored_as_evidence(k):
    k.open()
    assert k.obs(grounds=[k.art("p1", "authored")]) == "inadmissible_class"


def test_forged_task_token_registers(k):
    k.open()
    for cls in ("exec", "judge", "input"):
        assert k.art("p1", cls, actor=explore()) == "forbidden_op"
    assert k.art("p1", "exec", actor=ADAPTER) == "forbidden_op"
    assert k.art("p1", "authored", actor=EXECUTOR) == "forbidden_op"
    reg = TokenRegistry()
    reg.issue(EXECUTOR)
    with pytest.raises(UnknownToken):
        reg.resolve("forged")


def test_forged_cross_problem(k):
    k.open("p1"); k.open("p2")
    other = k.art("p2", "exec")
    assert k.obs("p1", grounds=[other]) == "scope_mismatch"
    f2 = k.obs("p2")
    assert k.submit(explore(), "p1", "add_fact",
                    {"title": "x", "claim_type": "inference", "premises": [f2], "grounds": []}) == "scope_mismatch"


def test_provenance_fields_not_from_proposer(k):
    k.open()
    body = {"hash": "0" * 64, "size": 1, "media_type": "x", "class": "exec", "producer": {"actor": "me"}}
    assert k.submit(EXECUTOR, "p1", "register_artifact", body) == "schema_error"
    assert k.submit(EXECUTOR, "p1", "register_artifact",
                    {"hash": "0" * 64, "size": 1, "media_type": "x", "class": "exec"}) == "schema_error"


def test_observation_needs_check_and_exec_ground(k):
    k.open()
    a = k.art("p1", "exec")
    assert k.submit(explore(), "p1", "add_fact",
                    {"title": "x", "claim_type": "observation", "premises": [], "grounds": [a]}) == "missing_evidence"
    j = k.art("p1", "judge")
    assert k.obs(grounds=[j]) == "missing_evidence"


def test_yielded_by_not_from_proposer(k):
    k.open()
    assert k.submit(explore(), "p1", "add_fact", {"title": "x", "claim_type": "inference", "premises": [],
                                                  "grounds": [k.art("p1", "exec")], "yielded_by": "i_1"}) == "schema_error"


def test_verdict_evidence_must_be_judge_class(k):
    k.open()
    f = k.obs()
    rid = k.submit(HUMAN, "p1", "request_judge", {"target": f, "judge_id": "replay"})
    assert k.submit(JUDGE, "p1", "judge_verdict", {"request": rid, "result": "pass", "version": "1",
                                                   "evidence": [k.art("p1", "exec")]}) == "inadmissible_class"
    assert k.submit(explore(), "p1", "judge_verdict", {"request": rid, "result": "pass", "version": "1",
                                                       "evidence": []}) == "forbidden_op"


# ---------- 权限、配额、合并 ----------

def test_roles():
    k = Kernel(); k.open()
    idler = {"kind": "adapter", "id": "ad1", "session": "s", "role": "idler"}
    body = {"title": "i", "premises": [], "risk": "r0", "budget": {"usd_milli": 100, "wall_s": 60}}
    assert k.submit(idler, "p1", "add_intent", body) == "forbidden_op"        # 3.1.5 的 6
    assert k.submit(explore(), "p1", "add_intent", body) == "forbidden_op"
    assert k.submit(reason(), "p1", "add_intent", body).startswith("i_")
    assert k.submit(explore(), "p1", "open_problem", {}) == "forbidden_op"


def test_fact_quota(k):
    k.open()
    for i in range(20):
        assert k.obs(title=f"o{i}").startswith("f_")
    assert k.obs(title="o20") == "quota_exceeded"
    assert k.obs(title="other", actor=explore("L2")).startswith("f_")


def test_content_key_merge(k):
    k.open()
    f1 = k.obs(title="same")
    f2 = k.obs(title="same")
    assert f1 == f2
    assert len(k.state["facts"][f1]["grounds"]) == 2


# ---------- 画像（3.1.5 的 8） ----------

def test_profile_derived(k):
    k.open("p1", scope_risks=("r0", "r2"))
    assert k.state["problems"]["p1"]["profile"] == {"info": "complete", "judge": "hard", "reversibility": "r2"}
    k.open("p2", goal_judge="costly", resource="remote")
    assert k.state["problems"]["p2"]["profile"] == {"info": "partial", "judge": "costly", "reversibility": "r0"}
    k.open("p3", goal_judge="soft")
    assert k.state["problems"]["p3"]["profile"]["judge"] == "deferred"
    k.open("p4", goal_judge="advice")
    assert k.state["problems"]["p4"]["profile"]["judge"] == "none"


def test_profile_not_accepted_from_human(k):
    """依乎天理：不存在人填三轴的入口。完整合法的开题体只多一个 profile 也被拒。"""
    k.open("p1")
    body = {key: v for key, v in k.events[-1]["body"].items() if key not in ("profile", "judge_snapshot")}
    st = k.art("p9", "input")
    body["origin"] = {"statement_ref": st, "materials": []}
    assert k.submit(HUMAN, "p9", "open_problem", {**body, "profile": {"info": "complete"}}) == "schema_error"
    assert k.submit(HUMAN, "p9", "open_problem", body) == "ok"


def test_risk_ceiling(k):
    k.open("p1", scope_risks=("r0", "r1"))
    body = {"title": "i", "premises": [], "risk": "r2", "budget": {"usd_milli": 100, "wall_s": 60}}
    assert k.submit(reason(), "p1", "add_intent", body) == "scope_mismatch"
    body["needs_scope"] = [{"resource": "target", "pattern": "x", "actions": ["write"], "risk": "r2"}]
    iid = k.submit(reason(), "p1", "add_intent", body)
    assert iid.startswith("i_") and lv.intent_state(k.state, "p1", iid) == "needs_human"


def test_scope_risk_defaults_to_r2(k):
    st = k.art("p1", "input")
    r = k.submit(HUMAN, "p1", "open_problem", {
        "title": "t", "origin": {"statement_ref": st, "materials": []},
        "goal": {"statement": "g", "check": {"judge_id": "replay"}, "max_attempts": 1, "accept": "judge"},
        "scope": [{"resource": "x", "pattern": "*", "actions": []}],
        "budget": {"usd_milli": 1, "wall_s": 1, "verify_share": 0, "bootstrap_share": 0},
        "env": {"base": "b", "baseline_ref": "r"}, "judges": ["replay"]})
    assert r == "ok" and k.state["problems"]["p1"]["profile"]["reversibility"] == "r2"


def test_checked_intent_achieved_unblocks(k):
    """3.1.5 的 9：带判据的 Intent 达成后为 achieved，以它为前提的 Intent 由 blocked 变 open。"""
    k.open()
    base = {"premises": [], "risk": "r0", "budget": {"usd_milli": 100, "wall_s": 60}}
    i1 = k.submit(reason(), "p1", "add_intent", {**base, "title": "cut",
                                                 "done": {"judge_id": "replay", "max_attempts": 2}})
    i2 = k.submit(reason(), "p1", "add_intent", {**base, "title": "next", "premises": [i1]})
    assert lv.intent_state(k.state, "p1", i2) == "blocked"
    c = k.art("p1", "authored", b"cand")
    k.verdict("p1", i1, "fail", candidate=c)
    assert lv.levels(k.state, "p1")[i1] == "E0"
    k.verdict("p1", i1, "pass", candidate=k.art("p1", "authored", b"cand2"))
    assert lv.intent_state(k.state, "p1", i1) == "achieved"
    assert lv.intent_state(k.state, "p1", i2) == "open"


def test_valuation_not_in_levels(k):
    """I8 的 M0 落点：expected_gain 不改变任何等级与状态。参考模型性质测试在 CI 常驻。"""
    k.open()
    f = k.obs(); k.verdict("p1", f, "pass")
    base = {"title": "i", "premises": [f], "risk": "r0", "budget": {"usd_milli": 100, "wall_s": 60}}
    a = k.submit(reason(), "p1", "add_intent", {**base, "expected_gain": 0.0})
    b = k.submit(reason(), "p1", "add_intent", {**base, "title": "j", "expected_gain": 99.0})
    st, res = lv.compute(k.state, "p1")
    assert lv.intent_state(k.state, "p1", a) == lv.intent_state(k.state, "p1", b)
    assert lv.gate(k.state, "p1", a) == lv.gate(k.state, "p1", b)


def test_profile_info_from_resource_registry():
    """评审方 #14 必修 1：画像的信息轴取自资源种类登记表（单一事实源）：有 net → partial，只有 workspace → complete。"""
    from paoding_graph.reducer import Config
    k = Kernel(Config(judges=CFG.judges))
    k.open("pa", resource="net")
    k.open("pb", resource="workspace")
    assert k.state["problems"]["pa"]["profile"]["info"] == "partial"
    assert k.state["problems"]["pb"]["profile"]["info"] == "complete"
