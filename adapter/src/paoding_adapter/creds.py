"""原话里的凭据（open-lane 裁决附加条件 3：正文带凭据时零出站、审批不泄漏）。

开放道把人的原话整段交给会话，原话里可能带着密码、令牌、密钥。原话本身是人给的材料，照常登记；
但会话写出去、给人看的东西不该再带着它们：访问申请的理由（扩权卡）、交付的答案与主张。
提示词要求模型不写（prompts/solve.md），这里是不靠模型自觉的那一道：按形状从原话里认出凭据，
写出去之前逐字遮盖；访问申请的地址里带凭据则直接拒绝（地址不能遮盖，遮了就不是那个地址）。

形状只认三类，宁缺勿滥：带标签的（密码：xxx、token=xxx）、常见前缀的（sk-、ghp_、AKIA…）、地址里的口令（user:pass@host）。
确定性代码，不调模型。
"""

from __future__ import annotations

import re

MASK = "‹原话里的凭据，已遮盖›"
MIN_LEN = 6

_LABELED = re.compile(
    r"(?:密码|口令|令牌|密钥|凭据|凭证|token|password|passwd|pwd|secret|api[_ -]?key|access[_ -]?key|key)"
    r"\s*(?:[:：=]|是|为)\s*[`'\"“‘]?(?P<v>[^\s`'\"”’，。；;,、）)】]+)",
    re.I,
)
_PREFIXED = re.compile(
    r"(?<![A-Za-z0-9])(?P<v>(?:sk-|sk_live_|ghp_|gho_|ghs_|github_pat_|glpat-|xox[abp]-|AKIA|AIza)[A-Za-z0-9_\-]{8,})"
)
_BEARER = re.compile(r"\bBearer\s+(?P<v>[A-Za-z0-9._~+/=\-]{8,})")
_USERINFO = re.compile(r"[a-z][a-z0-9+.\-]*://[^\s/:@]+:(?P<v>[^\s/@]+)@", re.I)


def found(text: str) -> tuple[str, ...]:
    """原话里认出的凭据，长的在前（遮盖时先遮长的，免得短的把长的切碎）。"""
    out: set[str] = set()
    for pat in (_LABELED, _PREFIXED, _BEARER, _USERINFO):
        for m in pat.finditer(text):
            v = m.group("v").strip()
            if len(v) >= MIN_LEN:
                out.add(v)
    return tuple(sorted(out, key=lambda s: (-len(s), s)))


def mask(text: str, secrets: tuple[str, ...]) -> tuple[str, bool]:
    """逐字遮盖；返回 (遮盖后的文字, 有没有遮)。"""
    hit = False
    for s in secrets:
        if s in text:
            text, hit = text.replace(s, MASK), True
    return text, hit
