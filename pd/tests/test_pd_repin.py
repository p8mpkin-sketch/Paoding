"""pd repin（体质修炼 003 T4-4）：品阶按全栈的功法存档解析成摘要，经 HTTP 提议通道提交；同一阶几版时要挑。

全栈这里用图服务的 HTTP 外壳加一个挂上的 /v1/evolution 代替（只给 archive 一栏），内核配置直接给值。
"""

import io
import json
import urllib.request

import yaml
from test_pd import PROBLEM

from paoding_graph.contract import BlobStore, Config, GraphHttp, GraphService, TokenRegistry
from paoding_pd.cli import default_judges, main

OLD, NEW, NEW2 = "a" * 64, "b" * 64, "c" * 64
ARCHIVE = ((OLD, 1, ()), (NEW, 2, ()), (NEW2, 2, ()))


def stack(tmp_path):
    reg = TokenRegistry()
    reg.issue({"kind": "human", "id": "cz"}, "tok")
    cfg = Config(judges=default_judges(), gongfa=(2, NEW), gongfa_archive=ARCHIVE)
    svc = GraphService(tmp_path / "g.sqlite", cfg, reg)
    app = GraphHttp(svc, BlobStore(tmp_path / "blobs"))
    rows = [{"jie": j, "digest": d, "current": d == NEW} for d, j, _ in ARCHIVE]
    app.mount("GET", r"/v1/evolution", lambda q, body: {"archive": rows})
    url = app.serve()
    spec = yaml.safe_load(PROBLEM)
    ops = []
    for text in ("题面", "材料"):
        data = text.encode()
        art = {"hash": app.blobs.put(data), "size": len(data), "media_type": "text/plain", "class": "input"}
        ops.append({"op": "register_artifact", "body": art})
    problem = {k: spec[k] for k in ("title", "goal", "scope", "budget", "env", "judges")}
    problem["origin"] = {"statement_ref": "$0", "materials": ["$1"]}
    req = urllib.request.Request(
        url + "/v1/problems",
        data=json.dumps(
            {"id": "p1", "idem_key": "w1", "ops": [*ops, {"op": "open_problem", "body": problem}]}
        ).encode(),
        method="POST",
        headers={"Authorization": "Bearer tok", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        assert json.loads(r.read())["ok"]
    return svc, app, url


def pd(tmp_path, url, *args):
    (tmp_path / "tok").write_text("tok")
    buf = io.StringIO()
    code = main(["--home", str(tmp_path / "data"), "--url", url, "--token-file", str(tmp_path / "tok"), *args], out=buf)
    return code, buf.getvalue()


def test_pd_repin_resolves_the_tier_and_submits_through_the_proposal_channel(tmp_path):
    svc, app, url = stack(tmp_path)
    try:
        assert svc.state["problems"]["p1"]["gongfa"] == {"jie": 2, "digest": NEW}
        code, out = pd(tmp_path, url, "repin", "p1", "--to-jie", "3", "--reason", "x")
        assert code == 2 and "没有这一版" in out and "第 1 阶 aaaaaaaaaaaa" in out
        code, out = pd(tmp_path, url, "repin", "p1", "--to-jie", "2", "--reason", "x")
        assert code == 2 and "第 2 阶有 2 版" in out  # 同一阶几版：要挑
        code, out = pd(tmp_path, url, "repin", "p1", "--to-jie", "2", "--to-digest", "ccc", "--reason", "同阶换一版")
        assert code == 1 and "改钉被拒" in out and "forbidden_op" in out  # 内核只许往低改
        code, out = pd(tmp_path, url, "repin", "p1", "--to-jie", "1", "--reason", "新火在真实任务上出事")
        assert code == 0 and "已把 p1 改钉到第 1 阶" in out
        (ev,) = [e for e in svc.log.events("p1") if e["kind"] == "repin"]
        assert ev["actor"]["kind"] == "human"
        assert ev["body"] == {"to": {"jie": 1, "digest": OLD}, "reason": "新火在真实任务上出事"}
        assert svc.state["problems"]["p1"]["gongfa"] == {"jie": 2, "digest": NEW}  # 开题时记下的不动
    finally:
        app.close()
