"""pd kaiti：一句话开题（确认道、开放道；零确认开关不放行）与 pd close。"""

import hashlib
import io
import json

from paoding_pd.cli import Local, main
from paoding_qicao.contract import extract

T1 = (
    "练习题：目标在 q1:8080，是个登录页，登录后页面会显示一个答案串，把它交出来写进 answer.txt。"
    "只许访问这个地址，半小时内搞定。答案：PD-7Q2M9XKD"
)


def _draft_for(text, form="answer"):
    e = extract(text, ["答案"])
    sid = lambda k: next(s.id for s in e.spans if s.kind == k)  # noqa: E731
    d = {"title": "取得登录后的答案串", "goal_sentence": [sid("sentence")], "check": {"form": form}}
    if e.of("addr"):
        d["entries"] = [{"span": sid("addr"), "role": "entry"}]
    if e.of("duration"):
        d["deadline"] = sid("duration")
    return d


class Model:
    def __init__(self, out):
        self.out = out

    def complete(self, system, user, max_tokens):
        return json.dumps(self.out, ensure_ascii=False)


def pd(home, *args, read=lambda _: "", model=None):
    buf = io.StringIO()
    code = main(["--home", str(home), *args], out=buf, read=read, model=model)
    return code, buf.getvalue()


def test_confirm_lane_opens_with_sealed_answer(tmp_path):
    code, out = pd(tmp_path, "kaiti", T1, model=Model(_draft_for(T1)))
    assert code == 0, out
    assert "确认道" in out and "练习道候选" not in out and "PD-7Q2M9XKD" not in out  # 没有风险表：r2，不是候选
    local = Local(tmp_path, {"kind": "human", "id": "cz"})
    (pid,) = local.graph.state["problems"]
    p = local.graph.state["problems"][pid]
    check = p["goal"]["check"]
    assert check["judge_id"] == "exact_match" and len(check["sealed"]) == 1
    ref = check["sealed"][0]
    key = tmp_path / "vault" / ref["vault"]
    content, salt = key.read_bytes(), key.with_name(key.name + ".salt").read_bytes()
    assert content == b"PD-7Q2M9XKD" and hashlib.sha256(salt + content).hexdigest() == ref["digest"]
    assert p["scope"] == [{"resource": "net", "pattern": "q1:8080", "actions": ["connect"], "risk": "r2"}]
    assert p["budget"]["wall_s"] == 1800
    stmt = local.graph.state["artifacts"][p["origin"]["statement_ref"]]
    assert b"PD-7Q2M9XKD" not in local.blobs.get(stmt["hash"])
    for blob in (tmp_path / "blobs").rglob("*"):
        if blob.is_file():
            assert b"PD-7Q2M9XKD" not in blob.read_bytes()


def test_settings_risk_table_and_draft_file(tmp_path):
    settings = {"settings": {"risk": [{"resource": "net", "pattern": "q*:*", "actions": ["connect"], "risk": "r0"}]}}
    (tmp_path / "s.json").write_text(json.dumps(settings))
    (tmp_path / "d.json").write_text(json.dumps(_draft_for(T1), ensure_ascii=False))
    code, out = pd(
        tmp_path / "h",
        "kaiti",
        T1,
        "--settings",
        str(tmp_path / "s.json"),
        "--draft-file",
        str(tmp_path / "d.json"),
        "--yes",
    )
    assert code == 0, out
    local = Local(tmp_path / "h", {"kind": "human", "id": "cz"})
    (p,) = local.graph.state["problems"].values()
    assert p["scope"][0]["risk"] == "r0" and p["profile"]["reversibility"] == "r0"


def test_refuse_and_decline_open_nothing(tmp_path):
    text = "帮我调研一下主流的智能体框架，写一份对比。"
    code, out = pd(tmp_path, "kaiti", text, "--strict", model=Model(_draft_for(text, "none")))
    assert code == 3 and "为什么不开" in out and "不加 --strict 就按开放道去做" in out
    code, out = pd(tmp_path, "kaiti", T1, model=Model(_draft_for(T1)), read=lambda _: "n")
    assert code == 1 and "已放弃" in out
    assert not Local(tmp_path, {"kind": "human", "id": "cz"}).graph.state["problems"]


def test_bad_model_output_refuses(tmp_path):
    code, out = pd(tmp_path, "kaiti", T1, model=Model({"title": "x", "scope": ["evil:1"]}))
    assert code == 3 and "起草结果不可用" in out


def test_no_model_configured(tmp_path, monkeypatch):
    for k in ("PD_DRAFT_URL", "PD_DRAFT_TOKEN", "PD_DRAFT_MODEL"):
        monkeypatch.delenv(k, raising=False)
    code, out = pd(tmp_path, "kaiti", T1)
    assert code == 2 and "没有起草模型" in out


def test_open_lane_opens_without_a_card_then_delivers_and_closes(tmp_path):
    """open-lane §11 第一步：今天被拒的那句话，命令行直接开（不问回车）；pd status 看交付；pd close 带反馈关题。"""
    text = "帮我调研一下主流的智能体框架，写一份对比。"
    asked = []
    code, out = pd(
        tmp_path, "kaiti", text, model=Model(_draft_for(text, "none")), read=lambda q: asked.append(q) or "n"
    )
    assert code == 0 and asked == [] and "开放道" in out, out
    local = Local(tmp_path, {"kind": "human", "id": "cz"})
    (pid,) = local.graph.state["problems"]
    assert local.graph.state["problems"][pid]["goal"]["accept"] == "open"
    code, out = pd(tmp_path, "status", pid)
    assert "开放道：不登记判据" in out and "交付：还没有" in out and "自述（未经判定）" in out
    # 一个求解会话交付（司南领租约，会话令牌提交 deliver）
    g = local.graph
    g.tokens.issue({"kind": "sinan", "id": "sn1"}, "tok-sn")
    lease = {"kind": "solve", "holder": "sn1", "reserve": {"usd_milli": 100, "wall_s": 60}, "ttl_s": 60}
    lid = g.submit("tok-sn", pid, "l1", [{"op": "lease", "body": lease}])["results"][0]["id"]
    g.tokens.issue({"kind": "adapter", "id": "ad1", "session": lid, "role": "solve"}, "tok-s")
    data = b"LangGraph vs AutoGen ..."
    ans = {"hash": local.blobs.put(data), "size": len(data), "media_type": "text/plain", "class": "authored"}
    out = g.submit(
        "tok-s",
        pid,
        "d1",
        [
            {"op": "register_artifact", "body": ans},
            {"op": "deliver", "body": {"outcome": "partial", "answer": "$0", "unverified": ["没跑基准"]}},
        ],
    )
    assert out["ok"], out
    code, out = pd(tmp_path, "status", pid)
    assert "部分完成；未经判定" in out and "未验证：没跑基准" in out
    code, out = pd(tmp_path, "close", pid, "--feedback", "adopted", "--yes")
    assert code == 0 and "delivered（已交付，未经判定；已采纳）" in out, out
    code, out = pd(tmp_path, "close", pid, "--yes")
    assert code == 1 and "已关" in out


def test_close_feedback_only_for_open_lane(tmp_path):
    pd(tmp_path, "kaiti", T1, "--yes", model=Model(_draft_for(T1)))
    (pid,) = Local(tmp_path, {"kind": "human", "id": "cz"}).graph.state["problems"]
    code, out = pd(tmp_path, "close", pid, "--feedback", "adopted", "--yes")
    assert code == 2 and "只用于开放道" in out
