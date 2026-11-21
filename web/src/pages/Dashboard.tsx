// 今日（v6 实时指挥台，docs/design/pages-v6 §2）：标题是唯一焦点；等你处理按种类列出、直达那张卡；
// 正在跑的每个任务写出智能体此刻在做什么（在途会话的“正在做”与最近自述，与任务页“过程”同一来源）；右栏是今天、近七日与最近完成。
// 列表读自 GET /v1/problems（每 5 秒）；待办读 /work，正在做读 /status 与会话活动的摘要；花费读 /budget/series。不推断阶段。
import { useRef, useState } from "react";
import type { ProblemItem, ProblemsView, Terminal } from "../api/types";
import { countUsage } from "../app/usage";
import { dailySeries, dayStart, leaseKinds, minutes, ratio, recentOf, runningOf, solvedToday, spendByDay, spendSince, terminalCounts, type DayBucket } from "../model/dashboard";
import type { HumanWorkItem } from "../api/types";
import { useAgents, useCosts, useTodos, MAX_LIVE, type Agent } from "../ui/live";
import { useRowKeys } from "../ui/keys";
import { VBars } from "../ui/Charts";
import { WHY } from "../ui/Todo";
import { LEASE_WORD } from "../ui/Sessions";
import { tok } from "../model/trace";
import { LEVEL_GLYPH, terminalWord } from "../model/levels";
import { usd } from "../model/text";
import { Empty, Mark, Mast, Meter, SectionHead, btnClass } from "../kit";
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

/** 待办类别的单字印（与待办页同一套）。 */
const WHY_MARK: Record<string, string> = { needs_human: "批", extension: "续", dispute: "裁", closeout: "验", acceptance: "验", stalled: "停", scope_request: "权", delivered: "看", blocked: "补" };

function DashboardView({ view, now, error }: { view: ProblemsView; now: number; error: string | null }) {
  const running = runningOf(view.items);
  const waiting = running.filter((p) => p.human_todo > 0);
  const asks = waiting.reduce((a, p) => a + p.human_todo, 0);
  const sessions = running.reduce((a, p) => a + p.active.length, 0);
  const today = solvedToday(view.items, now);
  const t = view.totals;
  const todos = useTodos(view.items, view.head);
  const agents = useAgents(running);
  const costs = useCosts(view.items, view.head, { series: true });
  const root = useRef<HTMLDivElement>(null);
  useRowKeys(root);

  if (view.items.length === 0) return <FirstRun />;

  const title = asks > 0
    ? <><span className="today-n">{cn(asks)}</span>件事等你拍板</>
    : running.length > 0 ? <>{cn(running.length)}个任务在跑，没有事等你</> : <>没有在跑的任务</>;
  // 导语只说“下一步做什么”，不复述下面已有的数字（阅读质量轮第 1、2 条）
  const dek = asks > 0 ? "按任务列在下面，从第一项开始；处理完的会自动消失。"
    : running.length > 0 ? "任务需要审批、验收或裁决时，会出现在这里。" : "新建一个任务，或从任务库克隆一个。";
  // 待办按种类计数（服务端给的 why）
  const byWhy = new Map<string, number>();
  for (const xs of Object.values(todos)) for (const x of xs) byWhy.set(x.why, (byWhy.get(x.why) ?? 0) + 1);
  const series = Object.values(costs.series).map((x) => x.points);
  const spentToday = spendSince(series, dayStart(now));
  const closedToday = view.items.filter((p) => p.closed && p.closed_ts !== null && dayStart(p.closed_ts) === dayStart(now)).length;
  const days = spendByDay(series, now, 7);
  return (
    <div className="today" data-page="today" ref={root}>
      <Mast cap={dateLine(now)} title={title} dek={dek} />
      {error && <p className="error">刷新失败，显示的是上一次读到的：<Plain text={error} /></p>}

      <div className="today-cols">
        <div className="today-main">
          {waiting.length > 0 && (
            <section className="today-sec today-focus" data-waiting aria-label="等你处理">
              {byWhy.size > 0 && (
                <p className="ask-kinds t2" data-ask-kinds>{[...byWhy].map(([w, n], i) => <span key={w} data-ask-kind={w}>{i > 0 && " · "}{WHY[w] ?? w} <b className="k-mono">{n}</b></span>)}</p>
              )}
              <ol className="asks">
                {waiting.map((p) => {
                  const items: HumanWorkItem[] = todos[p.id] ?? [];
                  return (
                    <li key={p.id} className="ask-row" data-ask={p.id}>
                      <Mark ch={WHY_MARK[items[0]?.why ?? ""] ?? "待"} tone="dai" label="等你处理" />
                      <div className="grow">
                        <div className="ell"><Text t={p.title} block={false} /></div>
                        {items.length > 0 ? (
                          <ul className="ask-items">
                            {items.map((x) => (
                              <li key={`${x.why}:${x.target}`} data-ask-item={`${x.why}:${x.target}`}>
                                <span>{WHY[x.why] ?? x.why}</span> <span className="k-mono t2">{x.target}</span>
                                <Link to={{ page: "problem", pid: p.id, asOf: null, node: x.why === "delivered" || x.why === "blocked" ? null : x.target }} className="k-link" data-krow="">去处理</Link>
                              </li>
                            ))}
                          </ul>
                        ) : <div className="t2">{p.human_todo} 项待处理 · <span className="k-mono">{p.id}</span></div>}
                      </div>
                      <Link to={{ page: "problem", pid: p.id, asOf: null, node: null }} className={btnClass("line", "sm")} data-krow="">去处理</Link>
                    </li>
                  );
                })}
              </ol>
              <div className="today-more"><Link to={{ page: "inbox" }} className="k-link">在待办里逐件看</Link></div>
            </section>
          )}

          <section className="today-sec dash-running" aria-labelledby="h-running">
            <SectionHead id="h-running" title="运行中" right={<span className="k-sh-note">智能体在做什么 · 花费 · 用时{running.length > MAX_LIVE ? ` · 只读前 ${MAX_LIVE} 个的会话` : ""}</span>} />
            {running.length === 0 ? <Empty title="没有运行中的任务" action={<Link to={{ page: "home" }} className={btnClass("line", "sm")}>新建任务</Link>}>任务运行时会列在这里。</Empty> : running.map((p) => <RunningRow key={p.id} p={p} a={agents[p.id]} />)}
          </section>
        </div>

        <aside className="today-side">
          <section className="today-sec" aria-labelledby="h-ledger">
            <SectionHead id="h-ledger" title="今天" />
            <div className="ledger" aria-label="今天的读数">
              <Cell label="今天花费" value={costs.loading ? "…" : usd(spentToday.usd)} sub={costs.loading ? "读取花费…" : `${spentToday.tasks} 个任务有花费${spentToday.untimed > 0 ? ` · 另有 ${usd(spentToday.untimed)} 没有时刻` : ""}`} data="today-spend" />
              <Cell label="今天结束" value={closedToday} sub={`其中判定通过 ${today}`} />
              <Cell label="运行中" value={running.length} sub={`${sessions} 个会话在途`} />
              <Cell label="平均每解" value={t.cost_per_solve_usd_milli === null ? "—" : usd(t.cost_per_solve_usd_milli)} sub={t.cost_per_solve_usd_milli === null ? "还没有解决的任务" : `累计 ${usd(t.spent_usd_milli)} ÷ ${t.solved}`} />
            </div>
          </section>
          <Stats view={view} now={now} />
          <section className="today-sec dash-spend" aria-labelledby="h-spend">
            <VBars title="近七日花费" data="spend7" note={costs.loading ? "读取中…" : `合计 ${usd(days.reduce((a, d) => a + d.usd, 0))}`} empty="近七日没有花费。"
              bars={days.map((d) => ({ key: String(d.day), label: dayLabel(d.day), value: d.usd, text: usd(d.usd), title: `${dayLabel(d.day)} · ${d.tasks} 个任务 · token ${tok(d.tokens)}` }))} />
          </section>
          <Recent items={view.items} now={now} />
        </aside>
      </div>
    </div>
  );
}

function Cell({ label, value, sub, hot, data }: { label: string; value: number | string; sub: string; hot?: boolean; data?: string }) {
  return (
    <div className="cell" data-cell={data ?? label}>
      <div className="k-cap">{label}</div>
      <div className={`big num${hot ? " hot" : ""}`}>{value}</div>
      <div className="t2">{sub}</div>
    </div>
  );
}

function RunningRow({ p, a }: { p: ProblemItem; a?: Agent }) {
  const kinds = leaseKinds(p);
  const cap = p.cap_usd_milli;
  const hot = !!cap && p.spent_usd_milli >= cap * 0.8;
  return (
    <article className="run-card run-row" data-problem={p.id}>
      <div className="grow">
        <div className="row">
          <span className={`pulse${p.human_todo > 0 ? " hot" : ""}`} aria-hidden="true" />
          <Link to={{ page: "problem", pid: p.id, asOf: null, node: null }} className="run-title" onClick={() => countUsage("dashboard")} data-krow=""><Text t={p.title} block={false} /></Link>
          {p.human_todo > 0 && <span className="k-tag hot" data-human-todo>等你处理</span>}
          {hot && <span className="k-tag" data-budget-tight>预算已用八成</span>}
        </div>
        <div className="t2 leases" data-active>
          {kinds.length ? kinds.map((k, i) => <span key={k.kind} data-lease-kind={k.kind}>{i > 0 && " · "}<b>{LEASE_WORD[k.kind] ?? k.kind}</b>{k.n > 1 ? ` ×${k.n}` : ""}</span>) : "无在途会话"}
          {a && (a.turns > 0 || a.calls > 0) && <span className="k-mono" data-agent-counts> · 模型调用 {a.turns} · 工具调用 {a.calls}</span>}
        </div>
        {a && kinds.length > 0 && (
          <div className="run-now" data-agent-now>
            <span className="t2">正在做</span>
            {a.error ? <span className="t2">读不到会话活动</span>
              : a.now ? <span className="run-now-b"><span className="live-dot" aria-hidden="true" /><b className="k-mono">{a.now.tool}</b> <code><Plain text={a.now.gist} /></code></span>
                : <span className="t2">{a.leases.length ? "在想下一步" : "会话正在起来"}</span>}
          </div>
        )}
        {a?.say && <p className="run-say reg reg-narrative" data-register="narrative" data-agent-say><Plain text={a.say.text} /></p>}
        <div className="lvl" data-goal-level={p.goal_level ?? "none"}>
          {p.goal_level ? <span className={`badge level level-${p.goal_level}`}><Glyph g={LEVEL_GLYPH[p.goal_level]} />{p.goal_level}</span> : null}
          <CriterionBadge badge={p.terminal_badge} />
        </div>
      </div>
      <div className="spend">
        <div className="row between k-mono"><span>{usd(p.spent_usd_milli)}</span><span className="ink3">{cap === null ? "无上限" : usd(cap)}</span></div>
        <Meter value={p.spent_usd_milli} cap={cap} hot={hot} marks={[0.5, 1]} label="花费 / 上限" />
      </div>
      <div className="wall num">{minutes(p.wall.elapsed_s)}<span className="ink3"> / {minutes(p.wall.cap_s)}</span></div>
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
      {counts.solved + counts.accepted + counts.delivered + counts.unsolved > 0 && <div className="seg" role="group" aria-label="按终态">
        <button type="button" aria-pressed={f === null} onClick={() => setF(null)}>全部 {counts.solved + counts.accepted + counts.delivered + counts.unsolved}</button>
        {(["solved", "accepted", "delivered", "unsolved"] as const).map((t) => (
          <button key={t} type="button" aria-pressed={f === t} data-filter={t} onClick={() => setF(t)}>{TERMINAL_MARK[t].ch} {counts[t]}<span className="sr-only">（{terminalWord(t)}）</span></button>
        ))}
      </div>}
      {list.length === 0 ? (
        <Empty title={f === null ? "还没有结束的任务" : "这个终态下没有任务"} action={f === null ? undefined : <button type="button" className={btnClass("bare", "sm")} onClick={() => setF(null)}>看全部</button>}>
          {f === null ? "任务关闭后会按时间列在这里，也可以在任务库里按终态筛。" : "换一个终态，或看全部。"}
        </Empty>
      ) : (
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
const pctText = (b: DayBucket) => { const r = ratio(b); return r === null ? "无完成" : `${Math.round(r * 100)}%`; };

/** 近 7 日：实心是当天解决的，斜线是关了但没解决的；柱下是成功率。另附表格视图。 */
export function Trend({ series }: { series: DayBucket[] }) {
  const [table, setTable] = useState(false);
  const max = Math.max(1, ...series.map((b) => b.closed));
  const W = 320, H = 120, gap = 10, bw = (W - gap * (series.length - 1)) / series.length;
  if (series.every((b) => b.closed === 0)) {
    return <p className="t2 trend-empty" data-trend-empty>近 7 日还没有任务结束。任务关闭后，这里按天画出解决与未解决。</p>;
  }
  return (
    <figure className="trend" data-trend>
      <figcaption>
        <span className="legend"><i className="sw solid" />解决<i className="sw hatch" />未解决</span>
        <button type="button" className="btn-small" aria-pressed={table} onClick={() => setTable(!table)}>表格</button>
      </figcaption>
      {table ? (
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
                {b.closed > 0 && <text x={x + bw / 2} y={H + 27} textAnchor="middle" className="t-tick">{pctText(b)}</text>}
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
    <div className="today first-run" data-page="today">
      <Mast cap="开始" title="四步上手" dek="交给庖丁一个任务，它会沿着事实的纹理拆开、尝试、验证；需要你拍板的时候，会在“待办”里找你。" />
      <ol className="steps4">
        <li><span className="no">一</span><div className="grow"><b>连上服务</b><p className="t2">左下角配置人的令牌；没有令牌时整站只读。</p></div></li>
        <li><span className="no hot">二</span><div className="grow"><b>建第一个任务</b><p className="t2">说清楚要达成什么、怎样算完成，约两分钟。可以从模板开始。</p></div><Link to={{ page: "home" }} className={btnClass("ink", "sm")}>新建任务</Link></li>
        <li><span className="no">三</span><div className="grow"><b>看它工作，必要时指点</b><p className="t2">在任务的工作区里写一句指导，之后的每一步都会参考。</p></div></li>
        <li><span className="no">四</span><div className="grow"><b>已经有一批任务？</b><p className="t2">导入 CSV 或 JSON，字段自动对应。</p></div><Link to={{ page: "import" }} className={btnClass("line", "sm")}>导入任务集</Link></li>
      </ol>
      <Empty title="随时按 ⌘K">搜索任何任务、页面或操作。</Empty>
    </div>
  );
}
