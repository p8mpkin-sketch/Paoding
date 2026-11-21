// 能力配置的演进读数（焚决 04 §7；界面用词照 fenjue-ui v0.3：功法→能力配置、品阶→版本 vN、炼档→集成记录、
// 火莲/合炼/并火/反噬→新增能力/全面提升/无增益/回归、常设留出→Holdout 对照）。
// 数据：GET /v1/evolution（组装根按每道题开题时记下的功法版本分组、分臂，FJ6）。只读：读数不驱动任何按钮的默认值，
// 回滚与评审是人的决定，这一页不给按钮。
import { Fragment, useEffect, useState } from "react";
import type { EvoDossier, EvoHoldout, EvoOutcome, EvoStats, EvoStatus, Evolution as EvolutionDoc } from "../api/evolution-types";
import { useServices } from "../app/context";
import { Mast } from "../kit";
import { usd } from "../model/text";
import { HBars, Tile } from "../ui/Charts";
import { Plain } from "../ui/registers";

const POLL_MS = 30_000;
export const SLOT_WORD: Record<string, string> = {
  H1: "会话策略", H2: "调度编排", H3: "工具集", H4: "上下文管理", H5: "知识检索", H6: "可观测性", H7: "结果呈现", H8: "任务解析",
};
export const OUTCOME_WORD: Record<EvoOutcome, string> = { huolian: "新增能力", helian: "全面提升", binghuo: "无增益", fanshi: "回归" };
const OUTCOME_NOTE: Record<EvoOutcome, string> = {
  huolian: "出现了基线与外部方案都没有的能力：采纳，版本加一",
  helian: "同一指标上胜过基线与外部方案：采纳，版本加一",
  binghuo: "没有超出两者：不采纳",
  fanshi: "内核测试不过或基线保障指标退步：不采纳",
};
const STEPS = ["发现", "抽象", "映射", "内核测试", "对照评估", "评审"] as const;
const STATUS: Record<EvoStatus, { word: string; step: number; tone: "wait" | "ok" | "off" | "ink" }> = {
  identified: { word: "已发现", step: 1, tone: "ink" },
  distilled: { word: "已抽象", step: 2, tone: "ink" },
  placed: { word: "待立项评审", step: 3, tone: "wait" },
  design_approved: { word: "已立项", step: 3, tone: "ink" },
  trialed: { word: "内核测试已过", step: 4, tone: "ink" },
  readings_ready: { word: "待评审", step: 5, tone: "wait" },
  adopted: { word: "已采纳", step: 6, tone: "ok" },
  rejected: { word: "未采纳", step: 6, tone: "ink" },
  reverted: { word: "已回滚", step: 6, tone: "off" },
};
const KIND_WORD: Record<string, string> = { 新生: "新增", 异火: "外部方案优势", 本火: "基线保障", 共有: "通用指标" };
const FEW = 10; // 每臂已结束的任务少于这个数时只提示“样本少”，不下结论（界面提示，不是告警门槛）

const pct = (x: number | null) => (x === null ? "—" : `${Math.round(x * 100)}%`);
const mins = (s: number | null) => (s === null ? "—" : s < 60 ? `${s} 秒` : `${(s / 60).toFixed(1).replace(/\.0$/, "")} 分`);
const money = (m: number | null) => (m === null ? "—" : usd(m));
const short = (d: string | null) => (d ? `${d.slice(0, 5)}…${d.slice(-4)}` : "—");
const num = (x: number | undefined) => (x === undefined ? "—" : String(x));

function useEvolution(): { doc: EvolutionDoc | null; error: string | null } {
  const { api } = useServices();
  const [doc, setDoc] = useState<EvolutionDoc | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => {
      if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
      api.evolution().then((d) => { if (alive) { setDoc(d); setError(null); } }, (e: unknown) => { if (alive) setError(e instanceof Error ? e.message : String(e)); });
    };
    load();
    const t = setInterval(load, POLL_MS);
    return () => { alive = false; clearInterval(t); };
  }, [api]);
  return { doc, error };
}

function Steps({ status }: { status: EvoStatus }) {
  const s = STATUS[status];
  return (
    <span className="ev-steps" role="img" aria-label={`流程走到第 ${s.step} 步（共 ${STEPS.length} 步）：${STEPS[s.step - 1]}`} title={STEPS.join(" → ")}>
      {STEPS.map((w, i) => <b key={w} className={i + 1 < s.step ? "done" : i + 1 === s.step ? `at ${s.tone}` : undefined} />)}
    </span>
  );
}

function Dot({ tone, children }: { tone: string; children: React.ReactNode }) {
  return <span className={`ev-dot ${tone}`}><i aria-hidden="true" />{children}</span>;
}

function DossierRow({ d }: { d: EvoDossier }) {
  const [open, setOpen] = useState(false);
  const s = STATUS[d.status];
  const v = d.verdict;
  return (
    <Fragment>
      <tr data-ev-dossier={d.dossier}>
        <td className="k-mono">{d.dossier}</td>
        <td>
          <button type="button" className="ev-name" aria-expanded={open} data-action="ev-dossier" onClick={() => setOpen(!open)}><Plain text={d.title} /></button>
          <div className="t2">{d.slot ? `${SLOT_WORD[d.slot] ?? d.slot} · ` : ""}<span className="k-mono">{d.fire ?? "—"}</span>{d.replaces.length ? <> 替换 <span className="k-mono">{d.replaces.join("、")}</span></> : null}</div>
        </td>
        <td><Steps status={d.status} /></td>
        <td><Dot tone={s.tone}>{s.word}</Dot></td>
        <td data-ev-outcome={v?.outcome ?? d.outcome_proposed ?? ""}>
          {v ? OUTCOME_WORD[v.outcome] : d.outcome_proposed ? `${OUTCOME_WORD[d.outcome_proposed]}（提议）` : "还没有读数"}
          {v?.jie !== undefined && d.status === "adopted" ? <span className="t2"> · 记为 v{v.jie}</span> : null}
        </td>
        <td className="t2">{v ? `${v.by} · ${v.date}` : "—"}</td>
        <td className="r k-mono">{d.kernel_lines_changed === null ? "—" : `${d.kernel_lines_changed} 行`}</td>
      </tr>
      {open && (
        <tr className="ev-more" data-ev-more={d.dossier}>
          <td />
          <td colSpan={6}>
            {d.readings.length > 0 ? (
              <table className="mini" aria-label={`集成记录 ${d.dossier} 的对照读数`}>
                <thead><tr><th>指标</th><th>类别</th><th className="r">基线</th><th className="r">外部方案移植</th><th className="r">融合方案</th><th className="r">门槛</th><th>判</th></tr></thead>
                <tbody>
                  {d.readings.map((r) => (
                    <tr key={r.dim}><td><Plain text={r.dim} /></td><td>{KIND_WORD[r.kind] ?? r.kind}</td><td className="r k-mono">{num(r.B)}</td><td className="r k-mono">{num(r.A1)}</td><td className="r k-mono">{num(r.F)}</td><td className="r k-mono">{num(r.gate)}</td><td>{r.verdict ?? "—"}</td></tr>
                  ))}
                </tbody>
              </table>
            ) : <p className="t2">还没有登记读数。</p>}
            {v?.conditions?.length ? <p className="t2">附加条件：{v.conditions.join("；")}</p> : null}
            {d.reverts.map((r, i) => <p key={i} className="t2">回滚{r.date ? `（${r.date}${r.by ? ` · ${r.by}` : ""}）` : ""}：<Plain text={r.why ?? ""} />{r.back_to ? <> → <span className="k-mono">{r.back_to}</span></> : null}</p>)}
          </td>
        </tr>
      )}
    </Fragment>
  );
}

function diff(a: number | null, b: number | null, fmt: (x: number) => string): string {
  if (a === null || b === null) return "—";
  const d = a - b;
  return d === 0 ? "持平" : `${d > 0 ? "+" : "−"}${fmt(Math.abs(d))}`;
}

function HoldoutCard({ h, permille }: { h: EvoHoldout; permille: number }) {
  const few = h.main.closed < FEW || h.held.closed < FEW;
  const rows: [string, string, (s: EvoStats) => string, string][] = [
    ["任务", "tasks", (s) => String(s.tasks), String(h.main.tasks - h.held.tasks)],
    ["已结束", "closed", (s) => String(s.closed), "—"],
    ["做成率", "done-rate", (s) => pct(s.done_rate), diff(h.main.done_rate, h.held.done_rate, (x) => `${Math.round(x * 100)} 个百分点`)],
    ["平均花费", "avg-spent", (s) => money(s.avg_spent_usd_milli), diff(h.main.avg_spent_usd_milli, h.held.avg_spent_usd_milli, usd)],
    ["平均用时", "avg-wall", (s) => mins(s.avg_wall_s), diff(h.main.avg_wall_s, h.held.avg_wall_s, (x) => mins(x))],
  ];
  return (
    <section className="ev-hold" data-ev-holdout={`${h.slot}:${h.holdout}`}>
      <h4>
        {SLOT_WORD[h.slot] ?? h.slot}：<span className="k-mono">{h.active}</span> 对照 <span className="k-mono">{h.holdout}</span>
        <span className="t2">{h.dossier ? ` · 集成记录 ${h.dossier}` : ""} · {h.live ? `此刻按 ${permille / 10}% 分给上一版` : "已撤下（只剩历史读数）"}</span>
      </h4>
      <table className="mini" aria-label={`${SLOT_WORD[h.slot] ?? h.slot} 的 Holdout 对照`}>
        <thead><tr><th>指标</th><th className="r">采纳的方案</th><th className="r">Holdout（上一版）</th><th className="r">差值</th></tr></thead>
        <tbody>
          {rows.map(([w, k, f, d]) => <tr key={k} data-ev-metric={k}><td>{w}</td><td className="r k-mono">{f(h.main)}</td><td className="r k-mono">{f(h.held)}</td><td className="r k-mono">{k === "tasks" ? "—" : d}</td></tr>)}
        </tbody>
      </table>
      {few && <p className="ev-few" data-ev-few>样本少：两臂各要有 {FEW} 个以上已结束的任务再看差值，现在是 {h.main.closed} 与 {h.held.closed}。</p>}
      {h.retire_signal && <p className="t2">该撤下的信号：<Plain text={h.retire_signal} /></p>}
      {h.control_arm && <p className="t2">对照臂：<Plain text={h.control_arm} /></p>}
    </section>
  );
}

export function Evolution() {
  const { doc, error } = useEvolution();
  if (error && !doc) return <p className="error">读不到演进读数：<Plain text={error} /></p>;
  if (!doc) return <p className="muted">读取中…</p>;
  const cur = doc.current;
  const slots = Object.keys(cur.fires).length;
  const inUse = Object.values(cur.fires).reduce((a, x) => a + x.length, 0);
  const holds = doc.holdout.filter((h) => h.live).length;
  const live = doc.versions.find((v) => v.current);
  const byDossier = new Map(doc.dossiers.map((d) => [d.dossier, d]));
  const tasksAt = (jie: number) => doc.versions.filter((v) => v.jie === jie).reduce((a, v) => a + v.tasks, 0);
  const pending = doc.dossiers.filter((d) => !d.verdict && (d.status === "readings_ready" || d.status === "placed"));
  const t = doc.outcomes;

  return (
    <div className="evolution" data-page="evolution">
      <Mast title={<>能力配置 <span className="ev-ver" data-ev-version>v{cur.jie}</span></>}
        dek="每集成一个外部方案，先过内核不变量测试，再与基线、外部方案移植分别对照，优于两者才采纳，版本号加一。这一页只读：回滚与评审由你决定。" />
      {pending.length > 0 && (
        <p className="ev-ask" data-ev-pending>{pending.map((d) => `集成记录 ${d.dossier}「${d.title}」${STATUS[d.status].word}`).join("；")}。</p>
      )}

      <section className="rd-tiles" aria-label="指标">
        <Tile label="当前版本" value={`v${cur.jie}`} sub={`${short(cur.digest)} · ${slots} 个模块槽、${inUse} 个模块在用、${holds} 处 Holdout 对照`} data="ev-version" />
        <Tile label="集成记录" value={t.decided} sub={`已评审 · 待评审 ${t.pending} · 已回滚 ${t.reverted}`} data="ev-decided" />
        <Tile label="Holdout 比例" value={`${cur.holdout_permille / 10}%`} sub="采纳新方案后，按任务编号把这一份留给上一版，持续对照" data="ev-permille" />
        <Tile label="本版本的任务" value={live?.tasks ?? 0} sub={live ? `做成率 ${pct(live.done_rate)} · 进行中 ${live.open}` : "这一版下还没有开过任务"} data="ev-live-tasks" />
      </section>

      <section className="rd-sec">
        <h3>版本历史 <span className="t2">只追加，回滚也记一行；任务按开始时锁定的版本归属</span></h3>
        <div className="rd-tbl">
          <table className="mini wide" data-ev-history>
            <thead><tr><th>版本</th><th>变化</th><th>集成记录</th><th>结论</th><th className="r">内核改动</th><th className="r">在这一版开始的任务</th></tr></thead>
            <tbody>
              {doc.history.map((h, i) => {
                const d = h.dossier ? byDossier.get(h.dossier) : undefined;
                return (
                  <tr key={i} data-ev-jie={h.jie} className={h.reverts ? "ev-revert" : undefined}>
                    <td className="k-mono">v{h.jie}</td>
                    <td><Plain text={h.change} />{h.reverts ? <span className="t2"> · 回滚集成记录 {h.reverts}</span> : h.replaces ? <span className="t2"> · 替换 <span className="k-mono">{h.replaces}</span></span> : null}</td>
                    <td className="k-mono">{h.dossier ?? h.reverts ?? "—"}</td>
                    <td>{h.reverts ? "回滚" : d?.verdict ? OUTCOME_WORD[d.verdict.outcome] : h.jie === 1 ? "等价（零差核对）" : "—"}</td>
                    <td className="r k-mono">{d?.kernel_lines_changed !== undefined && d.kernel_lines_changed !== null ? `${d.kernel_lines_changed} 行` : h.jie === 1 ? "0 行" : "—"}</td>
                    <td className="r k-mono">{tasksAt(h.jie)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {doc.revisions.length > 0 && (
          <>
            <p className="t2">模块修订（不改版本号）：</p>
            <ul className="ev-rev" data-ev-revisions>{doc.revisions.map((r) => <li key={r.fire}><span className="k-mono">{r.fire}</span>{r.from ? <> ← <span className="k-mono">{r.from}</span></> : " 新增"}：<Plain text={r.change} /></li>)}</ul>
          </>
        )}
      </section>

      <div className="rd-grid">
        <HBars title="集成记录的结论" data="ev-outcomes" note={`已评审 ${t.decided} 份`} empty="还没有评审过的集成记录。"
          rows={t.decided === 0 ? [] : (Object.keys(OUTCOME_WORD) as EvoOutcome[]).map((k) => ({ key: k, label: OUTCOME_WORD[k], value: t[k], text: `${t[k]} 份`, title: OUTCOME_NOTE[k] }))} />
        <section className="ev-legend" aria-label="四种结论">
          <h4>四种结论</h4>
          <dl>{(Object.keys(OUTCOME_WORD) as EvoOutcome[]).map((k) => <Fragment key={k}><dt>{OUTCOME_WORD[k]}</dt><dd>{OUTCOME_NOTE[k]}</dd></Fragment>)}</dl>
        </section>
      </div>

      <section className="rd-sec">
        <h3>集成记录 <span className="t2">{STEPS.join(" → ")}；点方案名看对照读数</span></h3>
        {doc.dossiers.length === 0 ? <p className="muted">还没有集成记录。</p> : (
          <div className="rd-tbl">
            <table className="mini wide" data-ev-dossiers>
              <thead><tr><th>编号</th><th>方案</th><th>流程</th><th>状态</th><th>结论</th><th>评审</th><th className="r">内核改动</th></tr></thead>
              <tbody>{doc.dossiers.map((d) => <DossierRow key={d.dossier} d={d} />)}</tbody>
            </table>
          </div>
        )}
      </section>

      <section className="rd-sec">
        <h3>Holdout 对照 <span className="t2">任务按开始时锁定的版本分臂；差值是“采纳的方案 − 上一版”</span></h3>
        <p className="t2">告警门槛以集成记录预登记的读数为准；这里给的是两臂的通用读数，只作观察。系统不会自动回滚。</p>
        {doc.holdout.length === 0 ? <p className="muted">现在没有 Holdout 对照。</p> : doc.holdout.map((h) => <HoldoutCard key={`${h.slot}:${h.holdout}:${h.active}`} h={h} permille={cur.holdout_permille} />)}
      </section>

      <section className="rd-sec">
        <h3>各版本下开始的任务 <span className="t2">同一版本号下改过模块（修订）会有不止一个配置摘要</span></h3>
        <div className="rd-tbl">
          <table className="mini wide" data-ev-versions>
            <thead><tr><th>版本</th><th>配置摘要</th><th className="r">任务</th><th className="r">进行中</th><th className="r">做成率</th><th className="r">平均花费</th><th className="r">平均用时</th></tr></thead>
            <tbody>
              {doc.versions.map((v) => (
                <tr key={`${v.jie}:${v.digest ?? "-"}:${v.repinned ? 1 : 0}`} data-ev-digest={v.digest ?? "none"}>
                  <td className="k-mono">v{v.jie}{v.current ? <span className="t2"> · 当前</span> : null}{v.repinned ? <span className="t2"> · 人工改回</span> : null}</td>
                  <td className="k-mono" title={v.digest ?? undefined}>{v.digest ? short(v.digest) : "开始时没有记录（焚决之前）"}</td>
                  <td className="r k-mono">{v.tasks}</td><td className="r k-mono">{v.open}</td><td className="r k-mono">{pct(v.done_rate)}</td>
                  <td className="r k-mono">{money(v.avg_spent_usd_milli)}</td><td className="r k-mono">{mins(v.avg_wall_s)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
