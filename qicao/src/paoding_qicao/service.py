"""起草服务（设计 §6 service.py、§7）：网页 /new 的后端。不持有令牌，不写图服务，不写保密库。

    POST /v1/drafts/extract {text}                                  → 前置抽取（确定性，不调模型）
    POST /v1/drafts {text, answer?, profile?, draft?, model?, nonce?, overrides?, acceptance?, strict?}
                                                                    → 校验结果 + 待提交的批次

开题仍由前端用人的令牌提交（禁令三）：先 PUT /v1/blobs 存题面等材料（本机核对哈希），有答案时 PUT /v1/vault
换回 VaultRef 替换批次里的 "$answer"，最后 POST /v1/problems。这里只算，不落任何东西。

- profile：这次起草用哪个已登记的模型档案（确认卡的“起草用”）；缺省取设置里角色路由的“起草”。
- acceptance：人选“人工验收”后给的清单（每项原文区间或人写的陈述），任务改为 accept=human。
- strict：人选了“严格判定”。没有答案、命令或已登记平台就拒绝；缺省（false）判不了的进开放道（open-lane §3.1），
  lane=open 不出确认卡，前端拿到批次直接提交。
- 交回 draft 即不调模型：确认卡改风险或预算（overrides）后重新校验走这条路，模型只在第一次回车时调一次。
- 零确认在第二期一律关（cz 2026-11-19 裁决 #83 第 2 条附条件；内核信封随第三期）：lane 只有 confirm 与 refuse，
  练习道候选照样标 eligible，卡上写"零确认未放行"。
- 答案：人填在答案栏的不回传；从原文答案行剪出的回传一次（secret），前端只拿它写保密库，不存本机。
- 偏移：区间的 start/end 换成 UTF-16 下标，前端字符串直接切。
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from typing import Any

from .catalog import Catalog, Form
from .draft import DraftError, ModelPort, draft_doc, first_json, parse_draft, prompt, system
from .extract import Extraction
from .importer import ImportError_, import_vetted
from .ops import batch, blobs
from .policy import Intake, PriorSource, Settings
from .vet import ANSWER_SLOT, Vetted, override, vet

MAX_TEXT = 64 * 1024  # 原文上限（字节）
Drafter = Callable[[Extraction, bool], Any]  # (抽取结果, 有没有答案) → 草案的 JSON 形态
# 档案名（None 即设置里角色路由的“起草”）→ (起草器或 None, 档案名, 没有起草器的原因)；未登记的档案名抛 ValueError
Picker = Callable[[str | None], tuple[Drafter | None, str, str]]


class BadRequest(ValueError):
    pass


def model_drafter(model: ModelPort, max_tokens: int = 1200, catalog: Catalog | None = None) -> Drafter:
    """catalog：判据形态目录（注册表驱动）；有外部平台登记时提示里多一种 external。"""
    sys_prompt = system(catalog.kinds() if catalog else None)
    return lambda ext, has: first_json(model.complete(sys_prompt, prompt(ext, has), max_tokens))


def heuristic_drafter(ext: Extraction, has_answer: bool) -> dict[str, Any]:
    """没有模型时的演示起草（假 CLI 后端与端到端测试用）：确定性地挑区间，同样要过 vet。
    目标句取第一个句子；地址都当入口；有答案按答案，否则原文有代码块按命令，否则判不了。"""
    sents = ext.of("sentence")
    first = sents[0] if sents else None
    code = ext.of("code")
    files = ext.of("file")
    form = "answer" if has_answer else ("command" if code else "none")
    base = (first.text if first else ext.text).strip()
    title = base.splitlines()[0][:24] if base else ""
    return {
        "title": title.rstrip("，。,. ") or "无题",
        "goal_sentence": [first.id] if first else [],
        "entries": [{"span": s.id, "role": "entry"} for s in ext.of("addr") + ext.of("url")],
        "deliverable": {"span": files[0].id} if files and has_answer else None,
        "check": {"form": form, **({"spans": [code[0].id]} if form == "command" else {})},
        "deadline": ext.of("duration")[0].id if ext.of("duration") else None,
        "spend": ext.of("money")[0].id if ext.of("money") else None,
        "tier_guess": None,
        "materials": [],
    }


def _u16(text: str) -> Callable[[int], int]:
    acc = [0]
    for ch in text:
        acc.append(acc[-1] + (2 if ord(ch) > 0xFFFF else 1))
    return lambda i: acc[i]


def _spans(ext: Extraction) -> list[dict[str, Any]]:
    u = _u16(ext.text)
    return [{"id": s.id, "kind": s.kind, "start": u(s.start), "end": u(s.end), "text": s.text} for s in ext.spans]


def _text(body: Any) -> str:
    if not isinstance(body, dict):
        raise BadRequest("请求体须是 JSON 对象")
    t = body.get("text")
    if not isinstance(t, str):
        raise BadRequest("text 须是字符串")
    if len(t.encode()) > MAX_TEXT:
        raise BadRequest(f"原文不超过 {MAX_TEXT} 字节")
    return t


class KaitiService:
    def __init__(
        self,
        intake: Intake,
        settings: Callable[[], Settings],
        priors: PriorSource,
        drafter: Drafter | None,
        profile: str = "",
        catalog: Catalog | None = None,
        pick: Picker | None = None,
    ) -> None:
        """settings 是取设置快照的函数：生命周期地图的设置存储（/v1/settings）上线后由组装根换成它。
        catalog 是判据形态目录（注册表与连接器档案驱动，见 catalog.py）；缺省只有 answer 与 command。
        pick 按档案名逐次给出起草器（宪章 Q28：档案、端点、密钥槽都在设置页，密钥在钥匙环）；
        给了它，drafter 与 profile 就不再用。"""
        self.intake, self.settings, self.priors, self.drafter, self.profile = intake, settings, priors, drafter, profile
        self.catalog = catalog
        self.pick = pick

    def _extract(self, text: str) -> Extraction:
        return self.intake.extract(text)

    def extract_view(self, body: Any) -> dict[str, Any]:
        ext = self._extract(_text(body))
        return {"text": ext.text, "spans": _spans(ext), "answers": len([a for a in ext.answers if a])}

    def draft_view(self, body: Any) -> dict[str, Any]:
        text = _text(body)
        answer = body.get("answer")
        if answer is not None and not isinstance(answer, str):
            raise BadRequest("answer 须是字符串")
        nonce = body.get("nonce") or secrets.token_hex(8)
        if not isinstance(nonce, str) or len(nonce) > 64:
            raise BadRequest("nonce 须是不超过 64 字的字符串")
        ext = self._extract(text)
        has = bool((answer or "").strip()) or any(ext.answers)
        want = body.get("profile")
        if want is not None and (not isinstance(want, str) or not 0 < len(want) <= 64):
            raise BadRequest("profile 须是已登记的模型档案名")
        settings = self.settings()
        doc, err, model = body.get("draft"), "", self.profile
        if doc is not None:
            model = str(body.get("model") or "")[:64]
        else:
            drafter = self.drafter
            if self.pick is not None:
                try:
                    drafter, model, err = self.pick(want)
                except ValueError as e:
                    raise BadRequest(str(e)) from None
            elif want is not None:
                raise BadRequest("本部署的起草不按档案选模型")
            if drafter is None:
                err = err or "本部署没有配置起草模型"
            else:
                try:
                    doc = drafter(ext, has)
                except (DraftError, OSError, ValueError) as e:
                    err = str(e)
        d = None
        if doc is not None:
            try:
                d = parse_draft(doc, ext, model)
            except DraftError as e:
                err = str(e)
        acc = body.get("acceptance")
        if acc is not None and (
            not isinstance(acc, list)
            or not all(isinstance(a, dict) and set(a) <= {"span", "text", "needs"} for a in acc)
        ):
            raise BadRequest("acceptance 须是 [{span} | {text}, needs?] 的列表")
        strict = body.get("strict", False)
        if not isinstance(strict, bool):
            raise BadRequest("strict 须是 true 或 false")
        v = vet(
            ext,
            answer,
            d,
            self.intake,
            settings,
            self.priors,
            zero_confirm=False,
            nonce=nonce,
            draft_error=err,
            catalog=self.catalog,
            acceptance=acc or None,
            strict=strict,
        )
        ov = body.get("overrides")
        if ov:
            if not isinstance(ov, dict):
                raise BadRequest("overrides 须是对象")
            try:
                v = override(v, ov, settings)
            except (ValueError, TypeError) as e:
                raise BadRequest(str(e)) from None
        if want is not None and model == want:
            # 人在确认卡上选的起草档案：出处记“人”（重新校验时前端带回同一个 profile；演示起草不按档案，不记）
            for r in v.derivation:
                if r["field"] == "draft.model":
                    r["source"], r["note"] = "human", "你选的起草档案"
        return self._view(v, ext, d, model, nonce, answer)

    def _view(self, v: Vetted, ext: Extraction, d: Any, model: str, nonce: str, answer: str | None) -> dict[str, Any]:
        out: dict[str, Any] = {
            **v.public(),
            "pid": v.pid,
            "nonce": nonce,
            "text": ext.text,
            "spans": _spans(ext),
            "has_answer": v.secret is not None,
            "draft": draft_doc(d) if d is not None else None,
            "model": model,
            "zero_confirm": False,
            "caps": {k: int(self.settings().caps[k]) for k in ("open_usd_milli", "open_wall_s")},
            "blobs": [],
            "ops": None,
        }
        if v.lane == "refuse" or v.input is None:
            # 降级路（§5.8）：补判定终点、人工验收（D3）、高级模式、去设置页登记这个平台；
            # 开放道开着时，因“判不了”被拒的题多一条路：不要严格判定，按开放道去做
            out["ways"] = ["endpoint", "human", "advanced", "register_platform"]
            if self.settings().lanes_open and any(n.code == "no_criterion" for n in v.notes):
                out["ways"].insert(0, "open")
            return out
        if v.external is not None or v.needs_ack:
            # 外部判定：创建时才领题，批次由导入生成；命令有外发形状：人勾选之前不给批次
            return out
        return self._ops(out, v, answer)

    def _ops(self, out: dict[str, Any], v: Vetted, answer: str | None) -> dict[str, Any]:
        for name, (media, data) in blobs(v).items():
            out["blobs"].append(
                {
                    "name": name,
                    "media_type": media,
                    "text": data.decode(),
                    "hash": hashlib.sha256(data).hexdigest(),
                    "size": len(data),
                }
            )
        out["ops"] = batch(v, lambda b: hashlib.sha256(b).hexdigest(), ANSWER_SLOT if v.secret is not None else None)
        if v.secret is not None and not (answer or "").strip():
            out["secret"] = v.secret  # 只在答案来自原文答案行时回传：前端拿它写保密库
        return out

    def import_view(
        self,
        form: Form,
        item: dict[str, Any],
        statement: str,
        notice: bytes,
        *,
        now_ms: int,
        nonce: str = "",
        budget: Any = None,
    ) -> dict[str, Any]:
        """从平台导入（§5.8）：领题由调用方做完（组装根），这里排版成与 draft_view 同形的确认卡与批次。"""
        if budget is not None and not isinstance(budget, dict):
            raise BadRequest("budget 须是 {usd_milli?, wall_s?}")
        settings = self.settings()
        nonce = nonce or secrets.token_hex(8)
        try:
            v = import_vetted(
                form,
                item,
                statement,
                notice,
                self.intake,
                settings,
                self.priors,
                now_ms=now_ms,
                nonce=nonce,
                budget=budget,
            )
        except ImportError_ as e:
            raise BadRequest(str(e)) from None
        out: dict[str, Any] = {
            **v.public(),
            "pid": v.pid,
            "nonce": nonce,
            "text": statement,
            "spans": [],
            "has_answer": False,
            "draft": None,
            "model": "",
            "zero_confirm": False,
            "caps": {k: int(settings.caps[k]) for k in ("open_usd_milli", "open_wall_s")},
            "blobs": [],
            "ops": None,
        }
        return self._ops(out, v, None)
