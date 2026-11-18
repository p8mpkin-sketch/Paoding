// 题库（工作台设计 §1 模块二）：题目列表（GET /v1/problems）加筛选与搜索。筛选条件都在 URL 里，只在本机生效。
import { useEffect, useState } from "react";
import type { ProblemItem, ProblemsView, Terminal } from "../api/types";
import { useServices } from "../app/context";
import { hrefOf, navigate, NO_FILTER, type BankFilter, type Route } from "../app/router";
import { TERMINAL_GLYPH, terminalWord } from "../model/levels";
import { usd } from "../model/text";
import { CriterionBadge, Glyph } from "../ui/criterion";
import { Plain, Text } from "../ui/registers";

export function Link({ to, children, className, ...data }: { to: Route; children: React.ReactNode; className?: string } & { [k: `data-${string}`]: string }) {
  return <a {...data} className={className} href={hrefOf(to)} onClick={(e) => { if (e.metaKey || e.ctrlKey || e.shiftKey) return; e.preventDefault(); navigate(to); }}>{children}</a>;
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

const TERMINALS: (Terminal | "running")[] = ["running", "solved", "accepted", "unsolved"];

/** 题库筛选：题名或 id 含搜索词（不分大小写）、终态、Goal 判官。纯排版，不改任何派生量。 */
export function filterBank(items: ProblemItem[], f: BankFilter): ProblemItem[] {
  const q = f.q.trim().toLowerCase();
  return items.filter((p) =>
    (!q || p.id.toLowerCase().includes(q) || p.title.value.toLowerCase().includes(q)) &&
    (!f.terminal || (p.terminal ?? "running") === f.terminal) &&
    (!f.judge || p.terminal_badge.judge_id === f.judge));
}

export function Problems({ filter = NO_FILTER }: { filter?: BankFilter }) {
  const { view, error } = useProblems();
  const [q, setQ] = useState(filter.q);
  useEffect(() => setQ(filter.q), [filter.q]);
  if (error) return <p className="error">读不到题目列表：<Plain text={error} /></p>;
  if (!view) return <p className="muted">读取中…</p>;
  const set = (patch: Partial<BankFilter>) => navigate({ page: "problems", ...filter, ...patch }, true);
  const judges = [...new Set(view.items.map((p) => p.terminal_badge.judge_id))].sort();
  const list = filterBank(view.items, filter);
  return (
    <div className="problems" data-page="bank">
      <header className="page-head">
        <h2>题库</h2>
        <span><Link to={{ page: "new" }} className="btn-link">＋ 新建问题</Link> <Link to={{ page: "import" }} className="btn-link">导入题集</Link></span>
      </header>
      <form className="filters" role="search" onSubmit={(e) => { e.preventDefault(); set({ q }); }}>
        <label>搜索 <input type="search" value={q} placeholder="题名或 id" data-field="q" onChange={(e) => setQ(e.target.value)} onBlur={() => set({ q })} /></label>
        <label>终态
          <select value={filter.terminal} data-field="terminal" onChange={(e) => set({ terminal: e.target.value })}>
            <option value="">全部</option>
            {TERMINALS.map((t) => <option key={t} value={t}>{TERMINAL_GLYPH[t]} {terminalWord(t === "running" ? null : t)}</option>)}
          </select>
        </label>
        <label>Goal 判官
          <select value={filter.judge} data-field="judge" onChange={(e) => set({ judge: e.target.value })}>
            <option value="">全部</option>
            {judges.map((j) => <option key={j} value={j}>{j}</option>)}
          </select>
        </label>
        <span className="muted">{list.length} / {view.items.length} 题 · 标签、难度、领域筛选要 Problem 新字段（设计 §6 C3）</span>
      </form>
      {list.length === 0 ? <p className="muted">{view.items.length ? "没有符合筛选的题目。" : "还没有题目。"}</p> : (
        <div className="table-scroll">
          <table className="mini wide">
            <thead><tr><th>题目</th><th>终态</th><th>Goal 判官</th><th>画像</th><th>已花 / 上限</th><th>开题 seq</th><th /></tr></thead>
            <tbody>
              {list.map((p) => (
                <tr key={p.id} data-problem={p.id}>
                  <td><Link to={{ page: "problem", pid: p.id, asOf: null, node: null }}><Text t={p.title} block={false} /></Link> <span className="muted"><Plain text={p.id} /></span></td>
                  <td data-terminal={p.terminal ?? "running"}><Glyph g={TERMINAL_GLYPH[p.terminal ?? "running"]} />{terminalWord(p.terminal)}</td>
                  <td><CriterionBadge badge={p.terminal_badge} /></td>
                  <td>{p.profile.info} · {p.profile.judge} · {p.profile.reversibility}</td>
                  <td>{usd(p.spent_usd_milli)} / {p.cap_usd_milli === null ? "—" : usd(p.cap_usd_milli)}</td>
                  <td>{p.opened_seq}</td>
                  <td><Link to={{ page: "new", from: p.id }} className="btn-small" data-action="clone">克隆</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
