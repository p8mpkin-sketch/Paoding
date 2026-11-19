// 一句话开题（设计 docs/design/kaiti §7；迁移表第二期）。/new 是一个输入框：回车 → 起草服务给出校验结果 →
// 确认卡（原文逐段标号对字段）或拒绝页（三条降级路）。零确认一律关：练习道候选也要人按"开题"。
// 页面不推导任何字段：抽取、校验、分道都在服务端（qicao 的 vet），这里只排版、只收人改的风险与预算。
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { newIdemKey } from "../api/client";
import type { ProfilePreview, Risk, VaultRef } from "../api/types";
import type { KaitiExtract, KaitiOverrides, KaitiRow, KaitiVetted } from "../api/kaiti";
import { useServices } from "../app/context";
import { saveDraft } from "../app/draft";
import { navigate } from "../app/router";
import { submitVetted } from "../app/submit";
import { Kbd, Mark, Mast, SectionHead, btnClass } from "../kit";
import {
  circled, fieldWord, goalSentences, GROUPS, groupOf, segments, SOURCE, spanNumbers, usdOf, valueText, wallOf, wizardDraftOf,
} from "../model/kaiti";
import { draftFromTemplate } from "../model/wizard";
import { Link } from "./Problems";
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

export function Kaiti() {
  const { api, cfg } = useServices();
  const writable = cfg.token !== null;
  const [text, setText] = useState("");
  const [answer, setAnswer] = useState("");
  const [ext, setExt] = useState<KaitiExtract | null>(null);
  const [v, setV] = useState<KaitiVetted | null>(null);
  const [ov, setOv] = useState<KaitiOverrides>({});
  const [busy, setBusy] = useState<"draft" | "revet" | "open" | "advanced" | null>(null);
  const [err, setErr] = useState<Error | null>(null);
  const [fieldErr, setFieldErr] = useState<string | null>(null);
  const [preview, setPreview] = useState<ProfilePreview | null>(null);
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

  // 卡上的数字框跟着校验结果走
  useEffect(() => {
    const b = v?.input?.budget;
    setUsdS(b ? String(b.usd_milli / 1000) : "");
    setMinS(b ? String(Math.round((b.wall_s / 60) * 100) / 100) : "");
  }, [v]);

  // 画像预览：服务端同一个推导函数（/v1/profile/preview），与向导一样
  const scopeKey = v?.input ? JSON.stringify([v.input.scope, v.input.goal.check.judge_id]) : "";
  useEffect(() => {
    if (!v?.input) { setPreview(null); return; }
    let live = true;
    api.profilePreview({ scope: v.input.scope, goal: { check: { judge_id: v.input.goal.check.judge_id } } }).then((p) => { if (live) setPreview(p); }, () => { if (live) setPreview(null); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, scopeKey]);

  const nums = useMemo(() => (v ? spanNumbers(v.spans, v.derivation) : new Map<string, number>()), [v]);

  async function draftIt() {
    if (!text.trim() || busy) return;
    setBusy("draft"); setErr(null); setFieldErr(null);
    try {
      const out = await api.draftVet({ text, ...(answer.trim() ? { answer } : {}) });
      setV(out); setOv({});
    } catch (e) {
      setErr(e as Error); setV(null);
    } finally {
      setBusy(null);
    }
  }

  async function revet(next: KaitiOverrides) {
    if (!v?.draft) return;
    setBusy("revet"); setFieldErr(null);
    try {
      const out = await api.draftVet({ text, ...(answer.trim() ? { answer } : {}), draft: v.draft, model: v.model, nonce: v.nonce, overrides: next });
      setV(out); setOv(next);
    } catch (e) {
      setFieldErr(rejectText(e as Error) ?? (e as Error).message);
      setV({ ...v }); // 数字框回到上一份校验结果
    } finally {
      setBusy(null);
    }
  }

  async function openIt() {
    if (!v || v.lane === "refuse" || busy) return;
    setBusy("open"); setErr(null);
    const body = JSON.stringify([v.ops, v.blobs.map((b) => b.hash)]);
    if (idem.current.body !== body) idem.current = { key: newIdemKey(), body };
    const t = pending("新建任务");
    try {
      const r = await submitVetted(api, v, answer, idem.current.key);
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
    void draftIt();
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
  const notes = v?.notes ?? [];
  const noCriterion = notes.some((n) => n.code === "no_criterion" || n.code === "answer_missing");

  return (
    <div className="kaiti" data-kaiti data-lane={v?.lane ?? "input"}>
      <Mast vol={["卷三", "新建"]} cap="新建任务" title="一句话说清要做的事"
        dek="写要做什么、怎样算做完、能连哪里、多久花多少。回车后系统起草一张任务单，每个字段都标着出处，你看过再创建。"
        actions={
          <div className="kt-links t2">
            <Link to={{ page: "new", advanced: true }} data-action="advanced-blank">高级模式</Link>
            <span aria-hidden="true">·</span>
            <Link to={{ page: "import" }}>导入任务集</Link>
          </div>
        } />

      <section className="kt-input" data-kaiti-input>
        <label className="sr-only" htmlFor="kt-text">要做的事</label>
        <textarea id="kt-text" ref={box} className="kt-box" data-field="kaiti-text" value={text} placeholder={EXAMPLE} rows={4}
          disabled={!writable || busy === "open"}
          onChange={(e) => { setText(e.target.value); if (v) setV(null); }} onKeyDown={onKey} />
        <Extracted ext={ext} />
        <details className="kt-answer" data-kaiti-answer>
          <summary>答案（只给判定器）{answer.trim() ? <span className="t2">已收起，不进题面</span> : <span className="t2">可空；原文里写“答案：…”也行</span>}</summary>
          <input type="password" autoComplete="off" value={answer} data-field="kaiti-answer" aria-label="答案（只给判定器）"
            onChange={(e) => { setAnswer(e.target.value); if (v) setV(null); }} />
        </details>
        <div className="kt-go">
          <button type="button" className={btnClass("ink")} data-action="draft" disabled={!writable || !text.trim() || busy !== null} onClick={() => void draftIt()}>
            {busy === "draft" ? "起草中…" : "起草任务单"} <Kbd>↵</Kbd>
          </button>
          <span className="t2">⇧↵ 换行</span>
          {!writable && <span className="t2">起草与新建任务都要人的令牌：先在左下角配置。</span>}
          {err && <span className="error" data-reject>{rejectText(err) ?? err.message}</span>}
        </div>
      </section>

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
                    <div className="kt-group-h">{g}</div>
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
                      {g === "判据" && v.input!.goal.check.judge_id === "replay" && (
                        <div className="kt-row kt-warn" data-field="command-note"><dt /><dd className="t2">这条命令会被当成完成的唯一标准，创建后不能改。</dd></div>
                      )}
                    </dl>
                  </div>
                );
              })}
              {fieldErr && <p className="error" data-field-error><Plain text={fieldErr} /></p>}
            </section>

            <aside className="kt-col kt-side" aria-label="为什么要你看">
              <div className="kt-lane" data-lane-chip>
                <b>确认道 · 一步确认</b>
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
            <button type="button" className={btnClass("ink")} data-action="open-problem" disabled={busy !== null || !writable} onClick={() => void openIt()}>
              {busy === "open" ? "创建中…" : "创建任务"} <Kbd>⌘↵</Kbd>
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
          <SectionHead title="三条路" note="不把它降级成模型自评，也不在你看不见的地方换判定方式" />
          <ol className="kt-ways">
            <li data-way="endpoint">
              <span className="kt-way-no">01</span>
              <b>补一个可判定的终点</b>
              <p className="t2">在上面补一行“答案：…”，或一段检查命令（用反引号括起来，例如 `make test`），再回车。</p>
              <button type="button" className={btnClass("line", "sm")} onClick={() => box.current?.focus()}>回到输入框</button>
            </li>
            <li data-way="human" aria-disabled="true">
              <span className="kt-way-no">02</span>
              <b>人工验收</b>
              <p className="t2">由你按验收清单逐条验收，终态最多“已验收”，不写“已证明”。内核还只接受判定器判定，放开之前不能选。</p>
              <button type="button" className={btnClass("line", "sm")} disabled>暂不可用</button>
            </li>
            <li data-way="advanced">
              <span className="kt-way-no">03</span>
              <b>进高级模式</b>
              <p className="t2">带着原文进四步向导，自己从判定器目录里选、挂检查材料。</p>
              <button type="button" className={btnClass("line", "sm")} data-action="refuse-advanced" disabled={busy !== null} onClick={() => void advanced()}>进高级模式</button>
            </li>
          </ol>
        </section>
      )}
    </div>
  );
}
