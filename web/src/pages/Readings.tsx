// 读数面板（量具；HMI 设计 §3.8、§4）。只显示，不驱动任何按钮的默认值。
// F1 只有能从现有端点读到的量：每解成本（服务端给的 totals）、按角色分项、验证池花费。
// 评测台四臂、归因表、折损、切口命中率、校准、留出还没有读端点，显示"暂不可用"，不编数字。
import { useEffect, useState } from "react";
import type { BudgetResponse } from "../api/types";
import { useServices } from "../app/context";
import { readUsage } from "../app/usage";
import { terminalWord } from "../model/levels";
import { usd } from "../model/text";
import { Plain } from "../ui/registers";
import { Link, useProblems } from "./Problems";

const UNAVAILABLE = ["评测台四臂与消融结果", "结构归因表", "折损账（割与折）", "切口命中率", "校准曲线（预测账）", "常设留出", "退役距离", "学习曲线"];

export function Readings() {
  const { api } = useServices();
  const { view, error } = useProblems();
  const list = view?.items ?? null;
  const [budgets, setBudgets] = useState<Record<string, BudgetResponse>>({});
  useEffect(() => {
    if (!list) return;
    let live = true;
    void Promise.all(list.map((p) => api.budget(p.id).then((b) => [p.id, b] as const, () => null))).then((rs) => {
      if (live) setBudgets(Object.fromEntries(rs.filter((r): r is readonly [string, BudgetResponse] => r !== null)));
    });
    return () => { live = false; };
  }, [api, list]);

  if (error) return <p className="error">读不到任务列表：<Plain text={error} /></p>;
  if (!list) return <p className="muted">读取中…</p>;
  const closed = list.filter((p) => p.closed);
  const totals = view!.totals;
  const roles = [...new Set(Object.values(budgets).flatMap((b) => Object.keys(b.by_kind)))].sort();
  const usage = readUsage();

  return (
    <div className="readings">
      <h2>读数</h2>
      <section>
        <h3>任务集</h3>
        <dl className="kv">
          <dt>任务数</dt><dd>{totals.problems}（已关 {closed.length}）</dd>
          <dt>终态</dt><dd>{(["solved", "accepted", "unsolved"] as const).map((t) => `${t} ${closed.filter((p) => p.terminal === t).length}`).join(" · ")}</dd>
          <dt>每解成本</dt><dd data-cost-per-solve>{totals.cost_per_solve_usd_milli !== null ? `${usd(totals.cost_per_solve_usd_milli)}（全部花费 ${usd(totals.spent_usd_milli)} ÷ solved ${totals.solved} 题；图服务给出）` : "尚无 solved 的题"}</dd>
        </dl>
      </section>
      <section>
        <h3>按角色分项</h3>
        <table className="mini wide">
          <thead><tr><th>任务</th><th>终态</th>{roles.map((r) => <th key={r}>{r}</th>)}<th>验证池</th><th>已花 / 上限</th></tr></thead>
          <tbody>
            {list.map((p) => {
              const b = budgets[p.id];
              return (
                <tr key={p.id}>
                  <td><Link to={{ page: "problem", pid: p.id, asOf: null, node: null }}><Plain text={p.id} /></Link></td>
                  <td>{terminalWord(p.terminal)}</td>
                  {roles.map((r) => <td key={r}>{b?.by_kind[r] ? usd(b.by_kind[r].usd_milli) : "—"}</td>)}
                  <td>{b ? usd(b.verify_spent.usd_milli) : "—"}</td>
                  <td>{usd(p.spent_usd_milli)} / {p.cap_usd_milli === null ? "—" : usd(p.cap_usd_milli)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
      <section>
        <h3>暂不可用</h3>
        <ul>{UNAVAILABLE.map((u) => <li key={u}>{u}：暂不可用（还没有对应的读端点）</li>)}</ul>
      </section>
      <section>
        <h3>界面使用读数（本机）</h3>
        <p className="muted">只存在这台机器上，不进任务日志，不发往服务端。用来判断各感知官模块有没有人用。</p>
        {Object.keys(usage).length === 0 ? <p className="muted">还没有读数。</p> : (
          <table className="mini"><tbody>{Object.keys(usage).sort().map((k) => <tr key={k}><td>{k}</td><td>{usage[k]}</td></tr>)}</tbody></table>
        )}
      </section>
    </div>
  );
}
