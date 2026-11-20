"""知识页的资料一栏（v5 第四期，资料库第一期）：书库挂在图服务 HTTP 上，导入作业由栈里的循环推进。

验：粘贴文字与上传文件两条导入路、只认人的令牌、本机路径与网址被拒、失败停住与重试取消、停用与软删、
“试一下”检索、单段原文、/healthz 里的书库一项。
"""

from __future__ import annotations

import json
import logging
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests" / "integration"))

from knowledge_hub import knowledge_config  # noqa: E402
from test_settings_keys import make, req  # noqa: E402

DOC = "# 部署\n\n部署前先跑全量测试。\n\n## 回滚\n\n回滚用上一个标签重新发布，数据库迁移要能反向执行。\n"


@pytest.fixture
def stack(tmp_path):
    s = make(tmp_path)
    s.start()
    yield s
    s.stop()


def wait_ready(url: str, sid: str, timeout: float = 10.0) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        _, out = req(url, "GET", "/v1/knowledge/sources")
        src = next(s for s in out["sources"] if s["id"] == sid)
        if src["live_revision"] is not None or src["failed"]:
            return src
        time.sleep(0.05)
    raise AssertionError(f"{sid} 没有导入完")


def put_blob(url: str, tok: str, data: bytes) -> str:
    r = urllib.request.Request(url + "/v1/blobs", data=data, method="PUT")
    r.add_header("Authorization", f"Bearer {tok}")
    r.add_header("Content-Type", "application/octet-stream")
    with urllib.request.urlopen(r, timeout=10) as resp:
        return str(json.loads(resp.read())["hash"])


def test_text_import_search_and_chunk(stack):
    url, tok = stack.url, stack.human_token
    assert req(url, "POST", "/v1/knowledge/sources", {"name": "运维手册", "text": DOC})[0] == 401
    code, _ = req(url, "POST", "/v1/knowledge/sources", {"name": "运维手册", "text": DOC}, stack.tok["sinan"])
    assert code == 403  # 组件令牌不能导入
    code, out = req(url, "POST", "/v1/knowledge/sources", {"name": "运维手册", "text": DOC, "file_name": "ops.md"}, tok)
    assert code == 200 and out["revision"] == 1 and out["jobs"][0]["stage"] == "parse"
    sid = out["source"]
    src = wait_ready(url, sid)
    assert src["origin"] == "text" and src["scope"] == "all" and src["chunks"] >= 1
    code, res = req(url, "POST", "/v1/knowledge/search", {"q": "回滚迁移"}, tok)
    assert code == 200 and res["hits"] and res["hits"][0]["source_name"] == "运维手册"
    assert res["embedder"] == "hash-512-v1" and res["via"] == "lexical+vector"
    cid = res["hits"][0]["id"]
    code, c = req(url, "GET", f"/v1/knowledge/chunks/{cid}")
    assert code == 200 and "回滚" in c["text"] and "回滚" in c["heading"]
    assert req(url, "GET", "/v1/knowledge/chunks/k_0000000000000000")[0] == 404
    _, h = req(url, "GET", "/healthz")
    assert h["components"]["knowledge"]["ok"] and h["components"]["knowledge"]["sources"] == 1


def test_file_import_and_new_revision(stack):
    url, tok = stack.url, stack.human_token
    data = "<html><body><h1>监控</h1><p>延迟超过 300ms 报警。</p></body></html>".encode()
    h = put_blob(url, tok, data)
    f = {"hash": h, "size": len(data), "media_type": "text/html", "name": "mon.html"}
    assert req(url, "POST", "/v1/knowledge/sources", {"name": "监控", "file": {**f, "size": 1}}, tok)[0] == 400
    assert req(url, "POST", "/v1/knowledge/sources", {"name": "监控", "file": {**f, "hash": "a" * 64}}, tok)[0] == 404
    code, out = req(url, "POST", "/v1/knowledge/sources", {"name": "监控", "scope": "pick", "file": f}, tok)
    assert code == 200
    sid = out["source"]
    wait_ready(url, sid)
    assert req(url, "POST", "/v1/knowledge/search", {"q": "报警"}, tok)[1]["hits"] == []  # pick：不点名不出现
    assert req(url, "POST", "/v1/knowledge/search", {"q": "报警", "pick": [sid]}, tok)[1]["hits"]
    code, out = req(url, "POST", f"/v1/knowledge/sources/{sid}/revisions", {"text": "延迟超过 500ms 才报警。"}, tok)
    assert code == 200 and out["revision"] == 2
    end = time.monotonic() + 10
    while time.monotonic() < end:
        src = next(s for s in req(url, "GET", "/v1/knowledge/sources")[1]["sources"] if s["id"] == sid)
        if src["live_revision"] == 2:
            break
        time.sleep(0.05)
    assert src["live_revision"] == 2 and src["revisions"] == 2


def test_local_paths_and_urls_are_refused(stack):
    url, tok = stack.url, stack.human_token
    code, out = req(url, "POST", "/v1/knowledge/sources", {"name": "题库", "path": "~/paoding-bank"}, tok)
    assert code == 400 and out["code"] == "forbidden_op"
    code, out = req(url, "POST", "/v1/knowledge/sources", {"name": "网页", "url": "http://127.0.0.1/"}, tok)
    assert code == 400 and out["code"] == "not_supported"
    assert req(url, "POST", "/v1/knowledge/sources", {"name": "空", "text": "  "}, tok)[0] == 400
    assert req(url, "POST", "/v1/knowledge/sources", {"name": "x"}, tok)[0] == 400


def test_failed_job_retry_cancel_and_curate(stack):
    url, tok = stack.url, stack.human_token
    data = b"%PDF-1.4 fake"
    h = put_blob(url, tok, data)
    f = {"hash": h, "size": len(data), "media_type": "application/pdf", "name": "a.pdf"}
    sid = req(url, "POST", "/v1/knowledge/sources", {"name": "扫描件", "file": f}, tok)[1]["source"]
    src = wait_ready(url, sid)
    assert src["failed"]["stage"] == "parse"
    _, jobs = req(url, "GET", "/v1/knowledge/jobs")
    assert jobs["jobs"][0]["failed"]["reason"]
    assert req(url, "POST", f"/v1/knowledge/jobs/{sid}/1/retry", None, tok)[0] == 200
    assert req(url, "POST", f"/v1/knowledge/jobs/{sid}/9/retry", None, tok)[0] == 404
    code, out = req(url, "POST", f"/v1/knowledge/jobs/{sid}/1/cancel", None, tok)
    assert code == 200 and out["jobs"] == []
    assert req(url, "POST", f"/v1/knowledge/jobs/{sid}/1/cancel", None, tok)[0] == 409

    sid2 = req(url, "POST", "/v1/knowledge/sources", {"name": "手册", "text": DOC}, tok)[1]["source"]
    wait_ready(url, sid2)
    assert req(url, "POST", f"/v1/knowledge/sources/{sid2}/disable", None, tok)[0] == 200
    assert req(url, "POST", "/v1/knowledge/search", {"q": "回滚"}, tok)[1]["hits"] == []
    assert req(url, "POST", f"/v1/knowledge/sources/{sid2}/enable", None, tok)[0] == 200
    code, out = req(url, "POST", f"/v1/knowledge/sources/{sid2}/delete", None, tok)
    assert code == 200 and next(s for s in out["sources"] if s["id"] == sid2)["deleted_at"] is not None
    assert req(url, "POST", f"/v1/knowledge/sources/{sid2}/delete", None, tok)[0] == 409
    assert req(url, "POST", f"/v1/knowledge/sources/{sid2}/restore", None, tok)[0] == 200
    assert req(url, "POST", "/v1/knowledge/search", {"q": "回滚"}, tok)[1]["hits"]
    assert req(url, "POST", "/v1/knowledge/sources/s_nonexist00/disable", None, tok)[0] == 404


def test_knowledge_config():
    assert knowledge_config(None) == {"embedder": {"kind": "hash"}}
    assert knowledge_config({"embedder": {"kind": "onnx"}})["embedder"]["kind"] == "onnx"
    with pytest.raises(ValueError):
        knowledge_config({"embedder": {"kind": "cloud"}})
    with pytest.raises(ValueError):
        knowledge_config({"other": 1})


CANARY = "sk-canaryStack5Vb8Nq2Lk7"


def test_canary_stays_out_of_index_logs_and_responses(stack, caplog):
    """验收①的全栈一轮：经 HTTP 导入带金丝雀的资料，停在解析，遮盖后导入；之后栈的日志文件、书库目录、
    所有读端点的应答里都没有它。"""
    caplog.set_level(logging.DEBUG)
    url, tok = stack.url, stack.human_token
    text = f"# 接口\n\n调接口用 {CANARY}，超时 30 秒。\n\n## 回滚\n\n回滚用上一个标签。\n"
    sid = req(url, "POST", "/v1/knowledge/sources", {"name": "接口说明", "text": text}, tok)[1]["source"]
    src = wait_ready(url, sid)
    assert src["failed"]["code"] == "secrets" and src["failed"]["count"] == 1
    assert req(url, "POST", f"/v1/knowledge/jobs/{sid}/1/retry", {"mask": "yes"}, tok)[0] == 400
    assert req(url, "POST", f"/v1/knowledge/jobs/{sid}/1/retry", {"mask": True}, tok)[0] == 200
    src = wait_ready(url, sid)
    assert src["live_revision"] == 1
    bodies = [req(url, "GET", "/v1/knowledge/sources")[1], req(url, "GET", "/v1/knowledge/jobs")[1]]
    for q in ("调接口", "sk-canaryStack5Vb8Nq2Lk7", "回滚"):
        res = req(url, "POST", "/v1/knowledge/search", {"q": q, "k": 20}, tok)[1]
        bodies.append(res)
        bodies += [req(url, "GET", f"/v1/knowledge/chunks/{h['id']}")[1] for h in res["hits"]]
    dump = json.dumps(bodies, ensure_ascii=False)
    assert "‹资料里的凭据，已遮盖›" in dump and CANARY not in dump
    # 运行日志：栈在测试里不写文件（run.py 才配文件），所以直接查这段时间里发出的每一条日志记录
    assert any("资料导入" in r.getMessage() for r in caplog.records), "书库循环应当打过日志，才算查过"
    for r in caplog.records:
        assert CANARY not in r.getMessage() and CANARY not in str(r.__dict__), r.name
    for f in (stack.cfg.home / "shuku").iterdir():
        assert CANARY.encode() not in f.read_bytes(), f.name
