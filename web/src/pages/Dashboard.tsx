// 总览（工作台设计 §1 模块一、线框 f1）：进行中、最近完成、全局统计、快捷入口。
// 全部读自 GET /v1/problems（每 5 秒轮询）。“阶段”不由前端推断：卡片列出在途租约的种类（异议 web-workbench 第 4 条）。
import { useState } from "react";
import type { ProblemItem, ProblemsView, Terminal } from "../api/types";
import { countUsage } from "../app/usage";
import { dailySeries, leaseKinds, minutes, ratio, recentOf, runningOf, solvedToday, terminalCounts, type DayBucket } from "../model/dashboard";
import { LEVEL_GLYPH, TERMINAL_GLYPH, terminalWord } from "../model/levels";
import { usd } from "../model/text";
import { CriterionBadge, Glyph } from "../ui/criterion";
import { Plain, Text } from "../ui/registers";
import { Link, useProblems } from "./Problems";

export const DASHBOARD_POLL_MS = 5000;

const when = (ms: number, now: number) => {
  const d = new Date(ms);
  const sameDay = new Date(now).toDateString() === d.toDateString();
  const hm = d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
  return sameDay ? `今天 ${hm}` : `${d.getMonth() + 1}-${d.getDate()} ${hm}`;
};

/** now 由外层注入（app/clock），视图层不读本机时钟。 */
export function Dashboard({ now }: { now: number }) {
  const { view, error } = useProblems(DASHBOARD_POLL_MS);
  if (!view) return <p className={error ? "error" : "muted"}>{error ? <>读不到题目列表：<Plain text={error} /></> : "读取中…"}</p>;
  return <DashboardView view={view} now={now} error={error} />;
}

function DashboardView({ view, now, error }: { view: ProblemsView; now: number; error: string | null }) {
  const running = runningOf(view.items);
  const waiting = running.filter((p) => p.human_todo > 0);
  return (
    <div className="dashboard" data-page="home">
      <section className="quick" aria-label="快捷入口">
        <Link to={{ page: "new" }} className="btn-link primary">＋ 新建问题</Link>
        <Link to={{ page: "import" }} className="btn-link">导入题集</Link>
        <Link to={{ page: "problems" }} className="btn-link">题库（可克隆）</Link>
        <Link to={{ page: "readings" }} className="btn-link">读数</Link>
        {error && <span className="error">刷新失败，显示的是上一次读到的：<Plain text={error} /></span>}
      </section>
      {waiting.length > 0 && (
        <section className="waiting" data-waiting>
          <h3>等你处理（{waiting.reduce((a, p) => a + p.human_todo, 0)}）</h3>
          <ul>{waiting.map((p) => <li key={p.id}><Link to={{ page: "problem", pid: p.id, asOf: null, node: null }}><Text t={p.title} block={false} /></Link> · 待人处理 {p.human_todo} 项</li>)}</ul>
        </section>
      )}
      <div className="dash-grid">
        <section className="dash-running" aria-labelledby="h-running">
          <h3 id="h-running">进行中（{running.length}）</h3>
          {running.length === 0 ? <p className="muted">没有进行中的题目。</p> : (
            <div className="cards">{running.map((p) => <RunningCard key={p.id} p={p} />)}</div>
          )}
          <Recent items={view.items} now={now} />
        </section>
        <Stats view={view} now={now} />
      </div>
    </div>
  );
}

function RunningCard({ p }: { p: ProblemItem }) {
  const kinds = leaseKinds(p);
  const cap = p.cap_usd_milli;
  const pct = cap ? Math.min(100, (p.spent_usd_milli * 100) / cap) : 0;
  return (
    <article className="run-card" data-problem={p.id} onClick={() => countUsage("dashboard")}>
      <header>
        <Link to={{ page: "problem", pid: p.id, asOf: null, node: null }}><Text t={p.title} block={false} /></Link>
        {p.human_todo > 0 && <span className="badge badge-warn" data-human-todo>待人 {p.human_todo}</span>}
      </header>
      <div className="run-leases" data-active>
        {kinds.length ? kinds.map((k) => <span key={k.kind} className="badge" data-lease-kind={k.kind}>{k.kind}{k.n > 1 ? ` ×${k.n}` : ""}</span>) : <span className="muted">无在途会话</span>}
      </div>
      <div data-goal-level={p.goal_level ?? "none"}>Goal 根结论 {p.goal_level ? <span className={`badge level level-${p.goal_level}`}><Glyph g={LEVEL_GLYPH[p.goal_level]} />{p.goal_level}</span> : "—"} <CriterionBadge badge={p.terminal_badge} /></div>
      <div className="bar slim" role="meter" aria-label="预算" aria-valuemin={0} aria-valuemax={cap ?? 0} aria-valuenow={p.spent_usd_milli}><div className="bar-spent" style={{ width: `${pct}%` }} /></div>
      <p className="muted">{usd(p.spent_usd_milli)} / {cap === null ? "—" : usd(cap)} · 已用 {minutes(p.wall.elapsed_s)} / {minutes(p.wall.cap_s)}</p>
    </article>
  );
}

function Recent({ items, now }: { items: ProblemItem[]; now: number }) {
  const [f, setF] = useState<Terminal | null>(null);
  const counts = terminalCounts(items);
  const list = recentOf(items, f).slice(0, 20);
  return (
    <section className="dash-recent" aria-labelledby="h-recent">
      <h3 id="h-recent">最近完成</h3>
      <div className="seg" role="group" aria-label="按终态">
        <button type="button" aria-pressed={f === null} onClick={() => setF(null)}>全部 {counts.solved + counts.accepted + counts.unsolved}</button>
        {(["solved", "accepted", "unsolved"] as const).map((t) => (
          <button key={t} type="button" aria-pressed={f === t} data-filter={t} onClick={() => setF(t)}><Glyph g={TERMINAL_GLYPH[t]} />{t} {counts[t]}</button>
        ))}
      </div>
      {list.length === 0 ? <p className="muted">还没有关题的题目。</p> : (
        <div className="table-scroll">
          <table className="mini wide">
            <thead><tr><th>题目</th><th>终态</th><th>Goal 判官</th><th>花费</th><th>关题</th></tr></thead>
            <tbody>
              {list.map((p) => (
                <tr key={p.id} data-problem={p.id} data-terminal={p.terminal ?? "running"}>
                  <td><Link to={{ page: "problem", pid: p.id, asOf: null, node: null }}><Text t={p.title} block={false} /></Link></td>
                  <td><Glyph g={TERMINAL_GLYPH[p.terminal ?? "running"]} />{terminalWord(p.terminal)}</td>
                  <td><CriterionBadge badge={p.terminal_badge} /></td>
                  <td>{usd(p.spent_usd_milli)}</td>
                  <td>{p.closed_ts !== null ? when(p.closed_ts, now) : `seq ${p.closed_seq}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Stats({ view, now }: { view: ProblemsView; now: number }) {
  const t = view.totals;
  const series = dailySeries(view.items, now);
  return (
    <aside className="dash-stats" aria-labelledby="h-stats">
      <h3 id="h-stats">全局统计</h3>
      <div className="tiles">
        <div className="tile" data-stat="solved-today"><span className="muted">今日解题</span><b>{solvedToday(view.items, now)}</b></div>
        <div className="tile" data-stat="spent"><span className="muted">累计花费</span><b>{usd(t.spent_usd_milli)}</b></div>
        <div className="tile" data-stat="per-solve"><span className="muted">每解成本</span><b>{t.cost_per_solve_usd_milli === null ? "—" : usd(t.cost_per_solve_usd_milli)}</b></div>
        <div className="tile" data-stat="count"><span className="muted">题目 / 已解</span><b>{t.problems} / {t.solved}</b></div>
      </div>
      <Trend series={series} />
    </aside>
  );
}

const dayLabel = (ms: number) => { const d = new Date(ms); return `${d.getMonth() + 1}-${d.getDate()}`; };
const pctText = (b: DayBucket) => { const r = ratio(b); return r === null ? "—" : `${Math.round(r * 100)}%`; };

/** 近 7 日：柱是每天关题数（一条序列，不用图例），柱下文字是当天 solved 占比；另附表格视图。 */
export function Trend({ series }: { series: DayBucket[] }) {
  const [table, setTable] = useState(false);
  const max = Math.max(1, ...series.map((b) => b.closed));
  const W = 280, H = 110, gap = 6, bw = (W - gap * (series.length - 1)) / series.length;
  return (
    <figure className="trend" data-trend>
      <figcaption>近 7 日关题数与成功率（按关题日，本机时区） <button type="button" className="btn-small" aria-pressed={table} onClick={() => setTable(!table)}>表格</button></figcaption>
      {series.every((b) => b.closed === 0) && <p className="muted" data-trend-empty>近 7 日没有关题。</p>}
      {table ? (
        <table className="mini wide" data-trend-table>
          <thead><tr><th>日期</th><th>关题</th><th>solved</th><th>成功率</th></tr></thead>
          <tbody>{series.map((b) => <tr key={b.day}><td>{dayLabel(b.day)}</td><td>{b.closed}</td><td>{b.solved}</td><td>{pctText(b)}</td></tr>)}</tbody>
        </table>
      ) : (
        <svg viewBox={`0 0 ${W} ${H + 34}`} width="100%" role="img" aria-label={series.map((b) => `${dayLabel(b.day)} 关题 ${b.closed}，成功率 ${pctText(b)}`).join("；")}>
          <line x1={0} y1={H} x2={W} y2={H} className="t-axis" />
          {series.map((b, i) => {
            const h = (b.closed / max) * (H - 14);
            const x = i * (bw + gap);
            return (
              <g key={b.day} data-day={dayLabel(b.day)}>
                <title>{`${dayLabel(b.day)}：关题 ${b.closed}，solved ${b.solved}，成功率 ${pctText(b)}`}</title>
                <rect x={x} y={0} width={bw} height={H} className="t-hit" />
                {b.closed > 0 && <path className="t-mark" d={`M${x},${H} v${-(h - 4)} q0,-4 4,-4 h${bw - 8} q4,0 4,4 v${h - 4} z`} />}
                {b.closed > 0 && <text x={x + bw / 2} y={H - h - 3} textAnchor="middle" className="t-val">{b.closed}</text>}
                <text x={x + bw / 2} y={H + 13} textAnchor="middle" className="t-tick">{dayLabel(b.day)}</text>
                <text x={x + bw / 2} y={H + 27} textAnchor="middle" className="t-tick">{pctText(b)}</text>
              </g>
            );
          })}
        </svg>
      )}
    </figure>
  );
}
