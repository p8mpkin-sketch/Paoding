"""通鉴的三种键（01-memory §2.2）：环境键、签名键、记忆条目 id。全是规范化 JSON 的哈希，不调用模型。

sig_key := sha256(JCS(Signature))     Signature = {profile, judges, resources, tags}（规格 4.3）
env_key := labels.env                 开题人给的不透明字符串，优先
         | sha256(JCS({base, targets}))  缺省由执行规格与授权目标推出
mem_id  := sha256(JCS({kind, scope, key}))  同一条判据在同一作用域只有一条
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from paoding_graph.contract import canonicalize


def digest(obj: Any) -> str:
    return hashlib.sha256(canonicalize(obj)).hexdigest()


def signature(problem: Mapping[str, Any]) -> dict[str, Any]:
    """problem：开题事件体（含图服务推出的 profile）或状态里的 Problem，两者这几个字段同形。"""
    labels = problem.get("labels") or {}
    return {
        "profile": dict(problem["profile"]),
        "judges": sorted(problem["judges"]),
        "resources": sorted({r["resource"] for r in problem["scope"]}),
        "tags": sorted(labels.get("tags", [])),
    }


def sig_key(problem: Mapping[str, Any]) -> str:
    return digest(signature(problem))


def env_key(problem: Mapping[str, Any]) -> str:
    labels = problem.get("labels") or {}
    if labels.get("env"):
        return str(labels["env"])
    return digest({"base": problem["env"]["base"], "targets": sorted(r["pattern"] for r in problem["scope"])})


def mem_id(kind: str, scope: Mapping[str, Any], key: Any) -> str:
    return digest({"kind": kind, "scope": dict(scope), "key": key})


def check_key(check: Mapping[str, Any]) -> str:
    """判据的内容哈希：判官、规格与对照的字节哈希、期望。判官版本不在内：换版本不是另一条事实。"""
    return digest({k: v for k, v in check.items() if k != "judge_version"})
