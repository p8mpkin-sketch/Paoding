"""资料库第二期的执行中检索：会话的 kb_search / kb_read 经书库一角查资料，段落以 knowledge 类登记，交付的主张引用它。

假 CLI（真代理、真工具端点、真图服务）→ kb_search（记 kb_query）→ kb_read（书库令牌登记 knowledge 类）
→ deliver 的主张引用它、自检不行 → 结果页分开标示（cz 验收附加条件 1：引用了资料不进有执行记录的分子）。
知识选项：auto 只查“所有任务”可见的资料，pick 只查点名的几份，off 不挂工具。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "adapter" / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests" / "integration"))

from adapter_rig import graph, upstream  # noqa: E402,F401  fixture
from knowledge_hub import KnowledgeHub  # noqa: E402
from test_open_lane_e2e import DELIVER, EXEC, close, kaiti, stand_up  # noqa: E402

from paoding_graph import views  # noqa: E402
from paoding_pd import render  # noqa: E402
from paoding_sinan.contract import Sinan, SinanConfig  # noqa: E402

SEARCH, READ = "mcp__paoding__kb_search", "mcp__paoding__kb_read"
DOC = "# 部署\n\n部署前先跑全量测试。\n\n## 回滚\n\n回滚用上一个标签重新发布，数据库迁移要能反向执行。\n"
ASK = "帮我查清楚线上出问题时怎么回滚，写一段说明。"


def hub_for(rig, tmp_path, graph):  # noqa: F811
    h = KnowledgeHub(tmp_path / "home", rig.blobs, {"embedder": {"kind": "hash"}}, graph, graph.tokens)
    rig.cfg.knowledge = h.session
    return h


def put(h: KnowledgeHub, name: str, text: str, scope: str = "all") -> str:
    data = text.encode()
    f = {"hash": h.blobs.put(data), "size": len(data), "media_type": "text/markdown", "name": f"{name}.md"}
    sid = h.sk.put_source(name, "text", scope, f)
    for _ in range(10):
        h.tick()
    assert h.sk.state["sources"][sid]["revisions"][0]["stage"] == "ready"
    return sid


STEPS = [
    {"tool": SEARCH, "input": {"query": "回滚 迁移", "k": 3}},
    {"tool": READ, "input": {"chunk": "$r0.hits.0.chunk"}},
    {"tool": EXEC, "input": {"cmd": "git tag --list"}},
    {
        "tool": DELIVER,
        "input": {
            "outcome": "answered",
            "answer": "回滚用上一个标签重新发布；迁移要能反向执行。",
            "claims": [
                {"text": "回滚用上一个标签重新发布", "refs": ["$r1.artifact"]},
                {"text": "仓库里有可用的标签", "refs": ["$r2.artifact"]},
                {"text": "迁移都能反向执行（没查）"},
            ],
            "self_check": [{"what": "列出了标签", "result": "pass", "refs": ["$r2.artifact"]}],
        },
    },
]


def test_session_cites_knowledge_and_the_page_counts_it_apart(tmp_path, graph, upstream):  # noqa: F811
    rig = stand_up(tmp_path, graph, upstream, STEPS)
    try:
        h = hub_for(rig, tmp_path, graph)
        sid = put(h, "运维手册", DOC)
        put(h, "私人笔记", "# 回滚\n\n回滚前先给老板打电话。\n", scope="pick")  # auto 查不到
        pid = kaiti(rig, ASK)["pid"]
        r = Sinan(SinanConfig(token="tok-sinan"), graph, graph, rig.blobs, rig.runner).run(pid)
        assert r["stop"] == "needs_human" and r["steps"][0]["outcome"] == "done", r
        st = graph.state
        (d,) = st["problems"][pid]["deliveries"]
        kid = d["claims"][0]["refs"][0]
        a = st["artifacts"][kid]
        assert a["class"] == "knowledge" and a["knowledge"]["source"] == sid
        assert a["producer"] == {"actor": "shuku"}  # 登记人是书库的组件令牌
        assert "回滚" in a["knowledge"]["locator"]
        assert "上一个标签" in rig.blobs.get(a["hash"]).decode()
        assert st["artifacts"][d["claims"][1]["refs"][0]]["class"] == "exec"
        # kb_query 进了事件账：查询词与命中的段落 id，不含原文
        (q,) = [e for e in graph.events(pid) if e["kind"] == "kb_query"]
        assert q["body"]["query"] == "回滚 迁移" and a["knowledge"]["chunk"] in q["body"]["hits"]
        assert "上一个标签" not in json.dumps(q, ensure_ascii=False)
        # 会话看到的工具里有 kb_search / kb_read，系统提示里讲了它们
        (sdir,) = [x for x in (tmp_path / "sessions").iterdir() if x.is_dir()]
        assert "kb_search" in (sdir / "system.md").read_text(encoding="utf-8")
        # 结果的读法：三条主张，一条有执行记录，一条引用了资料（cz 验收附加条件 1：不进执行记录的分子）
        text = render.status(st, pid, graph.budget(pid))
        assert "主张 3 条，有留档支撑 1 条" in text and "引用资料 1 条" in text, text
        v = views.artifact(st, kid)
        assert v["knowledge"]["chunk"] == a["knowledge"]["chunk"]
        assert h.cited() == {sid: 1}
        close(graph, pid, feedback="adopted")
    finally:
        rig.close()


def test_kb_query_is_logged_and_pick_scope_only_sees_the_named(tmp_path, graph, upstream):  # noqa: F811
    rig = stand_up(
        tmp_path,
        graph,
        upstream,
        [
            {"tool": SEARCH, "input": {"query": "回滚"}},
            {"tool": READ, "input": {"chunk": "k_0000000000000000"}},
            {"tool": DELIVER, "input": {"outcome": "blocked", "needs": ["手册里没写"]}},
        ],
    )
    try:
        h = hub_for(rig, tmp_path, graph)
        put(h, "运维手册", DOC)
        note = put(h, "私人笔记", "# 回滚\n\n回滚前先给值班的人打电话。\n", scope="pick")
        pid = kaiti(rig, ASK)["pid"]
        assert h.session.available(pid)
        Sinan(SinanConfig(token="tok-sinan"), graph, graph, rig.blobs, rig.runner).run(pid)
        st = graph.state
        assert not [a for a in st["artifacts"].values() if a["class"] == "knowledge"]  # 编造的段落号读不到
        q = [e for e in graph.events(pid) if e["kind"] == "kb_query"]
        assert len(q) == 1 and q[0]["actor"] == {"kind": "graph", "id": "shuku"}
        assert q[0]["body"]["query"] == "回滚" and q[0]["body"]["hits"]
        # auto：只查“所有任务”可见的资料，点名才可见的私人笔记查不到
        out = h.session.search(pid, q[0]["body"]["lease"], "回滚", 8)
        assert {x["source_name"] for x in out["hits"]} == {"运维手册"}
        assert note not in {a["knowledge"]["source"] for a in st["artifacts"].values() if a.get("knowledge")}
    finally:
        rig.close()
