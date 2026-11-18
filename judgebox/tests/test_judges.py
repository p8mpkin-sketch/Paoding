"""判官运行器与内建判官（§3.3）。执行层是进程内替身；真容器的重放在 test_replay_docker.py。

验收 3.3.5：1（超时 → inconclusive，费用入账）、2（抖动）、4（错误候选不升级、次数上限）、
5（任务令牌提交裁决被拒）、6（规格被改过拒绝运行）、8（空谓词 untouched）、9（保密库对解题者不可见）。
"""
import hashlib
import json
import os

import pytest
from judge_rig import REG, FakeBox, JRig, jr, with_flake  # noqa: F401

from paoding_judgebox.contract import (BUILTINS, RegistryError, Vault, VaultError, kernel_judges, load_registry)

EM = "exact_match"


def verdicts(r, pid="p1"):
    return [v for v in r.state["verdicts"] if v["problem_id"] == pid]


def judge_costs(r, pid="p1"):
    return [c for c in r.state["costs"] if c["problem_id"] == pid and c["source"] == "judge"]


# ---------- 注册表 ----------

def test_registry_holds_only_the_neutral_builtins():
    assert sorted(REG) == ["exact_match", "replay"] and sorted(BUILTINS) == ["exact_match", "replay"]
    for spec in REG.values():
        assert spec["grade"] == "decisive" and spec["version"] == "1" and spec["flake"]["require"] in ("all", "majority")


def test_kernel_judges_shape_matches_graph_config():
    k = kernel_judges(REG)
    assert k["exact_match"] == {"version": "1", "grade": "decisive", "kind": "deterministic", "max_cost": 0.0}
    assert k["replay"]["max_cost"] == 0.01 and k["replay"]["kind"] == "programmatic"


@pytest.mark.parametrize("text,why", [
    ("version: '1'\nkind: deterministic\ngrade: decisive\n", "缺 id"),
    ("id: a\nversion: '1'\nkind: oracle\ngrade: decisive\n", "kind"),
    ("id: a\nversion: '1'\nkind: deterministic\ngrade: sure\n", "kind"),
    ("id: a\nkind: deterministic\ngrade: decisive\n", "version"),
])
def test_registry_rejects_malformed_entries(tmp_path, text, why):
    (tmp_path / "a.yaml").write_text(text)
    with pytest.raises(RegistryError, match=why):
        load_registry(tmp_path)


def test_registry_rejects_duplicate_ids(tmp_path):
    for n in ("a", "b"):
        (tmp_path / f"{n}.yaml").write_text("id: same\nversion: '1'\nkind: deterministic\ngrade: decisive\n")
    with pytest.raises(RegistryError, match="重复"):
        load_registry(tmp_path)


def test_registry_fills_defaults(tmp_path):
    (tmp_path / "a.yaml").write_text("id: a\nversion: 3\nkind: panel\ngrade: advisory\n")
    spec = load_registry(tmp_path)["a"]
    assert spec["version"] == "3" and spec["flake"] == {"reruns": 0, "require": "all"} and spec["timeout_s"] == 60


# ---------- 保密库 ----------

def test_vault_roundtrip_and_reference_shape(tmp_path):
    v = Vault(tmp_path / "v")
    ref = v.put("answer-1", b"s3cret")
    assert set(ref) == {"vault", "digest"} and len(ref["digest"]) == 64
    assert v.open(ref) == b"s3cret"


def test_vault_digest_is_salted(tmp_path):
    v = Vault(tmp_path / "v")
    a, b = v.put("k1", b"same"), v.put("k2", b"same")
    assert a["digest"] != b["digest"] != hashlib.sha256(b"same").hexdigest()


def test_vault_detects_swapped_content(tmp_path):
    v = Vault(tmp_path / "v")
    ref = v.put("k", b"old")
    (tmp_path / "v" / "k").write_bytes(b"new")
    with pytest.raises(VaultError, match="摘要"):
        v.open(ref)


@pytest.mark.parametrize("key", ["../x", "", "a/b", ".hidden", "x" * 200])
def test_vault_rejects_unsafe_keys(tmp_path, key):
    v = Vault(tmp_path / "v")
    with pytest.raises(VaultError):
        v.put(key, b"x")
    with pytest.raises(VaultError):
        v.open({"vault": key, "digest": "0" * 64})


def test_vault_files_are_owner_only(tmp_path):
    v = Vault(tmp_path / "v")
    v.put("k", b"x")
    assert os.stat(tmp_path / "v").st_mode & 0o777 == 0o700
    assert all(os.stat(p).st_mode & 0o777 == 0o600 for p in (tmp_path / "v").iterdir())


def test_vault_missing_key(tmp_path):
    with pytest.raises(VaultError, match="没有"):
        Vault(tmp_path / "v").open({"vault": "nope", "digest": "0" * 64})


# ---------- exact_match ----------

def sealed(r, answer=b"42\n", **kw):
    ref = r.vault.put("answer", answer)
    r.open(check={"judge_id": EM, "sealed": [ref]}, **kw)
    return ref


def test_exact_match_pass_solves_and_closes(jr):
    sealed(jr)
    aid, out = jr.candidate(b"  42 ")
    assert out["ok"]
    [done] = jr.runner.tick()
    assert done["result"] == "pass" and done["status"] == "judged"
    assert jr.level("p1", "goal") == "E3" and jr.state["problems"]["p1"]["closed"]
    [v] = verdicts(jr)
    assert v["candidate"] == aid and v["grade"] == "decisive" and v["version"] == "1"
    ev = jr.state["artifacts"][v["evidence"][0]]
    assert ev["class"] == "judge" and ev["producer"]["actor"] == "jr1"


def test_wrong_candidate_does_not_raise_level(jr):                       # 3.3.5-4
    sealed(jr)
    jr.candidate(b"41")
    [done] = jr.runner.tick()
    assert done["result"] == "fail"
    assert jr.level("p1", "goal") == "E0" and not jr.state["problems"]["p1"].get("closed")
    assert verdicts(jr)[0]["result"] == "fail"


def test_candidate_quota_is_enforced_by_the_kernel(jr):                  # 3.3.5-4
    sealed(jr, max_attempts=2)
    for wrong in (b"1", b"2"):
        _, out = jr.candidate(wrong)
        assert out["ok"]
    jr.runner.tick()
    _, out = jr.candidate(b"42")
    assert not out["ok"] and out["results"][0]["code"] == "quota_exceeded"
    assert jr.level("p1", "goal") == "E0" and len(verdicts(jr)) == 2


def test_judge_output_never_contains_the_answer(jr):                     # 3.3.5-9
    answer = b"the-sealed-answer-7781"
    sealed(jr, answer)
    jr.candidate(b"guess")
    jr.runner.tick()
    for art in jr.state["artifacts"].values():
        if art["class"] == "judge":
            assert answer not in jr.blobs.get(art["hash"])
    log = json.dumps(jr.svc.events("p1", 0, 1000), ensure_ascii=False)
    assert answer.decode() not in log
    for p in (jr.blobs.root.rglob("*")):
        assert not p.is_file() or answer not in p.read_bytes()


def test_vault_use_is_recorded_as_touched(jr):                           # 3.3.5-9：show 据此拒绝
    sealed(jr)
    jr.candidate(b"42")
    [done] = jr.runner.tick()
    ev = jr.state["artifacts"][done["evidence"]]
    assert ev["exec"]["touched"] == ["vault:answer"] and ev["exec"]["tool"] == EM


def test_problem_carries_only_the_vault_reference(jr):                   # 3.3.5-9
    ref = sealed(jr, b"zzz-hidden")
    check = jr.state["problems"]["p1"]["goal"]["check"]
    assert check["sealed"] == [ref] and "zzz-hidden" not in json.dumps(jr.state["problems"]["p1"])


def test_exact_match_public_digest(jr):
    jr.open(check={"judge_id": EM, "expect": {"sha256": hashlib.sha256(b"open").hexdigest()}})
    jr.candidate(b"open\n")
    assert jr.runner.tick()[0]["result"] == "pass"


def test_exact_match_without_any_answer_is_unsupported(jr):
    jr.open(check={"judge_id": EM})
    jr.candidate(b"x")
    [done] = jr.runner.tick()
    assert (done["result"], done["reason"]) == ("inconclusive", "unsupported")
    assert verdicts(jr) == [] and jr.level("p1", "goal") == "E0"


def test_swapped_vault_asset_is_an_environment_error(jr, tmp_path):
    sealed(jr)
    (tmp_path / "vault" / "answer").write_bytes(b"43")
    jr.candidate(b"43")
    [done] = jr.runner.tick()
    assert (done["result"], done["reason"]) == ("inconclusive", "env_error") and jr.level("p1", "goal") == "E0"


def test_missing_vault_is_an_environment_error(jr):
    sealed(jr)
    jr.runner.vault = None
    jr.candidate(b"42")
    assert jr.runner.tick()[0]["reason"] == "env_error"


# ---------- 谁能裁决 ----------

def test_task_tokens_cannot_submit_verdicts(jr):                         # 3.3.5-5
    sealed(jr)
    lid, tok = jr.session()
    _, out = jr.candidate(b"42")
    rid = out["results"][0]["id"]
    body = {"request": rid, "result": "pass", "version": "1", "evidence": []}
    for who in (tok, "sinan", "exec", "human"):
        out = jr.submit(who, "p1", [{"op": "judge_verdict", "body": body}])
        assert not out["ok"] and out["results"][0]["code"] == "forbidden_op", who
    assert jr.level("p1", "goal") == "E0" and verdicts(jr) == []


def test_task_tokens_cannot_register_judge_class(jr):                    # 3.3.5-5
    sealed(jr)
    lid, tok = jr.session()
    prov = {"sandbox_id": "s", "base": "b", "baseline_ref": "r", "tool": "t", "command": "c", "cwd": "/",
            "exit_code": 0, "touched": [], "started_at": 1, "ended_at": 2, "truncated": False}
    out = jr.submit(tok, "p1", [{"op": "register_artifact", "body": {
        "hash": jr.blobs.put(b"forged verdict"), "size": 14, "media_type": "text/plain", "class": "judge", "exec": prov}}])
    assert not out["ok"] and out["results"][0]["code"] == "forbidden_op"


def test_task_tokens_cannot_take_judge_leases(jr):
    sealed(jr)
    _, out = jr.candidate(b"42")
    out = jr.submit("sinan", "p1", [{"op": "lease", "body": {
        "kind": "judge", "target": out["results"][0]["id"], "holder": "sn1", "reserve": {"usd_milli": 1, "wall_s": 1},
        "ttl_s": 60}}])
    assert not out["ok"] and out["results"][0]["code"] == "forbidden_op"


# ---------- 运行器的记账与幂等 ----------

def test_every_run_books_cost_and_releases_its_lease(jr):
    sealed(jr)
    jr.candidate(b"1")
    [done] = jr.runner.tick()
    lease = jr.state["leases"][done["lease"]]
    assert lease["kind"] == "judge" and not lease["active"] and lease["outcome"] == "done"
    [c] = judge_costs(jr)
    assert c["task_id"] == done["lease"] and c["usd_milli"] == 0 and c["lease_kind"] == "judge"
    assert jr.svc.budget("p1")["reserved"]["usd_milli"] == 0


def test_tick_is_idempotent(jr):
    sealed(jr)
    jr.candidate(b"1")
    assert len(jr.runner.tick()) == 1
    n = jr.svc.head()["seq"] if isinstance(jr.svc.head(), dict) else jr.state["seq"]
    assert jr.runner.tick() == [] and jr.runner.run("p1", "j_4") is None
    assert jr.state["seq"] == n


def test_tick_handles_several_problems_and_requests(jr):
    for pid, cand in (("p1", b"42"), ("p2", b"0")):
        ref = jr.vault.put(f"answer-{pid}", b"42")
        jr.open(pid, check={"judge_id": EM, "sealed": [ref]})
        jr.candidate(cand, pid=pid)
    jr.candidate(b"7", pid="p2")
    out = jr.runner.tick()
    assert sorted((d["result"]) for d in out) == ["fail", "fail", "pass"]
    assert jr.level("p1", "goal") == "E3" and jr.level("p2", "goal") == "E0"


def test_version_mismatch_refuses_to_run(tmp_path):
    r = JRig(tmp_path, registry=with_flake(REG, EM, version="2"))
    sealed(r)
    r.candidate(b"42")
    [done] = r.runner.tick()
    assert (done["result"], done["reason"]) == ("inconclusive", "env_error")
    assert r.level("p1", "goal") == "E0"
    ev = r.blobs.get(r.state["artifacts"][done["evidence"]]["hash"]).decode()
    assert "版本" in ev


def test_judge_without_a_runner_is_unsupported(jr):
    sealed(jr)
    jr.cfg.judges = {}
    jr.candidate(b"42")
    assert jr.runner.tick()[0]["reason"] == "unsupported"


def test_crashing_judge_gives_up_after_three_leases(jr):
    sealed(jr)

    def boom(ctx):
        raise ZeroDivisionError("bug")
    jr.cfg.judges = {EM: boom}
    _, out = jr.candidate(b"42")
    rid = out["results"][0]["id"]
    for _ in range(3):
        with pytest.raises(ZeroDivisionError):
            jr.runner.run("p1", rid)
    assert jr.runner.run("p1", rid) is None
    leases = [l for l in jr.state["leases"].values() if l["kind"] == "judge"]
    assert [l["outcome"] for l in leases] == ["failed"] * 3 and len(judge_costs(jr)) == 3
    assert jr.state["requests"][rid].get("verdict_seq") is None       # 留在 /work 里给人看


def test_inconclusive_needs_a_reason_code(jr):
    sealed(jr)
    _, out = jr.candidate(b"42")
    rid = out["results"][0]["id"]
    jr.one("judge", "p1", "lease", {"kind": "judge", "target": rid, "holder": "jr1",
                                    "reserve": {"usd_milli": 1, "wall_s": 1}, "ttl_s": 60})
    for reason in (None, "ok", "bored"):
        body = {"request": rid, "result": "inconclusive", "version": "1", "evidence": [],
                **({"reason": reason} if reason else {})}
        out = jr.submit("judge", "p1", [{"op": "judge_verdict", "body": body}])
        assert not out["ok"] and out["results"][0]["code"] == "schema_error"


# ---------- replay（替身执行层） ----------

def replay_fact(r, script="probe target-a 8080", expect=None, pid="p1"):
    if pid not in r.state["problems"]:
        r.open(pid)
    lid, tok = r.session(pid)
    spec = r.spec(script, pid)
    return r.fact(tok, {"judge_id": "replay", "spec_ref": spec, "expect": expect or {"exit_code": 0}}, pid)


def test_replay_pass_raises_the_fact(jr):
    jr.box.runs = [(0, "open\n", [], 1500)]
    fid, rid = replay_fact(jr)
    before = jr.level("p1", fid)
    [done] = jr.runner.tick()
    assert done["result"] == "pass" and before != "E3" and jr.level("p1", fid) == "E3"
    ev = jr.state["artifacts"][done["evidence"]]
    assert ev["class"] == "judge" and ev["exec"]["tool"] == "replay" and ev["exec"]["sandbox_id"] == "box-0"


def test_replay_runs_in_a_clean_container_and_tears_it_down(jr):
    jr.box.runs = [(1, "closed\n", [], 10)]
    fid, rid = replay_fact(jr)
    [done] = jr.runner.tick()
    assert done["result"] == "fail"
    [box] = jr.box.launched
    assert box["mount_workspace"] is False and box["spec"].workspace == "" and box["spec"].image.startswith("python")
    assert box["lease"] == done["lease"] and jr.box.destroyed == ["box-0"]
    assert all(kind == "judge" for _, _, kind, _ in jr.box.cmds)        # 执行层不替判官登记


def test_replay_never_gets_irreversible_reach(jr):
    """判官容器的上限是被判对象的风险但不超过 r1：r2 规则放行的地址不进重放容器。"""
    jr.open(risk="r2")
    jr.box.runs = [(0, "", [], 1)]
    lid, tok = jr.session()
    jr.fact(tok, {"judge_id": "replay", "spec_ref": jr.spec("true"), "expect": {}})
    jr.runner.tick()
    assert jr.box.launched[0]["spec"].egress_allow == ()


def test_replay_timeout_is_inconclusive_and_still_costs(jr):             # 3.3.5-1
    jr.box.runs = [(None, "partial", [], 61_000)]
    fid, rid = replay_fact(jr)
    before = jr.level("p1", fid)
    [done] = jr.runner.tick()
    assert (done["result"], done["reason"]) == ("inconclusive", "timeout")
    assert verdicts(jr) == [] and jr.level("p1", fid) == before
    [c] = judge_costs(jr)
    assert c["wall_s"] == 61 and jr.svc.budget("p1")["verify_spent"]["wall_s"] == 61
    assert jr.state["requests"][rid]["inconclusive"] == "timeout" and jr.box.destroyed == ["box-0"]


def test_replay_flaky_when_reruns_disagree(tmp_path):                    # 3.3.5-2
    r = JRig(tmp_path, registry=with_flake(REG, "replay", flake={"reruns": 2, "require": "all"}))
    r.box.runs = [(0, "", [], 1000), (1, "", [], 1000), (0, "", [], 1000)]
    fid, rid = replay_fact(r)
    before = r.level("p1", fid)
    [done] = r.runner.tick()
    assert (done["result"], done["reason"]) == ("flaky", "flaky")
    assert [v["result"] for v in verdicts(r)] == ["flaky"] and r.level("p1", fid) == before
    assert len(r.box.launched) == 3 and len(r.box.destroyed) == 3       # 每次重跑都是新的洁净容器
    assert judge_costs(r)[0]["wall_s"] == 3


def test_replay_majority_policy(tmp_path):                               # 3.3.5-2
    r = JRig(tmp_path, registry=with_flake(REG, "replay", flake={"reruns": 2, "require": "majority"}))
    r.box.runs = [(0, "", [], 1), (1, "", [], 1), (0, "", [], 1)]
    fid, rid = replay_fact(r)
    assert r.runner.tick()[0]["result"] == "pass" and r.level("p1", fid) == "E3"


def test_replay_stable_reruns_agree(tmp_path):
    r = JRig(tmp_path, registry=with_flake(REG, "replay", flake={"reruns": 1, "require": "all"}))
    r.box.runs = [(1, "", [], 1), (1, "", [], 1)]
    replay_fact(r)
    assert r.runner.tick()[0]["result"] == "fail"


def test_replay_untouched_predicate(tmp_path):                           # 3.3.5-8
    r = JRig(tmp_path, registry=with_flake(REG, "replay", params={"require_touch": True}))
    r.box.runs = [(0, "ok", [], 1)]
    fid, rid = replay_fact(r)
    before = r.level("p1", fid)
    [done] = r.runner.tick()
    assert (done["result"], done["reason"]) == ("inconclusive", "untouched") and r.level("p1", fid) == before


def test_replay_touching_the_resource_counts(tmp_path):                  # 3.3.5-8
    r = JRig(tmp_path, registry=with_flake(REG, "replay", params={"require_touch": True}))
    r.box.runs = [(0, "ok", ["net:target-a:8080"], 1)]
    fid, rid = replay_fact(r)
    assert r.runner.tick()[0]["result"] == "pass"


def test_tampered_spec_is_refused(jr):                                   # 3.3.5-6
    jr.box.runs = [(0, "", [], 1)]
    fid, rid = replay_fact(jr, script="probe target-a 8080")
    before = jr.level("p1", fid)
    spec_hash = hashlib.sha256(b"probe target-a 8080").hexdigest()
    jr.blobs.path(spec_hash).chmod(0o644)
    jr.blobs.path(spec_hash).write_bytes(b"true")                        # 等价改写：让它恒真
    [done] = jr.runner.tick()
    assert (done["result"], done["reason"]) == ("inconclusive", "env_error")
    assert jr.box.launched == [] and jr.level("p1", fid) == before and verdicts(jr) == []


def test_replay_launch_failure_is_an_environment_error(jr):
    jr.box.fail_launch = True
    fid, rid = replay_fact(jr)
    [done] = jr.runner.tick()
    assert (done["result"], done["reason"]) == ("inconclusive", "env_error") and jr.box.destroyed == []


def test_replay_without_executor(jr):
    jr.runner.executor = None
    replay_fact(jr)
    assert jr.runner.tick()[0]["reason"] == "env_error"


@pytest.mark.parametrize("expect,code,text,want", [
    ({}, 0, "", "pass"), ({}, 2, "", "fail"),
    ({"exit_code": 3}, 3, "", "pass"),
    ({"stdout_contains": "open"}, 0, "port open", "pass"), ({"stdout_contains": "open"}, 0, "closed", "fail"),
    ({"stdout_regex": r"^v\d+$"}, 0, "v12", "pass"), ({"stdout_regex": r"^v\d+$"}, 0, "x12", "fail"),
    ({"exit_code": 0, "stdout_contains": "a"}, 1, "a", "fail"),
])
def test_replay_expectations(jr, expect, code, text, want):
    jr.box.runs = [(code, text, [], 1)]
    replay_fact(jr, expect=expect)
    assert jr.runner.tick()[0]["result"] == want


def test_replay_of_a_goal_candidate_passes_spec_and_candidate(jr):
    spec_body = "sh /workspace/candidate"
    jr.open(check={"judge_id": "replay", "expect": {"stdout_contains": "ok"}})
    jr.box.runs = [(0, "ok", [], 1)]
    jr.candidate(b"echo ok", judge="replay")
    assert jr.runner.tick()[0]["result"] == "pass" and jr.level("p1", "goal") == "E3"
    setup = jr.box.cmds[0][1]
    assert "/workspace/spec" in setup and spec_body not in setup        # 没有规格时候选本身就是被执行的脚本
