"""会话活动端点（开放道进度可见性）：GET /v1/leases/{id}/activity 挂在图服务 HTTP 上，读 adapter 的会话流水。

只起 HTTP，不起司南等循环：租约由测试用组件令牌开，会话目录里的活动由 adapter 的 ActivityLog 写（同一份实现）。
在途读与真会话的折叠在 adapter/tests/test_activity.py。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests" / "integration"))
sys.path.insert(0, str(ROOT / "adapter" / "tests"))

from test_settings_keys import make, req  # noqa: E402
from test_solve import lease_solve, open_lane  # noqa: E402

from paoding_adapter import activity as act  # noqa: E402


@pytest.fixture
def stack(tmp_path):
    s = make(tmp_path)
    s.url = s.http.serve()
    yield s
    s.http.close()


class Tokens:
    """test_solve 的辅助函数用固定的令牌名；这里换成栈里发的令牌。"""

    def __init__(self, stack):
        self.g, self.map = stack.graph, {"tok-human": stack.human_token, "tok-sinan": stack.tok["sinan"]}

    def submit(self, tok, pid, idem, ops):
        return self.g.submit(self.map[tok], pid, idem, ops)


def test_activity_endpoint_reads_the_session_log(stack):
    url = stack.url
    code, out = req(url, "GET", "/v1/leases/l_999/activity")
    assert code == 404 and out["code"] == "unknown_ref"
    g = Tokens(stack)
    open_lane(g)
    lid = lease_solve(g)
    code, out = req(url, "GET", f"/v1/leases/{lid}/activity")
    assert code == 200 and out["status"] == "none" and out["items"] == [] and out["kind"] == "solve"
    assert out["problem_id"] == "p1" and out["active"] is True

    sdir = stack.runner.cfg.root / lid
    sdir.mkdir(parents=True)
    log = act.ActivityLog(sdir)
    log.feed(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "先看看仓库。"},
                    {"type": "tool_use", "id": "t1", "name": "mcp__paoding__exec", "input": {"cmd": "ls"}},
                ]
            },
        },
        1,
    )
    (sdir / act.END_FILE).write_text(
        json.dumps({"role": "solve", "status": "released", "rounds": 1, "elapsed_s": 12, "spent_usd_milli": 34})
    )
    code, out = req(url, "GET", f"/v1/leases/{lid}/activity?after=0")
    assert code == 200 and out["live"] is False and out["elapsed_s"] == 12 and out["spent_usd_milli"] == 34
    assert [x["kind"] for x in out["items"]] == ["say", "call"] and out["now"] is None
    code, out = req(url, "GET", f"/v1/leases/{lid}/activity?after=2")
    assert out["items"] == [] and out["next_after"] == 2 and out["last_say"]["text"] == "先看看仓库。"
    assert req(url, "GET", f"/v1/leases/{lid}/activity?after=x")[0] == 400
