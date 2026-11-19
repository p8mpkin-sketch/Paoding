"""外部裁决一期在判官注册表一侧（docs/design/external-verdict/ §5.1）：authority 字段、连接器档案摘要进内核快照。"""

import pytest
from paoding_judgebox.contract import DEFAULT_DIR, RegistryError, kernel_judges, load_connectors, load_registry

EXT = """id: ext_receipt
version: "1"
kind: deferred
grade: decisive
authority: external
applies_to: [goal]
runner: {type: connector, base: builtin}
params: {connector: plat}
"""
CONN = """id: plat
version: "2"
base_url: http://127.0.0.1:9
credential: {key_slot: plat}
endpoints:
  submit: {method: POST, path: "/api/tasks/{task}/submissions", body: {answer: $candidate}}
  receipt: {method: GET, path: "/api/submissions/{sid}"}
fields: {submission_id: /submission_id, status: /status}
verdict: {accepted: pass, rejected: fail, pending: pending}
"""


def test_builtin_registry_entries_unchanged():
    reg = load_registry(DEFAULT_DIR)
    kj = kernel_judges(reg)
    assert all(set(e) == {"version", "grade", "kind", "max_cost"} for e in kj.values())  # 本地判官逐字同旧版
    assert all(s["authority"] == "local" for s in reg.values())


def test_external_entry_gets_connector_stamp(tmp_path):
    (tmp_path / "j").mkdir()
    (tmp_path / "c").mkdir()
    (tmp_path / "j" / "ext.yaml").write_text(EXT, encoding="utf-8")
    (tmp_path / "c" / "plat.yaml").write_text(CONN, encoding="utf-8")
    reg, conns = load_registry(tmp_path / "j"), load_connectors(tmp_path / "c")
    e = kernel_judges(reg, conns)["ext_receipt"]
    assert e["authority"] == "external" and e["kind"] == "deferred"
    assert e["connector"]["id"] == "plat" and e["connector"]["version"] == "2" and len(e["connector"]["digest"]) == 64
    assert "connector" not in kernel_judges(reg)["ext_receipt"]  # 档案没加载：内核据此拒绝以它开题
    # 档案改一个字节，摘要就变
    (tmp_path / "c" / "plat.yaml").write_text(CONN.replace('"2"', '"3"'), encoding="utf-8")
    assert load_connectors(tmp_path / "c")["plat"]["digest"] != e["connector"]["digest"]


@pytest.mark.parametrize(
    "text",
    [
        EXT.replace("kind: deferred", "kind: deterministic"),  # 外部裁决必须是延迟判官
        EXT.replace("params: {connector: plat}", "params: {}"),
        EXT.replace("authority: external", "authority: human"),
    ],
)
def test_bad_external_entries(tmp_path, text):
    (tmp_path / "x.yaml").write_text(text, encoding="utf-8")
    with pytest.raises(RegistryError):
        load_registry(tmp_path)


def test_connector_credential_is_slot_only(tmp_path):
    (tmp_path / "p.yaml").write_text(
        CONN.replace("{key_slot: plat}", "{key_slot: plat, token: sk-x}"), encoding="utf-8"
    )
    with pytest.raises(RegistryError):
        load_connectors(tmp_path)


def test_no_connectors_dir_means_none(tmp_path):
    assert load_connectors(tmp_path / "missing") == {}
