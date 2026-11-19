// 开题向导（感知官；HMI 设计 §3.2、§10.1；视觉重做第二期）。
// 四页：要做什么（基本信息+起点）、怎么算做完（判据）、能动用什么（授权）、花多少（预算+复核）。右侧任务单随填随变。
// 表单里没有画像字段：画像预览由服务端的同一推导函数给出（POST /v1/profile/preview），前端不复刻推导规则。
import { useEffect, useMemo, useRef, useState } from "react";
import { newIdemKey } from "../api/client";
import type { CatalogItem, JudgeEntry, ProfilePreview, Risk } from "../api/types";
import { useServices } from "../app/context";
import { clearDraft, loadDraft, saveDraft } from "../app/draft";
import { navigate } from "../app/router";
import { submitDraft } from "../app/submit";
import { sha256Hex } from "../model/hash";
import { GRADE_WORD } from "../model/levels";
import { shortHash, usd } from "../model/text";
import { buildOpen, draftFromProblem, draftFromTemplate, judgesFor, problemsOf, scopeOf, STEPS, textMaterial, uploadedOf, type Draft, type DraftMaterial, type MaterialKind } from "../model/wizard";
import { FileUp } from "lucide-react";
import { Mark, Mast, SectionHead, btnClass } from "../kit";
import { Plain } from "../ui/registers";
import { rejectText } from "../ui/useProposal";
import { pending, recorded, rejected } from "../ui/feedback";

const pointers = (b: Record<string, unknown>) => Object.keys(b).filter((k) => k !== "rule").sort().map((k) => `${k}=${JSON.stringify(b[k])}`).join(" ");
/** 四步：model 里的六段按页合并（基本信息+起点、终点、资源、预算+复核）。 */
const PAGES: { word: string; hint: string; of: number[] }[] = [
  { word: "要做什么", hint: "任务名、目标与材料", of: [0, 1] },
  { word: "怎么算做完", hint: "判定器与判定条件", of: [2] },
  { word: "能动用什么", hint: "环境与授权范围", of: [3] },
  { word: "花多少，提交", hint: "预算、初始提示与复核", of: [4, 5] },
];
const KIND_WORD: Record<MaterialKind, string> = { file: "文件", text: "文字", link: "链接" };
const blankSlot = (n: number): DraftMaterial => ({ slot: `材料 ${n}`, required: false, name: null, hash: null, size: 0, media_type: "", kind: "file", text: "" });

export function Wizard({ from }: { from?: string } = {}) {
  const { api, cfg } = useServices();
  const [templates, setTemplates] = useState<CatalogItem[] | null>(null);
  const [registry, setRegistry] = useState<JudgeEntry[] | null>(null);
  const [d, setD] = useState<Draft | null>(null);
  const [step, setStep] = useState(0);
  const [restored, setRestored] = useState(false);
  const [preview, setPreview] = useState<ProfilePreview | null>(null);
  const [previewErr, setPreviewErr] = useState<string | null>(null);
  const [err, setErr] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const [hintNote, setHintNote] = useState<string | null>(null);
  // 幂等键只用于同一请求的重试：提交体一变就换新键
  const idem = useRef<{ key: string; body: string }>({ key: newIdemKey(), body: "" });

  useEffect(() => {
    let live = true;
    (async () => {
      const [ts, js] = await Promise.all([api.templates(), api.judges()]);
      let draft: Draft | null = null;
      let at = 0;
      if (from) {
        // 克隆：读原题的 status、budget 与材料登记，预填草稿
        const [snap, budget] = await Promise.all([api.status(from), api.budget(from)]);
        const refs = [snap.problem.origin.statement_ref, ...snap.problem.origin.materials];
        const arts = await Promise.all(refs.map((id) => api.artifact(id).catch(() => null)));
        draft = draftFromProblem(snap, budget, arts.filter((a) => a !== null));
      } else {
        const saved = loadDraft();
        if (saved) { draft = saved.draft; at = Math.min(saved.step, PAGES.length - 1); if (live) setRestored(true); }
      }
      if (!live) return;
      setTemplates(ts.items);
      setRegistry(js.items);
      setD(draft ?? draftFromTemplate(ts.items[0] ?? null));
      setStep(at);
    })().catch((e: Error) => { if (live) setErr(e); });
    return () => { live = false; };
  }, [api, from]);

  // 草稿只存本机；克隆出来的草稿也存，刷新后接着填
  useEffect(() => { if (d) saveDraft(d, step); }, [d, step]);

  const scopeKey = d ? JSON.stringify([scopeOf(d), d.judge]) : "";
  useEffect(() => {
    if (!d || !d.judge || scopeOf(d).length === 0) { setPreview(null); return; }
    let live = true;
    api.profilePreview({ scope: scopeOf(d), goal: { check: { judge_id: d.judge } } }).then(
      (p) => { if (live) { setPreview(p); setPreviewErr(null); } },
      (e: Error) => { if (live) { setPreview(null); setPreviewErr(e.message); } },
    );
    return () => { live = false; };
    // 只在 scope 或判官变化时重取
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, scopeKey]);

  const issues = useMemo(() => (d ? problemsOf(d) : STEPS.map(() => [])), [d]);
  if (!templates || !registry || !d) return <p className={err ? "error" : "muted"}>{err ? rejectText(err) : "读取模板与判官注册表…"}</p>;
  const judges = judgesFor(d, registry);
  const set = (patch: Partial<Draft>) => setD({ ...d, ...patch });
  const setMat = (i: number, patch: Partial<DraftMaterial>) => setD((cur) => cur && { ...cur, materials: cur.materials.map((m, k) => (k === i ? { ...m, ...patch } : m)) });
  const uploaded = uploadedOf(d);
  const allOk = issues.every((s) => s.length === 0);
  const open = buildOpen(d);
  const pick = (name: string) => setD(draftFromTemplate(templates.find((x) => x.name === name) ?? null, d));
  const restart = () => { clearDraft(); setRestored(false); setStep(0); setD(draftFromTemplate(templates[0] ?? null)); if (from) navigate({ page: "new" }, true); };
  const writable = cfg.token !== null;

  async function store(i: number, bytes: Uint8Array, name: string, media_type: string) {
    setErr(null);
    try {
      const [put, local] = await Promise.all([api.putBlob(bytes), sha256Hex(bytes)]);
      if (put.hash !== local) throw new Error("服务端返回的哈希与本地计算的不一致");
      setMat(i, { name, hash: local, size: bytes.length, media_type });
    } catch (e) {
      setErr(e as Error);
    }
  }
  async function upload(i: number, file: File) {
    await store(i, new Uint8Array(await file.arrayBuffer()), file.name, file.type || "application/octet-stream");
  }

  async function submit() {
    setBusy(true);
    setErr(null);
    setHintNote(null);
    const body = JSON.stringify([open, d!.hint ?? ""]);
    if (idem.current.body !== body) idem.current = { key: newIdemKey(), body };
    const t = pending("开题");
    try {
      const r = await submitDraft(api, d!, idem.current.key);
      clearDraft();
      recorded(t, "开题", r.seq, r.hintError ? `初始提示没交上：${r.hintError}` : r.hintSeq !== null ? `初始提示 seq ${r.hintSeq}` : undefined);
      if (r.hintError) { setHintNote(`题已开出（seq ${r.seq}），但初始提示没交上：${r.hintError}。可以到工作区再注入。`); return; }
      navigate({ page: "problem", pid: r.pid, asOf: null, node: null });
    } catch (e) {
      setErr(e as Error);
      rejected(t, "开题", rejectText(e as Error) ?? (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const pageIssues = PAGES.map((pg) => pg.of.flatMap((i) => issues[i]));
  const on = (i: number) => PAGES[step].of.includes(i);
  const risks = d.scope.filter((r) => r.pattern.trim() || r.resource.trim()).map((r) => r.risk || "r2");
  const topRisk = risks.includes("r2") ? "r2" : risks.includes("r1") ? "r1" : risks.length ? "r0" : null;
  const judgeOf = registry.find((j) => j.judge_id === d.judge);

  return (
    <div className="wizard" data-wizard data-step-index={step}>
      <Mast vol={["卷三", "新建"]} cap={d.clonedFrom ? "克隆任务" : "新建任务"}
        title={d.clonedFrom ? <>从 <span className="k-mono" data-cloned-from={d.clonedFrom}><Plain text={d.clonedFrom} /></span> 克隆一个任务</> : "四步开一个任务"}
        dek="说清要做什么、怎么算做完、能动用什么、花多少。右边的任务单随填随变，缺什么会直接标出来。草稿只存在本机。"
        actions={
          <div className="wizard-tpl">
            <label className="sel-u">模板
              <select value={d.template} disabled={uploaded.length > 0 || !!d.clonedFrom} data-field="template" onChange={(e) => pick(e.target.value)}>
                <option value="">不用模板</option>
                {templates.map((t) => <option key={t.name} value={t.name}>{t.name}（{shortHash(t.hash)}{t.signature ? "" : " · 未签名"}）</option>)}
              </select>
            </label>
            {restored && <span className="t2" data-restored>已恢复本机草稿 <button type="button" className={btnClass("bare", "sm")} data-action="restart" onClick={restart}>重新开始</button></span>}
          </div>
        } />

      <ol className="steps wsteps" aria-label="步骤">
        {PAGES.map((pg, i) => (
          <li key={pg.word}>
            <button type="button" aria-current={step === i ? "step" : undefined} data-step-tab={i} data-done={pageIssues[i].length === 0 && i < 3} onClick={() => setStep(i)}>
              <span className="ws-no">{String(i + 1).padStart(2, "0")}</span>
              <span className="ws-word">{pg.word}</span>
              <span className="ws-hint">{pageIssues[i].length ? `缺 ${pageIssues[i].length} 项` : i < 3 ? "已齐" : pg.hint}</span>
            </button>
          </li>
        ))}
      </ol>

      <div className="wizard-body">
        <div className="wizard-main">
          {on(0) && (
            <section className="today-sec" data-step="basics">
              <SectionHead title="基本信息" note="任务名与要达成什么" />
              <div className="form-grid">
                <label>任务编号<span className="t2">字母、数字、点、下划线、连字符</span><input value={d.id} data-field="id" onChange={(e) => set({ id: e.target.value })} /></label>
                <label>任务名<input value={d.title} data-field="title" onChange={(e) => set({ title: e.target.value })} /></label>
                <label className="wide">目标陈述<span className="t2">要达成什么；怎么判定在第二步填</span><textarea value={d.statement} data-field="statement" onChange={(e) => set({ statement: e.target.value })} /></label>
              </div>
            </section>
          )}

          {on(1) && (
            <section className="today-sec" data-step="origin">
              <SectionHead title="起点：材料" note="第一份是题面；网址只当文字存，不抓取" />
              <ul className="materials">
                {d.materials.map((m, i) => {
                  const kind = m.kind ?? "file";
                  return (
                    <li key={i} data-material={i}>
                      <div className="material-head">
                        <input className="slot-name" value={m.slot} aria-label="槽位名" onChange={(e) => setMat(i, { slot: e.target.value })} disabled={m.required} />
                        {m.required && <span className="k-tag">必填</span>}
                        <span className="seg" role="group" aria-label="材料形式">
                          {(["file", "text", "link"] as const).map((k) => (
                            <button key={k} type="button" aria-pressed={kind === k} disabled={!!m.hash} data-kind={k} onClick={() => setMat(i, { kind: k })}>{KIND_WORD[k]}</button>
                          ))}
                        </span>
                        <span className="grow" />
                        {!m.required && <button type="button" className={btnClass("bare", "sm")} onClick={() => set({ materials: d.materials.filter((_, k) => k !== i), specSlot: "" })}>删去</button>}
                      </div>
                      {m.hash ? (
                        <div className="hash-badge"><Mark ch="存" tone="jie" /> <Plain text={m.name ?? ""} /> <span className="t2">{m.size} 字节 · sha256 <code>{shortHash(m.hash)}</code> · 与本地计算一致</span>
                          <button type="button" className={btnClass("bare", "sm")} onClick={() => setMat(i, { hash: null, name: null, size: 0, media_type: "" })}>换一份</button></div>
                      ) : kind === "file" ? (
                        <label className="drop sm">
                          <FileUp aria-hidden="true" />
                          <span className="drop-main">{writable ? "选择文件" : "先配置令牌才能上传"}</span>
                          <input type="file" disabled={!writable} data-slot={m.slot} onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(i, f); }} />
                        </label>
                      ) : (
                        <div className="material-text">
                          {kind === "text"
                            ? <textarea value={m.text ?? ""} data-text-slot={i} placeholder="贴一段文字" aria-label={`${m.slot}：文字`} onChange={(e) => setMat(i, { text: e.target.value })} />
                            : <input value={m.text ?? ""} data-text-slot={i} placeholder="网址（只当文字存）" aria-label={`${m.slot}：网址`} onChange={(e) => setMat(i, { text: e.target.value })} />}
                          <p className="t2">开题时自动存成材料；也可以现在就存，看到哈希。
                            <button type="button" className={btnClass("bare", "sm")} data-action="store-text" disabled={!writable || !textMaterial(m)} onClick={() => { const t = textMaterial(m); if (t) void store(i, t.bytes, t.name, t.media_type); }}>现在存</button></p>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
              <button type="button" className={btnClass("line", "sm")} data-action="add-slot" onClick={() => set({ materials: [...d.materials, blankSlot(d.materials.length)] })}>加一份材料</button>
              {!writable && <p className="t2">上传材料与开题都是写操作：先在左下角配置人的令牌。</p>}
            </section>
          )}

          {on(2) && (
            <section className="today-sec" data-step="criterion">
              <SectionHead title="终点：怎么判定“做完了”" note={`判定器来自注册表${d.judgeFilter.length ? "，按模板过滤" : ""}`} />
              <fieldset className="accept">
                <legend className="sr-only">判定方式</legend>
                <label className="choice" data-on={d.accept === "judge"}><input type="radio" name="accept" checked={d.accept === "judge"} onChange={() => set({ accept: "judge" })} /> <span><b>判定器判定</b><span className="t2">判定通过即解决（solved）</span></span></label>
                <label className="choice" data-on={d.accept === "human"}><input type="radio" name="accept" checked={d.accept === "human"} onChange={() => set({ accept: "human" })} /> <span><b>人验收</b><span className="t2">判定器先判，最后由人验收；终态写已验收，不写“已证明”</span></span></label>
              </fieldset>
              <table className="bank" data-judges>
                <thead><tr><th /><th>判定器</th><th>等级</th><th>类型</th><th className="r">单次上限</th></tr></thead>
                <tbody>
                  {judges.map((j) => (
                    <tr key={j.judge_id} data-judge={j.judge_id}>
                      <td><input type="radio" name="judge" aria-label={j.judge_id} checked={d.judge === j.judge_id} disabled={d.lockJudge && d.judge !== j.judge_id} onChange={() => set({ judge: j.judge_id })} /></td>
                      <td className="k-mono">{j.judge_id}@{j.version}</td><td>{GRADE_WORD[j.grade]}</td><td>{j.kind}</td><td className="r k-mono">{j.max_cost}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="form-grid">
                <label className="wide">判定条件 expect<span className="t2">JSON 对象，由判定器解释</span><textarea value={d.expect} data-field="expect" placeholder='{"answer": "…"}' onChange={(e) => set({ expect: e.target.value })} /></label>
                <label>挂一份材料 spec_ref
                  <select value={d.specSlot} data-field="spec_ref" onChange={(e) => set({ specSlot: e.target.value })}>
                    <option value="">不挂</option>
                    {uploaded.map(({ m, slot }) => <option key={slot} value={String(slot)}>{m.slot} · {shortHash(m.hash!)}</option>)}
                  </select>
                </label>
                <label>最多尝试 max_attempts<input inputMode="numeric" value={d.maxAttempts} data-field="max_attempts" onChange={(e) => set({ maxAttempts: e.target.value })} /></label>
              </div>
            </section>
          )}

          {on(3) && (
            <section className="today-sec" data-step="scope">
              <SectionHead title="资源：目标环境与授权" note="每条规则逐条标风险；这是授权，不是画像" />
              <div className="form-grid">
                <label>环境 base<span className="t2">环境模板或镜像名</span><input value={d.env.base} data-field="env-base" onChange={(e) => set({ env: { ...d.env, base: e.target.value } })} /></label>
                <label>baseline_ref<span className="t2">可空</span><input value={d.env.baseline_ref} data-field="env-baseline" onChange={(e) => set({ env: { ...d.env, baseline_ref: e.target.value } })} /></label>
              </div>
              <div className="table-scroll">
                <table className="bank rules">
                  <thead><tr><th>资源</th><th>pattern（地址、路径…）</th><th>动作（逗号分隔）</th><th>风险（必选，空按 r2）</th><th /></tr></thead>
                  <tbody>
                    {d.scope.map((r, i) => {
                      const upd = (patch: Partial<typeof r>) => set({ scope: d.scope.map((x, k) => (k === i ? { ...x, ...patch } : x)) });
                      return (
                        <tr key={i} data-rule={i}>
                          <td><input value={r.resource} aria-label={`规则 ${i + 1} 资源`} onChange={(e) => upd({ resource: e.target.value })} /></td>
                          <td><input value={r.pattern} aria-label={`规则 ${i + 1} pattern`} onChange={(e) => upd({ pattern: e.target.value })} /></td>
                          <td><input value={r.actions} aria-label={`规则 ${i + 1} 动作`} onChange={(e) => upd({ actions: e.target.value })} /></td>
                          <td>
                            <select value={r.risk} data-risk={i} aria-label={`规则 ${i + 1} 风险`} onChange={(e) => upd({ risk: e.target.value as Risk | "" })}>
                              <option value="">未标（按 r2）</option><option value="r0">r0 可逆或只读</option><option value="r1">r1 有成本</option><option value="r2">r2 不可逆</option>
                            </select>
                            {r.risk === "" && <span className="k-tag hot">显示为 r2</span>}
                          </td>
                          <td><button type="button" className={btnClass("bare", "sm")} onClick={() => set({ scope: d.scope.filter((_, k) => k !== i) })}>删去</button></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <button type="button" className={btnClass("line", "sm")} data-action="add-rule" onClick={() => set({ scope: [...d.scope, { resource: "", pattern: "", actions: "", risk: "" }] })}>加一条规则</button>
            </section>
          )}

          {on(4) && (
            <section className="today-sec" data-step="budget">
              <SectionHead title="预算" note={d.b1CapMilli && Number(d.usd) > 0 ? `B1 单题上限 ${usd(d.b1CapMilli)}，这份是它的 ${((Number(d.usd) * 1000) / d.b1CapMilli).toFixed(1)} 倍（默认 3 倍）` : "模板没有给出 B1 单题上限"} />
              <div className="form-grid four">
                <label>成本上限<span className="t2">美元</span><input inputMode="decimal" value={d.usd} data-field="usd" onChange={(e) => set({ usd: e.target.value })} /></label>
                <label>时间上限 wall_s<span className="t2">{Number(d.wall_s) > 0 ? `约 ${(Number(d.wall_s) / 3600).toFixed(1)} 小时` : "秒"}</span><input inputMode="numeric" value={d.wall_s} data-field="wall_s" onChange={(e) => set({ wall_s: e.target.value })} /></label>
                <label>判定预算占比<span className="t2">verify_share，0–1</span><input inputMode="decimal" value={d.verify_share} data-field="verify_share" onChange={(e) => set({ verify_share: e.target.value })} /></label>
                <label>起步占比<span className="t2">bootstrap_share，0–1</span><input inputMode="decimal" value={d.bootstrap_share} data-field="bootstrap_share" onChange={(e) => set({ bootstrap_share: e.target.value })} /></label>
              </div>
            </section>
          )}

          {on(5) && (
            <section className="today-sec" data-step="review">
              <SectionHead title="复核与提交" note="缺项清了才能提交" />
              <ol className="asks review-list">
                {PAGES.slice(0, 3).map((pg, i) => (
                  <li key={pg.word} className="ask-row" data-review={i}>
                    <Mark ch={pageIssues[i].length ? "缺" : "齐"} tone={pageIssues[i].length ? "dai" : "jie"} />
                    <div className="grow"><div>{String(i + 1).padStart(2, "0")} {pg.word}</div><div className="t2">{pageIssues[i].length ? pageIssues[i].join("；") : "已齐"}</div></div>
                    <button type="button" className={btnClass("bare", "sm")} onClick={() => setStep(i)}>去改</button>
                  </li>
                ))}
              </ol>
              <div className="form-grid">
                <label className="wide">初始提示<span className="t2">可空；开题后作为第一条提示提交，属于人的判断，不是证据</span>
                  <textarea value={d.hint ?? ""} data-field="hint" maxLength={2000} onChange={(e) => set({ hint: e.target.value })} />
                </label>
              </div>
              <details className="sample">
                <summary>将提交的批次（纯文本）</summary>
                <pre className="output" data-problem-json>{JSON.stringify({ id: open.id, ops: [...open.materials, { op: "open_problem", body: open.problem }] }, null, 2)}</pre>
                {d.materials.some((m) => !m.hash && (m.text ?? "").trim()) && <p className="t2">文字或链接材料会在提交时先存成 Blob，再进这一批。</p>}
              </details>
            </section>
          )}

          {pageIssues[step].length > 0 && step < 3 && <ul className="issues" aria-label="这一步还缺">{pageIssues[step].map((s) => <li key={s}>{s}</li>)}</ul>}

          <footer className="wizard-foot">
            <button type="button" className={btnClass("line")} disabled={step === 0} onClick={() => setStep(step - 1)}>上一步</button>
            {step < 3 && <button type="button" className={btnClass("ink")} data-action="next" onClick={() => setStep(step + 1)}>下一步<span className="t2 inv">{PAGES[step + 1].word}</span></button>}
            {step === 3 && <button type="button" className={btnClass("zhu")} data-action="open-problem" disabled={!allOk || busy || !writable} onClick={submit}>{busy ? "提交中…" : "提交开题"}</button>}
            {step === 3 && !writable && <span className="t2">开题是写操作：先在左下角配置令牌。</span>}
            {rejectText(err) && <span className="error" data-reject>{rejectText(err)}</span>}
            {hintNote && <span className="warn" data-hint-note><Plain text={hintNote} /></span>}
          </footer>
        </div>

        <aside className="wizard-side" aria-label="任务单">
          <div className="sheet">
            <div className="sheet-head"><span className="k-mono">任务单</span><span className="k-mono ink3">{d.id ? <Plain text={d.id} /> : "未编号"}</span></div>
            <div className="sheet-title">{d.title.trim() ? <Plain text={d.title} /> : <span className="ink3">还没有任务名</span>}</div>
            <dl className="sheet-dl">
              <dt>目标</dt><dd>{d.statement.trim() ? <span className="clamp"><Plain text={d.statement} /></span> : <span className="ink3">—</span>}</dd>
              <dt>材料</dt><dd>{d.materials.length} 份 · 已存 {uploaded.length}</dd>
              <dt>判定</dt><dd>{d.judge ? <span className="k-mono">{d.judge}{judgeOf ? `@${judgeOf.version}` : ""}</span> : <span className="ink3">未选</span>}{d.accept === "human" ? " · 人验收" : ""}</dd>
              <dt>授权</dt><dd>{risks.length} 条{topRisk && <> · 最高 <span className={topRisk === "r2" ? "zhu" : ""}>{topRisk}</span></>}</dd>
              <dt>预算</dt><dd className="k-mono">{Number(d.usd) > 0 ? `$${Number(d.usd).toFixed(2)}` : "—"} · {Number(d.wall_s) > 0 ? `${(Number(d.wall_s) / 3600).toFixed(1)} 小时` : "—"}</dd>
            </dl>
            <section className="sheet-sec" data-profile-preview>
              <div className="sheet-sub">画像预览<span className="t2">服务端推导，这里没有可填的画像字段</span></div>
              {preview ? (
                <table className="bank profile">
                  <tbody>
                    {(["reversibility", "judge", "info"] as const).map((axis) => (
                      <tr key={axis} data-axis={axis}><td className="k-mono ink3">{axis}</td><td className="k-mono">{preview.profile[axis]}</td><td className="note"><Plain text={String(preview.basis[axis].rule ?? "—")} /><br /><code className="pointers"><Plain text={pointers(preview.basis[axis]) || "—"} /></code></td></tr>
                    ))}
                  </tbody>
                </table>
              ) : <p className="t2">{previewErr ? `预检失败：${previewErr}` : "选好判定器、填了至少一条授权规则后显示。"}</p>}
            </section>
            <div className="sheet-foot">
              {allOk ? <><Mark ch="齐" tone="jie" /> 可以提交</> : <><Mark ch="缺" tone="dai" /> 还缺 {pageIssues.reduce((a, x) => a + x.length, 0)} 项</>}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
