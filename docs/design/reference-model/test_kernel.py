"""参考模型的测试。每个用例注明它对应规格的哪一条验收测试或哪一段文字。

运行：python3 -m unittest -v test_kernel（在本目录下）。
"""
import random
import unittest
from dataclasses import replace

import market_walkthrough
from kernel import (RANK, X, Artifact, Fact, Intent, Opinion, Seal, State, Valuation, Verdict, achieved_at,
                    approval_card, calibration, can_deref, card_hash, claimable, compute, counts_as_progress, escalated, failed_last, gate,
                    gate_m0, holdout, intent_state, invalidations, knot, mountable, must_escalate, rejudge_wanted,
                    reroutes, seal_check, show_body, terminal, unlocks, validate_add_fact, validate_follow,
                    validate_decision, validate_register, validate_register_excerpt, validate_rollback)


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
                      "e2": Fact("e2", "inference", session="s0"), "e3": Fact("e3", control=True),
                      "x": Fact("x")}
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


def random_state(rng, reviews=True, control=None):
    """随机状态。control：None 表示每条论断随机带或不带对照；True 表示全部带对照。"""
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
    for fid in ids:
        facts[fid] = replace(facts[fid], control=rng.random() < 0.5 if control is None else control)
    return State(facts=facts, verdicts=verdicts, opinions=opinions, intents=intents, approvals=approvals)


class Properties(unittest.TestCase):
    """随机状态上的性质。对应 3.1.3"最小不动点唯一，与迭代顺序无关"与 3.1.5 的 4（重算终止）。"""

    def random_state(self, rng, reviews=True, control=None):
        return random_state(rng, reviews, control)

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
        """只有判定性判官支持、观察都带对照时，等级只取 X、E3、E0，完整版消费门与 M0 消费门逐例相同。
        不带对照时两者唯一的差别是 r2 对观察类前提的要求，见 ControlledPredicates。"""
        rng = random.Random(17)
        for _ in range(400):
            st = self.random_state(rng, reviews=False, control=True)
            res = compute(st)
            self.assertLessEqual(set(res.levels[f] for f in st.facts), {X, "E3", "E0"})
            for intent in st.intents.values():
                self.assertEqual(gate(st, res, intent), gate_m0(st, res, intent))


class ControlledPredicates(unittest.TestCase):
    """对照判据（3.3.3）进消费门与续期门的进展：r2 的观察类前提要带对照，或由人豁免。"""

    def states(self, fact, **extra):
        st = State(facts={"o": fact}, verdicts=[V(1, "o", "pass")],
                   intents={"i": Intent("i", "r2", ("o",))}, approvals={"i": [5]}, **extra)
        res = compute(st)
        self.assertEqual(res.levels["o"], "E3")
        return st, res, intent_state(st, res, st.intents["i"]), gate(st, res, st.intents["i"])

    def test_r2_asks_observation_premises_for_a_control(self):
        st, res, state, ok = self.states(Fact("o"))
        self.assertEqual((state, ok), ("needs_human", False))
        self.assertTrue(gate_m0(st, res, st.intents["i"]))        # 与 M0 消费门唯一的差别就在这里
        self.assertEqual(self.states(Fact("o", control=True))[2:], ("open", True))

    def test_a_waiver_stands_in_for_the_control(self):
        self.assertEqual(self.states(Fact("o"), waivers={"i": {"o"}})[2:], ("open", True))

    def test_inference_premises_are_not_asked_for_a_control(self):
        self.assertEqual(self.states(Fact("o", "inference"))[2:], ("open", True))

    def test_r0_and_r1_do_not_need_a_control(self):
        for risk in ("r0", "r1"):
            st = State(facts={"o": Fact("o")}, verdicts=[V(1, "o", "pass")], intents={"i": Intent("i", risk, ("o",))})
            self.assertTrue(gate(st, compute(st), st.intents["i"]))

    def test_progress_counts_controlled_observations_and_achieved_intents_only(self):
        st = State(facts={"plain": Fact("plain"), "ctl": Fact("ctl", control=True),
                          "inf": Fact("inf", "inference")},
                   intents={"cut": Intent("cut", done="replay"), "loose": Intent("loose"),
                            "open": Intent("open", done="replay")},
                   verdicts=[V(1, "plain", "pass"), V(2, "ctl", "pass"), V(3, "inf", "pass"),
                             V(4, "cut", "pass", candidate="c")])
        res = compute(st)
        got = {k: counts_as_progress(st, res, k) for k in ("plain", "ctl", "inf", "cut", "loose", "open")}
        self.assertEqual(got, {"plain": False, "ctl": True, "inf": False, "cut": True, "loose": False,
                               "open": False})


class Knot(unittest.TestCase):
    """3.1.7 的难点标记、换缝与升档护栏；4.1 的认领规则。"""

    def flags(self, st, key="i"):
        res = compute(st)
        return knot(st, res, st.intents[key]), claimable(st, res, st.intents[key])

    def one(self, **kw):
        return State(intents={"i": Intent("i", "r0", (), budget=1000)}, **kw)

    def test_a_failed_or_empty_handed_lease_marks_a_knot(self):
        self.assertEqual(self.flags(self.one()), (False, True))
        for outcome, marked in (("failed", True), ("nothing", True), ("found", False), ("expired", False)):
            self.assertEqual(self.flags(self.one(outcomes={"i": [(5, outcome)]})), (marked, not marked))

    def test_only_the_last_outcome_counts(self):
        self.assertEqual(self.flags(self.one(outcomes={"i": [(5, "failed"), (9, "found")]})), (False, True))
        self.assertEqual(self.flags(self.one(outcomes={"i": [(5, "found"), (9, "nothing")]})), (True, False))

    def test_a_disputed_or_unstable_premise_marks_a_knot(self):
        facts = {"d": Fact("d", "inference", session="s0"), "u": Fact("u"), "ok": Fact("ok")}
        st = State(facts=facts, verdicts=[V(1, "u", "pass"), V(2, "u", "fail"), V(3, "ok", "pass")],
                   opinions=[R(4, "d", "s1", "fam1"), R(5, "d", "s2", "fam2", polarity="contradict")],
                   intents={"id": Intent("id", "r0", ("d",)), "iu": Intent("iu", "r0", ("u",)),
                            "iok": Intent("iok", "r0", ("ok",))})
        res = compute(st)
        self.assertIn("d", res.disputed)
        self.assertIn("u", res.unstable)
        self.assertEqual([knot(st, res, st.intents[k]) for k in ("id", "iu", "iok")], [True, True, False])

    def test_a_lease_that_lost_its_premise_marks_a_knot(self):
        self.assertEqual(self.flags(self.one(premise_lost={"i"})), (True, False))

    def test_an_observation_achieved_after_the_failure_clears_it(self):
        look = Intent("look", "r0", (), done="replay", budget=500, follows=("i", "observe"))
        for seq, marked in ((8, False), (3, True)):               # 失败发生在 seq 5
            st = self.one(outcomes={"i": [(5, "failed")]})
            st.intents["look"] = look
            self.assertEqual(self.flags(st), (True, False))       # 观察 Intent 达成之前，原 Intent 不认领
            st.verdicts.append(V(seq, "look", "pass", candidate="probe"))
            self.assertEqual(achieved_at(st, look), seq)
            self.assertEqual(self.flags(st), (marked, not marked))

    def test_an_explicit_escalation_clears_it_and_picks_the_strong_tier(self):
        st = self.one(outcomes={"i": [(5, "failed")]}, escalations={"i": [7]})
        self.assertEqual(self.flags(st), (False, True))
        self.assertTrue(escalated(st, st.intents["i"]))
        st.outcomes["i"].append((9, "failed"))                    # 升档后再败：又是难点，升档不延续
        self.assertEqual(self.flags(st), (True, False))
        self.assertFalse(escalated(st, st.intents["i"]))
        self.assertFalse(escalated(self.one(escalations={"i": [7]}), st.intents["i"]))

    def test_two_reroutes_without_a_solution_force_escalation(self):
        chain = {"i0": Intent("i0"), "i1": Intent("i1", follows=("i0", "reroute")),
                 "i2": Intent("i2", follows=("i1", "reroute"))}
        st = State(intents=chain, abandoned={"i0", "i1"},
                   outcomes={"i0": [(3, "failed")], "i1": [(6, "failed")], "i2": [(9, "failed")]})
        res = compute(st)
        self.assertEqual([reroutes(st, chain[k]) for k in ("i0", "i1", "i2")], [0, 1, 2])
        self.assertTrue(failed_last(st, chain["i2"]) and must_escalate(st, chain["i2"]))
        self.assertEqual((knot(st, res, chain["i2"]), claimable(st, res, chain["i2"])), (False, True))
        self.assertTrue(escalated(st, chain["i2"]))
        once = State(intents={k: chain[k] for k in ("i0", "i1")}, abandoned={"i0"},
                     outcomes={"i0": [(3, "failed")], "i1": [(6, "failed")]})
        self.assertFalse(must_escalate(once, chain["i1"]))        # 只换过一次缝：仍交 Reason 决定
        self.assertEqual(self.flags(once, "i1"), (True, False))

    def test_terminal_intents_carry_no_knot(self):
        st = State(intents={"done": Intent("done", done="replay"), "gone": Intent("gone")},
                   verdicts=[V(9, "done", "pass", candidate="c")], abandoned={"gone"},
                   outcomes={"done": [(5, "failed")], "gone": [(5, "failed")]})
        res = compute(st)
        self.assertEqual([knot(st, res, i) for i in st.intents.values()], [False, False])

    def test_observation_intents_are_validated(self):
        st = self.one(outcomes={"i": [(5, "failed")]})
        ok = Intent("look", "r0", (), done="replay", budget=500, follows=("i", "observe"))
        self.assertEqual(validate_follow(st, ok), "ok")
        self.assertEqual(validate_follow(st, replace(ok, budget=501)), "schema_error")     # 预算超过原 Intent 的一半
        self.assertEqual(validate_follow(st, replace(ok, done=None)), "schema_error")      # 观察 Intent 必须带判据
        self.assertEqual(validate_follow(st, replace(ok, risk="r1")), "schema_error")      # 只能是 r0
        self.assertEqual(validate_follow(st, replace(ok, follows=("nope", "observe"))), "unknown_ref")
        self.assertEqual(validate_follow(st, replace(ok, follows=("i", "peek"))), "schema_error")
        self.assertEqual(validate_follow(st, Intent("new", "r1", follows=("i", "reroute"))), "ok")
        self.assertEqual(validate_follow(st, Intent("plain")), "ok")

    def test_difficulty_signals_never_reach_levels_or_the_gate(self):
        rng = random.Random(23)
        for _ in range(200):
            st = random_state(rng)
            before = compute(st)
            gates = {k: (gate(st, before, i), intent_state(st, before, i)) for k, i in st.intents.items()}
            st.outcomes = {k: [(900 + n, rng.choice(("failed", "nothing", "found", "expired")))
                               for n in range(rng.randint(0, 3))] for k in st.intents}
            st.premise_lost = {k for k in st.intents if rng.random() < 0.3}
            st.escalations = {k: [rng.randint(890, 910)] for k in st.intents if rng.random() < 0.3}
            after = compute(st)
            self.assertEqual(after, before)
            self.assertEqual({k: (gate(st, after, i), intent_state(st, after, i)) for k, i in st.intents.items()},
                             gates)


class Unlocks(unittest.TestCase):
    """3.1.7 的关节度：以 i 为前提（含经带判据的 Intent 传递）的 blocked Intent 数。"""

    def test_counts_blocked_dependents_transitively(self):
        intents = {"a": Intent("a", done="replay"), "b": Intent("b", premises=("a",), done="replay"),
                   "c": Intent("c", premises=("b",)), "d": Intent("d", premises=("a",)), "e": Intent("e")}
        st = State(intents=intents)
        res = compute(st)
        self.assertEqual([unlocks(st, res, intents[k]) for k in "abcde"], [3, 1, 0, 0, 0])
        st.verdicts.append(V(1, "a", "pass", candidate="c1"))     # a 达成：b 与 d 放行，只剩 c 被 b 挡着
        res = compute(st)
        self.assertEqual([unlocks(st, res, intents[k]) for k in "ab"], [1, 1])


class JudgeAssets(unittest.TestCase):
    """3.3.2 判官资产两级；3.3.5 的 6 与 9。"""

    def test_structural_assets_mount_read_only_in_every_container(self):
        for container in ("model", "exec", "judge"):
            self.assertTrue(mountable(container, "a_12"))
        self.assertTrue(can_deref("adapter", "a_12"))

    def test_sealed_assets_only_reach_the_judge(self):
        self.assertEqual([mountable(c, "vault:answer") for c in ("model", "exec", "judge")], [False, False, True])
        self.assertEqual([can_deref(a, "vault:answer") for a in ("adapter", "executor", "sinan", "task", "judge")],
                         [False, False, False, False, True])

    def test_a_vault_reference_is_not_an_artifact(self):
        arts = {"a1": Artifact("a1", "exec")}
        self.assertEqual(validate_add_fact(arts, {}, "p1", "observation", True, (), ("vault:answer",)), "unknown_ref")

    def test_judge_output_that_touched_the_vault_is_withheld_from_tasks(self):
        plain = Artifact("a7", "judge", touched=("a_3",))
        secret = Artifact("a8", "judge", touched=("a_3", "vault:answer"))
        self.assertTrue(show_body("task", plain))
        self.assertEqual([show_body(a, secret) for a in ("task", "adapter", "judge", "human")],
                         [False, False, True, True])


class Seals(unittest.TestCase):
    """2.4 题界与封存；3.1.5 的 10 到 12。"""

    seal = Seal("child", 120, "h120", "state_ok", "reducer_1", "solved")

    def test_only_the_graph_registers_an_excerpt_and_only_after_replay(self):
        self.assertEqual(validate_register_excerpt("graph", self.seal, "state_ok"), "ok")
        self.assertEqual(validate_register_excerpt("graph", self.seal, "state_other"), "bad_seal")
        for actor in ("adapter", "human", "executor", "judge", "task"):
            self.assertEqual(validate_register_excerpt(actor, self.seal, "state_ok"), "forbidden_op")

    def test_levels_do_not_cross_the_problem_boundary(self):
        """摘录在接收题里是 input 类材料：可以作 grounds，但论断仍要由本题的判官重新判定。"""
        arts = {"a_ex": Artifact("a_ex", "input")}
        self.assertEqual(validate_add_fact(arts, {}, "p1", "observation", True, (), ("a_ex",)), "ok")
        st = State(facts={"n": Fact("n")})
        self.assertEqual(compute(st).levels["n"], "E0")           # 来源题里它是 E3，这里从 E0 起
        st.verdicts.append(V(1, "n", "pass"))
        self.assertEqual(compute(st).levels["n"], "E3")

    def test_seal_check_needs_a_solved_seal_and_the_registered_check(self):
        self.assertEqual(seal_check(self.seal, "state_ok", "check_h", "check_h"), "pass")
        self.assertEqual(seal_check(self.seal, "state_other", "check_h", "check_h"), "fail")     # 日志对不上
        self.assertEqual(seal_check(self.seal, "state_ok", "check_easier", "check_h"), "fail")   # 子题换了判据
        for weak in ("accepted", "unsolved", None):
            self.assertEqual(seal_check(replace(self.seal, terminal=weak), "state_ok", "check_h", "check_h"), "fail")

    def test_a_revoked_seal_withdraws_the_delegated_intent(self):
        """seal_revoked 使以该封存为候选的裁决不再计入序列，与撤销判官版本是同一机制。"""
        intents = {"sub": Intent("sub", done="seal_check"), "next": Intent("next", premises=("sub",))}
        verdict = V(1, "sub", "pass", judge="seal_check", candidate="seal:child@120")
        st = State(intents=intents, verdicts=[verdict])
        res = compute(st)
        self.assertEqual([intent_state(st, res, i) for i in intents.values()], ["achieved", "open"])
        st.verdicts[0] = replace(verdict, dismissed=True)
        res = compute(st)
        self.assertEqual([intent_state(st, res, i) for i in intents.values()], ["open", "blocked"])


class Terminal(unittest.TestCase):
    """3.1.2 终态三值：solved 只来自判官确认，人验收是 accepted。"""

    def test_three_values(self):
        st = State(verdicts=[V(1, "goal", "pass", judge="exact_match", candidate="c")])
        self.assertIsNone(terminal(st, compute(st)))                                  # 未关题
        st.closed = True
        self.assertEqual(terminal(st, compute(st)), "solved")
        self.assertEqual(terminal(st, compute(st), accept="human", accepted=True), "accepted")
        self.assertEqual(terminal(st, compute(st), accept="human"), "unsolved")       # 判官过了，人没有验收

    def test_a_weak_judge_never_reaches_solved(self):
        st = State(verdicts=[V(1, "goal", "pass", judge="metric", grade="consistent", candidate="c")], closed=True)
        self.assertEqual(terminal(st, compute(st)), "unsolved")
        self.assertEqual(terminal(st, compute(st), accepted=True), "accepted")


class ForecastLedger(unittest.TestCase):
    """3.5.3 预测账：只有带判据的对象参与结算；预测读等级，等级不读预测。"""

    def test_brier_by_family_and_role(self):
        intents = {"hit": Intent("hit", done="replay"), "miss": Intent("miss", done="replay"),
                   "pending": Intent("pending", done="replay"), "loose": Intent("loose")}
        facts = {"obs": Fact("obs"), "inf": Fact("inf", "inference")}
        vals = [Valuation(1, "forecast", "hit", 0.8, "fam1", "explore"),
                Valuation(2, "forecast", "miss", 0.6, "fam1", "explore"),
                Valuation(3, "forecast", "pending", 0.9, "fam1", "explore"),
                Valuation(4, "forecast", "loose", 0.9, "fam1", "explore"),      # 无判据不结算
                Valuation(5, "forecast", "inf", 0.9, "fam1", "explore"),        # 推断没有判据
                Valuation(6, "forecast", "obs", 0.7, "fam2", "bootstrap"),
                Valuation(7, "quote", "hit", 0.1, "fam1", "explore")]           # 不是预测
        st = State(intents=intents, facts=facts, valuations=vals, abandoned={"miss"},
                   verdicts=[V(10, "hit", "pass", candidate="c"), V(11, "obs", "pass")])
        got = calibration(st, compute(st))
        self.assertEqual(set(got), {("fam1", "explore"), ("fam2", "bootstrap")})
        self.assertEqual(got[("fam1", "explore")][0], 2)
        self.assertAlmostEqual(got[("fam1", "explore")][1], (0.2 ** 2 + 0.6 ** 2) / 2)
        self.assertAlmostEqual(got[("fam2", "bootstrap")][1], 0.3 ** 2)
        st.closed = True                                                         # 关题时仍未达成的记 0
        got = calibration(st, compute(st))
        self.assertEqual(got[("fam1", "explore")][0], 3)
        self.assertAlmostEqual(got[("fam1", "explore")][1], (0.2 ** 2 + 0.6 ** 2 + 0.9 ** 2) / 3)


class Holdout(unittest.TestCase):
    """8.6 常设留出的互斥分配：每题至多留出一项，每项的留出率为 ε。"""

    roster = ["bagua", "idlers", "kit:lean-proving", "ladder", "view"]

    def test_at_most_one_item_per_problem_at_rate_eps(self):
        picks = [holdout(f"p{n}", self.roster) for n in range(20000)]
        self.assertTrue(all(p is None or p in self.roster for p in picks))
        for name in self.roster:
            self.assertAlmostEqual(picks.count(name) / len(picks), 0.10, delta=0.01)
        self.assertAlmostEqual(picks.count(None) / len(picks), 0.50, delta=0.02)
        self.assertEqual(picks, [holdout(f"p{n}", list(reversed(self.roster))) for n in range(20000)])   # 可重放

    def test_a_long_roster_shrinks_the_rate_instead_of_overlapping(self):
        long_roster = [f"organ{k:02d}" for k in range(16)]
        picks = [holdout(f"p{n}", long_roster) for n in range(16000)]
        self.assertNotIn(None, picks)
        for name in long_roster:
            self.assertAlmostEqual(picks.count(name) / len(picks), 1 / 16, delta=0.01)

    def test_empty_roster_and_new_epoch(self):
        self.assertIsNone(holdout("p1", []))
        same = sum(holdout(f"p{n}", self.roster) == holdout(f"p{n}", self.roster, epoch="next") for n in range(2000))
        self.assertLess(same, 1400)                               # 换代后重新抽签
        raised = [holdout(f"p{n}", self.roster[:3], eps=0.30) for n in range(9000)]
        self.assertAlmostEqual(raised.count(None) / len(raised), 0.10, delta=0.02)


class ValuationsStayOutOfLevels(unittest.TestCase):
    """I8 估值不进等级（2.2）：任意改动估值类事件，等级与消费门逐例不变。"""

    KINDS = ("forecast", "quote", "price", "hint", "attack_survived", "weight", "stake", "payout", "forfeit")

    def rich_state(self, rng):
        st = random_state(rng)
        ids = sorted(st.facts)
        seq = 500
        for k in range(2):                                        # 加两条带判据的 Intent，让消费门有 Intent 前提
            key = f"c{k}"
            st.intents[key] = Intent(key, "r0", tuple(rng.sample(ids, rng.randint(0, 1))), done="replay")
            for _ in range(rng.randint(0, 2)):
                seq += 1
                st.verdicts.append(V(seq, key, rng.choice(("pass", "fail")), candidate=rng.choice(("x", "y"))))
        st.intents["dep"] = Intent("dep", rng.choice(("r0", "r1", "r2")), ("c0", rng.choice(ids)))
        st.outcomes = {k: [(600 + n, rng.choice(("failed", "nothing", "found")))
                           for n in range(rng.randint(0, 2))] for k in st.intents}
        st.closed = rng.random() < 0.5
        return st

    def valued(self, rng, st):
        targets = sorted(st.facts) + sorted(st.intents) + ["goal", "contract-1", ""]
        vals = [Valuation(10_000 + n, rng.choice(self.KINDS), rng.choice(targets),
                          rng.choice((0.0, 0.01, 0.5, 0.99, 1.0, 7.5, -3.0)),
                          rng.choice(("fam1", "fam2")), rng.choice(("reason", "explore", "idler")))
                for n in range(rng.randint(0, 12))]
        intents = {k: replace(i, expected_gain=rng.choice((None, 0.0, 0.3, 1e6))) for k, i in st.intents.items()}
        return replace(st, valuations=vals, intents=intents)

    def snapshot(self, st):
        res = compute(st)
        per_intent = {k: (gate(st, res, i), gate_m0(st, res, i), intent_state(st, res, i), knot(st, res, i),
                          claimable(st, res, i), unlocks(st, res, i), card_hash(approval_card(st, res, i)))
                      for k, i in st.intents.items()}
        falsified = sorted(f for f in st.facts if res.levels[f] == X)
        return (res, per_intent, terminal(st, res), terminal(st, res, "human", True),
                [invalidations(st, f) for f in falsified],
                {f: counts_as_progress(st, res, f) for f in st.facts})

    def test_any_change_to_valuations_leaves_levels_and_gates_unchanged(self):
        rng = random.Random(8)
        for _ in range(300):
            st = self.rich_state(rng)
            bare = self.snapshot(st)
            for _ in range(3):
                self.assertEqual(self.snapshot(self.valued(rng, st)), bare)

    def test_the_same_changes_do_move_the_forecast_ledger(self):
        """反过来的方向是通的：预测账读等级。用它确认上一条测试改动的不是没人读的字段。"""
        rng, moved = random.Random(8), 0
        for _ in range(300):
            st = self.rich_state(rng)
            a, b = self.valued(rng, st), self.valued(rng, st)
            moved += calibration(a, compute(a)) != calibration(b, compute(b))
        self.assertGreater(moved, 50)


class SeenBinding(unittest.TestCase):
    """3.1.9 人的决策与所见绑定；3.1.5 的 17、19。"""

    def setUp(self):
        self.intent = Intent("act", "r2", ("n",), done="metric", tests=("n",), rollback="恢复原配置")
        self.other = Intent("side", "r0", ("m",), expected_gain=0.2)
        self.st = State(facts={"n": Fact("n", "inference", session="s0"), "m": Fact("m")},
                        intents={"act": self.intent, "side": self.other},
                        opinions=[R(1, "n", "s1", "fam1"), R(2, "n", "s2", "fam2")])

    def seen(self, st):
        return card_hash(approval_card(st, compute(st), st.intents["act"]))

    def decide(self, seen_hash, st):
        return validate_decision(seen_hash, approval_card(st, compute(st), st.intents["act"]))

    def test_unchanged_card_is_accepted(self):
        self.assertEqual(self.decide(self.seen(self.st), self.st), "ok")

    def test_a_counter_argument_on_a_premise_makes_the_old_view_stale(self):
        seen = self.seen(self.st)
        later = replace(self.st, opinions=self.st.opinions + [R(9, "n", "s3", "fam1", polarity="contradict")])
        self.assertIn("n", compute(later).disputed)
        self.assertEqual(self.decide(seen, later), "stale_view")

    def test_a_level_change_on_a_premise_makes_the_old_view_stale(self):
        seen = self.seen(self.st)
        later = replace(self.st, opinions=self.st.opinions[:1])          # 一条复审被撤下，n 由 E2 落到 E1
        self.assertEqual(self.decide(seen, later), "stale_view")

    def test_unrelated_events_do_not_expire_the_view(self):
        """哈希按卡片范围计算：别的 Intent 的裁决、任何估值类事件，都不让批准过期。"""
        seen = self.seen(self.st)
        noisy = replace(self.st,
                        verdicts=self.st.verdicts + [V(20, "m", "pass")],
                        valuations=[Valuation(21, "forecast", "act", 0.9, "fam1", "explore"),
                                    Valuation(22, "price", "act", 0.4)],
                        intents={"act": replace(self.intent, expected_gain=99.0),
                                 "side": replace(self.other, expected_gain=0.9)})
        self.assertEqual(self.decide(seen, noisy), "ok")

    def test_a_waiver_or_a_changed_rollback_changes_the_card(self):
        seen = self.seen(self.st)
        waived = replace(self.st, waivers={"act": {"n"}})
        self.assertEqual(self.decide(seen, waived), "stale_view")
        edited = replace(self.st, intents={**self.st.intents, "act": replace(self.intent, rollback="另一种回退")})
        self.assertEqual(self.decide(seen, edited), "stale_view")

    def test_the_hash_does_not_depend_on_key_order(self):
        card = approval_card(self.st, compute(self.st), self.intent)
        shuffled = {"target": card["target"], "fields": dict(reversed(list(card["fields"].items()))),
                    "kind": card["kind"]}
        self.assertEqual(card_hash(card), card_hash(shuffled))

    def test_r2_must_declare_rollback(self):
        self.assertEqual(validate_rollback(self.intent), "ok")
        self.assertEqual(validate_rollback(replace(self.intent, rollback=None)), "schema_error")
        self.assertEqual(validate_rollback(Intent("soft", "r1", ())), "ok")


class WalkthroughLean(unittest.TestCase):
    """6.4 的等级与状态变化：第二领域接入，内核函数零改动。"""

    def test_steps(self):
        lemma = dict(risk="r0", done="lean_check", budget=900)
        st = State(facts={"n1": Fact("n1", "inference", session="boot")})                 # 第 2 步
        st.intents.update({k: Intent(k, **lemma) for k in ("iS", "i1", "i2", "i3")})      # 第 3 步
        st.intents["iM"] = Intent("iM", premises=("iS", "i1", "i2", "i3"), **lemma)
        J = lambda seq, target: V(seq, target, "pass", judge="lean_check", candidate=f"proof_{target}")
        state = lambda key: intent_state(st, compute(st), st.intents[key])
        self.assertEqual(state("iM"), "blocked")
        st.verdicts += [J(4, "iS"), J(5, "i1"), J(6, "i3")]                               # 第 4、5 步
        st.outcomes["i2"] = [(7, "failed")]
        res = compute(st)
        self.assertEqual([state(k) for k in ("iS", "i1", "i3", "i2", "iM")],
                         ["achieved", "achieved", "achieved", "open", "blocked"])
        self.assertTrue(knot(st, res, st.intents["i2"]))                                  # 第 6 步：难点，不认领
        self.assertFalse(claimable(st, res, st.intents["i2"]))
        look = Intent("i2o", "r0", (), done="lean_check", budget=450, follows=("i2", "observe"))
        self.assertEqual(validate_follow(st, look), "ok")
        st.intents["i2o"] = look
        st.facts["n2"] = Fact("n2", session="e7", control=True)                           # 第 7 步：反例
        st.verdicts += [J(8, "i2o"), V(9, "n2", "pass", judge="lean_check")]
        res = compute(st)
        self.assertEqual((res.levels["n2"], state("i2o")), ("E3", "achieved"))
        self.assertFalse(knot(st, res, st.intents["i2"]))                                 # 看清了，标记解除
        st.abandoned.add("i2")                                                            # 第 8 步：换缝
        self.assertEqual(state("iM"), "abandoned")
        st.intents["i2b"] = Intent("i2b", follows=("i2", "reroute"), **lemma)
        st.intents.update({k: Intent(k, **lemma) for k in ("i4", "iSb")})
        st.intents["iMb"] = Intent("iMb", premises=("iSb", "i1", "i2b", "i3", "i4"), **lemma)
        self.assertEqual(reroutes(st, st.intents["i2b"]), 1)
        self.assertEqual(state("iMb"), "blocked")
        st.verdicts += [J(10, "iSb"), J(11, "i2b"), J(12, "i4")]                          # 第 9 步
        self.assertEqual(state("iMb"), "open")
        st.verdicts.append(V(13, "goal", "pass", judge="lean_check", candidate="main"))   # 第 10 步
        st.closed = True                                                                  # 第 11 步
        res = compute(st)
        self.assertEqual((res.levels["goal"], terminal(st, res)), ("E3", "solved"))
        self.assertEqual(res.levels["n1"], "E0")                                          # Bootstrap 的推断始终没有被消费


class WalkthroughMarket(unittest.TestCase):
    """6.3 榷场走查的资本列：逐步守恒，与走查表逐格相符。"""

    def test_ledger(self):
        rows = market_walkthrough.run()
        self.assertEqual(rows, market_walkthrough.TABLE)
        self.assertEqual(rows[1], (9.0, 9.0, 6.0, 36.0, 0.0))
        self.assertEqual(rows[5][2:], (6.16, 34.70, 1.14))
        self.assertEqual(rows[9], (9.20, 7.52, 6.16, 18.08, 19.04))
        self.assertAlmostEqual(sum(rows[9]), 60.0, delta=0.011)   # 两位小数下的合计
        self.assertAlmostEqual(market_walkthrough.lemma_session_cost(), 0.44, delta=0.01)


if __name__ == "__main__":
    unittest.main()
