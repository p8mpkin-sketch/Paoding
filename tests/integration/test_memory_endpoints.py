"""知识页的记忆一栏（v5 第四期）：通鉴的卡片与人的钉住、遗忘挂在图服务 HTTP 上。

条目直接以通鉴服务的身份种进日志（真实流程里由关题封存派生，那条路有 tongjian 的单元测试）；这里只验 HTTP 外壳：
读卡、只认人的令牌、须写理由、所见的卡变了即 409、过期的钉不住、遗忘后条目退役。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests" / "integration"))

from test_settings_keys import make, req  # noqa: E402

from paoding_tongjian.service import SERVICE  # noqa: E402


@pytest.fixture
def stack(tmp_path):
    s = make(tmp_path)
    s.start()
    tj = s.memory.tj
    case = {"seal": {"problem_id": "seeded"}, "recall_outcomes": []}
    items = [
        {
            "id": "m-ex",
            "kind": "excluded",
            "scope": {"env_key": "e"},
            "source": {"problem": "seeded"},
            "title": "这条路走不通",
        },
        {
            "id": "m-env",
            "kind": "env_fact",
            "scope": {"env_key": "e"},
            "source": {"problem": "seeded"},
            "title": "端口 8080",
        },
    ]
    assert tj._commit(
        "seed", [(SERVICE, "case_sealed", {"case": case}), (SERVICE, "mem_derived", {"case": "seeded", "items": items})]
    )["ok"]
    yield s
    s.stop()


def test_card_pin_forget(stack):
    url, tok = stack.url, stack.human_token
    code, items = req(url, "GET", "/v1/memory")
    assert code == 200 and {m["id"] for m in items["items"]} == {"m-ex", "m-env"}
    code, card = req(url, "GET", "/v1/memory/items/m-ex")
    assert (
        code == 200
        and card["item"]["title"] == "这条路走不通"
        and card["state"] == "active"
        and card["seen"]["card_hash"]
    )
    assert req(url, "GET", "/v1/memory/items/nope")[0] == 404

    body = {"reason": "以后都用得上", "seen": card["seen"]}
    assert req(url, "POST", "/v1/memory/items/m-ex/pin", body)[0] == 401  # 没令牌
    assert req(url, "POST", "/v1/memory/items/m-ex/pin", {**body, "reason": " "}, tok)[0] == 400  # 须写理由
    code, out = req(url, "POST", "/v1/memory/items/m-ex/pin", body, tok)
    assert code == 200 and out["ok"] and out["card"]["pinned"] is True

    code, out = req(url, "POST", "/v1/memory/items/m-ex/forget", {"reason": "过时了", "seen": card["seen"]}, tok)
    assert code == 409 and out["code"] == "stale_view"  # 钉住之后卡变了：要先看最新的
    fresh = req(url, "GET", "/v1/memory/items/m-ex")[1]
    code, out = req(url, "POST", "/v1/memory/items/m-ex/forget", {"reason": "过时了", "seen": fresh["seen"]}, tok)
    assert code == 200 and out["card"]["state"] == "retired"
    again = req(url, "GET", "/v1/memory/items/m-ex")[1]
    code, out = req(url, "POST", "/v1/memory/items/m-ex/pin", {"reason": "再钉", "seen": again["seen"]}, tok)
    assert code == 400 and "已遗忘" in out["detail"]
    assert [m["state"] for m in req(url, "GET", "/v1/memory")[1]["items"] if m["id"] == "m-ex"] == ["retired"]
