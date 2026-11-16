"""参考模型的测试。每个用例注明它对应规格的哪一条验收测试或哪一段文字。

运行：python3 -m unittest -v test_kernel（在本目录下）。
"""
import random
import unittest
from dataclasses import replace

from kernel import (RANK, X, Artifact, Fact, Intent, Opinion, State, Verdict, compute, gate, gate_m0,
                    intent_state, invalidations, rejudge_wanted, validate_add_fact, validate_register)


def V(seq, target, result, judge="replay", version="1", grade="decisive", **kw):
    return Verdict(seq, target, judge, version, grade, result, **kw)


def R(seq, target, session, family, polarity="support", **kw):
    return Opinion(seq, target, polarity, "review", session, family, **kw)


def rank(level):
    return -1 if level == X else RANK[level]


class Hysteresis(unittest.TestCase):
    """3.1.2 的裁决序列与有效裁决；3.3.5 的 2、7。"""

    def run_seq(self, *results):
        st = State(facts={"a": Fact("a")}, verdicts=[V(i + 1, "a", r) for i, r in enumerate(results)])
        return st, compute(st)

    def test_single_verdict_is_taken_as_is(self):
        self.assertEqual(self.run_seq("pass")[1].levels["a"], "E3")
        self.assertEqual(self.run_seq("fail")[1].levels["a"], X)

    def test_one_rerun_failure_only_returns_to_e0(self):
        st, res = self.run_seq("pass", "fail")
        self.assertEqual(res.levels["a"], "E0")
        self.assertIn("a", res.unstable)
        self.assertEqual(rejudge_wanted(st), [("a", "replay", "1", None)])

    def test_two_consecutive_failures_falsify(self):
        st, res = self.run_seq("pass", "fail", "fail")
        self.assertEqual(res.levels["a"], X)
        self.assertNotIn("a", res.unstable)
        self.assertEqual(rejudge_wanted(st), [])

    def test_two_consecutive_passes_restore_e3(self):
        self.assertEqual(self.run_seq("pass", "fail", "pass")[1].levels["a"], "E0")
        st, res = self.run_seq("pass", "fail", "pass", "pass")
        self.assertEqual(res.levels["a"], "E3")
        self.assertNotIn("a", res.unstable)

    def test_automatic_rejudge_stops_at_four_verdicts(self):
        st, res = self.run_seq("pass", "fail", "pass", "fail")
        self.assertEqual(res.levels["a"], "E0")
        self.assertIn("a", res.unstable)
        self.assertEqual(rejudge_wanted(st), [])          # 不再自动复判，交人处理

    def test_flaky_verdict_gives_neither_e3_nor_x(self):
        st, res = self.run_seq("flaky")
        self.assertEqual(res.levels["a"], "E0")
        self.assertNotIn("a", res.unstable)
        st, res = self.run_seq("pass", "flaky")
        self.assertEqual(res.levels["a"], "E0")
        self.assertIn("a", res.unstable)


class BadFactInjection(unittest.TestCase):
    """3.1.5 的 3：A（E3）；B 只由 A 推出；C 由 B 推出且另有判官支持；D 只由 B 推出。"""

    def build(self, *a_results):
        facts = {
            "A": Fact("A", "observation", session="s0"),
            "B": Fact("B", "inference", premises=("A",), session="s1", body_ref="body_B"),
            "C": Fact("C", "inference", premises=("B",), session="s1"),
            "D": Fact("D", "inference", premises=("B",), session="s1", body_ref="body_D"),
        }
        verdicts = [V(i + 1, "A", r) for i, r in enumerate(a_results)] + [V(10, "C", "pass")]
        opinions = [R(11, "B", "s2", "fam1"), R(12, "B", "s3", "fam2"), R(13, "D", "s2", "fam1")]
        intents = {k: Intent(k, "r1", (k[1],)) for k in ("iB", "iC", "iD")}
        return State(facts=facts, verdicts=verdicts, opinions=opinions, intents=intents)

    def states(self, st):
        res = compute(st)
        return res, {k: intent_state(st, res, i) for k, i in st.intents.items()}

    def test_before(self):
        res, intents = self.states(self.build("pass"))
        self.assertEqual(res.levels, {"goal": "E0", "A": "E3", "B": "E2", "C": "E3", "D": "E1"})
        self.assertEqual(set(intents.values()), {"open"})

    def test_two_failures_falsify_a_and_spare_c(self):
        st = self.build("pass", "fail", "fail")
        res, intents = self.states(st)
        self.assertEqual(res.levels, {"goal": "E0", "A": X, "B": "E0", "C": "E3", "D": "E0"})
        self.assertEqual(invalidations(st, "A"), {"B", "D"})
        self.assertEqual(intents, {"iB": "blocked", "iC": "open", "iD": "blocked"})

    def test_single_failure_degrades_without_falsifying(self):
        res, intents = self.states(self.build("pass", "fail"))
        self.assertEqual(res.levels, {"goal": "E0", "A": "E0", "B": "E0", "C": "E3", "D": "E0"})
        self.assertIn("A", res.unstable)
        self.assertEqual(intents, {"iB": "blocked", "iC": "open", "iD": "blocked"})

    def test_m0_form(self):
        """M0 只有判官支持：A 被证伪后，以它为前提的 Intent 被放弃；只失败一次时 r1 被阻塞。"""
        for results, r1_state in ((("pass", "fail", "fail"), "abandoned"), (("pass", "fail"), "blocked")):
            st = State(facts={"A": Fact("A")}, verdicts=[V(i + 1, "A", r) for i, r in enumerate(results)],
                       intents={"i1": Intent("i1", "r1", ("A",)), "i0": Intent("i0", "r0", ("A",))})
            res = compute(st)
            self.assertEqual(intent_state(st, res, st.intents["i1"]), r1_state)
            # r0 永不阻塞：只要前提不是 X
            self.assertEqual(intent_state(st, res, st.intents["i0"]),
                             "abandoned" if r1_state == "abandoned" else "open")


class CyclicSupport(unittest.TestCase):
    """3.1.5 的 4：A 的支持以 B 为前提，B 的支持以 A 为前提。"""

    def build(self):
        facts = {"A": Fact("A", "inference", session="sa"), "B": Fact("B", "inference", session="sb")}
        opinions = [R(1, "A", "s1", "fam1", premises=("B",)), R(2, "A", "s2", "fam2", premises=("B",)),
                    R(3, "B", "s1", "fam1", premises=("A",)), R(4, "B", "s2", "fam2", premises=("A",))]
        return State(facts=facts, opinions=opinions)

    def test_cycle_gets_no_level(self):
        res = compute(self.build())
        self.assertEqual((res.levels["A"], res.levels["B"]), ("E0", "E0"))

    def test_cycle_guard_does_not_block_grounded_support(self):
        st = self.build()
        st.verdicts.append(V(5, "A", "pass"))
        res = compute(st)
        self.assertEqual((res.levels["A"], res.levels["B"]), ("E3", "E2"))

    def test_m0_form_forward_reference_is_rejected(self):
        self.assertEqual(validate_add_fact({}, {"n1": "E0"}, "p1", "inference", False, ("n2",), ()), "unknown_ref")


class EchoChamber(unittest.TestCase):
    """5.2 场景 1 与 3.1.4 的"独立支持如何机械判定"。"""

    def level(self, *opinions, premise_level=None):
        facts = {"f": Fact("f", "inference", session="s0", body_ref="body_f")}
        verdicts = []
        if premise_level:
            facts["p"] = Fact("p", "inference", session="sp")
            facts["f"] = replace(facts["f"], premises=("p",))
            opinions = opinions + {"E1": (R(90, "p", "s8", "fam1"),), "E3": ()}[premise_level]
            verdicts = [V(91, "p", "pass")] if premise_level == "E3" else []
        return compute(State(facts=facts, opinions=list(opinions), verdicts=verdicts)).levels["f"]

    def test_same_family_same_evidence_stops_at_e1(self):
        self.assertEqual(self.level(R(1, "f", "s1", "fam1"), R(2, "f", "s2", "fam1")), "E1")

    def test_different_family_reaches_e2(self):
        self.assertEqual(self.level(R(1, "f", "s1", "fam1"), R(2, "f", "s2", "fam2")), "E2")

    def test_same_family_with_new_exec_evidence_reaches_e2(self):
        s1 = R(1, "f", "s1", "fam1", exec_evidence=frozenset({"a1"}))
        self.assertEqual(self.level(s1, R(2, "f", "s2", "fam1", exec_evidence=frozenset({"a1", "a2"}))), "E2")
        self.assertEqual(self.level(s1, R(2, "f", "s2", "fam1", exec_evidence=frozenset({"a1"}))), "E1")

    def test_one_session_cannot_confirm_itself_twice(self):
        self.assertEqual(self.level(R(1, "f", "s1", "fam1"), R(2, "f", "s1", "fam2")), "E1")

    def test_proposer_and_readers_of_the_body_are_not_independent(self):
        self.assertEqual(self.level(R(1, "f", "s0", "fam2")), "E0")
        self.assertEqual(self.level(R(1, "f", "s1", "fam2", context=frozenset({"body_f"}))), "E0")

    def test_review_without_admissible_evidence_does_not_count(self):
        self.assertEqual(self.level(R(1, "f", "s1", "fam1", has_evidence=False)), "E0")

    def test_trust_does_not_exceed_premises(self):
        pair = (R(1, "f", "s1", "fam1"), R(2, "f", "s2", "fam2"))
        self.assertEqual(self.level(*pair, premise_level="E1"), "E1")
        self.assertEqual(self.level(*pair, premise_level="E3"), "E2")


class ConsumptionGate(unittest.TestCase):
    """3.1.3 的消费门表；3.1.5 的 7、9。"""

    def setUp(self):
        self.facts = {"e0": Fact("e0", "inference", session="s0"), "e1": Fact("e1", "inference", session="s0"),
                      "e2": Fact("e2", "inference", session="s0"), "e3": Fact("e3"), "x": Fact("x")}
        self.base = dict(
            verdicts=[V(1, "e3", "pass"), V(2, "x", "fail")],
            opinions=[R(3, "e1", "s1", "fam1"), R(4, "e2", "s1", "fam1"), R(5, "e2", "s2", "fam2")])

    def state_of(self, intent, **extra):
        st = State(facts=dict(self.facts), intents={intent.id: intent}, **{**self.base, **extra})
        res = compute(st)
        self.assertEqual({k: res.levels[k] for k in self.facts},
                         {"e0": "E0", "e1": "E1", "e2": "E2", "e3": "E3", "x": X})
        return intent_state(st, res, intent), gate(st, res, intent)

    def test_r0_only_needs_non_falsified_premises(self):
        self.assertEqual(self.state_of(Intent("i", "r0", ("e0",))), ("open", True))
        self.assertEqual(self.state_of(Intent("i", "r0", ("x",))), ("abandoned", False))

    def test_r1_needs_e1_without_dispute(self):
        self.assertEqual(self.state_of(Intent("i", "r1", ("e0",))), ("blocked", False))
        self.assertEqual(self.state_of(Intent("i", "r1", ("e1",))), ("open", True))
        contra = self.base["opinions"] + [R(9, "e1", "s3", "fam2", polarity="contradict")]
        self.assertEqual(self.state_of(Intent("i", "r1", ("e1",)), opinions=contra), ("blocked", False))

    def test_r2_needs_e3_and_approval(self):
        i = Intent("i", "r2", ("e3",))
        self.assertEqual(self.state_of(i), ("needs_human", False))
        self.assertEqual(self.state_of(i, approvals={"i": [20]}), ("open", True))

    def test_r2_accepts_e2_only_with_a_waiver(self):
        i = Intent("i", "r2", ("e2",))
        self.assertEqual(self.state_of(i, approvals={"i": [20]}), ("needs_human", False))
        self.assertEqual(self.state_of(i, approvals={"i": [20]}, waivers={"i": {"e2"}}), ("open", True))
        low = Intent("i", "r2", ("e1",))
        self.assertEqual(self.state_of(low, approvals={"i": [20]}, waivers={"i": {"e1"}}), ("blocked", False))

    def test_r2_approval_covers_one_lease_only(self):
        i = Intent("i", "r2", ("e3",))
        self.assertEqual(self.state_of(i, approvals={"i": [20]}, leases={"i": [21]}), ("needs_human", False))
        self.assertEqual(self.state_of(i, approvals={"i": [20, 22]}, leases={"i": [21]}), ("open", True))

    def test_scope_request_waits_for_human(self):
        i = Intent("i", "r0", ("e0",), needs_scope=True)
        self.assertEqual(self.state_of(i), ("needs_human", False))
        self.assertEqual(self.state_of(i, approvals={"i": [20]}, leases={"i": [21]}), ("open", True))

    def test_checked_intent_as_premise_must_be_achieved(self):
        dep, nxt = Intent("dep", "r0", (), done="replay"), Intent("nxt", "r0", ("dep",))
        for verdicts, dep_state, nxt_state in (
                ([], "open", "blocked"),
                ([V(30, "dep", "fail", candidate="c1")], "open", "blocked"),
                ([V(30, "dep", "fail", candidate="c1"), V(31, "dep", "pass", candidate="c2")], "achieved", "open")):
            st = State(intents={"dep": dep, "nxt": nxt}, verdicts=verdicts)
            res = compute(st)
            self.assertEqual((intent_state(st, res, dep), intent_state(st, res, nxt)), (dep_state, nxt_state))
            self.assertNotEqual(res.levels["dep"], X)        # 目标没有 X，失败的候选只累计次数


class GoalValidityAndRulings(unittest.TestCase):
    def test_goal_is_judged_per_candidate_and_never_falsified(self):
        st = State(verdicts=[V(1, "goal", "fail", judge="exact_match", candidate="c1")])
        self.assertEqual(compute(st).levels["goal"], "E0")
        st.verdicts.append(V(2, "goal", "pass", judge="exact_match", candidate="c2"))
        self.assertEqual(compute(st).levels["goal"], "E3")

    def test_expiry_is_not_falsification(self):
        """3.1.3 有效期；5.1 场景 10。通过与失败的裁决同样过期。"""
        for result, fresh in (("pass", "E3"), ("fail", X)):
            st = State(facts={"n": Fact("n")}, verdicts=[V(1, "n", result, judge="probe", expires_at=100)], now=50)
            self.assertEqual(compute(st).levels["n"], fresh)
            st.now = 100
            res = compute(st)
            self.assertEqual(res.levels["n"], "E0")
            self.assertIn("n", res.stale)
        st.verdicts.append(V(2, "n", "pass", judge="probe", expires_at=300))
        self.assertEqual(compute(st).levels["n"], "E3")           # 复检后按新的裁决计

    def test_revoking_a_judge_version_withdraws_its_support(self):
        """3.3.5 的 3。"""
        st = State(facts={"n": Fact("n")}, verdicts=[V(1, "n", "pass")], intents={"i": Intent("i", "r1", ("n",))})
        self.assertEqual(intent_state(st, compute(st), st.intents["i"]), "open")
        st.revoked.add(("replay", "1"))
        res = compute(st)
        self.assertEqual((res.levels["n"], intent_state(st, res, st.intents["i"])), ("E0", "blocked"))

    def test_human_refutation_overrides_a_judge(self):
        st = State(facts={"n": Fact("n")}, verdicts=[V(1, "n", "pass")],
                   opinions=[Opinion(2, "n", "contradict", "human")])
        self.assertEqual(compute(st).levels["n"], X)

    def test_human_upholding_dismisses_failed_verdicts(self):
        verdicts = [V(1, "n", "pass"), V(2, "n", "fail", dismissed=True), V(3, "n", "fail", dismissed=True)]
        self.assertEqual(compute(State(facts={"n": Fact("n")}, verdicts=verdicts)).levels["n"], "E3")


class ConsistentJudge(unittest.TestCase):
    """3.1.4：E3d 是相符性判官通过；转 E3 只能靠判定性判官；相符性判官的失败只产生争议。"""

    def state(self, *verdicts):
        return State(facts={"n": Fact("n", "inference", session="s0")}, verdicts=list(verdicts),
                     opinions=[R(50, "n", "s1", "fam1")], intents={"i": Intent("i", "r2", ("n",))},
                     approvals={"i": [60]})

    def test_consistent_pass_is_e3d_until_a_decisive_pass(self):
        st = self.state(V(1, "n", "pass", judge="metric", grade="consistent"))
        self.assertEqual(compute(st).levels["n"], "E3d")
        st.verdicts.append(V(2, "n", "pass", judge="counterfactual"))
        self.assertEqual(compute(st).levels["n"], "E3")

    def test_consistent_failure_disputes_without_falsifying(self):
        res = compute(self.state(V(1, "n", "fail", judge="metric", grade="consistent")))
        self.assertEqual(res.levels["n"], "E1")               # 按剩余支持计
        self.assertIn("n", res.disputed)

    def test_failed_recheck_withdraws_e3d(self):
        res = compute(self.state(V(1, "n", "pass", judge="metric", grade="consistent"),
                                 V(2, "n", "fail", judge="metric", grade="consistent")))
        self.assertEqual(res.levels["n"], "E1")
        self.assertIn("n", res.unstable)

    def test_r2_on_e3d_still_needs_a_waiver(self):
        st = self.state(V(1, "n", "pass", judge="metric", grade="consistent"))
        intent = st.intents["i"]
        self.assertEqual(intent_state(st, compute(st), intent), "needs_human")
        st.waivers["i"] = {"n"}
        self.assertEqual(intent_state(st, compute(st), intent), "open")


class WalkthroughCtf(unittest.TestCase):
    """6.1 的等级与状态变化（M0 能力）。"""

    def test_steps(self):
        st = State(facts={"n1": Fact("n1", session="boot"),
                          "n2": Fact("n2", "inference", premises=("n1",), session="boot")})
        self.assertEqual(compute(st).levels["n1"], "E0")                      # 第 4 步
        st.verdicts.append(V(5, "n1", "pass"))                                # 第 5 步
        res = compute(st)
        self.assertEqual((res.levels["n1"], res.levels["n2"]), ("E3", "E0"))
        st.intents["i4"] = Intent("i4", "r0", (), done="replay")              # 第 10 步
        st.intents["i5"] = Intent("i5", "r0", ("i4",), needs_scope=True)      # 第 12 步
        st.verdicts.append(V(11, "i4", "pass", candidate="fetch.sh"))         # 第 11 步
        res = compute(st)
        self.assertEqual(intent_state(st, res, st.intents["i4"]), "achieved")
        self.assertEqual(intent_state(st, res, st.intents["i5"]), "needs_human")
        st.approvals["i5"] = [13]                                             # 第 13 步
        self.assertEqual(intent_state(st, compute(st), st.intents["i5"]), "open")
        st.verdicts.append(V(14, "goal", "pass", judge="exact_match", candidate="answer"))
        self.assertEqual(compute(st).levels["goal"], "E3")                    # 第 15 步


class WalkthroughOps(unittest.TestCase):
    """6.2 的等级与状态变化（完整版能力）。"""

    def build(self):
        facts = {k: Fact(k, session="boot") for k in ("n1", "n2", "n6", "n7")}
        facts["n10"] = Fact("n10", "inference", premises=("n1", "n2", "n6"), session="e4", body_ref="body_n10")
        verdicts = [V(1, "n1", "pass", judge="record_match"), V(2, "n2", "pass", judge="record_match"),
                    V(3, "n6", "pass", judge="record_match"),
                    V(4, "n7", "pass", judge="probe", expires_at=600)]
        i7 = Intent("i7", "r2", ("n10",), done="metric_assert", tests=("n10",))
        return State(facts=facts, verdicts=verdicts, intents={"i7": i7})

    def test_main_path(self):
        st = self.build()
        i7 = st.intents["i7"]
        res = compute(st)
        self.assertEqual((res.levels["n7"], res.levels["n10"]), ("E3", "E0"))              # 第 5 步
        self.assertEqual(intent_state(st, res, i7), "blocked")                             # 第 6 步
        st.opinions.append(R(7, "n10", "v1", "fam2"))                                      # 第 7 步
        self.assertEqual(compute(st).levels["n10"], "E1")
        st.opinions.append(R(8, "n10", "v2", "fam2", exec_evidence=frozenset({"a_new"})))
        self.assertEqual(compute(st).levels["n10"], "E2")
        contra = R(9, "n10", "idler", "fam3", polarity="contradict")                       # 第 8 步
        st.opinions.append(contra)
        self.assertIn("n10", compute(st).disputed)
        st.opinions[-1] = replace(contra, dismissed=True)
        res = compute(st)
        self.assertNotIn("n10", res.disputed)
        self.assertEqual(intent_state(st, res, i7), "needs_human")                         # 第 9 步
        st.approvals["i7"], st.waivers["i7"] = [10], {"n10"}                               # 第 10 步
        self.assertEqual(intent_state(st, compute(st), i7), "open")
        st.leases["i7"] = [11]                                                             # 第 11 步
        st.verdicts.append(V(12, "i7", "pass", judge="metric_assert", candidate="rollback"))
        res = compute(st)                                                                  # 第 12 步
        self.assertEqual(intent_state(st, res, i7), "achieved")
        self.assertEqual(res.levels["n10"], "E3d")
        st.now = 600                                                                       # n7 的判据到期
        res = compute(st)
        self.assertEqual(res.levels["n7"], "E0")
        self.assertIn("n7", res.stale)

    def test_failed_prediction_branch(self):
        st = self.build()
        st.opinions += [R(7, "n10", "v1", "fam2"), R(8, "n10", "v2", "fam1")]
        st.approvals["i7"], st.waivers["i7"], st.leases["i7"] = [10], {"n10"}, [11]
        st.verdicts.append(V(12, "i7", "fail", judge="metric_assert", candidate="rollback"))
        res = compute(st)
        self.assertEqual(res.levels["n10"], "E2")              # 一条相符性反证不证伪
        self.assertIn("n10", res.disputed)
        self.assertEqual(intent_state(st, res, st.intents["i7"]), "needs_human")      # 不可逆动作不自动重做

    def test_tests_field_is_inert_without_approval(self):
        st = self.build()
        st.verdicts.append(V(12, "i7", "pass", judge="metric_assert", candidate="rollback"))
        self.assertEqual(compute(st).levels["n10"], "E0")


class ForgedReferences(unittest.TestCase):
    """3.2.5 的 2 的前四种形态；3.4.5 的 4。第五种（写假文件后读出）要有真实的执行层。"""

    arts = {"a1": Artifact("a1", "exec"), "a2": Artifact("a2", "authored"), "a3": Artifact("a3", "exec", "p2"),
            "a4": Artifact("a4", "input")}

    def check(self, claim_type, has_check, premises, grounds, levels=None):
        return validate_add_fact(self.arts, levels or {"n1": "E3", "nx": X}, "p1", claim_type, has_check,
                                 premises, grounds)

    def test_reject_codes(self):
        self.assertEqual(self.check("observation", True, (), ("a9",)), "unknown_ref")
        self.assertEqual(self.check("observation", True, (), ("a2",)), "inadmissible_class")
        self.assertEqual(self.check("observation", True, (), ("a3",)), "scope_mismatch")
        self.assertEqual(self.check("observation", True, (), ()), "missing_evidence")
        self.assertEqual(self.check("observation", False, (), ("a1",)), "missing_evidence")
        self.assertEqual(self.check("inference", False, (), ()), "missing_evidence")
        self.assertEqual(self.check("inference", False, ("nx",), ()), "stale_premise")
        self.assertEqual(self.check("observation", True, (), ("a1",)), "ok")
        self.assertEqual(self.check("observation", True, (), ("a4",)), "ok")
        self.assertEqual(self.check("inference", False, ("n1",), ()), "ok")

    def test_only_component_tokens_can_register(self):
        for cls in ("exec", "judge", "input", "authored"):
            self.assertEqual(validate_register("task", cls), "forbidden_op")
        self.assertEqual(validate_register("adapter", "exec"), "forbidden_op")
        self.assertEqual(validate_register("executor", "exec"), "ok")
        self.assertEqual(validate_register("adapter", "authored"), "ok")


class Properties(unittest.TestCase):
    """随机状态上的性质。对应 3.1.3"最小不动点唯一，与迭代顺序无关"与 3.1.5 的 4（重算终止）。"""

    def random_state(self, rng, reviews=True):
        n = rng.randint(2, 9)
        ids = [f"n{i}" for i in range(n)]
        facts = {}
        for i, fid in enumerate(ids):
            premises = tuple(rng.sample(ids[:i], rng.randint(0, min(2, i))))
            facts[fid] = Fact(fid, rng.choice(("observation", "inference")), premises,
                              f"s{rng.randint(0, 3)}", rng.choice((None, f"body_{fid}")))
        seq, verdicts, opinions = 0, [], []
        for fid in ids:
            for _ in range(rng.choice((0, 0, 1, 1, 2, 3))):
                seq += 1
                verdicts.append(V(seq, fid, rng.choice(("pass", "pass", "pass", "fail", "flaky")),
                                  grade="decisive" if reviews is False else rng.choice(("decisive", "consistent")),
                                  version=rng.choice(("1", "2"))))
        if reviews:
            for _ in range(rng.randint(0, 3 * n)):
                seq += 1
                target = rng.choice(ids)
                opinions.append(R(seq, target, f"s{rng.randint(0, 5)}", rng.choice(("fam1", "fam2")),
                                  polarity=rng.choice(("support", "support", "support", "contradict")),
                                  premises=tuple(rng.sample(ids, rng.randint(0, 2))),      # 允许成环
                                  context=frozenset(rng.sample([f"body_{x}" for x in ids], rng.randint(0, 2))),
                                  exec_evidence=frozenset(rng.sample(["a1", "a2", "a3"], rng.randint(0, 2)))))
        intents = {f"i{k}": Intent(f"i{k}", rng.choice(("r0", "r1", "r2")),
                                   tuple(rng.sample(ids, rng.randint(0, 2))), needs_scope=rng.random() < 0.2)
                   for k in range(3)}
        approvals = {k: [seq + 1] for k in intents if rng.random() < 0.5}
        return State(facts=facts, verdicts=verdicts, opinions=opinions, intents=intents, approvals=approvals)

    def test_fixpoint_is_unique_and_terminates(self):
        rng = random.Random(20261117)
        for _ in range(400):
            st = self.random_state(rng)
            base = compute(st)
            for _ in range(3):
                order = list(st.facts)
                rng.shuffle(order)
                self.assertEqual(compute(st, order), base)

    def test_trust_never_exceeds_premises(self):
        rng = random.Random(7)
        for _ in range(400):
            st = self.random_state(rng)
            levels = compute(st).levels
            for fid, fact in st.facts.items():
                if levels[fid] in ("E1", "E2"):
                    for p in fact.premises:
                        self.assertGreaterEqual(rank(levels[p]), rank(levels[fid]))

    def test_adding_a_supporting_review_never_lowers_a_level(self):
        rng = random.Random(11)
        for _ in range(400):
            st = self.random_state(rng)
            before = compute(st).levels
            target = rng.choice(sorted(st.facts))
            st.opinions.append(R(10_000, target, "s_new", "fam3", premises=tuple(rng.sample(sorted(st.facts), 1))))
            after = compute(st).levels
            for fid in st.facts:
                self.assertGreaterEqual(rank(after[fid]), rank(before[fid]))

    def test_removing_a_falsification_never_lowers_a_level(self):
        rng = random.Random(13)
        for _ in range(400):
            st = self.random_state(rng)
            now = compute(st).levels
            for node in [f for f in st.facts if now[f] == X]:
                without = replace(st, verdicts=[v for v in st.verdicts
                                                if not (v.target == node and v.result == "fail")])
                then = compute(without).levels
                for fid in st.facts:
                    self.assertGreaterEqual(rank(then[fid]), rank(now[fid]))

    def test_m0_is_the_judge_only_special_case(self):
        """只有判定性判官支持时，等级只取 X、E3、E0，完整版消费门与 M0 消费门逐例相同。"""
        rng = random.Random(17)
        for _ in range(400):
            st = self.random_state(rng, reviews=False)
            res = compute(st)
            self.assertLessEqual(set(res.levels[f] for f in st.facts), {X, "E3", "E0"})
            for intent in st.intents.values():
                self.assertEqual(gate(st, res, intent), gate_m0(st, res, intent))


if __name__ == "__main__":
    unittest.main()
