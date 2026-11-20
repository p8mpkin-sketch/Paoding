// 一句话开题（设计 docs/design/kaiti §7；迁移表第二期）。/new 是一个输入框：回车 → 起草服务给出校验结果 →
// 确认卡（原文逐段标号对字段）或拒绝页（三条降级路）。零确认一律关：练习道候选也要人按"开题"。
// 页面不推导任何字段：抽取、校验、分道都在服务端（qicao 的 vet），这里只排版、只收人改的风险与预算。
import * as Popover from "@radix-ui/react-popover";
import { ChevronDown } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { newIdemKey } from "../api/client";
import type { ProfilePreview, Risk, VaultRef } from "../api/types";
import type { KaitiAcceptance, KaitiExtract, KaitiOverrides, KaitiRow, KaitiVetted } from "../api/kaiti";
import type { Settings, SettingsSources } from "../api/settings-types";
import { useServices } from "../app/context";
import { saveDraft } from "../app/draft";
import { navigate } from "../app/router";
import { submitVetted } from "../app/submit";
import { Kbd, Mark, SectionHead, btnClass } from "../kit";
import {
  circled, fieldWord, goalSentences, GROUPS, groupOf, segments, SOURCE, spanNumbers, usdOf, valueText, wallOf, wizardDraftOf,
} from "../model/kaiti";
import { draftFromTemplate } from "../model/wizard";
import { Link, Recent } from "./Problems";
import { pending, recorded, rejected } from "../ui/feedback";
import { Plain } from "../ui/registers";
import { rejectText } from "../ui/useProposal";

const EXAMPLE = "例：目标在 q1:8080，是个登录页，登录后页面会显示一个答案串，把它交出来。半小时内搞定。";
const KIND_WORD: Record<string, string> = { code: "代码", url: "网址", addr: "地址", host: "域名", money: "金额", duration: "时长", file: "文件" };
const RISK_WORD: Record<Risk, string> = { r0: "r0 可逆或只读", r1: "r1 有成本", r2: "r2 不可逆" };
const EXTRACT_DEBOUNCE_MS = 300;

/** 输入框下面的前置抽取（确定性，不调模型）：人按回车之前就能看到系统会给它哪些地址。 */
function Extracted({ ext }: { ext: KaitiExtract | null }) {
  if (!ext) return null;
  const toks = ext.spans.filter((s) => s.kind !== "sentence");
  return (
    <div className="kt-extract" data-kaiti-extract aria-live="polite">
      {toks.length === 0 && ext.answers === 0 ? <span className="t2">还没认出地址、时长、金额或代码</span> : null}
      {toks.map((s) => (
        <span key={s.id} className="kt-chip" data-kind={s.kind}>{KIND_WORD[s.kind] ?? s.kind} <code><Plain text={s.text} /></code></span>
      ))}
      {ext.answers > 0 && <span className="kt-chip" data-kind="answer">答案行 {ext.answers} 处 · 已收起，不进题面、不给起草模型</span>}
    </div>
  );
}

/** 原文，被引用的区间带编号；句子与词元的下划线样式不同（不靠颜色）。 */
function Original({ v, nums }: { v: KaitiVetted; nums: Map<string, number> }) {
  const segs = useMemo(() => segments(v.text, v.spans, nums), [v, nums]);
  return (
    <p className="kt-text" data-kaiti-text>
      {segs.map((s, i) => (
        <span key={i}>
          <span className={[s.sentence ? "kt-sent" : "", s.token ? "kt-tok" : ""].filter(Boolean).join(" ") || undefined}><Plain text={s.text} /></span>
          {s.ends.map((n) => <sup key={n} className="kt-n" data-span-no={n}><span aria-hidden="true">{circled(n)}</span><span className="sr-only">（原文第 {n} 段到此）</span></sup>)}
        </span>
      ))}
    </p>
  );
}

function Source({ r, nums }: { r: KaitiRow; nums: Map<string, number> }) {
  const s = SOURCE[r.source];
  const refs = (r.spans ?? []).map((id) => nums.get(id)).filter((n): n is number => n !== undefined);
  return (
    <span className="kt-srcs" data-source={r.source}>
      <Mark ch={s.ch} tone={s.tone} label={s.word} />
      {refs.length > 0 && <span className="k-mono">{refs.map(circled).join("")}<span className="sr-only">摘自原文第 {refs.join("、")} 段</span></span>}
    </span>
  );
}

const SESSION_ROLES = [["bootstrap", "Bootstrap"], ["reason", "Reason"], ["explore", "Explore"], ["verify", "Verify"]] as const;

/** 05 模型（宪章 02 §3.2、03 §3.1，Q10、Q12）：起草用哪个档案（改了即重新起草）；执行用哪个档案（缺省按角色路由，
 * 另选即写进任务的 prefs.model，会话开起时按它解析一次）。两处都只列设置页登记过的档案。 */
function ModelBlock({ v, models, busy, onPick, onRun, nums }: {
  v: KaitiVetted; models: Settings["models"] | null; busy: boolean; onPick: (name: string) => void; onRun: (name: string | null) => void; nums: Map<string, number>;
}) {
  const row = v.derivation.find((r) => r.field === "draft.model");
  const runRow = v.derivation.find((r) => r.field === "prefs.model");
  const run = v.input?.prefs?.model ?? "";
  const names = models?.profiles.map((p) => p.name) ?? [];
  const known = names.includes(v.model);
  return (
    <div className="kt-group" data-group="模型" data-model-block>
      <div className="kt-group-h">模型</div>
      <dl className="kt-rows">
        <div className="kt-row" data-field="draft.model">
          <dt>起草用</dt>
          <dd>
            {names.length > 0 ? (
              <select value={known ? v.model : ""} aria-label="起草用的模型档案（改了即重新起草）" data-action="pick-draft-profile" disabled={busy}
                onChange={(e) => { if (e.target.value) onPick(e.target.value); }}>
                {!known && <option value="" disabled>{v.model ? `${v.model}（演示起草，不按档案）` : "（未起草）"}</option>}
                {names.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            ) : <span className="kt-val"><Plain text={v.model || "—"} /></span>}
            {row && <Source r={row} nums={nums} />}
            <span className="t2 kt-note">只列设置页登记过的档案；改了会重新起草一次</span>
          </dd>
        </div>
        <div className="kt-row" data-field="prefs.model">
          <dt>执行用</dt>
          <dd>
            {names.length > 0 && (
              <select value={run} aria-label="执行会话用的模型档案" data-action="pick-run-profile" disabled={busy || !v.input}
                onChange={(e) => onRun(e.target.value || null)}>
                <option value="">按角色路由（缺省）</option>
                {names.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            )}
            {run ? (runRow && <Source r={runRow} nums={nums} />) : (
              <>
                <span className="kt-val" data-session-routes>
                  {models ? SESSION_ROLES.map(([k, w]) => `${w} → ${models.routes[k]}`).join(" · ") : "读取中…"}
                </span>
                <Mark ch={SOURCE.table.ch} tone={SOURCE.table.tone} label="查设置页的角色路由" />
              </>
            )}
            <span className="t2 kt-note">另选一个档案，这个任务的每个会话都用它；会话开起时定下，中途改设置不影响已在跑的会话</span>
          </dd>
        </div>
      </dl>
    </div>
  );
}

/** 拒绝页第 02 条路（宪章 D3、02 §3.3）：验收清单只许原文里的句子或你自己写的，模型不起草条目。 */
function HumanWay({ v, busy, onGo }: { v: KaitiVetted; busy: boolean; onGo: (items: KaitiAcceptance[]) => void }) {
  const sents = v.spans.filter((x) => x.kind === "sentence");
  const [picked, setPicked] = useState<string[]>([]);
  const [lines, setLines] = useState<{ text: string; artifact: boolean }[]>([{ text: "", artifact: false }]);
  const items: KaitiAcceptance[] = [
    ...sents.filter((x) => picked.includes(x.id)).map((x) => ({ span: x.id })),
    ...lines.filter((l) => l.text.trim()).map((l) => ({ text: l.text.trim(), ...(l.artifact ? { needs: "artifact" as const } : {}) })),
  ];
  const edit = (k: number, patch: Partial<{ text: string; artifact: boolean }>) => setLines((xs) => xs.map((l, j) => (j === k ? { ...l, ...patch } : l)));
  return (
    <div className="kt-human" data-human-way>
      {sents.length > 0 && <>
        <div className="sheet-sub">从原文里选<span className="t2">逐字取原句，出处记“摘”</span></div>
        <ul className="kt-acc">
          {sents.map((x) => (
            <li key={x.id}><label><input type="checkbox" data-acc-span={x.id} checked={picked.includes(x.id)} disabled={busy}
              onChange={(e) => setPicked((p) => (e.target.checked ? [...p, x.id] : p.filter((y) => y !== x.id)))} /> <Plain text={x.text} /></label></li>
          ))}
        </ul>
      </>}
      <div className="sheet-sub">自己写<span className="t2">一条一句、能被你判断的陈述，出处记“人”</span></div>
      <ul className="kt-acc">
        {lines.map((l, k) => (
          <li key={k}>
            <input value={l.text} maxLength={200} placeholder="例如：对比覆盖至少三个框架" data-acc-text={k} disabled={busy} onChange={(e) => edit(k, { text: e.target.value })} />
            <label className="t2"><input type="checkbox" checked={l.artifact} data-acc-needs={k} disabled={busy} onChange={(e) => edit(k, { artifact: e.target.checked })} /> 验收时要附交付物</label>
          </li>
        ))}
      </ul>
      <button type="button" className={btnClass("bare", "sm")} data-action="acc-add" disabled={busy || lines.length >= 32} onClick={() => setLines((xs) => [...xs, { text: "", artifact: false }])}>再加一条</button>{" "}
      <button type="button" className={btnClass("line", "sm")} data-action="refuse-human" disabled={busy || items.length === 0} onClick={() => onGo(items)}>按这份清单起草</button>
    </div>
  );
}

const TIER_WORD: Record<string, string> = { easy: "小", medium: "中", hard: "大" };
const money = (milli: number) => `$${(milli / 1000).toFixed(2)}`;
const tierWord = (k: string, t: SettingsSources["priors"] | null) => {
  const x = t?.tiers[k];
  return x ? `${TIER_WORD[k] ?? k} · ${money(x.usd_milli)}` : k;
};

/** 输入框下面的一个选项：显示当前值，点开才展开。 */
function ChipPop({ label, value, field, disabled, children }: { label: string; value: string; field: string; disabled?: boolean; children: React.ReactNode }) {
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button type="button" className="kt-pickb" data-field={field} disabled={disabled}>{label} <b>{value}</b><ChevronDown aria-hidden="true" /></button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content className="kt-pop" align="start" sideOffset={6} data-pop={field}>{children}</Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

export function Kaiti({ home = false }: { home?: boolean } = {}) {
  const { api, cfg } = useServices();
  const writable = cfg.token !== null;
  const [text, setText] = useState("");
  const [answer, setAnswer] = useState("");
  const [ext, setExt] = useState<KaitiExtract | null>(null);
  const [v, setV] = useState<KaitiVetted | null>(null);
  const [ov, setOv] = useState<KaitiOverrides>({});
  const [acc, setAcc] = useState<KaitiAcceptance[] | null>(null);
  const [busy, setBusy] = useState<"draft" | "revet" | "open" | "advanced" | null>(null);
  const [err, setErr] = useState<Error | null>(null);
  const [fieldErr, setFieldErr] = useState<string | null>(null);
  const [preview, setPreview] = useState<ProfilePreview | null>(null);
  const [models, setModels] = useState<Settings["models"] | null>(null);
  const [prof, setProf] = useState<string | null>(null);
  // 输入框旁选的执行模型（前端 v5 第二期）：空即按角色路由；选了就在起草后作为 overrides.model 交回校验，写进 prefs.model
  const [runPick, setRunPick] = useState("");
  // 预算档位（v5 第三期）：档位表来自外部注入的先验表（/v1/settings/sources 的 priors；占位表时如实标出）；空即按服务端先验
  const [tiers, setTiers] = useState<SettingsSources["priors"] | null>(null);
  const [tier, setTier] = useState("");
  // 严格判定：默认关。关着时不收答案，开放道回车即开；打开才出答案框与判定方式的入口
  const [strictOn, setStrictOn] = useState(false);
  const [usdS, setUsdS] = useState("");
  const [minS, setMinS] = useState("");
  const box = useRef<HTMLTextAreaElement>(null);
  const idem = useRef<{ key: string; body: string }>({ key: newIdemKey(), body: "" });

  // 前置抽取：停手 300 毫秒后取一次；要人的令牌（与起草同一个入口）
  useEffect(() => {
    if (!writable || !text.trim()) { setExt(null); return; }
    let live = true;
    const t = setTimeout(() => { api.draftExtract(text).then((x) => { if (live) setExt(x); }, () => { if (live) setExt(null); }); }, EXTRACT_DEBOUNCE_MS);
    return () => { live = false; clearTimeout(t); };
  }, [api, text, writable]);

  // 模型档案与角色路由：读设置页那一份（要人的令牌），卡上只列已登记的档案
  useEffect(() => {
    if (!writable) return;
    let live = true;
    api.settings().then((d) => { if (live) setModels(d.settings.models); }, () => { if (live) setModels(null); });
    return () => { live = false; };
  }, [api, writable]);

  useEffect(() => {
    let live = true;
    api.settingsSources().then((d) => { if (live) setTiers(d.priors); }, () => { if (live) setTiers(null); });
    return () => { live = false; };
  }, [api]);

  // 卡上的数字框跟着校验结果走
  useEffect(() => {
    const b = v?.input?.budget;
    setUsdS(b ? String(b.usd_milli / 1000) : "");
    setMinS(b ? String(Math.round((b.wall_s / 60) * 100) / 100) : "");
  }, [v]);

  // 画像预览：服务端同一个推导函数（/v1/profile/preview），与向导一样
  const scopeKey = v?.input ? JSON.stringify([v.input.scope, v.input.goal.check?.judge_id ?? "open"]) : "";
  useEffect(() => {
    if (!v?.input) { setPreview(null); return; }
    let live = true;
    const check = v.input.goal.check;
    api.profilePreview({ scope: v.input.scope, goal: check ? { check: { judge_id: check.judge_id } } : { accept: "open" } }).then((p) => { if (live) setPreview(p); }, () => { if (live) setPreview(null); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, scopeKey]);

  const nums = useMemo(() => (v ? spanNumbers(v.spans, v.derivation) : new Map<string, number>()), [v]);

  async function draftIt(profile: string | null = null, strict = false) {
    if (!text.trim() || busy) return;
    setBusy("draft"); setErr(null); setFieldErr(null);
    let out: KaitiVetted | null = null;
    try {
      out = await api.draftVet({ text, ...(answer.trim() ? { answer } : {}), ...(profile ? { profile } : {}), ...(strict ? { strict } : {}) });
      const t = tier ? tiers?.tiers[tier] : undefined;
      const want: KaitiOverrides = { ...(runPick ? { model: runPick } : {}), ...(t ? { usd_milli: t.usd_milli, wall_s: t.wall_s } : {}) };
      let picked: KaitiOverrides = {};
      if (Object.keys(want).length && out.input && out.lane !== "refuse" && out.draft) {
        // 交回同一份草案（不再调模型），只加输入框下面选的执行模型与预算档位
        picked = want;
        out = await api.draftVet({ text, ...(answer.trim() ? { answer } : {}), draft: out.draft, model: out.model, ...(profile ? { profile } : {}), nonce: out.nonce, overrides: picked });
      }
      setV(out); setOv(picked); setProf(profile); setAcc(null);
    } catch (e) {
      setErr(e as Error); setV(null);
      out = null; // 人选的执行模型或预算没写进去：不按开放道自动开题
    } finally {
      setBusy(null);
    }
    // 开放道不出确认卡（open-lane §3.1 第 3 点）：开题零出站、花费有硬顶，回车即创建，进任务页看它做
    if (out?.lane === "open" && out.ops) await openIt(out);
  }

  async function revet(next: KaitiOverrides) {
    if (!v?.draft) return;
    setBusy("revet"); setFieldErr(null);
    try {
      const out = await api.draftVet({ text, ...(answer.trim() ? { answer } : {}), draft: v.draft, model: v.model, ...(prof ? { profile: prof } : {}), nonce: v.nonce, overrides: next, ...(acc ? { acceptance: acc } : {}) });
      setV(out); setOv(next);
    } catch (e) {
      setFieldErr(rejectText(e as Error) ?? (e as Error).message);
      setV({ ...v }); // 数字框回到上一份校验结果
    } finally {
      setBusy(null);
    }
  }

  /** 拒绝页第 02 条路：带着人给的验收清单重新校验（交回草案，不再调模型），任务改为人工验收。 */
  async function humanRoute(items: KaitiAcceptance[]) {
    if (!v?.draft || busy) return;
    setBusy("revet"); setErr(null);
    try {
      const out = await api.draftVet({ text, ...(answer.trim() ? { answer } : {}), draft: v.draft, model: v.model, ...(prof ? { profile: prof } : {}), nonce: v.nonce, acceptance: items });
      setV(out); setOv({}); setAcc(items);
    } catch (e) {
      setErr(e as Error);
    } finally {
      setBusy(null);
    }
  }

  async function openIt(given: KaitiVetted | null = null) {
    const cur = given ?? v;
    if (!cur || cur.lane === "refuse" || cur.needs_ack === "command" || (busy && !given)) return;
    setBusy("open"); setErr(null);
    const body = JSON.stringify([cur.ops, cur.blobs.map((b) => b.hash)]);
    if (idem.current.body !== body) idem.current = { key: newIdemKey(), body };
    const t = pending("新建任务");
    try {
      // 外部判定：此刻才领题（平台从这一刻开始计时），批次由导入生成；卡上改过的预算一并带过去
      const ready = cur.external
        ? await api.platformImport(cur.external.connector, { task: cur.external.task, nonce: cur.nonce, budget: cur.input ? { usd_milli: cur.input.budget.usd_milli, wall_s: cur.input.budget.wall_s } : undefined })
        : cur;
      const r = await submitVetted(api, ready, answer, idem.current.key);
      recorded(t, "新建任务", r.seq);
      navigate({ page: "problem", pid: r.pid, asOf: null, node: null });
    } catch (e) {
      setErr(e as Error);
      rejected(t, "新建任务", rejectText(e as Error) ?? (e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  /** 带着草案进四步向导（高级模式）。有答案时先写保密库，草稿里只放引用。 */
  async function advanced() {
    setBusy("advanced"); setErr(null);
    try {
      if (v?.input) {
        let ref: VaultRef | null = null;
        if (v.has_answer) ref = await api.putVault(new TextEncoder().encode(answer.trim() || v.secret || ""));
        saveDraft(wizardDraftOf(v, ref), 0);
      } else {
        const base = draftFromTemplate(null);
        const goal = v ? goalSentences(v).join("") : "";
        saveDraft({
          ...base, statement: goal, kaiti: { text: v?.text ?? text },
          materials: [{ ...base.materials[0], kind: "text", text: v?.text ?? text }],
          marks: { statement: goal ? "span" : "human", materials: "span" },
        }, 1);
      }
      navigate({ page: "new", advanced: true });
    } catch (e) {
      setErr(e as Error);
    } finally {
      setBusy(null);
    }
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing) return;
    e.preventDefault();
    void draftIt(prof);
  }

  function onCardKey(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); void openIt(); }
  }

  function commitUsd() {
    const n = Math.round(Number(usdS) * 1000);
    if (!Number.isFinite(n) || n <= 0) { setFieldErr("成本上限须为正数（美元）"); return; }
    if (v?.input && n !== v.input.budget.usd_milli) void revet({ ...ov, usd_milli: n });
  }
  function commitWall() {
    const n = Math.round(Number(minS) * 60);
    if (!Number.isFinite(n) || n <= 0) { setFieldErr("时间上限须为正数（分钟）"); return; }
    if (v?.input && n !== v.input.budget.wall_s) void revet({ ...ov, wall_s: n });
  }

  const refused = v?.lane === "refuse";
  const acked = !!v?.derivation.some((r) => r.field === "goal.check.ack");
  const notes = v?.notes ?? [];
  const noCriterion = notes.some((n) => n.code === "no_criterion" || n.code === "answer_missing");

  return (
    <div className="kaiti" data-kaiti data-lane={v?.lane ?? "input"}>
      <section className="kt-hero" data-kaiti-input>
        <h1 className="kt-ask">要做什么？</h1>
        <div className="kt-composer">
          {models !== null && models.profiles.length === 0 && (
            <div className="kt-notice" role="status"><span><b>还没有能用的模型。</b>先添加一个并测通，才能开始。</span><Link to={{ page: "models" }} className={btnClass("ink", "sm")}>添加模型</Link></div>
          )}
          <label className="sr-only" htmlFor="kt-text">要做的事</label>
          <textarea id="kt-text" ref={box} className="kt-box" data-field="kaiti-text" value={text} placeholder={strictOn ? EXAMPLE : "说一句要做的事。不用给标准答案，做完会附上证据。"} rows={3}
            disabled={!writable || busy === "open"}
            onChange={(e) => { setText(e.target.value); if (v) setV(null); }} onKeyDown={onKey} />
          <Extracted ext={ext} />
          <div className="kt-bar">
            <ChipPop label="模型" value={runPick ? runPick : "自动"} field="run-model" disabled={!writable || busy !== null}>
              <p className="kt-pop-h">执行用的模型</p>
              <select value={runPick} aria-label="执行这个任务用的模型" data-field="run-model-select"
                onChange={(e) => { setRunPick(e.target.value); if (v) setV(null); }}>
                <option value="">自动（按默认分配）</option>
                {(models?.profiles ?? []).map((p) => <option key={p.name} value={p.name}>{p.name}{p.model ? ` · ${p.model}` : ""}</option>)}
              </select>
              <Link to={{ page: "models" }} className="kt-pop-link">管理模型</Link>
            </ChipPop>
            <ChipPop label="预算" value={tier ? tierWord(tier, tiers) : "自动"} field="budget-tier" disabled={!writable || busy !== null}>
              <p className="kt-pop-h">花多少、跑多久</p>
              <div className="kt-tiers" role="radiogroup" aria-label="预算档位">
                <button type="button" role="radio" aria-checked={tier === ""} data-tier="" onClick={() => { setTier(""); if (v) setV(null); }}>自动<span className="t2">按任务的类型估</span></button>
                {Object.entries(tiers?.tiers ?? {}).map(([k, t]) => (
                  <button key={k} type="button" role="radio" aria-checked={tier === k} data-tier={k} onClick={() => { setTier(k); if (v) setV(null); }}>
                    {TIER_WORD[k] ?? k}<span className="t2 k-mono">{money(t.usd_milli)} · {Math.round(t.wall_s / 60)} 分钟</span>
                  </button>
                ))}
              </div>
              {tiers?.placeholder && <p className="t2">档位数字是占位表，正式值由部署注入。</p>}
            </ChipPop>
            <ChipPop label="知识" value="自动" field="knowledge" disabled={!writable}>
              <p className="kt-pop-h">它会用到的知识</p>
              <p className="t2">现在自动用以前任务沉淀下来的记忆（开始前先复核）。导入资料、执行时检索的资料库做好后，这里可以指定资料或不用。</p>
            </ChipPop>
            <span className="grow" />
            <button type="button" className="kt-switch" role="switch" aria-checked={strictOn} data-action="strict" disabled={!writable || busy !== null}
              onClick={() => { setStrictOn(!strictOn); if (strictOn) setAnswer(""); if (v) setV(null); }}>
              <span className="kt-sw" aria-hidden="true" />严格判定
            </button>
            <button type="button" className={btnClass("ink")} data-action="draft" disabled={!writable || !text.trim() || busy !== null || (models !== null && models.profiles.length === 0)} onClick={() => void draftIt(prof)}>
              {busy === "draft" ? "起草中…" : "开始"} <Kbd>↵</Kbd>
            </button>
          </div>
          {strictOn && (
            <div className="kt-strict" data-kaiti-answer>
              <p className="t2">给练习和评测用：由判定器比对结果，记入解出率。平时不用开。开始前会先给你看一张确认卡：判据、授权、预算。</p>
              <label className="kt-f">
                <span>答案（只给判定器，智能体看不到）</span>
                <input type="password" autoComplete="off" value={answer} data-field="kaiti-answer" placeholder="粘贴标准答案；也可以在原文里写“答案：…”"
                  onChange={(e) => { setAnswer(e.target.value); if (v) setV(null); }} />
              </label>
              <p className="t2">检查命令直接写在原文里（例如“跑 make test 返回 0”）。判定权在外部平台的，<Link to={{ page: "platform" }} data-action="to-platform">从平台导入</Link>；要逐项填，用<Link to={{ page: "new", advanced: true }} data-action="advanced-blank">高级模式</Link>。</p>
            </div>
          )}
        </div>
        <p className="kt-facts"><span>回车开始，Shift+回车换行</span><span>默认不联网，要访问外部地址时会先问你</span><span>预算用完前会先把已有结果交出来</span></p>
        {!writable && <p className="t2">新建任务要人的令牌：先在左下角配置。</p>}
        {err && <p className="error" data-reject>{rejectText(err) ?? err.message}</p>}
      </section>
      {home && !v && <Recent />}

      {v && !refused && v.input && (
        <div className="kt-card" data-kaiti-card onKeyDown={onCardKey}>
          <div className="kt-cols">
            <section className="kt-col" aria-label="原文">
              <SectionHead title="原文" note="编号对应右边的字段" />
              <Original v={v} nums={nums} />
              {v.has_answer && <p className="t2" data-answer-sealed>答案已收起：不在题面里，起草模型也没看到。</p>}
            </section>

            <section className="kt-col" aria-label="任务单">
              <SectionHead title={<Plain text={v.input.title} />} note={<>任务编号 <span className="k-mono"><Plain text={v.pid} /></span></>} />
              {GROUPS.map((g) => {
                const rows = v.derivation.filter((r) => groupOf(r.field) === g);
                return (
                  <div key={g} className="kt-group" data-group={g}>
                    <div className="kt-group-h">{g}{g === "判据" && v.input!.goal.accept === "human" && <span className="t2" data-human-accept> · 终态最多为人工验收（已验收），不写“已证明”</span>}</div>
                    <dl className="kt-rows">
                      {rows.map((r, i) => {
                        const risk = r.field.match(/^scope\[(\d+)\]\.risk$/);
                        return (
                          <div key={`${r.field}-${i}`} className="kt-row" data-field={r.field}>
                            <dt>{fieldWord(r.field)}</dt>
                            <dd>
                              {risk ? (
                                <select value={String(r.value)} aria-label={`${fieldWord(r.field)}（可改）`} data-risk={risk[1]} disabled={busy !== null}
                                  onChange={(e) => void revet({ ...ov, risk: { ...(ov.risk ?? {}), [risk[1]]: e.target.value as Risk } })}>
                                  {(Object.keys(RISK_WORD) as Risk[]).map((k) => <option key={k} value={k}>{RISK_WORD[k]}</option>)}
                                </select>
                              ) : r.field === "budget.usd_milli" ? (
                                <span className="kt-num"><span aria-hidden="true">$</span>
                                  <input inputMode="decimal" value={usdS} data-field="usd" aria-label="成本上限（美元，可改）" disabled={busy !== null}
                                    onChange={(e) => setUsdS(e.target.value)} onBlur={commitUsd} onKeyDown={(e) => { if (e.key === "Enter" && !e.metaKey && !e.ctrlKey) { e.preventDefault(); commitUsd(); } }} />
                                  <span className="t2">上限 {usdOf(v.caps.open_usd_milli)}</span></span>
                              ) : r.field === "budget.wall_s" ? (
                                <span className="kt-num">
                                  <input inputMode="decimal" value={minS} data-field="wall-min" aria-label="时间上限（分钟，可改）" disabled={busy !== null}
                                    onChange={(e) => setMinS(e.target.value)} onBlur={commitWall} onKeyDown={(e) => { if (e.key === "Enter" && !e.metaKey && !e.ctrlKey) { e.preventDefault(); commitWall(); } }} />
                                  <span className="t2">分钟 · 上限 {wallOf(v.caps.open_wall_s)}</span></span>
                              ) : <span className="kt-val"><Plain text={valueText(r)} /></span>}
                              <Source r={r} nums={nums} />
                              {r.note && <span className="t2 kt-note"><Plain text={r.note} /></span>}
                            </dd>
                          </div>
                        );
                      })}
                      {g === "判据" && v.has_answer && (
                        <div className="kt-row" data-field="answer"><dt>答案</dt><dd><span className="kt-val">已收起，只给判定器（保密库）</span><Mark ch="人" tone="jie" label="你给的" /></dd></div>
                      )}
                      {g === "判据" && v.input!.goal.check?.spec_ref !== undefined && (
                        <div className="kt-row kt-warn" data-field="command-note"><dt /><dd className="t2">
                          判定器会在洁净容器里<b>重放</b>这条命令，按退出码判定，创建后不能改。如果它是向外部平台提交，它就不是检查：重放会再提交一次，或者因为出不去网被判失败。外部平台说了算的任务，请先<Link to={{ page: "settings" }}>登记这个平台</Link>，再<Link to={{ page: "platform" }}>从平台导入</Link>。
                        </dd></div>
                      )}
                      {g === "判据" && (v.needs_ack === "command" || acked) && (
                        <div className="kt-row kt-warn" data-field="command-ack"><dt /><dd>
                          <label><input type="checkbox" checked={acked} disabled={busy !== null} data-action="ack-command"
                            onChange={(e) => { const { ack_command: _drop, ...rest } = ov; void revet(e.target.checked ? { ...rest, ack_command: true } : rest); }} />
                            {" "}我确认这条命令只检查、不提交</label>
                          {!acked && <span className="t2">命令有外发的形状：勾选之后才能创建</span>}
                        </dd></div>
                      )}
                    </dl>
                  </div>
                );
              })}
              <ModelBlock v={v} models={models} busy={busy !== null} nums={nums} onPick={(n) => void draftIt(n)}
                onRun={(n) => { setRunPick(n ?? ""); const { model: _drop, ...rest } = ov; void revet(n ? { ...rest, model: n } : rest); }} />
              {fieldErr && <p className="error" data-field-error><Plain text={fieldErr} /></p>}
            </section>

            <aside className="kt-col kt-side" aria-label="为什么要你看">
              <div className="kt-lane" data-lane-chip>
                <b>{v.lane === "open" ? "开放道 · 未经判定" : "确认道 · 一步确认"}</b>
                {v.external && <span className="t2" data-external>外部判定 · 平台 <span className="k-mono"><Plain text={v.external.connector} /></span> · 创建时领题</span>}
                {v.eligible && <span className="t2" data-eligible>练习道候选 · 零确认尚未放行</span>}
              </div>
              <div className="sheet-sub">为什么要你看</div>
              <ol className="kt-why">
                {notes.map((n, i) => <li key={`${n.code}-${i}`} data-note={n.code}><span className="k-mono">{String(i + 1).padStart(2, "0")}</span> <Plain text={n.text} /></li>)}
                {notes.length === 0 && <li className="t2">没有特别要看的；零确认放行之前，每个任务都要你按一下。</li>}
              </ol>
              <div className="sheet-sub">画像预览<span className="t2">服务端推导，不可填</span></div>
              {preview ? (
                <table className="bank profile" data-profile-preview><tbody>
                  {(["reversibility", "judge", "info"] as const).map((axis) => (
                    <tr key={axis} data-axis={axis}><td className="k-mono ink3">{axis}</td><td className="k-mono">{preview.profile[axis]}</td><td className="note"><Plain text={String(preview.basis[axis].rule ?? "—")} /></td></tr>
                  ))}
                </tbody></table>
              ) : <p className="t2">读取中…</p>}
              <p className="t2">[估] 预算默认值来自 <span className="k-mono"><Plain text={v.priors} /></span></p>
            </aside>
          </div>

          <footer className="wizard-foot">
            <button type="button" className={btnClass("ink")} data-action="open-problem" disabled={busy !== null || !writable || v.needs_ack === "command"} onClick={() => void openIt()}>
              {busy === "open" ? (v.external ? "领题并创建中…" : "创建中…") : v.external ? "领题并创建任务" : "创建任务"} <Kbd>⌘↵</Kbd>
            </button>
            <button type="button" className={btnClass("line")} data-action="to-advanced" disabled={busy !== null} onClick={() => void advanced()}>在高级模式里改</button>
            <button type="button" className={btnClass("bare")} data-action="discard" disabled={busy !== null} onClick={() => { setV(null); box.current?.focus(); }}>放弃</button>
            {busy === "revet" && <span className="t2">重新校验…</span>}
          </footer>
        </div>
      )}

      {v && refused && (
        <section className="kt-refuse" data-kaiti-refuse>
          <h2 className="kt-refuse-h">{noCriterion ? "这件事还说不清怎样算做完。" : "没有创建任务。"}</h2>
          {goalSentences(v).length > 0 && <blockquote className="kt-quote"><Plain text={goalSentences(v).join("")} /></blockquote>}
          <div className="sheet-sub">为什么不开</div>
          <ol className="kt-why">
            {notes.filter((n) => n.lane === "refuse").map((n, i) => <li key={`${n.code}-${i}`} data-note={n.code}><span className="k-mono">{String(i + 1).padStart(2, "0")}</span> <Plain text={n.text} /></li>)}
          </ol>
          <SectionHead title="四条路" note="不把它降级成模型自评，也不在你看不见的地方换判定方式" />
          <ol className="kt-ways">
            <li data-way="endpoint">
              <span className="kt-way-no">01</span>
              <b>补一个可判定的终点</b>
              <p className="t2">在上面补一行“答案：…”，或一段检查命令（用反引号括起来，例如 `make test`），再回车。</p>
              <button type="button" className={btnClass("line", "sm")} onClick={() => box.current?.focus()}>回到输入框</button>
            </li>
            <li data-way="human">
              <span className="kt-way-no">02</span>
              <b>人工验收</b>
              <p className="t2">先写下怎样算做完：交付后由你按这份清单逐条判，终态最多“已验收”，不写“已证明”。清单创建后不能改；交付物只做结构检查，结果只是读数。</p>
              {v.draft ? <HumanWay v={v} busy={busy !== null} onGo={(items) => void humanRoute(items)} />
                : <p className="t2">起草没有结果，这条路走不了：先补一句目标再回车。</p>}
            </li>
            <li data-way="advanced">
              <span className="kt-way-no">03</span>
              <b>进高级模式</b>
              <p className="t2">带着原文进四步向导，自己从判定器目录里选、挂检查材料。</p>
              <button type="button" className={btnClass("line", "sm")} data-action="refuse-advanced" disabled={busy !== null} onClick={() => void advanced()}>进高级模式</button>
            </li>
            <li data-way="register_platform">
              <span className="kt-way-no">04</span>
              <b>去设置页登记这个平台</b>
              <p className="t2">判定权在外部平台（平台回执说了算）的任务：先登记平台的连接器档案、设好凭据槽位，再从平台导入。登记后在这里贴同样的话也能认出平台。</p>
              <span className="kt-way-links">
                <Link to={{ page: "settings" }} className={btnClass("line", "sm")} data-action="refuse-register">去设置页</Link>{" "}
                <Link to={{ page: "platform" }} className={btnClass("line", "sm")} data-action="refuse-platform">从平台导入</Link>
              </span>
            </li>
          </ol>
        </section>
      )}
    </div>
  );
}
