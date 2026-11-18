"""对照判据 N1（§3.3.3，从 M1 提前）：判官验证带对照的观察类论断时，用 control.inputs 再跑一次同一份规格。

主运行通过且对照不通过才算通过。表格四行各一条测试，另有输入怎么进容器、谁不认对照、内核复核。
"""

from judge_rig import JRig, jr  # noqa: F401  —— jr 是 fixture

TOUCH = ["net:target-a:8080"]  # 替身执行层报告的访问摘要


def controlled_fact(r, ctl=b"target=bogus\n", script="probe $(cat /workspace/inputs/1 2>/dev/null)"):
    if "p1" not in r.state["problems"]:
        r.open()
    lid, tok = r.session()
    spec, inp = r.spec(script), r.art(ctl, cls="authored", who=tok)
    check = {"judge_id": "replay", "spec_ref": spec, "expect": {"exit_code": 0}, "control": {"inputs": [inp]}}
    return r.fact(tok, check)


def verdicts(r):
    return r.state["verdicts"]


def test_main_passes_and_control_fails_is_a_controlled_pass(jr):
    jr.box.runs = [(0, "open\n", TOUCH, 1000), (1, "refused\n", TOUCH, 1000)]
    fid, rid = controlled_fact(jr)
    [done] = jr.runner.tick()
    assert done["result"] == "pass" and jr.level("p1", fid) == "E3"
    [v] = verdicts(jr)
    assert v["controlled"] is True and v["control_end"] == "fail"
    assert len(jr.box.launched) == 2 and jr.box.destroyed == ["box-0", "box-1"]  # 两个洁净容器
    out = jr.blobs.get(jr.state["artifacts"][done["evidence"]]["hash"])
    assert b"open" in out and b"--- control ---" in out and b"refused" in out


def test_constant_spec_passes_both_runs_and_is_no_contrast(jr):
    """直接打印常量的规格：对照也通过，结果不依赖输入。无结论，等级不变。"""
    jr.box.runs = [(0, "ok\n", TOUCH, 1), (0, "ok\n", TOUCH, 1)]
    fid, rid = controlled_fact(jr)
    before = jr.level("p1", fid)
    [done] = jr.runner.tick()
    assert (done["result"], done["reason"]) == ("inconclusive", "no_contrast")
    assert verdicts(jr) == [] and jr.level("p1", fid) == before != "E3"
    req = jr.state["requests"][rid]
    assert req["inconclusive"] == "no_contrast" and req["control_end"] == "pass"


def test_main_fail_is_fail_and_the_control_is_not_run(jr):
    jr.box.runs = [(1, "closed\n", TOUCH, 1)]
    fid, rid = controlled_fact(jr)
    [done] = jr.runner.tick()
    assert done["result"] == "fail" and len(jr.box.launched) == 1
    [v] = verdicts(jr)
    assert v["control_end"] == "not_run" and v["controlled"] is False
    assert jr.level("p1", fid) == "X"


def test_control_timeout_is_inconclusive_with_its_reason(jr):
    jr.box.runs = [(0, "open\n", TOUCH, 1000), (None, "", TOUCH, 61_000)]
    fid, rid = controlled_fact(jr)
    [done] = jr.runner.tick()
    assert (done["result"], done["reason"]) == ("inconclusive", "timeout") and verdicts(jr) == []
    assert jr.state["requests"][rid]["control_end"] == "timeout"


def test_untouched_control_is_inconclusive(jr):
    jr.box.runs = [(0, "open\n", TOUCH, 1), (1, "", [], 1)]
    fid, rid = controlled_fact(jr)
    [done] = jr.runner.tick()
    assert (done["result"], done["reason"]) == ("inconclusive", "untouched")


def test_flaky_control_is_no_contrast(tmp_path):
    from judge_rig import REG, with_flake

    r = JRig(tmp_path, registry=with_flake(REG, "replay", flake={"reruns": 1, "require": "all"}))
    r.box.runs = [(0, "", TOUCH, 1), (0, "", TOUCH, 1), (0, "", TOUCH, 1), (1, "", TOUCH, 1)]
    fid, rid = controlled_fact(r)
    [done] = r.runner.tick()
    assert (done["result"], done["reason"]) == ("inconclusive", "no_contrast")
    assert r.state["requests"][rid]["control_end"] == "flaky"


def test_control_inputs_are_written_only_into_the_control_run(jr):
    """两次运行的环境只差在输入上：都建 /workspace/inputs，只有对照运行写入 control.inputs。"""
    jr.box.runs = [(0, "", TOUCH, 1), (1, "", TOUCH, 1)]
    controlled_fact(jr, ctl=b"target=bogus\n")
    jr.runner.tick()
    setups = [cmd for _, cmd, _, _ in jr.box.cmds if cmd.startswith("printf")]
    assert len(setups) == 2
    main, ctl = setups
    assert "mkdir -p /workspace/inputs" in main and "/workspace/inputs/1" not in main
    assert "mkdir -p /workspace/inputs" in ctl and "> /workspace/inputs/1" in ctl


def test_a_judge_that_does_not_know_controls_cannot_pass_one(jr):
    """不认对照的判官（这里是 exact_match）不能替对照说"不通过"：一律 inconclusive(unsupported)。"""
    jr.open()
    lid, tok = jr.session()
    inp = jr.art(b"x", cls="authored", who=tok)
    fid, rid = jr.fact(tok, {"judge_id": "exact_match", "expect": {"sha256": "0" * 64}, "control": {"inputs": [inp]}})
    [done] = jr.runner.tick()
    assert (done["result"], done["reason"]) == ("inconclusive", "unsupported")
    assert jr.state["requests"][rid]["control_end"] == "unsupported"


def test_the_kernel_refuses_a_controlled_pass_without_a_failing_control(jr):
    """内核再核一遍：带对照的判据，pass 必须带 control_end=fail。判官运行器出错也升不了等级。"""
    jr.box.runs = []
    fid, rid = controlled_fact(jr)
    lid = jr.one(
        "judge",
        "p1",
        "lease",
        {"kind": "judge", "target": rid, "holder": "jr1", "reserve": {"usd_milli": 1, "wall_s": 60}, "ttl_s": 60},
    )
    base = {"request": rid, "result": "pass", "version": "1", "evidence": []}
    for extra in ({}, {"control_end": "pass"}, {"control_end": "not_run"}):
        out = jr.submit("judge", "p1", [{"op": "judge_verdict", "body": {**base, **extra}}])
        assert not out["ok"] and out["results"][0]["code"] == "schema_error", (extra, out)
    assert lid
