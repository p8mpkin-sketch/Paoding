// 开题向导（感知官；HMI 设计 §3.2、§10.1）。固定四步：Origin、判据、授权、预算。
// 表单里没有画像字段：画像预览由服务端的同一推导函数给出（POST /v1/profile/preview），前端不复刻推导规则。
import { useEffect, useMemo, useState } from "react";
import { newIdemKey } from "../api/client";
import type { CatalogItem, JudgeEntry, ProfilePreview, Risk } from "../api/types";
import { useServices } from "../app/context";
import { navigate } from "../app/router";
import { sha256Hex } from "../model/hash";
import { GRADE_WORD } from "../model/levels";
import { shortHash, usd } from "../model/text";
import { buildOpen, draftFromTemplate, judgesFor, problemsOf, scopeOf, STEPS, uploadedOf, type Draft } from "../model/wizard";
import { Plain } from "../ui/registers";
import { rejectText } from "../ui/useProposal";

const pointers = (b: Record<string, unknown>) => Object.keys(b).filter((k) => k !== "rule").sort().map((k) => `${k}=${JSON.stringify(b[k])}`).join(" ");

export function Wizard() {
  const { api, cfg } = useServices();
  const [templates, setTemplates] = useState<CatalogItem[] | null>(null);
  const [registry, setRegistry] = useState<JudgeEntry[] | null>(null);
  const [d, setD] = useState<Draft | null>(null);
  const [step, setStep] = useState(0);
  const [preview, setPreview] = useState<ProfilePreview | null>(null);
  const [previewErr, setPreviewErr] = useState<string | null>(null);
  const [err, setErr] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  // 幂等键只用于同一请求的重试：提交体一变就换新键
  const [idem, setIdem] = useState<{ key: string; body: string }>({ key: newIdemKey(), body: "" });

  useEffect(() => {
    Promise.all([api.templates(), api.judges()]).then(
      ([ts, js]) => { setTemplates(ts.items); setRegistry(js.items); setD(draftFromTemplate(ts.items[0] ?? null)); },
      (e: Error) => setErr(e),
    );
  }, [api]);

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

  const issues = useMemo(() => (d ? problemsOf(d) : [[], [], [], []]), [d]);
  if (!templates || !registry || !d) return <p className={err ? "error" : "muted"}>{err ? rejectText(err) : "读取模板与判官注册表…"}</p>;
  const judges = judgesFor(d, registry);
  const set = (patch: Partial<Draft>) => setD({ ...d, ...patch });
  const uploaded = uploadedOf(d);
  const allOk = issues.every((s) => s.length === 0);
  const open = buildOpen(d);
  const pick = (name: string) => setD(draftFromTemplate(templates.find((x) => x.name === name) ?? null, d));

  async function upload(i: number, file: File) {
    setErr(null);
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      const [put, local] = await Promise.all([api.putBlob(bytes), sha256Hex(bytes)]);
      if (put.hash !== local) throw new Error("服务端返回的哈希与本地计算的不一致");
      setD((cur) => cur && { ...cur, materials: cur.materials.map((m, k) => (k === i ? { ...m, name: file.name, hash: local, size: bytes.length, media_type: file.type || "application/octet-stream" } : m)) });
    } catch (e) {
      setErr(e as Error);
    }
  }

  async function submit() {
    setBusy(true);
    setErr(null);
    const body = JSON.stringify(open);
    const key = idem.body === body ? idem.key : newIdemKey();
    setIdem({ key, body });
    try {
      await api.openProblem(open.id, open.materials, open.problem, key);
      navigate({ page: "problem", pid: open.id, asOf: null, node: null });
    } catch (e) {
      setErr(e as Error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="wizard" data-wizard>
      <header className="wizard-head">
        <h2>开题</h2>
        <label>模板
          <select value={d.template} disabled={uploaded.length > 0} data-field="template" onChange={(e) => pick(e.target.value)}>
            <option value="">不用模板</option>
            {templates.map((t) => <option key={t.name} value={t.name}>{t.name}（{shortHash(t.hash)}{t.signature ? "" : " · 未签名"}）</option>)}
          </select>
        </label>
        <ol className="steps">
          {STEPS.map((s, i) => (
            <li key={s}><button type="button" className="chip" aria-current={step === i} onClick={() => setStep(i)}>{"①②③④"[i]} {s}{issues[i].length ? ` · 缺 ${issues[i].length} 项` : ""}</button></li>
          ))}
        </ol>
        <span>第 {step + 1}/4 步</span>
      </header>

      {step === 0 && (
        <section data-step="origin">
          <label>题目 id <input value={d.id} data-field="id" onChange={(e) => set({ id: e.target.value })} /></label>
          <label>题名 <input value={d.title} data-field="title" onChange={(e) => set({ title: e.target.value })} /></label>
          <h4>材料（登记为 input 类；与开题在同一批里提交）</h4>
          <ul className="materials">
            {d.materials.map((m, i) => (
              <li key={m.slot}>
                <span>{m.slot}{m.required ? "（必填）" : ""}</span>
                <input type="file" disabled={cfg.token === null} data-slot={m.slot} onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(i, f); }} />
                {m.hash && <span className="hash-badge"><Plain text={m.name ?? ""} /> · {m.size} 字节 · sha256 <code>{shortHash(m.hash)}</code> ✓ 本地计算一致</span>}
              </li>
            ))}
          </ul>
          <button type="button" className="btn-small" data-action="add-slot" onClick={() => set({ materials: [...d.materials, { slot: `材料 ${d.materials.length}`, required: false, name: null, hash: null, size: 0, media_type: "" }] })}>加一个材料槽位</button>
          {cfg.token === null && <p className="muted">上传材料与开题都是写操作：先在页面右上角配置人的令牌。</p>}
        </section>
      )}

      {step === 1 && (
        <section data-step="criterion">
          <label>目标陈述 <input value={d.statement} data-field="statement" onChange={(e) => set({ statement: e.target.value })} /></label>
          <label>Goal 判官（来自注册表，按模板过滤；不能在这里新建）
            <select value={d.judge} disabled={d.lockJudge} data-field="judge" onChange={(e) => set({ judge: e.target.value })}>
              <option value="">未选</option>
              {judges.map((j) => <option key={j.judge_id} value={j.judge_id}>{j.judge_id}@{j.version} · {GRADE_WORD[j.grade]} · {j.kind}</option>)}
            </select>
          </label>
          <label>expect（JSON 对象，由判官解释）<textarea value={d.expect} data-field="expect" onChange={(e) => set({ expect: e.target.value })} /></label>
          <label>spec_ref（已上传的 input 类）
            <select value={d.specSlot} data-field="spec_ref" onChange={(e) => set({ specSlot: e.target.value })}>
              <option value="">不挂</option>
              {uploaded.map(({ m, slot }) => <option key={slot} value={String(slot)}>{m.slot} · {shortHash(m.hash!)}</option>)}
            </select>
          </label>
          <label>max_attempts <input inputMode="numeric" value={d.maxAttempts} data-field="max_attempts" onChange={(e) => set({ maxAttempts: e.target.value })} /></label>
          <fieldset>
            <legend>accept</legend>
            <label><input type="radio" checked={d.accept === "judge"} onChange={() => set({ accept: "judge" })} /> judge（判官确认）</label>
            <label><input type="radio" checked={d.accept === "human"} onChange={() => set({ accept: "human" })} /> human（人验收；终态写 accepted，不写"已证明"）</label>
          </fieldset>
        </section>
      )}

      {step === 2 && (
        <section data-step="scope">
          <table className="mini">
            <thead><tr><th>resource</th><th>pattern</th><th>actions（逗号分隔）</th><th>risk（必选，空 = r2）</th><th /></tr></thead>
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
          <button type="button" className="btn-small" data-action="add-rule" onClick={() => set({ scope: [...d.scope, { resource: "", pattern: "", actions: "", risk: "" }] })}>加一条规则</button>
          <p className="muted">风险由授权的人逐条标注。这是授权，不是画像。</p>
        </section>
      )}

      {step === 3 && (
        <section data-step="budget">
          <label>usd <input inputMode="decimal" value={d.usd} data-field="usd" onChange={(e) => set({ usd: e.target.value })} /></label>
          <label>wall_s <input inputMode="numeric" value={d.wall_s} data-field="wall_s" onChange={(e) => set({ wall_s: e.target.value })} /></label>
          <label>verify_share <input inputMode="decimal" value={d.verify_share} onChange={(e) => set({ verify_share: e.target.value })} /></label>
          <label>bootstrap_share <input inputMode="decimal" value={d.bootstrap_share} onChange={(e) => set({ bootstrap_share: e.target.value })} /></label>
          <p className="muted">
            {d.b1CapMilli && Number(d.usd) > 0
              ? `B1 单题上限 ${usd(d.b1CapMilli)}，这份预算是它的 ${((Number(d.usd) * 1000) / d.b1CapMilli).toFixed(1)} 倍（规格 4.1 默认 3 倍）。`
              : "模板没有给出 B1 单题上限，无法显示倍数。"}
          </p>
        </section>
      )}

      {issues[step].length > 0 && <ul className="issues">{issues[step].map((s) => <li key={s}>{s}</li>)}</ul>}

      <hr />
      <section data-profile-preview>
        <h4>画像预览（服务端推导；这里没有可填的画像字段）</h4>
        {preview ? (
          <table className="mini">
            <thead><tr><th>轴</th><th>显示</th><th>依据</th><th>指向</th></tr></thead>
            <tbody>
              {(["reversibility", "judge", "info"] as const).map((axis) => (
                <tr key={axis} data-axis={axis}><td>{axis}</td><td>{preview.profile[axis]}</td><td><Plain text={String(preview.basis[axis].rule ?? "—")} /></td><td><code><Plain text={pointers(preview.basis[axis]) || "—"} /></code></td></tr>
              ))}
            </tbody>
          </table>
        ) : <p className="muted">{previewErr ? `预检失败：${previewErr}` : "填好判官与至少一条 scope 规则后显示。"}</p>}
      </section>
      <section>
        <h4>Problem 预览（将提交的批次，纯文本）</h4>
        <pre className="output" data-problem-json>{JSON.stringify({ id: open.id, ops: [...open.materials, { op: "open_problem", body: open.problem }] }, null, 2)}</pre>
      </section>
      <footer className="wizard-foot">
        <button type="button" disabled={step === 0} onClick={() => setStep(step - 1)}>上一步</button>
        <button type="button" disabled={step === 3} onClick={() => setStep(step + 1)}>下一步</button>
        <button type="button" data-action="open-problem" disabled={!allOk || busy || cfg.token === null} onClick={submit}>提交开题</button>
        {rejectText(err) && <span className="error" data-reject>{rejectText(err)}</span>}
      </footer>
    </div>
  );
}
