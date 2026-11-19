"""外部裁决二期：connector 运行器对着平台模拟（docs/design/external-verdict/ §5.1–§5.4）。

运行器单独测，不起全栈：档案校验、交付幂等、读回执、映射、待定退避、摘要核对、归属核对、凭据缺失与平台拒绝。
全栈上的翻转与凭据的金丝雀在 test_external_verdict_flip.py。
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from paoding_judgebox.builtin import Ctx  # noqa: E402
from paoding_judgebox.contract import (  # noqa: E402
    Connector,
    ProfileError,
    RegistryError,
    SubmissionStore,
    connector_judge,
    connector_plugins,
    load_connectors,
    validate_profile,
)
from platform_mock import Platform, profile  # noqa: E402

SNAP_ID = "mock-platform"


@pytest.fixture
def plat():
    p = Platform()
    yield p
    p.close()


def _loaded(tmp: Path, prof: dict[str, Any]) -> dict[str, dict[str, Any]]:
    d = tmp / "connectors.d"
    d.mkdir(exist_ok=True)
    (d / f"{prof['id']}.yaml").write_text(yaml.safe_dump(prof, allow_unicode=True), encoding="utf-8")
    return load_connectors(d)


def _ctx(
    conns: dict[str, dict[str, Any]],
    candidate: bytes | None,
    *,
    ref: str = "a1",
    now: int = 10**12,
    task: str = "T-17",
    digest: str | None = None,
    target: str = "goal",
    pid: str = "p1",
) -> Ctx:
    snap = {"id": SNAP_ID, "version": "1", "digest": digest or conns[SNAP_ID]["digest"]}
    return Ctx(
        spec={"id": "ext_receipt", "version": "1"},
        check={"judge_id": "ext_receipt", "binding": {"connector": SNAP_ID, "task": task, "max_submissions": 3}},
        problem={"id": pid, "opened_ts": 0, "judge_snapshot": {"ext_receipt": {"version": "1", "connector": snap}}},
        target=target,
        target_risk="r0",
        candidate=candidate,
        candidate_ref=ref,
        spec_bytes=None,
        spec_hash=None,
        vault=None,
        executor=None,
        request_id="r1",
        lease_id="l1",
        bases={},
        now_ms=now,
    )


def _judge(tmp: Path, plat: Platform, conns: dict[str, dict[str, Any]] | None = None, key: str | None = "plat"):
    conns = conns or _loaded(tmp, profile(plat))
    secret = {"mock-platform": plat.token if key == "plat" else key}
    return conns, connector_judge(conns, secret.get, SubmissionStore(tmp / "state"))


def test_profile_shape_is_checked_at_load(tmp_path, plat):
    good = profile(plat)
    assert validate_profile(copy.deepcopy(good)) == good
    bad: list[dict[str, Any]] = []
    for mutate in (
        lambda p: p.pop("base_url"),
        lambda p: p.update(base_url="ftp://x"),
        lambda p: p.update(base_url="http://u:pw@127.0.0.1:1"),  # 凭据不许藏在地址里
        lambda p: p["credential"].update(token="sk-x"),  # 只写槽位名，不写值
        lambda p: p["credential"].update(key_slot="Has Space"),
        lambda p: p["endpoints"].pop("receipt"),
        lambda p: p["endpoints"]["submit"].update(method="DELETE"),
        lambda p: p["fields"].update(status="status"),  # 不是 JSON 指针
        lambda p: p["verdict"].update(accepted="ok"),
        lambda p: p.update(deliver="agent"),
        lambda p: p["poll"].update(first_s=0),
        lambda p: p.update(extra=1),
    ):
        p = copy.deepcopy(good)
        mutate(p)
        bad.append(p)
    for i, p in enumerate(bad):
        with pytest.raises(ProfileError):
            validate_profile(p, f"case{i}")
        d = tmp_path / f"c{i}"
        d.mkdir()
        (d / "x.yaml").write_text(yaml.safe_dump(p), encoding="utf-8")
        with pytest.raises(RegistryError):  # 启动时就失败，不留到判题时
            load_connectors(d)


def test_pending_twice_then_pass_submits_once(tmp_path, plat):
    conns, fn = _judge(tmp_path, plat)
    outs, now = [], 10**12
    for _ in range(3):
        o = fn(_ctx(conns, plat.flag.encode(), now=now))
        outs.append(o)
        now = o.recheck_at or now
    assert [(o.result, o.reason) for o in outs] == [
        ("inconclusive", "pending"),
        ("inconclusive", "pending"),
        ("pass", "ok"),
    ]
    # 退避：first_s 起按次数翻倍
    assert outs[0].recheck_at == 10**12 + 1000 and outs[1].recheck_at == outs[0].recheck_at + 2000
    assert sum(1 for line in plat.log if line.startswith("POST")) == 1
    body = json.loads(outs[2].output)
    assert body["receipt"]["status"] == "accepted" and body["submission"].startswith("s-")


def test_wrong_answer_fails(tmp_path, plat):
    conns, fn = _judge(tmp_path, plat)
    plat.PENDING_POLLS = 0
    o = fn(_ctx(conns, b"FLAG-wrong"))
    assert (o.result, o.reason) == ("fail", "ok")


def test_store_survives_restart_and_keys_by_candidate(tmp_path, plat):
    conns, fn = _judge(tmp_path, plat)
    fn(_ctx(conns, b"x", ref="a1"))
    _, fn2 = _judge(tmp_path, plat, conns)  # 进程重启：状态目录还在
    fn2(_ctx(conns, b"x", ref="a1"))
    assert sum(1 for line in plat.log if line.startswith("POST")) == 1
    fn2(_ctx(conns, b"y", ref="a2"))  # 另一个候选：另交一次
    assert sum(1 for line in plat.log if line.startswith("POST")) == 2
    files = list((tmp_path / "state").iterdir())
    assert len(files) == 2 and all(b"x" not in f.read_bytes().split(b'"')[1::2] for f in files)


def test_backoff_caps_at_max(tmp_path, plat):
    conns, fn = _judge(tmp_path, plat)
    plat.PENDING_POLLS = 99
    waits = []
    for _ in range(6):
        o = fn(_ctx(conns, b"x"))
        waits.append((o.recheck_at or 0) - 10**12)
    assert waits == [1000, 2000, 4000, 8000, 8000, 8000]


def test_unmapped_status_is_unsupported(tmp_path, plat):
    prof = profile(plat)
    prof["verdict"] = {"accepted": "pass"}  # 表外的 pending、rejected
    conns, fn = _judge(tmp_path, plat, _loaded(tmp_path, prof))
    o = fn(_ctx(conns, b"x"))
    assert (o.result, o.reason) == ("inconclusive", "unsupported")


def test_digest_mismatch_refuses_to_run(tmp_path, plat):
    conns, fn = _judge(tmp_path, plat)
    o = fn(_ctx(conns, b"x", digest="0" * 64))
    assert (o.result, o.reason) == ("inconclusive", "env_error")
    assert plat.log == []  # 档案与快照不一致：一个请求也不发


def test_non_goal_target_and_missing_candidate(tmp_path, plat):
    conns, fn = _judge(tmp_path, plat)
    assert fn(_ctx(conns, b"x", target="i1")).reason == "unsupported"
    assert fn(_ctx(conns, None)).reason == "unsupported"
    assert plat.log == []


def test_missing_slot_and_platform_refusal_are_env_errors(tmp_path, plat):
    conns, fn = _judge(tmp_path, plat, key=None)
    o = fn(_ctx(conns, b"x"))
    assert (o.result, o.reason) == ("inconclusive", "env_error") and b"mock-platform" in o.output
    conns, fn = _judge(tmp_path, plat, conns, key="wrong-token")
    o = fn(_ctx(conns, b"x"))
    assert o.reason == "env_error" and b"401" in o.output and b"wrong-token" not in o.output
    # 平台额度用完（429）：env_error，不是 fail
    conns, fn = _judge(tmp_path, plat, conns)
    for i in range(3):
        plat.post("/api/tasks/T-17/submissions", {"answer": str(i)})
    o = fn(_ctx(conns, b"z", ref="a9"))
    assert o.reason == "env_error" and b"429" in o.output


def test_deliver_worker_reads_receipt_and_checks_owner(tmp_path, plat):
    prof = profile(plat, deliver="worker")
    conns, fn = _judge(tmp_path, plat, _loaded(tmp_path, prof))
    plat.PENDING_POLLS = 0
    sid = plat.post("/api/tasks/T-17/submissions", {"answer": plat.flag})["submission_id"]
    assert fn(_ctx(conns, sid.encode(), ref="a1")).result == "pass"
    assert sum(1 for line in plat.log if line.startswith("POST")) == 1  # 判官没有再交
    # 归属：同一提交号拿去冒充另一道题
    o = fn(_ctx(conns, sid.encode(), ref="a2", task="T-99"))
    assert o.reason == "env_error" and b"another task" in o.output


def test_plugins_only_for_connector_runners(tmp_path, plat):
    conns = _loaded(tmp_path, profile(plat))
    reg = {
        "ext_receipt": {"runner": {"type": "connector"}},
        "exact_match": {"runner": {"type": "builtin"}},
    }
    plugins = connector_plugins(reg, conns, lambda s: None, SubmissionStore(tmp_path / "s"))
    assert set(plugins) == {"ext_receipt"}


def test_notice_carries_runtime_address(tmp_path, plat):
    conns = _loaded(tmp_path, profile(plat))
    c = Connector(conns[SNAP_ID]["doc"], {"mock-platform": plat.token}.get)
    a, b = json.loads(c.notice("T-17")), json.loads(c.notice("T-17"))
    assert a["instance"] != b["instance"] and a["instance"] == c.field(a, "instance")
    assert plat.token.encode() not in c.notice("T-17")
