"""任务包渲染（3.4.5 的 5 的字节部分）与 CLI 绑定的命令构造（十项表，不运行真 CLI）。

缓存命中的另一半（同一 as_of_seq 下后一个会话首次请求的缓存读 token > 0）要真模型，留到 D4 真机。
"""
import json
import os

import pytest
from pathlib import Path

from adapter_rig import CFG, graph, lease_bootstrap  # noqa: F401（fixture）

from paoding_adapter import backend as be
from paoding_adapter.package import common_prefix_ratio, render

GOLDEN = Path(__file__).with_name("golden") / "reason_package.txt"
R = {"usd_milli": 1000, "wall_s": 600}


def _reason_lease(g):
    lid = lease_bootstrap(g)
    g.submit("tok-sinan", "p1", "rel", [{"op": "release", "body": {"lease": lid, "outcome": "nothing"}}])
    out = g.submit("tok-sinan", "p1", "lease-r", [{"op": "lease", "body": {
        "kind": "reason", "holder": "sn1", "reserve": R, "ttl_s": 120}}])
    return g.state["leases"][out["results"][0]["id"]]


STATEMENT1 = ("一台服务在给定环境里运行。题目材料包括它的配置文件、启动脚本与一份运行日志。"
             "目标是确定某个配置项的实际取值，并把它作为候选提交；判官按精确匹配裁决。"
             "授权范围只允许读取目标环境，不允许修改它。环境可以随时重置到基线。"
             "日志很长，只有一部分与目标相关；配置文件之间存在覆盖关系，后加载的覆盖先加载的。")
STATEMENT = STATEMENT1
LIMITS = {"budget": R, "max_turns": 40, "ops_quota": {"facts": 20, "intents": 8}, "tools": ["submit", "show"]}


def _render(g, lease, statement=STATEMENT, **kw):
    kw.setdefault("limits", LIMITS)
    return render(g.state, "p1", lease, statement=statement, judges_cfg=CFG.judges, budget=g.budget("p1"),
                  kits=[{"name": "k2", "description": "第二个", "path": "/kits/k2"},
                        {"name": "k1", "description": "第一个", "path": "/kits/k1"}], **kw)


def _add_intents(g, n, start=0):
    for i in range(start, start + n):
        g.submit("tok-human", "p1", f"i{i}", [{"op": "add_intent", "body": {
            "title": f"方向 {i}：检查第 {i} 组配置项", "premises": [], "risk": "r0", "budget": R}}])


def test_golden_package_bytes(graph):
    """前缀字节稳定：同一状态渲染出的任务包与黄金文件逐字节相同。改动渲染须同时更新黄金文件（PD_UPDATE_GOLDEN=1）。"""
    from adapter_rig import open_problem
    open_problem(graph)
    lease = _reason_lease(graph)
    _add_intents(graph, 3)
    pkg = _render(graph, lease)
    text = pkg.system + "\n----\n" + pkg.user
    if os.environ.get("PD_UPDATE_GOLDEN"):
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(text, encoding="utf-8")
    assert text == GOLDEN.read_text(encoding="utf-8")
    assert pkg.as_bytes() == _render(graph, lease).as_bytes()          # 同一状态两次渲染逐字节相同


@pytest.mark.parametrize("scale", [1, 2, 4])
def test_prefix_stable_when_only_nodes_added(graph, scale):
    """3.4.5 的 5（异议 002 第 3 项裁决后的验收）：只新增节点时，前一个包的①–④逐字节是后一个包的前缀。

    可变段⑤–⑦不参与断言；整包公共前缀比例只作遥测读数打印，不设阈值。"""
    from adapter_rig import open_problem
    open_problem(graph)
    lease = _reason_lease(graph)
    _add_intents(graph, 2)
    a = _render(graph, lease, statement=STATEMENT1 * scale)
    _add_intents(graph, 3, start=2)
    b = _render(graph, lease, statement=STATEMENT1 * scale)
    assert a.prefix and a.system.startswith(a.prefix)
    assert b.prefix.startswith(a.prefix) and b.prefix != a.prefix          # ①–④ 100% 字节前缀稳定
    assert b.system.encode().startswith(a.prefix.encode())
    ra = common_prefix_ratio(a.system + a.user, b.system + b.user)
    print(f"遥测 scale={scale} statement={len((STATEMENT1 * scale).encode())}B ratio={ra:.3f}")


def test_concurrent_sessions_share_system_prefix(graph):
    """同一 as_of_seq 下并发启动的两个 Explore：①–⑤逐字节相同，差别只在⑥⑦。"""
    from adapter_rig import open_problem
    open_problem(graph)
    _reason_lease(graph)
    _add_intents(graph, 2)
    a_iid, b_iid = sorted(graph.state["intents"])
    la = {"id": "l_a", "kind": "explore", "target": a_iid}
    lb = {"id": "l_b", "kind": "explore", "target": b_iid}
    a, b = _render(graph, la), _render(graph, lb)
    assert a.system == b.system and a.user != b.user
    assert a.package["as_of_seq"] == b.package["as_of_seq"] == graph.state["seq"]


def test_package_records_hints_shown(graph):
    """HMI H4：任务包的 focus.hints 记下本会话看到的 Hint，供“暴露关联”投影。"""
    from adapter_rig import open_problem
    open_problem(graph)
    lease = _reason_lease(graph)
    hid = graph.submit("tok-human", "p1", "h1", [{"op": "hint", "body": {"text": "看看配置"}}])["results"][0]["id"]
    pkg = _render(graph, lease)
    assert pkg.package["focus"]["hints"] == [hid]
    assert "看看配置" in pkg.user and "看看配置" not in pkg.system           # Hint 进⑥，不破坏前缀


def test_no_timestamps_in_prefix(graph):
    from adapter_rig import open_problem
    open_problem(graph)
    lease = _reason_lease(graph)
    pkg = _render(graph, lease)
    prefix = pkg.system[:pkg.system.index("# ⑤")]
    assert str(graph.state["now"]) not in prefix and lease["id"] not in prefix


# ---------- CLI 绑定：十项表 ----------

def _plan(tmp_path, tools=be.PROXY_TOOLS, resume=False):
    return be.LaunchPlan("l_7", tmp_path / "workspace", tmp_path / "system.md", "任务", tmp_path / "mcp.json",
                         proxy_tools=tools, proxy_url="http://proxy:8080", task_token="pdt-abc",
                         max_budget_usd=1.5, max_turns=40, resume=resume)


def _flag(argv, name):
    return argv[argv.index(name) + 1]


def test_binding_ten_items(tmp_path):
    argv, env = be.CliBinding().command(_plan(tmp_path))
    assert argv[0] == "claude" and _flag(argv, "-p") == "任务"
    assert _flag(argv, "--output-format") == "stream-json" and "--verbose" in argv          # 1
    assert "--bare" in argv                                                                  # 2
    assert set(_flag(argv, "--tools").split(",")) == set(be.FILE_TOOLS) and "--restricted" in argv   # 3
    assert not {"Bash", "PowerShell", "WebFetch"} & set(_flag(argv, "--tools").split(","))
    assert _flag(argv, "--mcp-config").endswith("mcp.json") and "--strict-mcp-config" in argv        # 4
    allowed = _flag(argv, "--allowedTools").split(",")                                       # 5
    assert {"mcp__paoding__exec", "mcp__paoding__submit", "mcp__paoding__show"} <= set(allowed)
    assert _flag(argv, "--permission-prompts") == "none"
    assert _flag(argv, "--append-system-prompt-file").endswith("system.md")                  # 6
    assert _flag(argv, "--session-id") == be.session_uuid("l_7")                             # 7
    assert _flag(argv, "--max-budget-usd") == "1.50"                                         # 8
    assert "--max-turns" not in argv                       # 帮助文本未列出，回合上限由 Adapter 执行
    assert env == {"ANTHROPIC_BASE_URL": "http://proxy:8080", "ANTHROPIC_API_KEY": "pdt-abc",
                   "HOME": str(tmp_path / "home"), "PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}


def test_binding_resume_and_reason(tmp_path):
    argv, _ = be.CliBinding().command(_plan(tmp_path, tools=("submit", "show"), resume=True))
    assert _flag(argv, "--resume") == be.session_uuid("l_7") and "--session-id" not in argv
    assert "mcp__paoding__exec" not in _flag(argv, "--allowedTools")


def test_container_has_no_real_key(tmp_path):
    argv, env = be.CliBinding().command(_plan(tmp_path))
    d = be.container_argv("cli:2.1", "pd-model-l_7", "pd-l_7", tmp_path / "workspace", tmp_path, argv, env)
    joined = " ".join(d)
    assert "ANTHROPIC_API_KEY=pdt-abc" in joined and "sk-" not in joined
    assert "--cap-drop" in d and "no-new-privileges" in d and "--privileged" not in d
    assert d.count("--mount") == 2


def test_mcp_config_shape():
    assert json.loads(be.mcp_config("http://h/mcp/k")) == {"mcpServers": {"paoding": {"type": "http",
                                                                                    "url": "http://h/mcp/k"}}}
