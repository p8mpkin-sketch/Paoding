// 题目列表：终态三值、画像、花费（GET /v1/problems）。
import { useEffect, useState } from "react";
import type { ProblemsView } from "../api/types";
import { useServices } from "../app/context";
import { hrefOf, navigate, type Route } from "../app/router";
import { terminalWord } from "../model/levels";
import { usd } from "../model/text";
import { CriterionBadge } from "../ui/criterion";
import { Plain, Text } from "../ui/registers";

export function Link({ to, children }: { to: Route; children: React.ReactNode }) {
  return <a href={hrefOf(to)} onClick={(e) => { if (e.metaKey || e.ctrlKey || e.shiftKey) return; e.preventDefault(); navigate(to); }}>{children}</a>;
}

export function useProblems(): { view: ProblemsView | null; error: string | null } {
  const { api } = useServices();
  const [view, setView] = useState<ProblemsView | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.problems().then(setView, (e: Error) => setError(e.message));
  }, [api]);
  return { view, error };
}

export function Problems() {
  const { view, error } = useProblems();
  if (error) return <p className="error">读不到题目列表：<Plain text={error} /></p>;
  if (!view) return <p className="muted">读取中…</p>;
  const list = view.items;
  return (
    <div className="problems">
      <h2>题目</h2>
      {list.length === 0 ? <p className="muted">还没有题目。</p> : (
        <table className="mini wide">
          <thead><tr><th>题目</th><th>终态</th><th>Goal 判官</th><th>画像</th><th>已花 / 上限</th><th>开题 seq</th></tr></thead>
          <tbody>
            {list.map((p) => (
              <tr key={p.id} data-problem={p.id}>
                <td><Link to={{ page: "problem", pid: p.id, asOf: null, node: null }}><Text t={p.title} block={false} /></Link> <span className="muted"><Plain text={p.id} /></span></td>
                <td data-terminal={p.terminal ?? "running"}>{terminalWord(p.terminal)}</td>
                <td><CriterionBadge badge={p.terminal_badge} /></td>
                <td>{p.profile.info} · {p.profile.judge} · {p.profile.reversibility}</td>
                <td>{usd(p.spent_usd_milli)} / {p.cap_usd_milli === null ? "—" : usd(p.cap_usd_milli)}</td>
                <td>{p.opened_seq}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
