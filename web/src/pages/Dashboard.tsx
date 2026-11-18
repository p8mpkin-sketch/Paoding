// 今日（视觉重做第二期；工作台设计 §1 模块一）：标题写成结论句，四格读数，等你处理、运行中、近七日、最近完成。
// 全部读自 GET /v1/problems（每 5 秒轮询）。“阶段”不由前端推断：运行中一行列出在途会话的种类（异议 web-workbench 第 4 条）。
import { useState } from "react";
import type { ProblemItem, ProblemsView, Terminal } from "../api/types";
import { countUsage } from "../app/usage";
import { dailySeries, leaseKinds, minutes, ratio, recentOf, runningOf, solvedToday, terminalCounts, type DayBucket } from "../model/dashboard";
import { LEVEL_GLYPH, terminalWord } from "../model/levels";
import { usd } from "../model/text";
import { Empty, Mark, Mast, Meter, Quan, SectionHead, btnClass } from "../kit";
import { TERMINAL_MARK } from "../ui/marks";
import { CriterionBadge, Glyph } from "../ui/criterion";
import { Plain, Text } from "../ui/registers";
import { Link, useProblems } from "./Problems";

export const DASHBOARD_POLL_MS = 5000;

const CN = "零一二三四五六七八九十";
/** 十以内写汉字（标题是一句话），以上写数字。 */
const cn = (n: number) => (n <= 10 ? CN[n] : String(n));

const when = (ms: number, now: number) => {
  const d = new Date(ms);
  const sameDay = new Date(now).toDateString() === d.toDateString();
  const hm = d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
  return sameDay ? `今天 ${hm}` : `${d.getMonth() + 1}-${d.getDate()} ${hm}`;
};
const dateLine = (now: number) => {
  const d = new Date(now);
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日 · 星期${"日一二三四五六"[d.getDay()]}`;
};

/** now 由外层注入（app/clock），视图层不读本机时钟。 */
export function Dashboard({ now }: { now: number }) {
  const { view, error } = useProblems(DASHBOARD_POLL_MS);
  if (!view) return <p className={error ? "error" : "muted"}>{error ? <>读不到任务列表：<Plain text={error} /></> : "读取中…"}</p>;
  return <DashboardView view={view} now={now} error={error} />;
}

function DashboardView({ view, now, error }: { view: ProblemsView; now: number; error: string | null }) {
  const running = runningOf(view.items);
  const waiting = running.filter((p) => p.human_todo > 0);
  const asks = waiting.reduce((a, p) => a + p.human_todo, 0);
  const sessions = running.reduce((a, p) => a + p.active.length, 0);
  const today = solvedToday(view.items, now);
  const tight = running.filter((p) => p.cap_usd_milli && p.spent_usd_milli >= p.cap_usd_milli * 0.8);
  const t = view.totals;

  if (view.items.length === 0) return <FirstRun />;

  const title = asks > 0
    ? <><span className="today-n">{cn(asks)}<Quan style={{ left: -12, top: -8, width: 58, height: 60 }} rot={-8} /></span>件事等你拍板</>
    : running.length > 0 ? <>{cn(running.length)}个任务在跑，没有事等你</> : <>没有在跑的任务</>;
  return (
    <div className="today" data-page="home">
      <Mast
        vol={["卷一", "今日"]}
        cap={dateLine(now)}
        title={title}
        dek={<>{running.length} 个任务在运行，今天解决了 {today} 个；累计花费 {usd(t.spent_usd_milli)}{t.cost_per_solve_usd_milli !== null ? `，平均每解 ${usd(t.cost_per_solve_usd_milli)}` : ""}。</>}
        zhupi={tight.length > 0 ? `${cn(tight.length)}件预算将尽` : undefined}
      />
      {error && <p className="error">刷新失败，显示的是上一次读到的：<Plain text={error} /></p>}

      <div className="ledger" aria-label="今日读数">
        <Cell label="运行中" value={running.length} sub={`${sessions} 个会话`} />
        <Cell label="等你处理" value={asks} sub={`涉及 ${waiting.length} 个任务`} hot={asks > 0} />
        <Cell label="今日解决" value={today} sub={`共 ${t.problems} 个任务，已解 ${t.solved}`} />
        <Cell label="累计花费" value={usd(t.spent_usd_milli)} sub={t.cost_per_solve_usd_milli === null ? "还没有解决的任务" : `每解 ${usd(t.cost_per_solve_usd_milli)}`} />
      </div>

      <div className="today-cols">
        <div className="today-main">
          <section className="today-sec" data-waiting={waiting.length > 0 ? "" : undefined} aria-labelledby="h-wait">
            <SectionHead id="h-wait" title="等你处理" note="按任务" right={<Link to={{ page: "inbox" }} className="k-link">全部待办</Link>} />
            {waiting.length === 0 ? <p className="muted pad">没有等你处理的事。任务需要审批、验收或裁决时会出现在这里。</p> : (
              <ol className="asks">
                {waiting.map((p, i) => (
                  <li key={p.id} className="ask-row">
                    <span className="ix">{String(i + 1).padStart(2, "0")}</span>
                    <Mark ch="待" tone="dai" />
                    <div className="grow">
                      <div className="ell"><Text t={p.title} block={false} /></div>
                      <div className="t2">待人处理 {p.human_todo} 项 · <span className="k-mono">{p.id}</span></div>
                    </div>
                    <Link to={{ page: "problem", pid: p.id, asOf: null, node: null }} className={btnClass(i === 0 ? "zhu" : "line", "sm")}>去处理</Link>
                  </li>
                ))}
              </ol>
            )}
          </section>

          <section className="today-sec dash-running" aria-labelledby="h-running">
            <SectionHead id="h-running" title="运行中" note="实时" right={<span className="k-sh-note">会话 · 目标结论 · 花费 · 用时</span>} />
            {running.length === 0 ? <p className="muted pad">没有运行中的任务。</p> : running.map((p) => <RunningRow key={p.id} p={p} />)}
          </section>
        </div>

        <aside className="today-side">
          <Stats view={view} now={now} />
          <Recent items={view.items} now={now} />
        </aside>
      </div>
    </div>
  );
}

function Cell({ label, value, sub, hot }: { label: string; value: number | string; sub: string; hot?: boolean }) {
  return (
    <div className="cell">
      <div className="k-cap">{label}</div>
      <div className={`big num${hot ? " hot" : ""}`}>{value}</div>
      <div className="t2">{sub}</div>
    </div>
  );
}

function RunningRow({ p }: { p: ProblemItem }) {
  const kinds = leaseKinds(p);
  const cap = p.cap_usd_milli;
  const hot = !!cap && p.spent_usd_milli >= cap * 0.8;
  return (
    <article className="run-card run-row" data-problem={p.id} onClick={() => countUsage("dashboard")}>
      <div className="grow">
        <div className="row">
          <span className={`pulse${p.human_todo > 0 ? " hot" : ""}`} aria-hidden="true" />
          <Link to={{ page: "problem", pid: p.id, asOf: null, node: null }} className="run-title"><Text t={p.title} block={false} /></Link>
          {p.human_todo > 0 && <span className="k-tag hot" data-human-todo>待人 {p.human_todo}</span>}
        </div>
        <div className="t2 leases" data-active>
          {kinds.length ? kinds.map((k, i) => <span key={k.kind} data-lease-kind={k.kind}>{i > 0 && " · "}<b>{k.kind}</b>{k.n > 1 ? ` ×${k.n}` : ""}</span>) : "无在途会话"}
        </div>
        <div className="lvl" data-goal-level={p.goal_level ?? "none"}>
          {p.goal_level ? <span className={`badge level level-${p.goal_level}`}><Glyph g={LEVEL_GLYPH[p.goal_level]} />{p.goal_level}</span> : <span className="muted">—</span>}
          <CriterionBadge badge={p.terminal_badge} />
        </div>
      </div>
      <div className="spend">
        <div className="row between k-mono"><span>{usd(p.spent_usd_milli)}</span><span className="ink3">{cap === null ? "无上限" : usd(cap)}</span></div>
        <Meter value={p.spent_usd_milli} cap={cap} hot={hot} marks={[0.5, 1]} label="花费 / 上限" />
      </div>
      <div className="wall k-mono">{minutes(p.wall.elapsed_s)}<span className="ink3"> / {minutes(p.wall.cap_s)}</span></div>
    </article>
  );
}

function Recent({ items, now }: { items: ProblemItem[]; now: number }) {
  const [f, setF] = useState<Terminal | null>(null);
  const counts = terminalCounts(items);
  const list = recentOf(items, f).slice(0, 12);
  return (
    <section className="today-sec dash-recent" aria-labelledby="h-recent">
      <SectionHead id="h-recent" title="最近完成" right={<Link to={{ page: "problems" }} className="k-link">任务库</Link>} />
      <div className="seg" role="group" aria-label="按终态">
        <button type="button" aria-pressed={f === null} onClick={() => setF(null)}>全部 {counts.solved + counts.accepted + counts.unsolved}</button>
        {(["solved", "accepted", "unsolved"] as const).map((t) => (
          <button key={t} type="button" aria-pressed={f === t} data-filter={t} onClick={() => setF(t)}>{TERMINAL_MARK[t].ch} {counts[t]}<span className="sr-only">（{terminalWord(t)}）</span></button>
        ))}
      </div>
      {list.length === 0 ? <p className="muted pad">还没有完成的任务。</p> : (
        <table className="recent">
          <caption className="sr-only">最近完成的任务</caption>
          <colgroup><col style={{ width: 30 }} /><col /><col style={{ width: 70 }} /><col style={{ width: 86 }} /></colgroup>
          <tbody>
            {list.map((p) => {
              const m = TERMINAL_MARK[p.terminal ?? "unsolved"];
              return (
                <tr key={p.id} data-problem={p.id} data-terminal={p.terminal ?? "running"}>
                  <td className="m"><Mark ch={m.ch} tone={m.tone} label={terminalWord(p.terminal)} /></td>
                  <td className="ell-cell"><Link to={{ page: "problem", pid: p.id, asOf: null, node: null }}><Text t={p.title} block={false} /></Link></td>
                  <td className="r k-mono">{usd(p.spent_usd_milli)}</td>
                  <td className="r t2 nowrap">{p.closed_ts !== null ? when(p.closed_ts, now) : `seq ${p.closed_seq}`}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}

function Stats({ view, now }: { view: ProblemsView; now: number }) {
  const series = dailySeries(view.items, now);
  const closed = series.reduce((a, b) => a + b.closed, 0);
  const solved = series.reduce((a, b) => a + b.solved, 0);
  return (
    <section className="today-sec dash-stats" aria-labelledby="h-stats">
      <SectionHead id="h-stats" title="近七日" right={closed > 0 ? <span className="seven"><b className="num">{Math.round((solved * 100) / closed)}%</b> 解决率</span> : undefined} />
      <Trend series={series} />
    </section>
  );
}

const dayLabel = (ms: number) => { const d = new Date(ms); return `${d.getMonth() + 1}-${d.getDate()}`; };
const pctText = (b: DayBucket) => { const r = ratio(b); return r === null ? "—" : `${Math.round(r * 100)}%`; };

/** 近 7 日：实心是当天解决的，斜线是关了但没解决的；柱下是成功率。另附表格视图。 */
export function Trend({ series }: { series: DayBucket[] }) {
  const [table, setTable] = useState(false);
  const max = Math.max(1, ...series.map((b) => b.closed));
  const W = 320, H = 120, gap = 10, bw = (W - gap * (series.length - 1)) / series.length;
  return (
    <figure className="trend" data-trend>
      <figcaption>
        <span className="legend"><i className="sw solid" />解决<i className="sw hatch" />未解决</span>
        <button type="button" className="btn-small" aria-pressed={table} onClick={() => setTable(!table)}>表格</button>
      </figcaption>
      {series.every((b) => b.closed === 0) && !table ? <p className="muted" data-trend-empty>近 7 日没有完成的任务。完成后这里按天画出解决与未解决。</p> : table ? (
        <table className="mini wide" data-trend-table>
          <thead><tr><th>日期</th><th>完成</th><th>解决</th><th>成功率</th></tr></thead>
          <tbody>{series.map((b) => <tr key={b.day}><td>{dayLabel(b.day)}</td><td>{b.closed}</td><td>{b.solved}</td><td>{pctText(b)}</td></tr>)}</tbody>
        </table>
      ) : (
        <svg viewBox={`0 0 ${W} ${H + 34}`} width="100%" role="img" aria-label={series.map((b) => `${dayLabel(b.day)} 完成 ${b.closed}，成功率 ${pctText(b)}`).join("；")}>
          <defs>
            <pattern id="trend-hatch" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="4" className="t-hatch" /></pattern>
          </defs>
          <line x1={0} y1={H} x2={W} y2={H} className="t-axis" />
          {series.map((b, i) => {
            const hs = (b.solved / max) * (H - 16);
            const hu = ((b.closed - b.solved) / max) * (H - 16);
            const x = i * (bw + gap);
            return (
              <g key={b.day} data-day={dayLabel(b.day)}>
                <title>{`${dayLabel(b.day)}：完成 ${b.closed}，解决 ${b.solved}，成功率 ${pctText(b)}`}</title>
                <rect x={x} y={0} width={bw} height={H} className="t-hit" />
                {b.solved > 0 && <rect x={x} y={H - hs} width={bw} height={hs} className="t-mark" />}
                {b.closed > b.solved && <rect x={x + 0.5} y={H - hs - hu - 2} width={bw - 1} height={hu} fill="url(#trend-hatch)" className="t-un" />}
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

/** 第一次打开、还没有任何任务时：空状态即教程。 */
function FirstRun() {
  return (
    <div className="today first-run" data-page="home">
      <Mast vol={["卷一", "今日"]} cap="开始" title="四步上手" dek="交给庖丁一个任务，它会沿着事实的纹理拆开、尝试、验证；需要你拍板的时候，会在“待办”里找你。" />
      <ol className="steps4">
        <li><span className="no">一</span><div className="grow"><b>连上服务</b><p className="t2">左下角配置人的令牌；没有令牌时整站只读。</p></div></li>
        <li><span className="no hot">二</span><div className="grow"><b>建第一个任务</b><p className="t2">说清楚要达成什么、怎样算完成，约两分钟。可以从模板开始。</p></div><Link to={{ page: "new" }} className={btnClass("ink", "sm")}>新建任务</Link></li>
        <li><span className="no">三</span><div className="grow"><b>看它工作，必要时指点</b><p className="t2">在任务的工作区里写一句指导，之后的每一步都会参考。</p></div></li>
        <li><span className="no">四</span><div className="grow"><b>已经有一批任务？</b><p className="t2">导入 CSV 或 JSON，字段自动对应。</p></div><Link to={{ page: "import" }} className={btnClass("line", "sm")}>导入任务集</Link></li>
      </ol>
      <Empty title="随时按 ⌘K">搜索任何任务、页面或操作。</Empty>
    </div>
  );
}
