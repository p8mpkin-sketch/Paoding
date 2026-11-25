// 能力配置 › 方案分析（界面一期，docs/design/engine-ui §2、§4、§4.1）：分析列表、分析详情（四栏 + 右栏）与第 1 次确认卡。
// 数据：组装根 scripts/analysis_hub.py 读引擎工作区（GET /v1/analyses…）；提交第 1 次确认只认人的令牌。
// 用词照 §6：界面里不出现设计名词；引擎自由文本里混着的内部名词经 plain() 替换（E-U4 之前的过渡）。
// 决定块由界面按勾选生成（E-U3：只点选，不手写），折叠显示“原文”；关键字是引擎的解析格式，原样保留。
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { ApiError } from "../api/client";
import type { AnArtifact, AnArtifactView, AnCandidate, AnCheck, AnObservation, AnPlacement, AnSubmitted, AnUnit, AnalysesView, AnalysisDetail, AnalysisRow } from "../api/analysis-types";
import { useServices } from "../app/context";
import { navigate, type AnalysisTab } from "../app/router";
import { Button, Empty, Mast, SectionHead } from "../kit";
import {
  ARTIFACT_KIND_WORD, CHECK_WORD, FLAG_WORD, FORM_WORD, GAP_WORD, GATE_N, MODE_WORD, OBS_KIND_WORD, PART_WORD, REC_WORD, SLOT_WORD, STEP_WORD, STOP_WORD, TIER_WORD, UNIT_WORD, VIA_WORD,
  budgetAdd, decisionLine, fmt, g1Block, g1Problems, moduleName, parts, plain, stages, stateOf, stepper, titleOf, type G1Choice, type Tone,
} from "../model/analysis";
import { shortHash, usd } from "../model/text";
import { pending, recorded, rejected } from "../ui/feedback";
import { Plain } from "../ui/registers";
import { Link } from "./Problems";

export const ANALYSES_POLL_MS = 10_000;
/** 抽象一步每个候选的预估（09 §5.2 占位表：主模型 35.2 万入 / 2.4 万出、盲审 2 万 / 4 千，加 20% 余量）〔占位〕。 */
const S4_PER_CANDIDATE_MILLI = 2880;

const errText = (e: unknown) => (e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e));
const P = ({ text }: { text: string }) => <Plain text={plain(text)} />;
/** ISO 时刻 → 本地“月-日 时:分”（页面不读系统时钟，只排版服务端给的时刻）。 */
export function when(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function St({ tone, children, title }: { tone: Tone; children: React.ReactNode; title?: string }) {
  return <span className={`an-st ${tone}`} title={title}><i aria-hidden="true" />{children}</span>;
}

function usePoll<T>(load: () => Promise<T>, ms: number, deps: unknown[]): { data: T | null; error: string | null; reload: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    let alive = true;
    const go = () => {
      if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
      load().then((d) => { if (alive) { setData(d); setError(null); } }, (e: unknown) => { if (alive) setError(errText(e)); });
    };
    go();
    const t = setInterval(go, ms);
    return () => { alive = false; clearInterval(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, n]);
  return { data, error, reload: () => setN((x) => x + 1) };
}

export function useAnalyses(ms = ANALYSES_POLL_MS) {
  const { api } = useServices();
  return usePoll<AnalysesView>(() => api.analyses(), ms, [api]);
}

/** 在等你的分析（还没提交的确认）：侧栏角标、标签角标、待你处理分组同一口径。 */
export const waitingOf = (items: AnalysisRow[]) => items.filter((r) => r.waiting && !r.waiting.submitted);

// ------------------------------------------------------------ 能力配置的三栏

export function CapTabs({ cur, waiting, candidates }: { cur: "evolution" | "analyses" | "candidates"; waiting?: number; candidates?: number }) {
  const tab = (k: typeof cur, word: string, to: Parameters<typeof navigate>[0], ct?: React.ReactNode) => (
    <button type="button" role="tab" aria-selected={cur === k} data-cap-tab={k} onClick={() => navigate(to)}>{word}{ct}</button>
  );
  return (
    <div className="tk-tabs an-captabs" role="tablist" aria-label="能力配置">
      {tab("evolution", "演进读数", { page: "evolution" })}
      {tab("analyses", "方案分析", { page: "analyses" }, waiting ? <span className="ct hot">{waiting}<span className="sr-only"> 个在等你</span></span> : null)}
      {tab("candidates", "候选方案", { page: "candidates" }, candidates !== undefined ? <span className="ct">{candidates}</span> : null)}
    </div>
  );
}

// ------------------------------------------------------------ 列表

function Spend({ spent, cap, tone }: { spent: number; cap: number; tone?: Tone }) {
  const f = cap > 0 ? Math.min(1, spent / cap) : 0;
  return (
    <span className="an-spend">
      <span className="k-mono">{usd(spent)} / {usd(cap)}</span>
      <span className={`an-bar ${tone ?? ""}`} role="meter" aria-label="花费 / 上限" aria-valuemin={0} aria-valuemax={cap} aria-valuenow={spent}><b style={{ width: `${f * 100}%` }} /></span>
    </span>
  );
}

const srcLine = (r: Pick<AnalysisRow, "sources" | "license">) => {
  const s = r.sources.map((x) => `${FORM_WORD[x.form] ?? x.form}（${VIA_WORD[x.via] ?? x.via}）`).join("、") || "没有来源";
  return s;
};

export function Analyses() {
  const { data, error } = useAnalyses();
  const { api } = useServices();
  const bang = usePoll(() => api.bang(), 60_000, [api]);
  if (error && !data) return <p className="error">读不到方案分析：<Plain text={error} /></p>;
  if (!data) return <p className="muted">读取中…</p>;
  const waiting = waitingOf(data.items);
  return (
    <div className="analyses" data-page="analyses">
      <Mast title="能力配置" dek="把一个外部系统交给方案分析：它找出值得借鉴的做法、抽成不带来源细节的核心机制、映射到我们的模块槽，每一步都停下来等你确认。分析只出设计，不写代码。" />
      <CapTabs cur="analyses" waiting={waiting.length} candidates={bang.data?.entries.length} />
      {waiting.length > 0 && (
        <div className="an-ask" data-an-waiting>
          <div className="grow"><b>{waiting.length} 个分析在等你</b>{waiting.map((r) => `「${titleOf(r.statement)}」第 ${GATE_N[r.waiting!.gate]} 次确认`).join("；")}</div>
          <Link to={{ page: "analysis", run: waiting[0].run, tab: "now" }} className="k-btn k-btn-zhu k-btn-sm">去处理</Link>
        </div>
      )}
      {error && <p className="error">刷新失败，显示的是上一次读到的：<Plain text={error} /></p>}
      {data.items.length === 0 ? (
        <Empty title="还没有方案分析">分析在方案分析实例里建立（引擎还没接进内核，一期只读引擎写下的工作区）。走到第 1 次确认时，这里会出现一行，侧栏“能力配置”标出在等你的数量。</Empty>
      ) : (
        <div className="md-tbl an-tbl" role="table" aria-label="方案分析">
          <div className="md-row an-row md-head" role="row">
            <span role="columnheader">分析</span><span role="columnheader">状态</span><span role="columnheader">走到</span>
            <span role="columnheader">花费 / 上限</span><span role="columnheader" className="r">更新</span>
          </div>
          {data.items.map((r) => {
            const st = stateOf(r);
            return (
              <div key={r.run} className="md-row an-row" role="row" data-an-run={r.run} data-state={r.waiting ? (r.waiting.submitted ? "submitted" : "waiting") : r.step ?? ""}>
                <span role="cell" className="an-name">
                  <Link to={{ page: "analysis", run: r.run, tab: "now" }}><Plain text={titleOf(r.statement)} /></Link>
                  <span className="t2">{MODE_WORD[r.mode] ?? r.mode} · {srcLine(r)}{r.license?.reuse === "idea_only" ? " · 只借思路" : ""}{r.candidates ? ` · ${r.candidates} 个候选` : ""}</span>
                </span>
                <span role="cell"><St tone={st.tone}>{st.word}</St></span>
                <span role="cell" className="t2">{st.at}</span>
                <span role="cell"><Spend spent={r.spent_usd_milli} cap={r.budget_usd_milli} tone={r.step === "paused_budget" ? "need" : r.waiting ? "" : "live"} /></span>
                <span role="cell" className="r t2 k-mono">{when(r.updated_at)}</span>
              </div>
            );
          })}
        </div>
      )}
      <p className="an-note">每个分析是方案分析实例里的一个开放任务：联网只经你批准、预算到线即停、每一步都记进检查点可续做；它看不到你的真实任务与资料库。一期只读，新建分析、第 2、3 次确认在二、三期。</p>
    </div>
  );
}

// ------------------------------------------------------------ 详情

function Stepper({ d }: { d: AnalysisDetail }) {
  const cells = stepper(d.step, !!d.waiting, d.mode);
  return (
    <ol className="an-steps" aria-label="分析进度">
      {cells.map((c) => (
        <li key={c.key} className={`${c.gate ? "gate " : ""}${c.cls}`} data-an-step={c.key} aria-current={c.cls === "now" || c.cls === "wait" ? "step" : undefined}>
          <span className="bar" aria-hidden="true" />
          <span className="w">{c.gate && c.cls !== "skip" ? `◆ ${c.word}` : c.word}</span>
        </li>
      ))}
    </ol>
  );
}

function Rail({ d }: { d: AnalysisDetail }) {
  const st = stages(d);
  const reads = Object.keys(SLOT_WORD).map((s) => d.units.find((u) => u.id === `read:${s}`) ?? null);
  const cuiyi = d.units.filter((u) => u.id.startsWith("cuiyi:"));
  const cand = d.candidates_doc;
  const snap = cand?.basis.snapshots[0];
  const tiers = Object.entries(d.spent.tokens ?? {});
  return (
    <aside className="an-rail" aria-label="分析概况">
      <section className="an-card" data-an-rail="budget">
        <h3>预算<span className="grow" /><span className="k-mono t2">{usd(d.spent.usd_milli)} / {usd(d.budget_usd_milli)}</span></h3>
        {st.map((s) => (
          <div key={s.key} className="an-stage" data-an-stage={s.key}>
            <div className="t2">{s.word} <span className="k-mono">{usd(s.spent)}</span> / <span className="k-mono">{usd(s.cap)}</span></div>
            <span className={`an-bar ${s.spent >= s.cap ? "need" : ""}`} role="meter" aria-label={`${s.word}的花费`} aria-valuemin={0} aria-valuemax={s.cap} aria-valuenow={s.spent}><b style={{ width: `${s.cap > 0 ? Math.min(100, (s.spent / s.cap) * 100) : 0}%` }} /></span>
          </div>
        ))}
        <p className="an-note">整题上限由内核的预算上限执行；每步按比例的软上限到了就收尾当前单元、带检查点交给你〔占位比例〕。</p>
      </section>
      <section className="an-card" data-an-rail="units">
        <h3>进度<span className="grow" /><span className="t2">发现阶段 · 每个模块槽一格</span></h3>
        <div className="an-units" role="list" aria-label="发现阶段的单元">
          {reads.map((u, i) => {
            const slot = Object.keys(SLOT_WORD)[i];
            const s = u ? UNIT_WORD[u.state] : UNIT_WORD.todo;
            return <span key={slot} role="listitem" className={`u ${s.tone}`} title={`${SLOT_WORD[slot]}：${s.word}${u?.summary ? ` · ${plain(u.summary)}` : ""}`}><b>{slot}</b><i aria-hidden="true" /></span>;
          })}
        </div>
        {cuiyi.length > 0 && (
          <div className="an-chips t2">抽象：{cuiyi.map((u) => <St key={u.id} tone={UNIT_WORD[u.state].tone}>{u.id.slice(6)}</St>)}</div>
        )}
        <dl className="an-kv">
          <dt>接力会话</dt><dd className="k-mono">{d.relays} / 8</dd>
          <dt>检查点</dt><dd className="k-mono">run.json · {when(d.updated_at)}</dd>
        </dl>
      </section>
      <section className="an-card" data-an-rail="models">
        <h3>模型用量</h3>
        {tiers.length === 0 ? <p className="t2">还没有调用模型。</p> : (
          <dl className="an-kv">
            {tiers.map(([tier, [i, o]]) => <Fragment key={tier}><dt>{TIER_WORD[tier] ?? tier}</dt><dd className="k-mono">{(i / 1000).toFixed(1)}k 入 · {(o / 1000).toFixed(1)}k 出</dd></Fragment>)}
          </dl>
        )}
        <p className="an-note">原文只交给轻量的读取模型；主模型只看结构化的观察，不能执行命令。</p>
      </section>
      <section className="an-card" data-an-rail="basis">
        <h3>依据</h3>
        <dl className="an-kv">
          <dt>能力配置</dt><dd className="k-mono" title={cand?.basis.gongfa_digest ?? d.engine.gongfa_digest}>{cand ? `v${cand.basis.gongfa_jie} · ` : ""}{shortHash(cand?.basis.gongfa_digest ?? d.engine.gongfa_digest ?? "—")}</dd>
          {cand && <><dt>能力剖面</dt><dd className="k-mono" title={cand.basis.profile_sha256}>{shortHash(cand.basis.profile_sha256)}</dd></>}
          {snap?.identity && Object.values(snap.identity)[0] && <><dt>快照</dt><dd className="k-mono" title={Object.values(snap.identity)[0]}>{shortHash(Object.values(snap.identity)[0])}</dd></>}
          {snap?.size_tier && <><dt>大小</dt><dd>{snap.size_tier} 档</dd></>}
          <dt>分析程序</dt><dd className="k-mono">{d.engine.fire ? `${moduleName(d.engine.fire)} ${d.engine.fire.split("@")[1] ? `@${d.engine.fire.split("@")[1]}` : ""}` : "—"}</dd>
        </dl>
        <p className="an-note">能力配置或剖面变了，这份分析的分数要复算。</p>
      </section>
    </aside>
  );
}

const TAB_WORD: Record<AnalysisTab, string> = { now: "当前", report: "报告", process: "过程", files: "文件" };

export function Analysis({ run, tab }: { run: string; tab: AnalysisTab }) {
  const { api } = useServices();
  const { data: d, error, reload } = usePoll<AnalysisDetail>(() => api.analysis(run), ANALYSES_POLL_MS, [api, run]);
  if (error && !d) return (
    <div className="analysis" data-page="analysis">
      <p className="error">读不到这次分析：<Plain text={error} /></p>
      <Link to={{ page: "analyses" }}>回到方案分析</Link>
    </div>
  );
  if (!d) return <p className="muted">读取中…</p>;
  const st = stateOf(d);
  const lic = d.license;
  const inj = d.observations.filter((o) => o.suspected_injection).length;
  const waitingTab = d.waiting && !d.waiting.submitted;
  return (
    <div className="analysis" data-page="analysis" data-an-run={d.run}>
      <header className="an-head">
        <h1><Plain text={titleOf(d.statement)} /></h1>
        <div className="an-chips">
          <St tone={st.tone}>{st.word}</St>
          <span className="an-chip">{MODE_WORD[d.mode] ?? d.mode}</span>
          <span className="an-chip">{srcLine(d)}</span>
          {lic && <span className={`an-chip${lic.reuse === "idea_only" ? " need" : ""}`} data-an-license={lic.spdx ?? lic.status} title={lic.detected ? `从 ${lic.detected} 认出` : undefined}>{lic.spdx ?? lic.status} · {lic.reuse === "idea_only" ? "只借思路，不参考原码" : "可参考原码"}</span>}
          {inj > 0 && <span className="an-chip need" data-an-injection={inj} title="勘察时发现来源里有像是写给智能体的指令；它只被当作数据，没有执行">来源含疑似指令 {inj} 处 · 已忽略</span>}
          <span className="k-mono t3">{d.run}</span>
        </div>
        {d.statement !== titleOf(d.statement) && <p className="t2">原话：<Plain text={d.statement} /></p>}
      </header>
      <Stepper d={d} />
      <div className="tk-tabs an-tabs" role="tablist" aria-label="分析">
        {(Object.keys(TAB_WORD) as AnalysisTab[]).map((k) => (
          <button key={k} type="button" role="tab" aria-selected={tab === k} data-an-tab={k} onClick={() => navigate({ page: "analysis", run, tab: k }, true)}>
            {k === "now" && waitingTab ? "待你确认" : TAB_WORD[k]}
            {k === "now" && waitingTab ? <span className="ct hot">{GATE_N[d.waiting!.gate]}</span> : null}
            {k === "files" ? <span className="ct">{d.artifacts.length}</span> : null}
          </button>
        ))}
      </div>
      {error && <p className="error">刷新失败，显示的是上一次读到的：<Plain text={error} /></p>}
      <div className="an-grid">
        <div className="an-body">
          {tab === "now" && <Now d={d} onSubmitted={reload} />}
          {tab === "report" && <Reports d={d} />}
          {tab === "process" && <Process d={d} />}
          {tab === "files" && <Files d={d} />}
        </div>
        <Rail d={d} />
      </div>
    </div>
  );
}

// ------------------------------------------------------------ 当前 / 待你确认

function Now({ d, onSubmitted }: { d: AnalysisDetail; onSubmitted: () => void }) {
  if (d.step === "G1" && d.candidates_doc) return <G1 d={d} onSubmitted={onSubmitted} />;
  if (d.step === "G2") return <G2Preview d={d} />;
  if (d.step === "G3") return <G3Preview d={d} />;
  if (d.step === "done") return d.dry_run ? <DryRunDone d={d} /> : <HandoffDone d={d} />;
  if (d.step === "failed") return <div className="an-warn"><b>分析失败</b>停在{lastStep(d)}；可重试的单元见“过程”。</div>;
  if (d.step === "paused_budget") return <div className="an-ask"><div className="grow"><b>预算用完，已暂停</b>已完成的部分交给了你，追加预算后接着做时不会重做。追加与缩小范围在二期。</div></div>;
  return <Working d={d} />;
}

const lastStep = (d: AnalysisDetail) => {
  const u = [...d.units].reverse().find((x) => x.state !== "done");
  return u ? `${STEP_WORD[u.step as keyof typeof STEP_WORD] ?? u.step}（${unitWord(u)}）` : "最后一步";
};

function Working({ d }: { d: AnalysisDetail }) {
  const st = stateOf(d);
  const recent = d.units.slice(-6).reverse();
  return (
    <section className="an-card" data-an-working>
      <div className="an-live"><span className="an-dot live" aria-hidden="true" /><b>正在{st.at}</b><span className="t2">做完会停下来等你确认，不需要你盯着</span></div>
      <ol className="an-trace">{recent.map((u) => <li key={u.id}><St tone={UNIT_WORD[u.state].tone}>{UNIT_WORD[u.state].word}</St><b>{unitWord(u)}</b><span className="t2"><P text={u.summary ?? ""} /></span></li>)}</ol>
      <p className="an-note">完整过程在“过程”一栏。</p>
    </section>
  );
}

function ObsList({ ids, obs }: { ids: string[]; obs: Map<string, AnObservation> }) {
  return (
    <ul className="an-obs">
      {ids.map((id) => {
        const o = obs.get(id);
        if (!o) return <li key={id}><span className="k-mono">{id}</span> <span className="t2">观察库里没有这一条</span></li>;
        return (
          <li key={id} data-an-obs={id}>
            <div><span className="k-mono t3">{id}</span> <span className="an-chip">{SLOT_WORD[o.slot] ?? o.slot}</span> <span className="an-chip">{OBS_KIND_WORD[o.kind] ?? o.kind}</span>{o.suspected_injection && <span className="an-chip need" title={o.injection_note}>来源含疑似指令</span>}</div>
            <div><P text={o.statement} /></div>
            <div className="t3 k-mono">{o.evidence.map((e, i) => <span key={i}>{e.path ?? e.url ?? e.snapshot}{e.lines ? `:${e.lines[0]}–${e.lines[1]}` : ""}{i < o.evidence.length - 1 ? "，" : ""}</span>)}</div>
          </li>
        );
      })}
    </ul>
  );
}

function Basis({ c, obs }: { c: AnCandidate; obs: Map<string, AnObservation> }) {
  const [showObs, setShowObs] = useState(false);
  const all = [...new Set(c.gaps.flatMap((g) => g.observations))];
  return (
    <div className="an-basis" data-an-basis={c.id}>
      <p><b>推荐理由：</b><P text={c.recommend.why} /></p>
      <p><b>现象：</b><P text={c.seed.shihuo.phenomenon} /></p>
      <p><b>差距：</b><P text={c.seed.shihuo.gap} /></p>
      <p><b>为什么算一种做法：</b><P text={c.seed.shihuo.is_fire} /></p>
      <div className="rd-tbl">
        <table className="mini wide" aria-label={`${c.id} 的逐维差距`}>
          <thead><tr><th>维度</th><th className="r">我们</th><th className="r">外部</th><th>类型</th><th className="r">权重</th><th className="r">痛点</th><th>痛点依据</th><th>观察</th></tr></thead>
          <tbody>
            {c.gaps.map((g) => (
              <tr key={g.dim}>
                <td className="k-mono">{g.dim}</td>
                <td className="r k-mono">{g.ours}{g.ours_by && <div className="t3">{moduleName(g.ours_by)}</div>}</td>
                <td className="r k-mono">{g.theirs}</td><td>{GAP_WORD[g.type] ?? g.type}</td>
                <td className="r k-mono">{fmt(g.weight)}</td><td className="r k-mono">{g.pain}</td>
                <td className="t2"><P text={g.pain_basis} /></td><td className="k-mono t3">{g.observations.join(" ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="t2 k-mono">
        置信 {c.confidence.toFixed(2)}{c.confidence_parts ? `（${Object.entries(c.confidence_parts).map(([k, v]) => `${PART_WORD[k] ?? k} ${fmt(v)}`).join("，")}）` : ""}
        {" · "}难度 {c.difficulty}{c.difficulty_parts ? `（${Object.entries(c.difficulty_parts).filter(([, v]) => v).map(([k, v]) => `${PART_WORD[k] ?? k} ${v}`).join("，")}）` : ""}
      </p>
      <button type="button" className="an-link" aria-expanded={showObs} data-action="an-obs" onClick={() => setShowObs(!showObs)}>{showObs ? "收起观察记录" : `看 ${all.length} 条观察记录与来源位置`}</button>
      {showObs && <ObsList ids={all} obs={obs} />}
      <p className="an-note">优先级 = 价值 × 置信 ÷ (难度 × (1 + 风险))，校验器按同一公式复算。推荐不是决定。</p>
    </div>
  );
}

function G1({ d, onSubmitted }: { d: AnalysisDetail; onSubmitted: () => void }) {
  const { api, cfg } = useServices();
  const doc = d.candidates_doc!;
  const order = doc.candidates.map((c) => c.id);
  const obs = useMemo(() => new Map(d.observations.map((o) => [o.id, o])), [d.observations]);
  const done = d.submitted[0] ?? null;
  const [ch, setCh] = useState<G1Choice>({ pick: [], exclude: {}, title: {}, note: "" });
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [renaming, setRenaming] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [add, setAdd] = useState("");
  const [busy, setBusy] = useState(false);
  const [fail, setFail] = useState<string | null>(null);
  const block = g1Block(order, ch);
  const problems = g1Problems(order, ch);
  const addMilli = budgetAdd(add);
  if (addMilli === null) problems.push("追加预算写成美元，最多 100");
  const picked = order.filter((id) => ch.pick.includes(id) && !(id in ch.exclude));
  const bad = doc.checks.filter((c) => !c.ok);

  const toggle = (id: string) => setCh((c) => ({ ...c, pick: c.pick.includes(id) ? c.pick.filter((x) => x !== id) : [...c.pick, id] }));
  const exclude = (id: string) => setCh((c) => {
    const ex = { ...c.exclude };
    if (id in ex) delete ex[id]; else ex[id] = "";
    return { ...c, exclude: ex };
  });
  const saveTitle = (c: AnCandidate) => {
    const t = draft.trim();
    setCh((x) => {
      const title = { ...x.title };
      if (!t || t === c.title) delete title[c.id]; else title[c.id] = t;
      return { ...x, title };
    });
    setRenaming(null);
  };
  const submit = useCallback(async () => {
    setBusy(true);
    setFail(null);
    const t = pending("提交第 1 次确认");
    try {
      await api.analysisDecide(d.run, { block, deliver_seq: d.waiting!.deliver_seq, budget_add_usd_milli: addMilli ?? 0 });
      recorded(t, "第 1 次确认已提交", null, "分析会按这段原文接着做抽象");
      onSubmitted();
    } catch (e) {
      setFail(errText(e));
      rejected(t, "没有提交", errText(e));
    } finally {
      setBusy(false);
    }
  }, [api, block, d.run, d.waiting, addMilli, onSubmitted]);

  const needs = d.needs.filter((n) => !/^请在下列候选中挑选/.test(n));
  return (
    <div className="an-g1" data-an-gate="G1">
      {bad.length > 0 && <div className="an-warn" data-an-failed><b>交付带“未过”标记</b>{bad.map((c) => `${c.id} ${CHECK_WORD[c.id] ?? ""}：${plain(c.detail ?? "")}`).join("；")}。内容可以看，但建议退回重做发现（二期）。</div>}
      {needs.map((n) => <div key={n} className="an-ask" data-an-need><div className="grow"><P text={n} /></div></div>)}
      <section className="an-card"><p className="an-sum"><P text={doc.plain_summary} /></p></section>

      <section className="an-sec">
        <SectionHead title="候选做法" note={done ? "已提交，下面是你看到的那一份" : "勾选要继续抽象的；点标题可改名，排除要写理由"}
          right={done ? null : <span className="t2">已选 {picked.length} 个 · 抽象预计 <span className="k-mono">{usd(picked.length * S4_PER_CANDIDATE_MILLI)}</span>〔占位〕
            {" "}<Button tone="bare" size="sm" data-action="an-pick-rec" onClick={() => setCh((c) => ({ ...c, pick: doc.candidates.filter((x) => x.recommend.level === "recommend" && !(x.id in c.exclude)).map((x) => x.id) }))}>勾上推荐的</Button></span>} />
        <div className="md-tbl an-cands" role="table" aria-label="候选做法">
          <div className="md-row an-cand md-head" role="row">
            <span role="columnheader"><span className="sr-only">选中</span></span><span role="columnheader">编号</span><span role="columnheader">做法</span>
            <span role="columnheader">模块槽</span><span role="columnheader" title="价值 × 置信 ÷ (难度 × (1 + 风险))">优先级</span><span role="columnheader">建议</span>
          </div>
          {doc.candidates.map((c) => {
            const ex = c.id in ch.exclude;
            const rec = REC_WORD[c.recommend.level] ?? { word: c.recommend.level, tone: "" as const };
            const title = ch.title[c.id] ?? c.title;
            const was = done?.decision;
            const wasPicked = was?.pick?.includes(c.id);
            return (
              <Fragment key={c.id}>
                <div className={`md-row an-cand${ex ? " excl" : ""}`} role="row" data-an-cand={c.id} data-picked={done ? !!wasPicked : picked.includes(c.id)}>
                  <span role="cell">
                    <input type="checkbox" checked={done ? !!wasPicked : picked.includes(c.id)} disabled={!!done || ex} onChange={() => toggle(c.id)} aria-label={`选中 ${title}`} data-field="an-pick" />
                  </span>
                  <span role="cell" className="k-mono t2">{c.id}</span>
                  <span role="cell" className="an-cand-main">
                    <span className="an-cand-t">
                      {renaming === c.id ? (
                        <form className="an-rename" onSubmit={(e) => { e.preventDefault(); saveTitle(c); }}>
                          <input value={draft} onChange={(e) => setDraft(e.target.value)} aria-label={`${c.id} 的新标题`} data-field="an-title" autoFocus maxLength={60} />
                          <Button tone="line" size="sm" type="submit" data-action="an-title-ok">好</Button>
                          <Button tone="bare" size="sm" onClick={() => setRenaming(null)}>取消</Button>
                        </form>
                      ) : (
                        <button type="button" className={`an-title${ch.title[c.id] ? " edited" : ""}`} disabled={!!done} title={done ? undefined : "点击改名"} data-action="an-rename"
                          onClick={() => { setRenaming(c.id); setDraft(title); }}><P text={title} /></button>
                      )}
                      {c.dedupe ? <Link to={{ page: "candidates", id: c.dedupe.bang }} className="an-chip" data-an-dedupe={c.dedupe.bang}>已在候选方案 {c.dedupe.bang}</Link> : <span className="an-chip">新登记</span>}
                    </span>
                    <span className="t2"><P text={c.seed.shihuo.phenomenon} /></span>
                    {c.flags?.length ? <span className="an-flags">{c.flags.map((f) => <span key={f} className={f === "license_restricted" || f === "injection_flagged_sources" ? "need" : ""}>{FLAG_WORD[f] ?? f}</span>)}</span> : null}
                  </span>
                  <span role="cell"><span>{SLOT_WORD[c.slot] ?? c.slot}</span>{c.also_slots?.length ? <span className="t3 an-also">兼及 {c.also_slots.map((s) => SLOT_WORD[s] ?? s).join("、")}</span> : null}</span>
                  <span role="cell" className="an-prio">
                    <span className="an-pbar"><span className="k-mono">{fmt(c.priority)}</span><span className="an-bar" aria-hidden="true"><b style={{ width: `${Math.min(100, (c.priority / Math.max(4, ...doc.candidates.map((x) => x.priority))) * 100)}%` }} /></span></span>
                    <span className="k-mono t3" title="价值 · 置信 · 难度 · 风险">{parts(c)}</span>
                  </span>
                  <span role="cell" className="an-rec">
                    <St tone={rec.tone}>{rec.word}</St>
                    <span className="an-acts">
                      <button type="button" className="an-link" aria-expanded={!!open[c.id]} data-action="an-basis" onClick={() => setOpen((o) => ({ ...o, [c.id]: !o[c.id] }))}>{open[c.id] ? "收起" : "依据"}</button>
                      {!done && <> · <button type="button" className="an-link" data-action="an-exclude" onClick={() => exclude(c.id)}>{ex ? "撤销排除" : "排除"}</button></>}
                    </span>
                  </span>
                </div>
                {ex && !done && (
                  <div className="an-cand-x" data-an-exclude={c.id}>
                    <label>排除理由（会记进候选方案，避免以后反复提起）
                      <input value={ch.exclude[c.id]} onChange={(e) => setCh((x) => ({ ...x, exclude: { ...x.exclude, [c.id]: e.target.value } }))} placeholder="例：已在待办里，不必走分析" data-field="an-why" maxLength={120} />
                    </label>
                  </div>
                )}
                {open[c.id] && <div className="an-cand-x"><Basis c={c} obs={obs} /></div>}
              </Fragment>
            );
          })}
        </div>
      </section>

      {doc.already_have.length > 0 && (
        <section className="an-sec">
          <SectionHead title="我们已有且不差" note="外部有、我们持平或更强；证明这些地方也看过了" />
          <div className="md-tbl" role="table" aria-label="我们已有且不差">
            {doc.already_have.map((a) => (
              <div key={a.dim} className="md-row an-have" role="row" data-an-have={a.dim}>
                <span role="cell" className="k-mono">{a.dim}</span>
                <span role="cell" className="k-mono t2">我们 {a.ours} · 外部 {a.theirs}</span>
                <span role="cell" className="t2">{a.by ? <>{moduleName(a.by)} <span className="k-mono t3">{a.by}</span></> : "—"}</span>
                <span role="cell" className="k-mono t3">{a.observations.join(" ")}</span>
              </div>
            ))}
          </div>
        </section>
      )}
      {doc.not_fire.length > 0 && (
        <section className="an-sec">
          <SectionHead title="只是普通需求" note="不是一种可复用的做法" />
          <div className="md-tbl" role="table" aria-label="只是普通需求">
            {doc.not_fire.map((n) => <div key={n.what} className="md-row an-half" role="row"><span role="cell"><P text={n.what} /></span><span role="cell" className="t2"><P text={n.why} /></span></div>)}
          </div>
        </section>
      )}
      <section className="an-sec">
        <SectionHead title="覆盖情况" note={`每个模块槽读了多少、为什么停${doc.unseen_slots.length ? `；没见到相关机制：${doc.unseen_slots.map((s) => SLOT_WORD[s] ?? s).join("、")}` : ""}`} />
        <div className="rd-tbl">
          <table className="mini wide" aria-label="覆盖情况" data-an-coverage>
            <thead><tr><th>模块槽</th><th className="r">读了几段</th><th className="r">输入 token</th><th>读到的文件</th><th>停下的原因</th></tr></thead>
            <tbody>
              {doc.coverage.map((v) => (
                <tr key={v.slot}><td>{SLOT_WORD[v.slot] ?? v.slot}</td><td className="r k-mono">{v.excerpts}</td><td className="r k-mono">{(v.tokens_in / 1000).toFixed(1)}k</td>
                  <td className="k-mono t3">{v.modules?.join("、") ?? "—"}</td><td>{STOP_WORD[v.stop] ?? v.stop}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="an-note">校验 {doc.checks.filter((c) => c.ok).length} / {doc.checks.length} 项通过{bad.length ? `，未过：${bad.map((c) => c.id).join("、")}` : ""}。原文只交给读取模型；每一句都能点回观察记录和来源位置。</p>
      </section>

      {done ? <Submitted s={done} /> : (
        <div className="an-decide" data-an-decide>
          <div className="an-decide-main">
            <div className="an-decide-row">
              <b>第 1 次确认 · 选 {picked.length} 个做抽象{Object.keys(ch.exclude).length ? `，排除 ${Object.keys(ch.exclude).length} 个` : ""}</b>
              <label className="t2 an-add">追加预算 $<input value={add} onChange={(e) => setAdd(e.target.value)} inputMode="decimal" placeholder="0" aria-label="追加预算（美元）" data-field="an-add" /></label>
              <input className="an-noteinput" value={ch.note} onChange={(e) => setCh((c) => ({ ...c, note: e.target.value }))} placeholder="备注（可选），会一起记下" aria-label="备注" data-field="an-note" maxLength={300} />
            </div>
            <details className="an-raw"><summary>记进检查点的原文（分析按这段执行）</summary><pre data-an-block><Plain text={block} /></pre></details>
            {problems.length > 0 && <p className="an-miss" data-an-problems>还差：{problems.join("；")}</p>}
            {fail && <p className="error" data-an-fail>没有提交：<Plain text={fail} /></p>}
          </div>
          <div className="an-decide-acts">
            <Button tone="ink" disabled={busy || problems.length > 0 || !cfg.token} onClick={submit} data-action="an-submit" title={!cfg.token ? "只读：还没有配置人的令牌" : undefined}>确认，继续下一步</Button>
            <span className="t3">{cfg.token ? "提交后不能撤回，可以在下一次确认时退回" : "只读：还没有配置人的令牌"}</span>
          </div>
        </div>
      )}
    </div>
  );
}

function Submitted({ s }: { s: AnSubmitted }) {
  return (
    <section className="an-card an-done" data-an-submitted>
      <div className="an-live"><span className="an-dot live" aria-hidden="true" /><b>第 {GATE_N[s.gate]} 次确认已提交</b><span className="t2">{when(s.at)} · 等分析接着做{s.budget_add_usd_milli ? ` · 追加 ${usd(s.budget_add_usd_milli)}` : ""}</span></div>
      <pre className="an-block"><Plain text={s.block} /></pre>
      <p className="an-note">这段原文和引擎续做时读到的逐字节相同。{s.forwarded ? "已交给分析实例。" : "引擎接进内核以前，由分析实例取走后接着做。"}</p>
    </section>
  );
}

function G2Preview({ d }: { d: AnalysisDetail }) {
  return (
    <div className="an-g2" data-an-gate="G2">
      <div className="an-ask"><div className="grow"><b>第 2 次确认：核心机制</b>逐个确认、改一句、退回或放弃的卡在二期；这里先只读，每个候选一节。</div></div>
      <Decided d={d} />
      {d.needs.map((n) => <div key={n} className="an-warn"><P text={n} /></div>)}
      {d.essences.map((e) => {
        const bad = [...e.checks, ...e.validators].filter((c) => !c.ok && !c.advisory);
        return (
          <section key={e.candidate} className="an-card" data-an-essence={e.candidate}>
            <h3><span className="k-mono t2">{e.candidate}</span> <P text={e.masked.statement} /></h3>
            {e.plain_summary && <p className="an-sum"><P text={e.plain_summary} /></p>}
            <p className="t2">新增指标：{e.masked.fusion.emergent.length ? e.masked.fusion.emergent.map((x) => `${x.dim}（${x.measure === "structural" ? "结构读数" : "运行读数"}，门槛 ${x.gate}）`).join("；") : "没有，最好的结局是全面提升"}</p>
            <div className="an-checks">{e.checks.map((c) => <St key={c.id} tone={c.ok ? (c.advisory ? "" : "ok") : "bad"} title={c.detail ? plain(c.detail) : undefined}>{c.id} {CHECK_WORD[c.id]}</St>)}</div>
            {e.drafts.disagreements?.length ? <p className="t2">三稿分歧：<P text={e.drafts.disagreements.join("；")} /></p> : null}
            {bad.length > 0 && <p className="an-miss">未过：{bad.map((c) => c.id).join("、")}</p>}
          </section>
        );
      })}
    </div>
  );
}

/** 之前几次确认里你定了什么：每次一行，原话在“过程”。 */
function Decided({ d }: { d: AnalysisDetail }) {
  const rows = d.gates.filter((g) => g.decision);
  if (rows.length === 0) return null;
  return (
    <ul className="an-list an-decided" data-an-decided>
      {rows.map((g) => <li key={g.deliver_seq}><b>第 {GATE_N[g.gate]} 次确认</b><span className="t2"><Plain text={decisionLine(g.decision!)} /></span></li>)}
    </ul>
  );
}

/** 对照组的固定顺序：基线、外部原版、外部方案移植、融合方案、基线复跑。 */
const ARM_ORDER = ["B", "A0", "A1", "F", "B1"];

const Checks = ({ rows }: { rows: AnCheck[] }) => (
  <div className="an-checks">{rows.map((c) => <St key={c.id} tone={c.ok ? (c.advisory ? "" : "ok") : "bad"} title={c.detail ? plain(c.detail) : undefined}>{c.id} {CHECK_WORD[c.id]}</St>)}</div>
);

/** 一个候选的映射：放进哪个模块槽、替换谁、内核动不动、拿什么量、怎么做、和谁冲突。只读。 */
function PlacementCard({ p, d }: { p: AnPlacement; d: AnalysisDetail }) {
  const w = d.words;
  const title = d.candidates_doc?.candidates.find((c) => c.id === p.candidate)?.title ?? "";
  const conf = p.conflicts;
  const conflicts = [
    ...conf.fires.map((c) => ({ k: moduleName(c.fire), v: w.resolution[c.resolution] ?? c.resolution, note: c.note })),
    ...conf.kernel.map((c) => ({ k: `内核 ${c.kernel}`, v: w.resolution[c.resolution] ?? c.resolution, note: c.note })),
    ...conf.candidates.map((c) => ({ k: c.other, v: w.relation[c.relation] ?? c.relation, note: c.note })),
    ...conf.slot_locks.map((c) => ({ k: SLOT_WORD[c.slot] ?? c.slot, v: `被在途的集成记录 ${c.dossier} 占用`, note: undefined })),
  ];
  const bad = [...p.checks.filter((c) => !c.ok && !c.advisory).map((c) => c.id), ...p.problems];
  return (
    <section className="an-card" data-an-placement={p.candidate}>
      <h3><span className="k-mono t2">{p.candidate}</span> <P text={title} /></h3>
      {p.plain_summary && <p className="an-sum"><P text={p.plain_summary} /></p>}
      <div className="an-chips">
        <span className="an-chip">模块槽 · {SLOT_WORD[p.fire.slot] ?? p.fire.slot}</span>
        <span className="an-chip k-mono">{p.fire.id}</span>
        {p.fire.also_touches?.length ? <span className="an-chip">兼及 {p.fire.also_touches.map((s) => SLOT_WORD[s] ?? s).join("、")}</span> : null}
        {p.group.length > 0 && <span className="an-chip">同组 {p.group.map((g) => g.id).join("、")}</span>}
        <span className="an-chip">{p.replaces ? `替换 ${moduleName(p.replaces)}（留作对照）` : "与现有模块并存"}</span>
        <span className={`an-chip${p.kernel_forecast.length ? " need" : ""}`}>{p.kernel_forecast.length ? `内核改动预判：${p.kernel_forecast.join("、")}` : "内核不改"}</span>
        <span className="an-chip">难度 {p.difficulty.value}</span>
      </div>
      {p.arms && (
        <dl className="an-kv">
          {ARM_ORDER.filter((k) => k in p.arms!).concat(Object.keys(p.arms).filter((k) => !ARM_ORDER.includes(k))).map((k) => [k, p.arms![k]] as const).map(([k, v]) => <Fragment key={k}><dt>{w.arm[k] ?? k}</dt><dd><P text={v} /></dd></Fragment>)}
        </dl>
      )}
      {p.readings?.length ? (
        <div className="an-tblwrap">
          <table className="an-dtbl">
            <caption>预登记的指标 {p.readings.length} 项</caption>
            <thead><tr><th scope="col">指标</th><th scope="col">类别</th><th scope="col">方向</th><th scope="col">门槛</th><th scope="col">怎么量</th></tr></thead>
            <tbody>
              {p.readings.map((r) => (
                <tr key={r.dim}>
                  <th scope="row"><P text={r.dim} />{r.mandatory ? <span className="t3">（必登）</span> : null}</th>
                  <td className="nw">{w.reading_kind[r.kind] ?? r.kind}</td>
                  <td className="nw">{r.dir === "up" ? "越高越好" : "越低越好"}</td>
                  <td className="k-mono"><P text={String(r.gate ?? "—")} /></td>
                  <td className="t2"><P text={r.test ?? r.run ?? "—"} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {p.steps?.length ? (
        <details className="an-raw" data-an-steps>
          <summary>实现步骤 {p.steps.length} 步</summary>
          <ol className="an-impl">
            {p.steps.map((s) => <li key={s.n}><P text={s.do} /><span className="t2">{SLOT_WORD[s.slot] ?? s.slot} · <span className="k-mono">{s.where.join("、")}</span> · 验收：<P text={s.accept} /></span></li>)}
          </ol>
        </details>
      ) : null}
      {conflicts.length > 0 && (
        <ul className="an-list" data-an-conflicts>
          {conflicts.map((c) => <li key={`${c.k}:${c.v}`}><b>{c.k}</b> {c.v}{c.note ? <span className="t2"> · <P text={c.note} /></span> : null}</li>)}
        </ul>
      )}
      <Checks rows={p.checks} />
      {bad.length > 0 && <p className="an-miss">未过：<P text={bad.join("、")} /></p>}
    </section>
  );
}

function OrderList({ d }: { d: AnalysisDetail }) {
  if (!d.order) return null;
  const title = (id: string) => d.candidates_doc?.candidates.find((c) => c.id === id)?.title ?? "";
  return (
    <section className="an-card" data-an-order>
      <h3>集成顺序</h3>
      <ol className="an-impl">
        {d.order.order.map((o) => <li key={o.candidate}><span><span className="k-mono t2">{o.candidate}</span> <P text={title(o.candidate)} /></span><span className="t2"><P text={o.why} />{o.waits_for?.length ? ` · 等 ${o.waits_for.join("、")} 定论` : ""}</span></li>)}
      </ol>
      {d.order.held.map((h) => <p key={h.candidate} className="an-miss">暂缓 {h.candidate}：{d.words.held[h.why] ?? h.why}{h.note ? <>（<P text={h.note} />）</> : null}</p>)}
      <p className="an-note">顺序按优先级与先后关系算出，一次只交一个：前一个定论后再做下一个。</p>
    </section>
  );
}

function G3Preview({ d }: { d: AnalysisDetail }) {
  return (
    <div className="an-g2" data-an-gate="G3">
      <div className="an-ask"><div className="grow"><b>第 3 次确认：映射与集成顺序</b>逐个决定交实现线、搁置或排除的卡在后续一期；这里先只读，每个候选一节。</div></div>
      {d.needs.map((n) => <div key={n} className="an-warn"><P text={n} /></div>)}
      <Decided d={d} />
      <OrderList d={d} />
      {d.placements.map((p) => <PlacementCard key={p.candidate} p={p} d={d} />)}
    </div>
  );
}

/** 三次确认都过了：交给实现线的、暂缓的、候选方案的变化，以及接下来由谁做什么。 */
function HandoffDone({ d }: { d: AnalysisDetail }) {
  const h = d.handoff;
  if (!h) return <Empty title="已完成">这次分析已经走完；交接内容见“报告”。</Empty>;
  const bad = h.validator.filter((c) => !c.ok && !c.advisory);
  return (
    <div className="an-g2" data-an-done="handoff">
      <section className="an-card">
        <div className="an-live"><span className={`an-dot ${bad.length ? "bad" : "ok"}`} aria-hidden="true" /><b>{h.items.length ? `已交接 · ${h.items.length} 个做法交给实现线` : "已完成 · 这次没有交给实现线的做法"}</b><span className="t2">{h.date}{h.held.length ? ` · 暂缓 ${h.held.length} 个` : ""}</span></div>
        {h.items.length > 0 && (
          <ol className="an-impl" data-an-handed>
            {h.items.map((it) => <li key={it.candidate}><span><span className="k-mono t2">{it.candidate}</span> <P text={it.title} /> <span className="an-chip">{SLOT_WORD[it.slot] ?? it.slot}</span> <span className="k-mono t3">{it.module}</span></span><span className="t2"><P text={it.plain_summary} /></span></li>)}
          </ol>
        )}
        {h.held.map((x) => <p key={x.candidate} className="an-miss">暂缓 {x.candidate}：{d.words.held[x.why] ?? x.why}{x.note ? <>（<P text={x.note} />）</> : null}</p>)}
        {d.license?.reuse === "idea_only" && <p className="an-miss">来源许可证 {d.license.spdx ?? d.license.status}：实现时不得打开原码，只借思路。</p>}
        <Checks rows={h.validator} />
        {bad.length > 0 && <p className="an-miss">交接内容校验未过：{bad.map((c) => c.id).join("、")}</p>}
      </section>
      {d.needs.length > 0 && (
        <section className="an-card" data-an-next>
          <h3>接下来</h3>
          <ul className="an-list">{d.needs.map((n) => <li key={n}><P text={n} /></li>)}</ul>
          <p className="an-note">候选方案的变化 {h.bang_updates.length} 条，由导入命令写入、随 PR 审；这里不直接改。{h.library_import ? "报告存入资料库在界面后续一期。" : ""}</p>
        </section>
      )}
      <section className="an-card"><h3>你的三次确认</h3><Decided d={d} /></section>
    </div>
  );
}

const NOT_PLACED_WORD: Record<string, string> = { empty: "没有内容", incomplete: "缺栏目" };

/** 预评估走完：每个做法一行的结论与正式走一遍的预估。只读；转正式在后续一期。 */
function DryRunDone({ d }: { d: AnalysisDetail }) {
  const r = d.dry_run!;
  const e = r.estimate;
  const notPlaced = r.not_placed ?? [];
  const candTitle = (id: string) => d.candidates_doc?.candidates.find((c) => c.id === id)?.title ?? "";
  return (
    <div className="an-g2" data-an-done="dry_run">
      <section className="an-card">
        <div className="an-live"><span className="an-dot ok" aria-hidden="true" /><b>预评估报告已出</b><span className="t2">自动取了优先级最高的 {r.auto_picked.length} 个 · 没有停下来等确认</span></div>
        <p className="an-sum"><P text={r.plain_summary} /></p>
        <div className="an-tblwrap">
          <table className="an-dtbl" data-an-dry>
            <caption>每个做法的预评估</caption>
            <thead><tr><th scope="col">做法</th><th scope="col">模块槽</th><th scope="col">替换</th><th scope="col">内核</th><th scope="col">难度</th><th scope="col">可能的结局</th><th scope="col">检验</th></tr></thead>
            <tbody>
              {r.items.map((it) => (
                <Fragment key={it.candidate}>
                  <tr data-an-dry-item={it.candidate} className={it.unpassed ? "an-dhas" : undefined}>
                    <th scope="row"><span className="k-mono t2">{it.candidate}</span> <P text={it.statement} /></th>
                    <td className="nw">{SLOT_WORD[it.slot] ?? it.slot}</td>
                    <td className="nw">{it.replaces ? moduleName(it.replaces) : "无"}</td>
                    <td className="nw">{it.kernel_forecast.length ? it.kernel_forecast.join("、") : "不改"}</td>
                    <td className="k-mono">{it.difficulty ?? "—"}</td>
                    <td><b>{d.words.outcome[it.likely_outcome] ?? it.likely_outcome}</b><span className="t2"> · <P text={it.why} /></span></td>
                    <td data-an-dry-check={it.unpassed ? "bad" : "ok"}>{it.unpassed ? <St tone="bad">未过</St> : <St tone="ok">过</St>}</td>
                  </tr>
                  {/* 未过的说明占整行：放在格子里会被挤成一字一行；紧跟在这个做法后面，开头自己说明自己是什么 */}
                  {it.unpassed && (
                    <tr className="an-ddetail" data-an-dry-detail={it.candidate}>
                      <td colSpan={7}><b>未过的检验</b><span className="t2"><P text={plain(it.unpassed)} /></span></td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
        {notPlaced.length > 0 && (
          <div className="an-notplaced" data-an-dry-notplaced>
            <h4>没有提炼出来，未做映射评估（{notPlaced.length} 个）</h4>
            <p className="t2">重写之后结构仍不对，上面的表里没有它们。</p>
            <ul>
              {notPlaced.map((n) => (
                <li key={n.candidate} data-an-dry-out={n.candidate}>
                  <span className="k-mono t2">{n.candidate}</span> {candTitle(n.candidate)}
                  <St tone="bad">{NOT_PLACED_WORD[n.kind] ?? "结构不对"}</St>
                  <span className="t2"> <P text={plain(n.why)} /></span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {e && <p className="t2">正式走一遍的预估：{Object.entries(e.tokens).map(([k, v]) => `${TIER_WORD[k] ?? k} 入 ${v.in.toLocaleString("en-US")} 出 ${v.out.toLocaleString("en-US")}`).join("；")}；约 {e.minutes} 分钟机器时间{e.budget_usd_milli ? `，预算 ${usd(e.budget_usd_milli)}` : ""}〔占位估算〕。</p>}
        <Checks rows={r.validators} />
      </section>
      {d.needs.map((n) => <div key={n} className="an-warn"><P text={n} /></div>)}
      <p className="an-note">预评估的结果只记到候选方案里（状态“预评估过”）。复用这次的快照与观察转成正式分析在界面后续一期。</p>
    </div>
  );
}

// ------------------------------------------------------------ 报告、过程、文件

function Reports({ d }: { d: AnalysisDetail }) {
  if (d.reports.length === 0) return <Empty title="还没有交付">走到第 1 次确认时，分析会交一份人读报告，按交付顺序列在这里。</Empty>;
  return (
    <div className="an-g2" data-an-reports>
      {d.reports.map((r) => (
        <section key={r.kind} className="an-card" data-an-report={r.kind}>
          <h3>{REPORT_WORD[r.kind] ?? r.kind}{r.deliver_seq !== null ? <span className="t3 k-mono"> · 交付 #{r.deliver_seq}</span> : null}</h3>
          <pre className="an-report"><P text={r.text} /></pre>
        </section>
      ))}
      <p className="an-note">报告由产物按固定格式生成，不是模型另写的；表里每个数都能在“文件”里对上。</p>
    </div>
  );
}

const REPORT_WORD: Record<string, string> = { G1: "第 1 次交付 · 候选做法", G2: "第 2 次交付 · 核心机制", G3: "第 3 次交付 · 映射与集成顺序", handoff: "交接", dry_run: "预评估报告" };

function unitWord(u: AnUnit): string {
  const [k, v] = u.id.split(":");
  if (k === "snapshot") return "取快照";
  if (k === "survey") return "勘察：文件清单与符号";
  if (k === "read") return `读 ${SLOT_WORD[v] ?? v}`;
  if (u.id === "candidates") return "整理候选清单";
  if (k === "cuiyi") return `抽象 ${v}`;
  if (k === "ruwei") return `映射 ${v}`;
  if (k === "handoff") return "整理交接内容";
  if (k === "dry_run") return "整理预评估报告";
  return u.id;
}

function Process({ d }: { d: AnalysisDetail }) {
  const byStep = new Map<string, AnUnit[]>();
  for (const u of d.units) byStep.set(u.step, [...(byStep.get(u.step) ?? []), u]);
  const rows: { key: string; head: string; units?: AnUnit[]; gate?: (typeof d.gates)[number] }[] = [];
  for (const s of ["S1", "S2", "S3", "G1", "S4", "G2", "S5", "G3", "S6"]) {
    if (s.startsWith("G")) {
      for (const g of d.gates.filter((x) => x.gate === s)) rows.push({ key: `${s}:${g.deliver_seq}`, head: `第 ${GATE_N[g.gate]} 次确认`, gate: g });
    } else if (byStep.has(s)) rows.push({ key: s, head: STEP_WORD[s as keyof typeof STEP_WORD], units: byStep.get(s) });
  }
  const pend = new Map(d.submitted.map((x) => [`${x.gate}:${x.deliver_seq}`, x]));
  return (
    <div className="an-g2" data-an-process>
      <ol className="an-proc">
        {rows.map((r) => (
          <li key={r.key} data-an-proc={r.key} className={r.gate ? "gate" : undefined}>
            <div className="an-proc-h"><b>{r.head}</b>{r.units ? <span className="t2">{r.units.filter((u) => u.state === "done").length} / {r.units.length} 完成{d.spent.by_step[r.key] ? ` · ${usd(d.spent.by_step[r.key])}` : ""}</span> : null}</div>
            {r.units && (
              <ul>
                {r.units.map((u) => (
                  <li key={u.id} data-an-unit={u.id}>
                    <St tone={UNIT_WORD[u.state].tone}>{UNIT_WORD[u.state].word}</St>
                    <span>{unitWord(u)}</span>
                    <span className="t2"><P text={u.summary ?? ""} />{u.attempts && u.attempts > 1 ? ` · 第 ${u.attempts} 次` : ""}</span>
                    {u.output && <span className="k-mono t3" title={u.output}>{shortHash(u.output)}</span>}
                  </li>
                ))}
              </ul>
            )}
            {r.gate && (
              <div className="t2">
                交付 #{r.gate.deliver_seq}
                {r.gate.decision ? <> · 你的决定 #{r.gate.follow_up_seq}：<Plain text={decisionLine(r.gate.decision)} /></>
                  : pend.has(`${r.gate.gate}:${r.gate.deliver_seq}`) ? <> · 已提交，等分析接着做</> : <> · 等你确认</>}
              </div>
            )}
          </li>
        ))}
      </ol>
      <p className="an-note">这里按检查点 run.json 排出每个单元；引擎接进分析实例后，这一栏换成任务页同一份全链路追踪（事件、会话活动、每次模型调用）。</p>
    </div>
  );
}

function Files({ d }: { d: AnalysisDetail }) {
  const { api } = useServices();
  const [sel, setSel] = useState<string | null>(null);
  const [view, setView] = useState<AnArtifactView | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!sel) return;
    let alive = true;
    setView(null);
    setErr(null);
    api.analysisArtifact(d.run, sel).then((v) => { if (alive) setView(v); }, (e: unknown) => { if (alive) setErr(errText(e)); });
    return () => { alive = false; };
  }, [api, d.run, sel]);
  const groups: [AnArtifact["kind"], AnArtifact[]][] = (["material", "exec", "analysis"] as const).map((k) => [k, d.artifacts.filter((a) => a.kind === k)]);
  return (
    <div className="an-g2" data-an-files>
      <p className="an-note">“分析写的”只能当说明，不能当依据；依据是你给的材料与执行输出。每份产物按 sha256 存，改一个字节就是另一份。</p>
      {groups.map(([k, xs]) => xs.length === 0 ? null : (
        <section key={k} className="an-sec">
          <SectionHead title={ARTIFACT_KIND_WORD[k]} note={`${xs.length} 份`} />
          <div className="md-tbl" role="table" aria-label={ARTIFACT_KIND_WORD[k]}>
            {xs.map((a) => (
              <div key={a.name} className={`md-row an-file${sel === a.sha256 ? " on" : ""}`} role="row" data-an-file={a.name}>
                <span role="cell"><button type="button" className="an-link" aria-expanded={sel === a.sha256} data-action="an-file" onClick={() => setSel(sel === a.sha256 ? null : a.sha256)}>{fileWord(a.name)}</button></span>
                <span role="cell" className="k-mono t3">{a.name}</span>
                <span role="cell" className="k-mono t3" title={`sha256 ${a.sha256}${a.artifact_id ? `\n对照 id ${a.artifact_id}` : ""}`}>{shortHash(a.sha256)}</span>
                <span role="cell" className="r k-mono t2">{(a.bytes / 1024).toFixed(1)} KB</span>
              </div>
            ))}
          </div>
        </section>
      ))}
      {sel && (
        <section className="an-card" data-an-artifact={sel}>
          {err ? <p className="error">读不到：<Plain text={err} /></p> : !view ? <p className="muted">读取中…</p> : (
            <>
              <h3>{fileWord(view.name)} <span className="k-mono t3">{view.name} · {shortHash(view.sha256)}</span></h3>
              <pre className="an-json"><Plain text={JSON.stringify(view.content, null, 2)} /></pre>
            </>
          )}
        </section>
      )}
    </div>
  );
}

function fileWord(name: string): string {
  const [k, v] = name.split(":");
  if (k === "snapshot") return "来源快照";
  if (k === "survey") return "勘察单";
  if (k === "read") return `观察摘要 · ${SLOT_WORD[v] ?? v}`;
  if (name === "candidates.json") return "候选清单";
  if (name === "candidates.needs") return "需要你做的";
  if (k === "essence") return v.endsWith(".v") ? `核心机制校验 · ${v.slice(0, -2)}` : `核心机制 · ${v}`;
  if (name === "candidates.proposal") return "候选提议（模型原稿）";
  if (k === "placement") return `映射 · ${v}`;
  if (name === "order.json") return "集成顺序";
  if (k === "report") return v === "S6" ? "交接报告" : `第 ${v.slice(1)} 次交付的报告`;
  if (name === "handoff.json") return "交接包";
  if (name === "dry_run.json") return "预评估报告";
  if (name === "dry_run.v") return "预评估校验";
  if (name === "bang_updates.json") return "候选方案的变化（提议）";
  return name;
}
