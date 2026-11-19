"""判据形态目录（external-verdict §5.8，修 R1）：一句话开题能登记哪几种判据，由判官注册表驱动，不在代码里写死。

注册表里 applies_to 含 goal、且标了 form 的条目各成一行：answer（有标准答案，sealed）、command（原文里的检查命令，
spec_ref）、external（判定权在已登记的外部平台，按连接器档案）。external 的行另带档案里的 match.hosts 与
task_ref.pattern，vet 据此**查表**认出平台、从原文里取逐字的任务号；起草模型只能指认区间，不能报平台名。

没有注册表时（离线工具、旧测试）用模板缺省：answer → defaults.answer_judge，command → defaults.command_judge。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any

FORMS = ("answer", "command", "external")
WORD = {
    "answer": "answer（有标准答案）",
    "command": "command（原文给了检查命令）",
    "external": "external（判定权在原文提到的外部平台，平台回执说了算）",
}


@dataclass(frozen=True)
class Form:
    form: str
    judge_id: str
    connector: str = ""  # external：连接器档案 id
    hosts: tuple[str, ...] = ()
    task_ref: str = ""  # 任务号的正则（档案的 task_ref.pattern）
    version: str = ""

    def matches(self, host: str) -> bool:
        """host 是 host 或 host:port；档案里的 hosts 可带端口、可通配。"""
        bare = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
        return any(fnmatchcase(host, p) or fnmatchcase(bare, p) for p in self.hosts)


@dataclass(frozen=True)
class Catalog:
    forms: tuple[Form, ...] = field(default_factory=tuple)

    def judge(self, form: str) -> str | None:
        return next((f.judge_id for f in self.forms if f.form == form), None)

    def platforms(self) -> tuple[Form, ...]:
        return tuple(f for f in self.forms if f.form == "external")

    def kinds(self) -> tuple[str, ...]:
        """起草提示里列出的形态（加上 none）。没有外部平台登记时不列 external：模型就不会指认它。"""
        return tuple(dict.fromkeys(f.form for f in self.forms)) + ("none",)

    def platform_of(self, host: str) -> list[Form]:
        return [f for f in self.platforms() if f.matches(host)]

    def task_refs(self, f: Form, text: str) -> list[str]:
        return list(dict.fromkeys(re.findall(f.task_ref, text))) if f.task_ref else []


def defaults_catalog(defaults: Mapping[str, Any]) -> Catalog:
    return Catalog((Form("answer", str(defaults["answer_judge"])), Form("command", str(defaults["command_judge"]))))


def catalog_of(registry: Mapping[str, Mapping[str, Any]], connectors: Mapping[str, Mapping[str, Any]]) -> Catalog:
    """registry：load_registry 的结果；connectors：load_connectors 的结果。外部条目的档案没加载就不进目录
    （内核本来也会拒绝以它开题）。同一形态多条时按 judge_id 排序取第一条。"""
    out: list[Form] = []
    for jid, s in sorted(registry.items()):
        form = s.get("form")
        if form not in FORMS or "goal" not in (s.get("applies_to") or []):
            continue
        if form != "external":
            out.append(Form(str(form), jid, version=str(s.get("version", ""))))
            continue
        cid = str((s.get("params") or {}).get("connector", ""))
        c = connectors.get(cid)
        if c is None:
            continue
        doc = c["doc"]
        out.append(
            Form(
                "external",
                jid,
                cid,
                tuple(str(h) for h in (doc.get("match") or {}).get("hosts", [])),
                str((doc.get("task_ref") or {}).get("pattern", "")),
                str(c["version"]),
            )
        )
    return Catalog(tuple(out))


def installed_catalog() -> Catalog:
    """本机装着的判官注册表与连接器档案（judgebox 的缺省目录）生成的目录：pd kaiti 离线起草时用，与全栈同一份数据。"""
    from paoding_judgebox.contract import load_connectors, load_registry

    return catalog_of(load_registry(), load_connectors())
