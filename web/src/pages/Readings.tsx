// 读数（v6 运营看板，docs/design/pages-v6 §4；HMI 设计 §3.8）。量具只显示，不驱动任何按钮的默认值。
// 数据：/v1/problems（终态、判定来源、花费、用时、服务端算的每解成本与按判定来源分列）、各任务的 /budget（按会话种类、
// 按会话的模型）与 /budget/series（花费随时间，#123）。时间范围只在本机筛；服务端口径的数字照原样排、旁注口径。
// 开放道单独成表（/v1/readings/open，地图 Q35）：交付、反馈、复核读数，不进做成率与每解成本。
// 评测台四臂、归因、折损、切口、校准、留出等还没有读端点：收在一处写“暂不可用”，不编数字。
import { useEffect, useMemo, useRef, useState } from "react";
import type { OpenReadingsView, ProblemItem } from "../api/types";
import { useServices } from "../app/context";
import { navigate } from "../app/router";
import { readUsage } from "../app/usage";
import { Mast } from "../kit";
import { dayStart, doneRate, spendByDay, WALL_BUCKETS, wallHistogram } from "../model/dashboard";
import { terminalWord } from "../model/levels";
import { usd } from "../model/text";
import { tok } from "../model/trace";
import { HBars, SegBars, Tile, VBars } from "../ui/Charts";
import { useCosts } from "../ui/live";
import { Plain } from "../ui/registers";
import { LEASE_WORD } from "../ui/Sessions";
import { Link, useProblems } from "./Problems";

const AUTHORITIES = [["local", "本地判定"], ["external", "外部判定"], ["human", "人工验收"], ["self", "开放道"]] as const;
const UNAVAILABLE = ["评测台四臂与消融结果", "结构归因表", "折损账（割与折）", "切口命中率", "校准曲线（预测账）", "退役距离", "学习曲线"];
const KIND_WORD: Record<string, string> = { ...LEASE_WORD, verify: "复核", recall: "回忆", other: "其他" };
type Range = "7" | "30" | "all";
const RANGE_WORD: Record<Range, string> = { "7": "近 7 天", "30": "近 30 天", all: "全部" };
const dayLabel = (ms: number) => { const d = new Date(ms); return `${d.getMonth() + 1}-${d.getDate()}`; };
const mins = (s: number) => (s < 60 ? `${s} 秒` : `${(s / 60).toFixed(1).replace(/\.0$/, "")} 分`);
const pct = (x: number | null) => (x === null ? "—" : `${Math.round(x * 100)}%`);
const OUT_CATS = [
  { key: "solved", label: "判定通过", cls: "solved" }, { key: "accepted", label: "已验收", cls: "accepted" }, { key: "delivered", label: "已交付", cls: "delivered" },
  { key: "unsolved", label: "没做成", cls: "unsolved" }, { key: "open", label: "进行中", cls: "open" },
];

type SortKey = "id" | "terminal" | "spent" | "verify" | "wall";

/** 开放道（判定来源 self）的读数：没有判官，所以只数交付、人的反馈与复核读数；全部时间、服务端口径。
 * 链头变了才重读。复核读数是另一个会话核出来的参考，不是判定，这里也只是计数。 */
function OpenLane({ head }: { head: number | null }) {
  const { api } = useServices();
  const [r, setR] = useState<OpenReadingsView | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api.openReadings().then((v) => { if (live) { setR(v); setErr(null); } }, (e: Error) => { if (live) setErr(e.message); });
    return () => { live = false; };
  }, [api, head]);
  if (err && !r) return <section className="rd-sec" data-open-readings><h3>开放道</h3><p className="t2">读不到开放道读数：<Plain text={err} /></p></section>;
  if (!r) return null;
  const rv = r.review;
  const reran = rv.reruns.pass + rv.reruns.fail + rv.reruns.not_rerun;
  return (
    <section className="rd-sec" data-open-readings>
      <h3>开放道（服务端口径，全部时间）</h3>
      <p className="t2">没有判定器，也没有标准答案：交付是智能体自己的结论，不进做成率、每解成本与任何对照读数。采纳率只数给了反馈的任务；复核是另起一个会话逐条核对的读数，不是判定。</p>
      <div className="rd-tiles" aria-label="开放道指标">
        <Tile label="开放道任务" value={r.problems} sub={`进行中 ${r.terminals.open} · 已交付 ${r.terminals.delivered} · 没做成 ${r.terminals.unsolved}`} data="open-problems" />
        <Tile label="交付" value={r.deliveries} sub={`完整 ${r.outcomes.answered} · 部分 ${r.outcomes.partial} · 受阻 ${r.outcomes.blocked} · 追问 ${r.follow_ups}`} data="open-deliveries" />
        <Tile label="采纳率" value={pct(r.adoption_rate)} sub={`采纳 ${r.feedback.adopted} · 不采纳 ${r.feedback.rejected} · 没给反馈 ${r.feedback.none}`} data="open-adoption" />
        <Tile label="每次交付花费" value={r.usd_milli_per_delivery === null ? "—" : usd(r.usd_milli_per_delivery)} sub={`开放道合计 ${usd(r.spent_usd_milli)}`} data="open-per-delivery" />
        <Tile label="复核过的交付" value={rv.deliveries} sub={rv.deliveries ? `${rv.claims} 条主张：有据 ${rv.supported} · 引用不符 ${rv.unsupported} · 看不出 ${rv.unclear}` : "还没有复核读数"} data="open-review" />
        <Tile label="自检重跑" value={reran} sub={reran ? `通过 ${rv.reruns.pass} · 不过 ${rv.reruns.fail} · 没能重跑 ${rv.reruns.not_rerun}` : "还没有重跑"} data="open-reruns" />
      </div>
    </section>
  );
}

export function Readings({ now = 0 }: { now?: number }) {
  const { view, error } = useProblems();
  const [range, setRange] = useState<Range>("30");
  const list = view?.items ?? null;
  const costs = useCosts(list, view?.head ?? null);
  const [sort, setSort] = useState<{ k: SortKey; desc: boolean }>({ k: "spent", desc: true });
  const [q, setQ] = useState("");
  const top = useRef<HTMLDivElement>(null);

  const since = range === "all" ? -Infinity : dayStart(now) - (Number(range) - 1) * 86_400_000;
  const items = useMemo(() => (list ?? []).filter((p) => p.opened_ts >= since || (p.closed_ts ?? 0) >= since || !p.closed), [list, since]);

  if (error && !view) return <p className="error">读不到任务列表：<Plain text={error} /></p>;
  if (!view || !list) return <p className="muted">读取中…</p>;
  const totals = view.totals;
  const closed = items.filter((p) => p.closed);
  const spent = items.reduce((a, p) => a + p.spent_usd_milli, 0);
  const seriesOf = (p: ProblemItem) => costs.series[p.id]?.points ?? [];
  const tokens = items.reduce((a, p) => a + (seriesOf(p).at(-1)?.tokens ?? 0), 0);
  const avgWall = closed.length ? Math.round(closed.reduce((a, p) => a + p.wall.elapsed_s, 0) / closed.length) : null;
  const days = spendByDay(items.map(seriesOf), now, range === "all" ? 60 : Number(range));

  // 钱花在哪：按会话种类（/budget 的 by_kind）、按模型（by_lease 的 model）
  const byKind = new Map<string, number>();
  const byModel = new Map<string, number>();
  for (const p of items) {
    const b = costs.budgets[p.id];
    if (!b) continue;
    for (const [k, v] of Object.entries(b.by_kind)) byKind.set(k, (byKind.get(k) ?? 0) + v.usd_milli);
    for (const l of b.by_lease ?? []) { const m = l.model || "未记模型"; byModel.set(m, (byModel.get(m) ?? 0) + l.usd_milli); }
  }
  const roles = [...new Set(Object.values(costs.budgets).flatMap((b) => Object.keys(b.by_kind)))].sort();
  const topTasks = [...items].sort((a, b) => b.spent_usd_milli - a.spent_usd_milli).slice(0, 10).filter((p) => p.spent_usd_milli > 0);
  const hist = wallHistogram(items);
  const outRows = AUTHORITIES.map(([k, word]) => {
    const xs = items.filter((p) => p.authority === k);
    return { key: k, label: word, segs: OUT_CATS.map((c) => ({ ...c, n: c.key === "open" ? xs.filter((p) => !p.closed).length : xs.filter((p) => p.closed && p.terminal === c.key).length })) };
  }).filter((r) => r.segs.some((s) => s.n > 0));

  const needle = q.trim().toLowerCase();
  const val = (p: ProblemItem): number | string => sort.k === "id" ? p.id : sort.k === "terminal" ? terminalWord(p.terminal) : sort.k === "spent" ? p.spent_usd_milli : sort.k === "verify" ? costs.budgets[p.id]?.verify_spent.usd_milli ?? -1 : p.wall.elapsed_s;
  const rows = items.filter((p) => !needle || p.id.toLowerCase().includes(needle) || p.title.value.toLowerCase().includes(needle))
    .sort((a, b) => { const x = val(a), y = val(b); const c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), "zh-CN"); return sort.desc ? -c : c; });
  const th = (k: SortKey, word: string, r = false) => (
    <th className={r ? "r" : undefined} aria-sort={sort.k === k ? (sort.desc ? "descending" : "ascending") : "none"}>
      <button type="button" className="th-sort" data-sort={k} onClick={() => setSort({ k, desc: sort.k === k ? !sort.desc : true })}>{word}{sort.k === k ? (sort.desc ? " ↓" : " ↑") : ""}</button>
    </th>
  );
  const usage = readUsage();
  const toBank = () => navigate({ page: "problems", q: "", terminal: "", judge: "" });

  return (
    <div className="readings rd" data-page="readings" ref={top}>
      <Mast title="读数" dek="任务、花费、结局与用时。只显示，不驱动任何默认值；还没有读端点的量写“暂不可用”。" />
      <div className="rd-bar">
        <div className="tr-seg" role="group" aria-label="时间范围">
          {(["7", "30", "all"] as const).map((r) => <button key={r} type="button" aria-pressed={range === r} data-range={r} onClick={() => setRange(r)}>{RANGE_WORD[r]}</button>)}
        </div>
        <span className="t2">{range === "all" ? "全部任务" : `${RANGE_WORD[range]}开始、结束或仍在跑的任务`} · {items.length} 个{costs.loading ? " · 读取花费…" : ""}{costs.capped ? " · 花费只读最近 200 个任务" : ""}</span>
      </div>

      <section className="rd-tiles" aria-label="指标">
        <Tile label="任务" value={items.length} sub={`在跑 ${items.length - closed.length} · 已结束 ${closed.length}`} onClick={toBank} data="tasks" />
        <Tile label="做成率" value={pct(doneRate(items))} sub="判定通过、验收、交付 ÷ 已结束" data="done-rate" />
        <Tile label="每解成本" value={totals.cost_per_solve_usd_milli === null ? "—" : usd(totals.cost_per_solve_usd_milli)} sub={totals.cost_per_solve_usd_milli === null ? "尚无本地判定通过的任务" : `全部时间：${usd(totals.spent_usd_milli)} ÷ ${totals.solved}（服务端口径）`} data="cost-per-solve" />
        <Tile label="花费" value={usd(spent)} sub={range === "all" ? "全部任务" : "这些任务的累计花费"} data="spent" />
        <Tile label="token" value={tok(tokens)} sub="输入 + 缓存 + 输出（花费序列）" data="tokens" />
        <Tile label="平均用时" value={avgWall === null ? "—" : mins(avgWall)} sub="已结束的任务" data="wall" />
      </section>

      <div className="rd-grid">
        <VBars title="每天花费" data="spend-days" note={`合计 ${usd(days.reduce((a, d) => a + d.usd, 0))}${range === "all" ? " · 只画最近 60 天" : ""}`} empty="这段时间没有花费。"
          bars={days.map((d) => ({ key: String(d.day), label: dayLabel(d.day), value: d.usd, text: usd(d.usd), title: `${dayLabel(d.day)} · ${d.tasks} 个任务 · token ${tok(d.tokens)}` }))} />
        <SegBars title="结局按判定来源" data="outcomes" note="个数" rows={outRows} cats={OUT_CATS} />
        <HBars title="钱花在哪类会话" data="by-kind" empty={costs.loading ? "读取中…" : "还没有花费。"}
          rows={[...byKind].sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ key: k, label: KIND_WORD[k] ?? k, value: v, text: usd(v) }))} />
        <HBars title="钱花在哪个模型" data="by-model" empty={costs.loading ? "读取中…" : "还没有按会话记的花费。"}
          rows={[...byModel].sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ key: k, label: <span className="k-mono">{k}</span>, value: v, text: usd(v), title: `${k}：${usd(v)}` }))} />
        <HBars title="最贵的十个任务" data="top-tasks" empty="还没有花费。"
          rows={topTasks.map((p) => ({ key: p.id, label: <span className="ell">{p.title.value}</span>, sub: <span className="k-mono">{p.id}</span>, value: p.spent_usd_milli, text: usd(p.spent_usd_milli), title: `${p.title.value}：${usd(p.spent_usd_milli)}`, onClick: () => navigate({ page: "problem", pid: p.id, asOf: null, node: null }) }))} />
        <VBars title="用时分布" data="wall-hist" note="已结束的任务个数" empty="还没有结束的任务。"
          bars={WALL_BUCKETS.map((b, i) => ({ key: b.label, label: b.label, value: hist[i], text: `${hist[i]} 个`, title: b.label }))} />
      </div>

      <section className="rd-sec">
        <h3>按判定来源分列（服务端口径，全部时间）</h3>
        <p className="t2">已验收（accepted）只出现在人工验收一行，不并进 solved；成功率与每解成本的分子只取本地判定的 solved。</p>
        <div className="rd-tbl">
        <table className="mini" data-by-authority>
          <thead><tr><th>判定来源</th><th className="r">任务</th><th className="r">进行中</th><th className="r">solved</th><th className="r">accepted</th><th className="r">delivered</th><th className="r">unsolved</th></tr></thead>
          <tbody>
            {AUTHORITIES.map(([k, word]) => {
              const t = totals.by_authority[k];
              if (!t) return null;
              return <tr key={k} data-authority={k}><td>{word}</td><td className="r">{t.problems}</td><td className="r">{t.open}</td><td className="r">{k === "human" ? "—" : t.solved}</td><td className="r">{k === "human" ? t.accepted : "—"}</td><td className="r">{t.delivered ?? 0}</td><td className="r">{t.unsolved}</td></tr>;
            })}
          </tbody>
        </table>
        </div>
      </section>

      <OpenLane head={view.head ?? null} />

      <section className="rd-sec">
        <div className="rd-sec-h">
          <h3>逐任务明细</h3>
          <input type="search" placeholder="搜标题或编号" value={q} onChange={(e) => setQ(e.target.value)} aria-label="搜标题或编号" data-field="rd-q" />
          <span className="t2">{rows.length} 个</span>
        </div>
        <div className="rd-tbl">
          <table className="mini wide" data-rd-detail>
            <thead><tr>{th("id", "任务")}{th("terminal", "终态")}{roles.map((r) => <th key={r} className="r">{KIND_WORD[r] ?? r}</th>)}{th("verify", "验证池", true)}{th("spent", "已花 / 上限", true)}{th("wall", "用时", true)}</tr></thead>
            <tbody>
              {rows.map((p) => {
                const b = costs.budgets[p.id];
                return (
                  <tr key={p.id} data-rd-row={p.id}>
                    <td><Link to={{ page: "problem", pid: p.id, asOf: null, node: null }}><Plain text={p.id} /></Link><span className="t2 rd-title"> <Plain text={p.title.value} /></span></td>
                    <td>{p.closed ? terminalWord(p.terminal) : "进行中"}</td>
                    {roles.map((r) => <td key={r} className="r k-mono">{b?.by_kind[r] ? usd(b.by_kind[r].usd_milli) : "—"}</td>)}
                    <td className="r k-mono">{b ? usd(b.verify_spent.usd_milli) : "—"}</td>
                    <td className="r k-mono">{usd(p.spent_usd_milli)} / {p.cap_usd_milli === null ? "—" : usd(p.cap_usd_milli)}</td>
                    <td className="r k-mono">{mins(p.wall.elapsed_s)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <details className="rd-sec rd-na">
        <summary><h3>暂不可用</h3><span className="t2">{UNAVAILABLE.length} 项还没有读端点</span></summary>
        <ul>{UNAVAILABLE.map((u) => <li key={u}>{u}：暂不可用（还没有对应的读端点）</li>)}</ul>
        <p className="t2">能力配置的版本历史、集成记录与 Holdout 对照在 <Link to={{ page: "evolution" }}>能力配置</Link> 页。</p>
      </details>
      <details className="rd-sec">
        <summary><h3>界面使用读数（本机）</h3></summary>
        <p className="muted">只存在这台机器上，不进任务日志，不发往服务端。用来判断各模块有没有人用。</p>
        {Object.keys(usage).length === 0 ? <p className="muted">还没有读数。</p> : (
          <table className="mini"><tbody>{Object.keys(usage).sort().map((k) => <tr key={k}><td>{k}</td><td>{usage[k]}</td></tr>)}</tbody></table>
        )}
      </details>
    </div>
  );
}
