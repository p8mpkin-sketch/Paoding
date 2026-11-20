"""导入资料里的凭据（设计稿“安全、测试”一节；cz 2026-11-20 验收条件：金丝雀密钥不进索引、日志与会话上下文）。

解析出纯文本之后、写进 Blob 与切分之前扫一遍。发现像密钥的串，这一版本停在解析一步（stage_failed，code=secrets），
原因里只写处数，不写串本身；人选“遮盖后导入”（job_retry 带 mask）后逐字遮盖再往下走，或者取消。

形状与 adapter/creds.py 同一套（带标签的、常见前缀的、Bearer、地址里的口令），另加 PEM 私钥块。
书库不依赖 adapter（ci/check_deps.py），所以这里是一份独立实现；改形状时两处一起改。确定性代码，不调模型。
"""

from __future__ import annotations

import re

MASK = "‹资料里的凭据，已遮盖›"
MIN_LEN = 6

_LABELED = re.compile(
    r"(?:密码|口令|令牌|密钥|凭据|凭证|token|password|passwd|pwd|secret|api[_ -]?key|access[_ -]?key)"
    r"\s*(?:[:：=]|是|为)\s*[`'\"“‘]?(?P<v>[^\s`'\"”’，。；;,、）)】]+)",
    re.I,
)
_PREFIXED = re.compile(
    r"(?<![A-Za-z0-9])(?P<v>(?:sk-|sk_live_|ghp_|gho_|ghs_|github_pat_|glpat-|xox[abp]-|AKIA|AIza)[A-Za-z0-9_\-]{8,})"
)
_BEARER = re.compile(r"\bBearer\s+(?P<v>[A-Za-z0-9._~+/=\-]{8,})")
_USERINFO = re.compile(r"[a-z][a-z0-9+.\-]*://[^\s/:@]+:(?P<v>[^\s/@]+)@", re.I)
_PEM = re.compile(r"(?P<v>-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----)", re.S)


def found(text: str) -> tuple[str, ...]:
    """认出的凭据，长的在前（遮盖时先遮长的，免得短的把长的切碎）。"""
    out: set[str] = set()
    for pat in (_PEM, _LABELED, _PREFIXED, _BEARER, _USERINFO):
        for m in pat.finditer(text):
            v = m.group("v").strip()
            if len(v) >= MIN_LEN:
                out.add(v)
    return tuple(sorted(out, key=lambda s: (-len(s), s)))


def mask(text: str, secrets: tuple[str, ...]) -> str:
    for s in secrets:
        text = text.replace(s, MASK)
    return text
