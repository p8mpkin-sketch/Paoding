"""全栈里的设置层一角（宪章 03 §2、§5、§7，L1 第①个 PR）：设置存储与钥匙环的 HTTP 端点。

    GET    /v1/settings          {version, digest, settings}（不含密钥）
    PUT    /v1/settings          人的令牌；请求体 {base_digest, settings}；base_digest 不是当前摘要 → 409 stale_view
    GET    /v1/settings/log      变更日志（只追加）
    GET    /v1/keys              人的令牌；每个槽 {slot, set, fingerprint, set_at, source, env}，没有读回密钥的接口
    PUT    /v1/keys/{slot}       人的令牌；请求体 {key}；只进端点代理的钥匙环，不落盘
    DELETE /v1/keys/{slot}       清除一个槽，立即生效
    DELETE /v1/keys              全部锁定

设置存储在 <home>/settings/：当前快照 settings.json 加只追加的 settings.log（每行一次变更：旧摘要、新摘要、
改了哪些键、谁、何时）。它不是题目日志，不进任何任务包；里面没有密钥（写入时拒绝形如密钥的键）。

生效（03 §5，D6）：单题硬顶只在开题时由图服务 validate 检查，所以上调、下调都只管之后开的题；全局硬顶交给
端点代理，立即生效。每次开题把当时的 (版本, 摘要) 抄进事件体（D5），重放不读设置存储。
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from paoding_adapter.contract import EndpointProxy, KeyRing
from paoding_graph.contract import BadBody, GraphHttp, GraphService, MountError, canonicalize

KEY_NOTE = "密钥重启后失效，可用环境变量持久注入"  # 裁决附加 2：设置页常显
CAP_KEYS = ("global_usd_milli", "open_usd_milli", "open_wall_s", "practice_usd_milli", "practice_wall_s")
ROLES = ("draft", "bootstrap", "reason", "explore", "verify")
TIERS = ("strong", "mid", "light")
RISKS = ("r0", "r1", "r2")
SLOT_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
_SECRETISH = re.compile(r"(api_?key|secret|password|token)$", re.I)


def defaults(*, endpoint: str = "", model: str = "", global_cap_usd_milli: int = 500_000) -> dict[str, Any]:
    """第一次启动时的设置：全局硬顶取今天写死的 500 美元；单题与练习的顶取占位值（与 qicao 的 DEFAULT_CAPS
    同一组数，起草的默认预算与内核硬顶对得上），在设置页改。一个缺省模型档案，五个角色都指它，密钥槽 default。
    端点与模型 id 从 config.yaml 迁入（03 §7）。"""
    return {
        "caps": {
            "global_usd_milli": global_cap_usd_milli,
            "open_usd_milli": min(20_000, global_cap_usd_milli),
            "open_wall_s": 14_400,
            "practice_usd_milli": min(500, global_cap_usd_milli),
            "practice_wall_s": 1_800,
        },
        "risk": [],
        # 运行时扩权（docs/design/runtime-grants/ §10.3）：缺省关；练习道白名单就是信封的 allow.net_patterns
        "grants": {"runtime": False, "auto": {"practice": True}},
        "models": {
            "profiles": [
                {
                    "name": "default",
                    "endpoint": endpoint,
                    "model": model,
                    "family": "",
                    "tier": "strong",
                    "key_slot": "default",
                }
            ],
            "routes": dict.fromkeys(ROLES, "default"),
        },
    }


def digest_of(settings: dict[str, Any]) -> str:
    return hashlib.sha256(canonicalize(settings)).hexdigest()


# ---------- 校验：确定性代码在写入时检查，不靠界面“不给选”（03 §1） ----------


def _pos_int(v: object, where: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        raise BadBody(f"{where} 取正整数，不是 {v!r}")
    return v


def _no_secrets(obj: object, where: str = "settings") -> None:
    """设置存储里不许出现密钥（03 §4.1 第 2 条）：键名像密钥的一律拒绝。密钥走 /v1/keys。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and _SECRETISH.search(k):
                raise BadBody(f"{where}.{k}：设置里不放密钥，密钥用 PUT /v1/keys/{{slot}} 注入")
            _no_secrets(v, f"{where}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _no_secrets(v, f"{where}[{i}]")


def validate(raw: object) -> dict[str, Any]:
    # grants 节可缺：这一节加进来之前写下的快照照旧有效、摘要不变，缺省即"运行时扩权关"
    allowed = {"caps", "risk", "models", "grants", "budget"}
    if not isinstance(raw, dict) or not {"caps", "risk", "models"} <= set(raw) <= allowed:
        raise BadBody("settings 是 {caps, risk, models} 三项，可选 grants、budget")
    _no_secrets(raw)
    caps = raw["caps"]
    if not isinstance(caps, dict) or set(caps) != set(CAP_KEYS):
        raise BadBody(f"caps 是 {list(CAP_KEYS)} 五项")
    c = {k: _pos_int(caps[k], f"caps.{k}") for k in CAP_KEYS}  # 每道顶都必须给：硬顶不可关
    # 三道顶的次序：练习 ≤ 单题 ≤ 全局（03 §5）
    if c["open_usd_milli"] > c["global_usd_milli"]:
        raise BadBody(f"单题硬顶 {c['open_usd_milli']} 超过全局硬顶 {c['global_usd_milli']}（毫美元）")
    if c["practice_usd_milli"] > c["open_usd_milli"]:
        raise BadBody(f"练习上限 {c['practice_usd_milli']} 超过单题硬顶 {c['open_usd_milli']}（毫美元）")
    if c["practice_wall_s"] > c["open_wall_s"]:
        raise BadBody(f"练习墙钟上限 {c['practice_wall_s']} 超过单题墙钟硬顶 {c['open_wall_s']}（秒）")

    risk = raw["risk"]
    if not isinstance(risk, list):
        raise BadBody("risk 是有序规则表")
    rules = []
    for i, r in enumerate(risk):
        if (
            not isinstance(r, dict)
            or set(r) != {"resource", "pattern", "actions", "risk"}
            or not all(isinstance(r[k], str) and r[k] for k in ("resource", "pattern"))
            or not isinstance(r["actions"], list)
            or not all(isinstance(a, str) and a for a in r["actions"])
            or r["risk"] not in RISKS
        ):
            raise BadBody(f"risk[{i}] 是 {{resource, pattern, actions: [..], risk: r0|r1|r2}}")
        rules.append({k: copy.deepcopy(r[k]) for k in ("resource", "pattern", "actions", "risk")})

    models = raw["models"]
    if not isinstance(models, dict) or set(models) != {"profiles", "routes"}:
        raise BadBody("models 是 {profiles, routes}")
    profiles, names = [], set()
    fields = ("name", "endpoint", "model", "family", "tier", "key_slot")
    for i, p in enumerate(models["profiles"] if isinstance(models["profiles"], list) else [None]):
        if not isinstance(p, dict) or set(p) != set(fields) or not all(isinstance(p[k], str) for k in fields):
            raise BadBody(f"models.profiles[{i}] 是 {{{', '.join(fields)}}}，都取字符串")
        if not p["name"] or p["name"] in names:
            raise BadBody(f"models.profiles[{i}].name 须非空且不重名")
        if p["tier"] not in TIERS:
            raise BadBody(f"models.profiles[{i}].tier 取 {TIERS}")
        if not SLOT_RE.fullmatch(p["key_slot"]):
            raise BadBody(f"models.profiles[{i}].key_slot 取小写字母、数字、- 与 _，至多 32 字符")
        names.add(p["name"])
        profiles.append({k: p[k] for k in fields})
    if not profiles:
        raise BadBody("models.profiles 至少一个档案")
    routes = models["routes"]
    if not isinstance(routes, dict) or set(routes) != set(ROLES):
        raise BadBody(f"models.routes 是 {list(ROLES)} 五个角色")
    for role in ROLES:
        if routes[role] not in names:
            raise BadBody(f"models.routes.{role}={routes[role]!r} 不是已登记的档案")
    out = {"caps": c, "risk": rules, "models": {"profiles": profiles, "routes": {r: routes[r] for r in ROLES}}}
    if "grants" in raw:
        g = raw["grants"]
        if (
            not isinstance(g, dict)
            or set(g) != {"runtime", "auto"}
            or not isinstance(g["runtime"], bool)
            or not isinstance(g["auto"], dict)
            or set(g["auto"]) != {"practice"}
            or not isinstance(g["auto"]["practice"], bool)
        ):
            raise BadBody("grants 是 {runtime: bool, auto: {practice: bool}}")
        out["grants"] = {"runtime": g["runtime"], "auto": {"practice": g["auto"]["practice"]}}
    if "budget" in raw:
        # 时限与花费分开的开关（docs/design/external-verdict/ §5.6）：缺省 elapsed 即旧行为
        bd = raw["budget"]
        if not isinstance(bd, dict) or set(bd) != {"wall_mode", "life_s"} or bd["wall_mode"] not in WALL_MODES:
            raise BadBody(f"budget 是 {{wall_mode: {'|'.join(WALL_MODES)}, life_s: 正整数}}")
        out["budget"] = {"wall_mode": bd["wall_mode"], "life_s": _pos_int(bd["life_s"], "budget.life_s")}
    return out


WALL_MODES = ("elapsed", "spend")
DEFAULT_BUDGET = {"wall_mode": "elapsed", "life_s": 7 * 86400}


def budget_of(settings: dict[str, Any]) -> dict[str, Any]:
    """设置里的 budget 节；缺省（旧快照）即 wall_mode=elapsed，哮天犬照旧按开题墙钟关题。"""
    return settings.get("budget") or dict(DEFAULT_BUDGET)


def grants_of(settings: dict[str, Any]) -> dict[str, Any]:
    """设置里的 grants 节；缺省（旧快照）即运行时扩权关、练习道自动批准开。"""
    return settings.get("grants") or {"runtime": False, "auto": {"practice": True}}


def _changed(old: dict[str, Any], new: dict[str, Any], prefix: str = "") -> list[str]:
    out: list[str] = []
    for k in sorted(set(old) | set(new)):
        a, b, path = old.get(k), new.get(k), f"{prefix}{k}"
        if isinstance(a, dict) and isinstance(b, dict):
            out += _changed(a, b, path + ".")
        elif a != b:
            out.append(path)
    return out


# ---------- 存储 ----------


class SettingsStore:
    def __init__(self, root: Path, initial: dict[str, Any]) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.snap, self.logf = root / "settings.json", root / "settings.log"
        self._lock = threading.Lock()
        if self.snap.exists():
            doc = json.loads(self.snap.read_text(encoding="utf-8"))
            self.version, self.settings = int(doc["version"]), validate(doc["settings"])
        else:
            self.version, self.settings = 1, validate(initial)
            self._write()
            self._append({"version": 1, "from": None, "to": self.digest, "keys": ["*"], "by": "init"})

    @property
    def digest(self) -> str:
        return digest_of(self.settings)

    def doc(self) -> dict[str, Any]:
        return {"version": self.version, "digest": self.digest, "settings": copy.deepcopy(self.settings)}

    def put(self, base_digest: str, raw: object, by: str) -> dict[str, Any]:
        new = validate(raw)
        with self._lock:
            if base_digest != self.digest:
                raise MountError(409, "stale_view", "设置在你读过之后被改过：重读再改", current=self.digest)
            keys = _changed(self.settings, new)
            if not keys:
                return self.doc()
            old = self.digest
            self.version, self.settings = self.version + 1, new
            self._write()
            self._append({"version": self.version, "from": old, "to": self.digest, "keys": keys, "by": by})
            return self.doc()

    def log(self) -> list[dict[str, Any]]:
        if not self.logf.exists():
            return []
        return [json.loads(line) for line in self.logf.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _write(self) -> None:
        tmp = self.snap.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": self.version, "settings": self.settings}, ensure_ascii=False, indent=1))
        tmp.replace(self.snap)

    def _append(self, rec: dict[str, Any]) -> None:
        with self.logf.open("a", encoding="utf-8") as f:
            f.write(json.dumps({**rec, "ts": int(time.time() * 1000)}, ensure_ascii=False) + "\n")

    # ---------- 读的钩子（起草模型等，03 §3.4） ----------

    def profile(self, name: str) -> dict[str, Any] | None:
        return next((dict(p) for p in self.settings["models"]["profiles"] if p["name"] == name), None)

    def resolve(self, role: str, override: str | None = None) -> dict[str, Any]:
        """角色 → 模型档案（端点、模型 id、密钥槽）。override 是任务级覆盖：只能选已登记档案，不能填端点或密钥。"""
        if role not in ROLES:
            raise KeyError(f"没有角色 {role!r}")
        name = override or self.settings["models"]["routes"][role]
        p = self.profile(name)
        if p is None:
            raise KeyError(f"没有模型档案 {name!r}：任务级只能从已登记档案里选")
        return p


# ---------- 接进全栈 ----------


class SettingsHub:
    """设置存储 + 钥匙环的端点；每次设置变更推到图服务（单题硬顶、设置摘要）与端点代理（全局硬顶）。"""

    def __init__(self, store: SettingsStore, graph: GraphService, proxy: EndpointProxy) -> None:
        self.store, self.graph, self.proxy = store, graph, proxy
        self.keyring: KeyRing = proxy.keyring
        # 设置变更后要跟着换的别处（一句话开题：内核的练习道信封抄设置层的练习上限）
        self.listeners: list[Callable[[dict[str, Any]], None]] = []
        self.apply()

    def apply(self) -> None:
        caps = self.store.settings["caps"]
        self.graph.cfg = dataclasses.replace(
            self.graph.cfg,
            open_cap_usd_milli=caps["open_usd_milli"],
            open_cap_wall_s=caps["open_wall_s"],
            settings=(self.store.version, self.store.digest),
            grants_runtime=grants_of(self.store.settings)["runtime"],
            grants_auto_practice=grants_of(self.store.settings)["auto"]["practice"],
            risk_table=tuple(dict(r) for r in self.store.settings["risk"]),
            wall_mode=budget_of(self.store.settings)["wall_mode"],
            life_s=budget_of(self.store.settings)["life_s"],
        )
        self.proxy.cfg.global_cap_usd_milli = caps["global_usd_milli"]
        for fn in self.listeners:
            fn(self.store.settings)

    def mount(self, http: GraphHttp) -> None:
        http.mount("GET", r"/v1/settings", lambda q, b: self.store.doc())
        http.mount("PUT", r"/v1/settings", self._put, human=True)
        http.mount("GET", r"/v1/settings/log", lambda q, b: {"items": self.store.log()})
        http.mount("GET", r"/v1/keys", lambda q, b: self.keys(), human=True)
        http.mount("PUT", r"/v1/keys/(?P<slot>[^/]+)", self._key_put, human=True)
        http.mount("DELETE", r"/v1/keys/(?P<slot>[^/]+)", self._key_clear, human=True)
        http.mount("DELETE", r"/v1/keys", self._keys_clear, human=True)

    def _put(self, q: dict[str, str], body: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(body, dict) or not isinstance(body.get("base_digest"), str) or "settings" not in body:
            raise BadBody("请求体是 {base_digest, settings}")
        out = self.store.put(body["base_digest"], body["settings"], by="human")
        self.apply()
        return out

    def keys(self) -> dict[str, Any]:
        slots = {p["key_slot"] for p in self.store.settings["models"]["profiles"]}
        known = {s["slot"] for s in self.keyring.status()}
        extra = [self.keyring.slot_status(s) for s in sorted(slots - known)]
        return {"slots": sorted(self.keyring.status() + extra, key=lambda s: s["slot"]), "note": KEY_NOTE}

    def _slot(self, q: dict[str, str]) -> str:
        slot = q.get("slot", "")
        if not SLOT_RE.fullmatch(slot):
            raise BadBody("槽名取小写字母、数字、- 与 _，至多 32 字符")
        return slot

    def _key_put(self, q: dict[str, str], body: dict[str, Any] | None) -> dict[str, Any]:
        slot = self._slot(q)
        key = body.get("key") if isinstance(body, dict) else None
        if not isinstance(key, str):
            raise BadBody("请求体是 {key}")
        try:
            st = self.keyring.set(slot, key, source="page")
        except ValueError as e:  # 消息里不带密钥
            raise BadBody(str(e)) from None
        return {**st, "note": KEY_NOTE}

    def _key_clear(self, q: dict[str, str], body: dict[str, Any] | None) -> dict[str, Any]:
        slot = self._slot(q)
        self.keyring.clear(slot)
        return {**self.keyring.slot_status(slot), "note": KEY_NOTE}

    def _keys_clear(self, q: dict[str, str], body: dict[str, Any] | None) -> dict[str, Any]:
        self.keyring.clear_all()
        return self.keys()
