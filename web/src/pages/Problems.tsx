// 题库（工作台设计 §1 模块二）：题目列表（GET /v1/problems）加筛选与搜索。筛选条件都在 URL 里，只在本机生效。
import { useEffect, useState } from "react";
import type { ProblemItem, ProblemsView, Terminal } from "../api/types";
import { useServices } from "../app/context";
import { hrefOf, navigate, NO_FILTER, type BankFilter, type Route } from "../app/router";
import { Search } from "lucide-react";
import { terminalWord } from "../model/levels";
import { Empty, Mark, Mast, btnClass } from "../kit";
import { RUN_MARK, TERMINAL_MARK } from "../ui/marks";
import { usd } from "../model/text";
import { CriterionBadge } from "../ui/criterion";
import { StationCell } from "../ui/StationStrip";
import { stationsOf } from "../model/stations";
import { Plain, Text } from "../ui/registers";

export function Link({ to, children, className, onClick, ...data }: { to: Route; children: React.ReactNode; className?: string; onClick?: () => void } & { [k: `data-${string}`]: string }) {
  return <a {...data} className={className} href={hrefOf(to)} onClick={(e) => { onClick?.(); if (e.metaKey || e.ctrlKey || e.shiftKey) return; e.preventDefault(); navigate(to); }}>{children}</a>;
}

/** 读一次题目列表；every 给出时按毫秒轮询（页面不可见时跳过）。 */
export function useProblems(every?: number): { view: ProblemsView | null; error: string | null } {
  const { api } = useServices();
  const [view, setView] = useState<ProblemsView | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    const load = () => api.problems().then((v) => { if (live) { setView(v); setError(null); } }, (e: Error) => { if (live) setError(e.message); });
    void load();
    if (!every) return () => { live = false; };
    const t = setInterval(() => { if (globalThis.document?.visibilityState !== "hidden") void load(); }, every);
    return () => { live = false; clearInterval(t); };
  }, [api, every]);
  return { view, error };
}


/** 题库筛选：题名或 id 含搜索词（不分大小写）、终态、Goal 判官。纯排版，不改任何派生量。 */
export function filterBank(items: ProblemItem[], f: BankFilter): ProblemItem[] {
  const q = f.q.trim().toLowerCase();
  return items.filter((p) =>
    (!q || p.id.toLowerCase().includes(q) || p.title.value.toLowerCase().includes(q)) &&
    (!f.terminal || (p.terminal ?? "running") === f.terminal) &&
    (!f.judge || p.terminal_badge.judge_id === f.judge));
}

const TABS: { t: Terminal | "running" | ""; word: string }[] = [
  { t: "", word: "全部" }, { t: "running", word: "运行中" }, { t: "solved", word: "已解决" }, { t: "accepted", word: "已验收" }, { t: "delivered", word: "已交付" }, { t: "unsolved", word: "未解决" },
];

export function Problems({ filter = NO_FILTER }: { filter?: BankFilter }) {
  const { view, error } = useProblems();
  const [q, setQ] = useState(filter.q);
  useEffect(() => setQ(filter.q), [filter.q]);
  if (error) return <p className="error">读不到任务列表：<Plain text={error} /></p>;
  if (!view) return <p className="muted">读取中…</p>;
  const set = (patch: Partial<BankFilter>) => navigate({ page: "problems", ...filter, ...patch }, true);
  const judges = [...new Set(view.items.map((p) => p.terminal_badge.judge_id))].sort();
  const list = filterBank(view.items, filter);
  const count = (t: string) => (t === "" ? view.items.length : view.items.filter((p) => (p.terminal ?? "running") === t).length);
  const c = (t: string) => count(t);
  return (
    <div className="problems" data-page="bank">
      <Mast cap="任务库" title={`${view.items.length} 个任务`}
        dek={`运行中 ${c("running")} · 已解决 ${c("solved")} · 已验收 ${c("accepted")} · 已交付（未经判定） ${c("delivered")} · 未解决 ${c("unsolved")}。每一行都可以克隆进向导，改几处再开。`} />
      <div className="ttabs" role="tablist" aria-label="按终态">
        {TABS.map(({ t, word }) => (
          <button key={word} type="button" role="tab" aria-selected={filter.terminal === t} data-tab={t || "all"} onClick={() => set({ terminal: t })}>
            {word} <span className="num">{count(t)}</span>
          </button>
        ))}
      </div>
      <form className="fl" role="search" onSubmit={(e) => { e.preventDefault(); set({ q }); }}>
        <label className="under"><span className="sr-only">搜索</span><Search aria-hidden="true" />
          <input type="search" value={q} placeholder="按任务名或编号搜索" data-field="q" onChange={(e) => setQ(e.target.value)} onBlur={() => set({ q })} />
        </label>
        <label className="sel-u">判定器
          <select value={filter.judge} data-field="judge" onChange={(e) => set({ judge: e.target.value })}>
            <option value="">全部</option>
            {judges.map((j) => <option key={j} value={j}>{j}</option>)}
          </select>
        </label>
        <span className="grow" />
        <span className="t2">显示 {list.length} / {view.items.length}</span>
      </form>
      {list.length === 0 ? (
        <Empty title={view.items.length ? "没有符合筛选的任务" : "还没有任务"} action={view.items.length ? undefined : <Link to={{ page: "new" }} className={btnClass("line", "sm")}>新建任务</Link>}>
          {view.items.length ? "换个关键词，或者回到“全部”。" : "新建一个，或者导入一批。"}
        </Empty>
      ) : (
        <div className="table-scroll">
          <table className="bank tasks">
            <thead><tr><th aria-label="状态" /><th>编号</th><th>任务</th><th>判定器</th><th>画像</th><th className="r">花费 / 上限</th><th>站位</th><th className="r">开于 seq</th><th aria-label="操作" /></tr></thead>
            <tbody>
              {list.map((p) => {
                const m = p.terminal ? TERMINAL_MARK[p.terminal] : RUN_MARK;
                return (
                  <tr key={p.id} data-problem={p.id}>
                    <td data-terminal={p.terminal ?? "running"}><Mark ch={m.ch} tone={m.tone} label={terminalWord(p.terminal)} /></td>
                    <td className="k-mono ink3"><Plain text={p.id} /></td>
                    <td className="title"><Link to={{ page: "problem", pid: p.id, asOf: null, node: null }}><Text t={p.title} block={false} /></Link></td>
                    <td><CriterionBadge badge={p.terminal_badge} /></td>
                    <td className="t2">{p.profile.info} · {p.profile.judge} · {p.profile.reversibility}</td>
                    <td className="r k-mono">{usd(p.spent_usd_milli)}<span className="ink3"> / {p.cap_usd_milli === null ? "—" : usd(p.cap_usd_milli)}</span></td>
                    <td><StationCell st={stationsOf({ closed: p.closed, active: p.active.map((a) => a.kind), todo: p.human_todo })} /></td>
                    <td className="r k-mono ink3">{p.opened_seq}</td>
                    <td className="r"><Link to={{ page: "new", advanced: true, from: p.id }} className={btnClass("bare", "sm")} data-action="clone">克隆</Link></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
