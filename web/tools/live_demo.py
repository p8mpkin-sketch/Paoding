"""用真图服务给网页一份看得见的数据：两道走完或走到一半的题，加一道每隔几秒往前走一步的题。

用法（仓库根目录）：
    (cd web && npm run build)
    uv run python web/tools/live_demo.py --port 8787
然后打开 http://127.0.0.1:8787/ 。人的令牌是 tok-human（页面右上角填）。

这里没有任何模型调用：事件由测试台（graph/tests/http_rig.py）按固定脚本经 HTTP 提交，
与四官日后提交的是同一条提议通道。服务用临时目录，退出即弃。
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "graph" / "tests"))

from http_rig import Api, R, drive  # noqa: E402


def half(api: Api, pid: str) -> None:
    """走到一半：一条观察、一条由它推出的推断、一条要扩大授权范围的 Intent（等人审批）、一条 Hint。"""
    api.open(pid)
    _, b = api.lease(pid, "bootstrap")
    boot = b["lease"]["id"]
    s = api.session(boot, "bootstrap")
    ex = api.one(pid, "register_artifact", api.art_op(b"entry: ok\n", "exec", "exec")["body"], "exec")
    o = api.propose_with(s, pid, [
        {"op": "add_fact", "body": {"title": "入口可读", "summary": "读到了入口", "claim_type": "observation",
                                    "check": {"judge_id": "replay", "expect": {"exit_code": 0}}, "premises": [], "grounds": [ex]}},
        {"op": "add_fact", "body": {"title": "另有一处入口", "summary": "由上一条推出", "claim_type": "inference",
                                    "premises": ["$0"], "grounds": []}}])
    assert o["ok"], o
    fact = o["results"][0]["id"]
    api.cost(pid, boot, 30, s)
    api.release(boot, "done")
    _, b = api.lease(pid, "reason")
    rl = b["lease"]["id"]
    s = api.session(rl, "reason")
    o = api.propose_with(s, pid, [{"op": "add_intent", "body": {
        "title": "扩大范围后再读", "summary": "需要第二个目标", "premises": [fact], "risk": "r1", "budget": R, "expected_gain": 0.4,
        "needs_scope": [{"resource": "target", "pattern": "second", "actions": ["read"], "risk": "r1"}]}}])
    assert o["ok"], o
    api.release(rl, "done")
    api.one(pid, "hint", {"text": "第二个目标更可能", "about": o["results"][0]["id"]})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--step", type=float, default=2.0, help="第三道题每一步之间的秒数")
    ap.add_argument("--origin", action="append", default=[], help="放行的跨源来源（开发服务器），可重复")
    a = ap.parse_args()
    dist = ROOT / "web" / "dist"
    api = Api(pathlib.Path(tempfile.mkdtemp()), port=a.port, static_dir=dist if dist.is_dir() else None,
              allowed_origins=tuple(a.origin))
    drive(api, "p1")
    half(api, "p2")
    print(f"图服务在 {api.url} ；人的令牌 tok-human", flush=True)
    if not dist.is_dir():
        print("没有 web/dist：只有 API。先在 web/ 下 npm run build，或用 PAODING_API 指过来跑开发服务器。", flush=True)
    # 第三道题慢慢走：每次写之前等一下，网页上能看到事件一条条到
    raw = api.req

    def slow(method, path, *args, **kw):
        if method != "GET":
            time.sleep(a.step)
        return raw(method, path, *args, **kw)

    api.req = slow
    try:
        drive(api, "p3")
        print("p3 已走完。服务继续开着，Ctrl-C 退出。", flush=True)
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        api.close()


if __name__ == "__main__":
    main()
