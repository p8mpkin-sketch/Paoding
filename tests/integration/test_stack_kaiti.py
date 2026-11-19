"""一句话开题第二期在组装根里的接线：/v1/drafts 只给人，开题仍由人的令牌按网页同一条路提交。不需要 Docker。

POST /v1/drafts → PUT /v1/blobs（逐份核对哈希）→ PUT /v1/vault（答案）→ 换掉 "$answer" → POST /v1/problems
"""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "e2e"))

from drive import call  # noqa: E402
from kaiti_hub import KaitiConfigError, kaiti_config  # noqa: E402
from stack import Stack, StackConfig  # noqa: E402

TEXT = "目标在 q1:8080，登录后页面会显示一个答案串，交出来。半小时内搞定。答案：PD-7Q2M9XKD"


@pytest.fixture
def stack(tmp_path):
    s = Stack(StackConfig.load(tmp_path / "home", port=0, executor="none"))
    url = s.http.serve()
    yield s, url
    s.http.close()


def runtime_off(s):
    """旧路：设置写一版 grants.runtime=off，起草回到原文地址即授权（回退路径，§3.1）。"""
    store = s.settings.store
    store.settings = {**store.settings, "grants": {**store.settings["grants"], "runtime": False}}
    s.settings.apply()


def test_drafts_then_open_like_the_web(stack):
    s, url = stack
    runtime_off(s)
    tok = s.human_token
    with pytest.raises(urllib.error.HTTPError) as e:
        call(url, "/v1/drafts", {"text": TEXT}, token=s.tok["sinan"])
    assert e.value.code == 403
    ext = call(url, "/v1/drafts/extract", {"text": TEXT}, token=tok)
    assert ext["answers"] == 1 and "PD-7Q2M9XKD" not in str(ext)

    out = call(url, "/v1/drafts", {"text": TEXT}, token=tok)
    assert out["lane"] == "confirm" and out["model"] == "heuristic"
    for b in out["blobs"]:
        assert call(url, "/v1/blobs", token=tok, raw=b["text"].encode())["hash"] == b["hash"]
    ref = call(url, "/v1/vault", token=tok, raw=out["secret"].encode())
    ops = out["ops"]
    ops[-1]["body"]["goal"]["check"]["sealed"] = [ref]
    res = call(url, "/v1/problems", {"id": out["pid"], "idem_key": "k1", "ops": ops}, token=tok)
    assert res["ok"], res
    p = s.graph.state["problems"][out["pid"]]
    assert p["goal"]["check"]["judge_id"] == "exact_match"
    assert p["scope"][0]["pattern"] == "q1:8080" and p["scope"][0]["risk"] == "r2"  # 没有风险表：r2
    assert (s.vault.root / ref["vault"]).read_bytes() == b"PD-7Q2M9XKD"
    assert ref["digest"] != hashlib.sha256(b"PD-7Q2M9XKD").hexdigest()  # 加盐
    assert s.kaiti.state == {
        "draft": "heuristic",
        "profile": "heuristic",
        "priors": "placeholder:placeholder-0",
        "zero_confirm": False,
    }


def test_kaiti_config_rejects_keys_in_file(tmp_path):
    with pytest.raises(KaitiConfigError):
        kaiti_config({"api_key": "sk-x"}, tmp_path)
    with pytest.raises(KaitiConfigError):
        kaiti_config({"draft": "gpt"}, tmp_path)
    assert kaiti_config({"priors": "p.yaml"}, tmp_path)["priors"] == str((tmp_path / "p.yaml").resolve())


def test_real_backend_without_token_means_no_drafter(tmp_path, monkeypatch):
    monkeypatch.delenv("PD_DRAFT_TOKEN", raising=False)
    from kaiti_hub import KaitiHub

    hub = KaitiHub({"model": "m"}, real=True, upstream="https://example.invalid")
    assert hub.state["draft"] == "off"
    out = hub.svc.draft_view({"text": TEXT})
    assert out["lane"] == "refuse"


def _open(s, url, out, lane, risk=None, key="k"):
    tok = s.human_token
    for b in out["blobs"]:
        call(url, "/v1/blobs", token=tok, raw=b["text"].encode())
    ref = call(url, "/v1/vault", token=tok, raw=out["secret"].encode())
    ops = json.loads(json.dumps(out["ops"]))
    body = ops[-1]["body"]
    body["goal"]["check"]["sealed"] = [ref]
    body["origin"]["draft"]["lane"] = lane
    if risk:
        for r in body["scope"]:
            r["risk"] = risk
        body["budget"]["usd_milli"] = 500
    return call(url, "/v1/problems", {"id": out["pid"], "idem_key": key, "ops": ops}, token=tok)


def test_practice_envelope_is_loaded_but_dormant(stack):
    """第三期：内核加载信封即休眠。起草服务只给确认道；手工把道别改成 practice 的提交体由内核逐条对信封。"""
    s, url = stack
    runtime_off(s)
    pol = s.graph.cfg.practice
    assert pol is not None
    caps = s.settings.store.settings["caps"]
    assert (pol.usd_milli_max, pol.wall_s_max) == (caps["practice_usd_milli"], caps["practice_wall_s"])
    out = call(url, "/v1/drafts", {"text": TEXT}, token=s.human_token)
    assert out["lane"] == "confirm" and out["ops"][-1]["body"]["origin"]["draft"]["lane"] == "confirm"
    # 没有风险表：规则是 r2，不在信封里，整单拒绝
    res = _open(s, url, out, "practice", key="k1")
    assert not res["ok"] and any(r.get("code") == "forbidden_op" for r in res["results"])
    assert out["pid"] not in s.graph.state["problems"]
    # 人把风险标成 r0、金额压到练习上限内：信封接受，版本与摘要抄进事件体
    res = _open(s, url, out, "practice", risk="r0", key="k2")
    assert res["ok"], res
    draft = s.graph.state["problems"][out["pid"]]["origin"]["draft"]
    assert draft["lane"] == "practice" and draft["policy"] == {"version": pol.version, "digest": pol.digest}
    assert s.graph.state["artifacts"][draft["record"]]["class"] == "input"


def test_practice_caps_follow_settings(stack):
    s, _ = stack
    before = s.graph.cfg.practice
    caps = {**s.settings.store.settings["caps"], "practice_usd_milli": 300}
    s._practice({**s.settings.store.settings, "caps": caps})
    after = s.graph.cfg.practice
    assert after.usd_milli_max == 300 and after.digest != before.digest and after.version == before.version


def test_drafts_read_the_settings_store(stack):
    """确认卡上的单题硬顶取设置存储的当前快照，与内核 open_cap_* 同源。"""
    s, url = stack
    store = s.settings.store
    store.settings = {**store.settings, "caps": {**store.settings["caps"], "open_usd_milli": 4321}}
    s.settings.apply()
    out = call(url, "/v1/drafts", {"text": TEXT}, token=s.human_token)
    assert out["caps"]["open_usd_milli"] == 4321 == s.graph.cfg.open_cap_usd_milli


def test_one_sentence_opens_with_zero_egress(stack):
    """扩权第四步（§3.1）：新装缺省 runtime=on，开题只有工作区一条；原文里的地址只作展示，执行时按需申请。"""
    s, url = stack
    out = call(url, "/v1/drafts", {"text": TEXT}, token=s.human_token)
    assert out["lane"] == "confirm"
    assert out["ops"][-1]["body"]["scope"] == [
        {"resource": "workspace", "pattern": "", "actions": ["read", "write"], "risk": "r0"}
    ]
    assert [m["value"] for m in out["mentions"]] == ["q1:8080"]
    assert any(d["field"] == "scope.mention" for d in out["derivation"])
    res = _open(s, url, out, "confirm", key="z1")
    assert res["ok"], res
    assert s.graph.state["problems"][out["pid"]]["scope"][0]["resource"] == "workspace"
