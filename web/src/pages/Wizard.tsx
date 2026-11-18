// 开题向导（感知官；HMI 设计 §3.2、§10.1；工作台设计 §1 模块二、线框 f2）。
// 六页：基本信息、起点（Origin）、终点（判据）、资源（授权）、预算、复核。中间四页即 HMI 的四步，不增不藏。
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
import { Plain } from "../ui/registers";
import { rejectText } from "../ui/useProposal";
import { pending, recorded, rejected } from "../ui/feedback";

const pointers = (b: Record<string, unknown>) => Object.keys(b).filter((k) => k !== "rule").sort().map((k) => `${k}=${JSON.stringify(b[k])}`).join(" ");
const MARK = "①②③④⑤⑥";
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
        if (saved) { draft = saved.draft; at = Math.min(saved.step, STEPS.length - 1); if (live) setRestored(true); }
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

  return (
    <div className="wizard" data-wizard data-step-index={step}>
      <header className="wizard-head">
        <h2>开题{d.clonedFrom && <span className="badge" data-cloned-from={d.clonedFrom}>克隆自 <Plain text={d.clonedFrom} /></span>}</h2>
        <label>模板
          <select value={d.template} disabled={uploaded.length > 0 || !!d.clonedFrom} data-field="template" onChange={(e) => pick(e.target.value)}>
            <option value="">不用模板</option>
            {templates.map((t) => <option key={t.name} value={t.name}>{t.name}（{shortHash(t.hash)}{t.signature ? "" : " · 未签名"}）</option>)}
          </select>
        </label>
        {restored && <span className="muted" data-restored>已恢复本机草稿 <button type="button" className="btn-small" data-action="restart" onClick={restart}>重新开始</button></span>}
        <ol className="steps" aria-label="步骤">
          {STEPS.map((s, i) => (
            <li key={s}><button type="button" className="chip" aria-current={step === i} data-step-tab={i} onClick={() => setStep(i)}>{MARK[i]} {s}{issues[i].length ? ` · 缺 ${issues[i].length}` : i < 5 ? " ✓" : ""}</button></li>
          ))}
        </ol>
        <p className="muted">②③④⑤ 即 Origin、判据、授权、预算四步（HMI §3.2）；① 与 ⑥ 只是把题名与提交前的复核单独成页。草稿只存在本机。</p>
      </header>

      <div className="wizard-body">
        <div className="wizard-main">
          {step === 0 && (
            <section data-step="basics">
              <h3>① 基本信息</h3>
              <label>题目 id <input value={d.id} data-field="id" placeholder="字母、数字、点、下划线、连字符" onChange={(e) => set({ id: e.target.value })} /></label>
              <label>题名 <input value={d.title} data-field="title" onChange={(e) => set({ title: e.target.value })} /></label>
              <label>目标陈述（要达成什么；判定条件在 ③ 填）<textarea value={d.statement} data-field="statement" onChange={(e) => set({ statement: e.target.value })} /></label>
              <p className="muted">标签、难度、领域：Problem 里还没有这些字段（设计 §6 C3），暂不提供。</p>
            </section>
          )}

          {step === 1 && (
            <section data-step="origin">
              <h3>② 起点：材料</h3>
              <p className="muted">每份材料登记为 input 类，与开题在同一批里提交；第一份是题面。网址只当文字存，不抓取。</p>
              <ul className="materials">
                {d.materials.map((m, i) => {
                  const kind = m.kind ?? "file";
                  return (
                    <li key={i} data-material={i}>
                      <div className="material-head">
                        <input className="slot-name" value={m.slot} aria-label="槽位名" onChange={(e) => setMat(i, { slot: e.target.value })} disabled={m.required} />
                        {m.required && <span className="muted">（必填）</span>}
                        <span className="seg" role="group" aria-label="材料形式">
                          {(["file", "text", "link"] as const).map((k) => (
                            <button key={k} type="button" aria-pressed={kind === k} disabled={!!m.hash} data-kind={k} onClick={() => setMat(i, { kind: k })}>{KIND_WORD[k]}</button>
                          ))}
                        </span>
                        {!m.required && <button type="button" className="btn-small" onClick={() => set({ materials: d.materials.filter((_, k) => k !== i), specSlot: "" })}>删</button>}
                      </div>
                      {m.hash ? (
                        <span className="hash-badge"><Plain text={m.name ?? ""} /> · {m.size} 字节 · sha256 <code>{shortHash(m.hash)}</code> ✓ 本地计算一致
                          <button type="button" className="btn-small" onClick={() => setMat(i, { hash: null, name: null, size: 0, media_type: "" })}>换一份</button></span>
                      ) : kind === "file" ? (
                        <input type="file" disabled={!writable} data-slot={m.slot} onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(i, f); }} />
                      ) : (
                        <div className="material-text">
                          {kind === "text"
                            ? <textarea value={m.text ?? ""} data-text-slot={i} placeholder="贴一段文字" onChange={(e) => setMat(i, { text: e.target.value })} />
                            : <input value={m.text ?? ""} data-text-slot={i} placeholder="网址（只当文字存）" onChange={(e) => setMat(i, { text: e.target.value })} />}
                          <p className="muted">开题时自动存成材料；也可以现在就存，看到哈希。
                            <button type="button" className="btn-small" data-action="store-text" disabled={!writable || !textMaterial(m)} onClick={() => { const t = textMaterial(m); if (t) void store(i, t.bytes, t.name, t.media_type); }}>现在存</button></p>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
              <button type="button" className="btn-small" data-action="add-slot" onClick={() => set({ materials: [...d.materials, blankSlot(d.materials.length)] })}>加一份材料</button>
              {!writable && <p className="muted">上传材料与开题都是写操作：先在页面右上角配置人的令牌。</p>}
            </section>
          )}

          {step === 2 && (
            <section data-step="criterion">
              <h3>③ 终点：怎么判定“做完了”</h3>
              <fieldset className="accept">
                <legend>判定方式</legend>
                <label className="choice"><input type="radio" name="accept" checked={d.accept === "judge"} onChange={() => set({ accept: "judge" })} /> <b>判官判定</b>：终态 solved</label>
                <label className="choice"><input type="radio" name="accept" checked={d.accept === "human"} onChange={() => set({ accept: "human" })} /> <b>人验收</b>：判官先判，最后由人验收；终态写 accepted，不写“已证明”</label>
              </fieldset>
              <p className="muted">Goal 判官来自注册表{d.judgeFilter.length ? "，按模板过滤" : ""}；判官不能在这里新建。</p>
              <table className="mini wide" data-judges>
                <thead><tr><th /><th>判官</th><th>等级</th><th>类型</th><th>单次上限</th></tr></thead>
                <tbody>
                  {judges.map((j) => (
                    <tr key={j.judge_id} data-judge={j.judge_id}>
                      <td><input type="radio" name="judge" aria-label={j.judge_id} checked={d.judge === j.judge_id} disabled={d.lockJudge && d.judge !== j.judge_id} onChange={() => set({ judge: j.judge_id })} /></td>
                      <td><code>{j.judge_id}@{j.version}</code></td><td>{GRADE_WORD[j.grade]}</td><td>{j.kind}</td><td>{j.max_cost}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <label>判定条件 expect（JSON 对象，由判官解释）<textarea value={d.expect} data-field="expect" placeholder='{"answer": "…"}' onChange={(e) => set({ expect: e.target.value })} /></label>
              <label>spec_ref（挂一份已存好的材料）
                <select value={d.specSlot} data-field="spec_ref" onChange={(e) => set({ specSlot: e.target.value })}>
                  <option value="">不挂</option>
                  {uploaded.map(({ m, slot }) => <option key={slot} value={String(slot)}>{m.slot} · {shortHash(m.hash!)}</option>)}
                </select>
              </label>
              <label>最多尝试 max_attempts <input inputMode="numeric" value={d.maxAttempts} data-field="max_attempts" onChange={(e) => set({ maxAttempts: e.target.value })} /></label>
            </section>
          )}

          {step === 3 && (
            <section data-step="scope">
              <h3>④ 资源：目标环境与授权</h3>
              <div className="env-fields">
                <label>环境 base（环境模板或镜像名）<input value={d.env.base} data-field="env-base" onChange={(e) => set({ env: { ...d.env, base: e.target.value } })} /></label>
                <label>baseline_ref（可空）<input value={d.env.baseline_ref} data-field="env-baseline" onChange={(e) => set({ env: { ...d.env, baseline_ref: e.target.value } })} /></label>
              </div>
              <h4>授权范围（scope）：每条规则逐条标风险</h4>
              <div className="table-scroll">
                <table className="mini">
                  <thead><tr><th>resource</th><th>pattern（地址、路径…）</th><th>actions（逗号分隔）</th><th>risk（必选，空 = r2）</th><th /></tr></thead>
                  <tbody>
                    {d.scope.map((r, i) => {
                      const upd = (patch: Partial<typeof r>) => set({ scope: d.scope.map((x, k) => (k === i ? { ...x, ...patch } : x)) });
                      return (
                        <tr key={i} data-rule={i}>
                          <td><input value={r.resource} onChange={(e) => upd({ resource: e.target.value })} /></td>
                          <td><input value={r.pattern} onChange={(e) => upd({ pattern: e.target.value })} /></td>
                          <td><input value={r.actions} onChange={(e) => upd({ actions: e.target.value })} /></td>
                          <td>
                            <select value={r.risk} data-risk={i} onChange={(e) => upd({ risk: e.target.value as Risk | "" })}>
                              <option value="">未标（按 r2）</option><option value="r0">r0 可逆或只读</option><option value="r1">r1 有成本</option><option value="r2">r2 不可逆</option>
                            </select>
                            {r.risk === "" && <strong> 显示为 r2</strong>}
                          </td>
                          <td><button type="button" className="btn-small" onClick={() => set({ scope: d.scope.filter((_, k) => k !== i) })}>删</button></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <button type="button" className="btn-small" data-action="add-rule" onClick={() => set({ scope: [...d.scope, { resource: "", pattern: "", actions: "", risk: "" }] })}>加一条规则</button>
              <p className="muted">风险由授权的人逐条标注。这是授权，不是画像。</p>
            </section>
          )}

          {step === 4 && (
            <section data-step="budget">
              <h3>⑤ 预算</h3>
              <div className="budget-grid">
                <label>成本上限（美元）<input inputMode="decimal" value={d.usd} data-field="usd" onChange={(e) => set({ usd: e.target.value })} /></label>
                <label>时间上限 wall_s（秒）<input inputMode="numeric" value={d.wall_s} data-field="wall_s" onChange={(e) => set({ wall_s: e.target.value })} /></label>
                <label>判定预算占比 verify_share（0–1）<input inputMode="decimal" value={d.verify_share} data-field="verify_share" onChange={(e) => set({ verify_share: e.target.value })} /></label>
                <label>起步占比 bootstrap_share（0–1）<input inputMode="decimal" value={d.bootstrap_share} data-field="bootstrap_share" onChange={(e) => set({ bootstrap_share: e.target.value })} /></label>
              </div>
              <p className="muted">
                {Number(d.wall_s) > 0 ? `时间上限约 ${(Number(d.wall_s) / 3600).toFixed(1)} 小时。` : ""}
                {d.b1CapMilli && Number(d.usd) > 0
                  ? `B1 单题上限 ${usd(d.b1CapMilli)}，这份预算是它的 ${((Number(d.usd) * 1000) / d.b1CapMilli).toFixed(1)} 倍（规格 4.1 默认 3 倍）。`
                  : "模板没有给出 B1 单题上限，无法显示倍数。"}
              </p>
            </section>
          )}

          {step === 5 && (
            <section data-step="review">
              <h3>⑥ 复核与提交</h3>
              <ul className="review-list">
                {STEPS.slice(0, 5).map((s, i) => (
                  <li key={s} data-review={i}>{issues[i].length ? "✕" : "✓"} {MARK[i]} {s}{issues[i].length ? `：${issues[i].join("；")}` : ""} <button type="button" className="btn-small" onClick={() => setStep(i)}>改</button></li>
                ))}
              </ul>
              <label>初始提示（可空；开题后作为第一条 Hint 提交，属于人的判断，不是证据）
                <textarea value={d.hint ?? ""} data-field="hint" maxLength={2000} onChange={(e) => set({ hint: e.target.value })} />
              </label>
              <p className="muted">模型选择与参考知识：Problem 里还没有这些字段（设计 §6 C13），暂不提供。</p>
              <h4>将提交的批次（纯文本）</h4>
              <pre className="output" data-problem-json>{JSON.stringify({ id: open.id, ops: [...open.materials, { op: "open_problem", body: open.problem }] }, null, 2)}</pre>
              {d.materials.some((m) => !m.hash && (m.text ?? "").trim()) && <p className="muted">文字或链接材料会在提交时先存成 Blob，再进这一批。</p>}
            </section>
          )}

          {issues[step].length > 0 && step < 5 && <ul className="issues">{issues[step].map((s) => <li key={s}>{s}</li>)}</ul>}

          <footer className="wizard-foot">
            <button type="button" disabled={step === 0} onClick={() => setStep(step - 1)}>上一步</button>
            {step < 5 && <button type="button" data-action="next" onClick={() => setStep(step + 1)}>下一步</button>}
            <button type="button" data-action="open-problem" disabled={!allOk || busy || !writable} onClick={submit}>{busy ? "提交中…" : "提交开题"}</button>
            {rejectText(err) && <span className="error" data-reject>{rejectText(err)}</span>}
            {hintNote && <span className="warn" data-hint-note><Plain text={hintNote} /></span>}
          </footer>
        </div>

        <aside className="wizard-side">
          <section data-profile-preview>
            <h4>画像预览（服务端推导；这里没有可填的画像字段）</h4>
            {preview ? (
              <table className="mini">
                <thead><tr><th>轴</th><th>显示</th><th>依据与指向</th></tr></thead>
                <tbody>
                  {(["reversibility", "judge", "info"] as const).map((axis) => (
                    <tr key={axis} data-axis={axis}><td>{axis}</td><td>{preview.profile[axis]}</td><td><Plain text={String(preview.basis[axis].rule ?? "—")} /><br /><code className="pointers"><Plain text={pointers(preview.basis[axis]) || "—"} /></code></td></tr>
                  ))}
                </tbody>
              </table>
            ) : <p className="muted">{previewErr ? `预检失败：${previewErr}` : "选好判官、填了至少一条 scope 规则后显示。"}</p>}
          </section>
          <section>
            <h4>各页缺项</h4>
            <ul className="side-issues">{STEPS.slice(0, 5).map((s, i) => <li key={s}>{MARK[i]} {s}：{issues[i].length ? `缺 ${issues[i].length}` : "✓"}</li>)}</ul>
          </section>
        </aside>
      </div>
    </div>
  );
}
