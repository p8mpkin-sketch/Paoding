"""pd kaiti：一句话开题一期（只有确认道；零确认开关不放行）。"""

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
    code, out = pd(tmp_path, "kaiti", text, model=Model(_draft_for(text, "none")))
    assert code == 3 and "为什么不开" in out
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
