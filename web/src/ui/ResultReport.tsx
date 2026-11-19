// 结果页（地图 Q22，工作台设计 C6）：关闭的任务在主区顶部给出结构化报告，与 `pd report` 同源同序。
// 确定性投影，不调用模型；未解出时同样产出。首行：终态与根结论的等级上限；随后判定来源、
// 人工验收的历次记录（只在人工验收的任务上）、按等级排的事实（E3 在前，已证伪在后）、已放弃的尝试。
import type { ViewModel } from "../model/viewmodel";
import { terminalWord } from "../model/levels";
import { Text } from "./registers";

const RANK: Record<string, number> = { E3: 0, E3d: 1, E2: 2, E1: 3, E0: 4, X: 5 };
export const AUTHORITY_WORD = { local: "本地判定", external: "外部判定", human: "人工验收" } as const;

/** 报告的事实顺序：等级高的在前，同级按创建先后（与 pd report 相同）。 */
export function reportOrder(rows: ViewModel["rows"]): ViewModel["rows"] {
  return rows
    .filter((r) => r.kind === "fact")
    .sort((a, b) => (RANK[a.level ?? ""] ?? 9) - (RANK[b.level ?? ""] ?? 9) || a.created_seq - b.created_seq);
}

export function ResultReport({ vm }: { vm: ViewModel }) {
  const facts = reportOrder(vm.rows);
  const gave = vm.rows.filter((r) => r.kind === "intent" && r.state === "abandoned");
  const lv = vm.goal.predicate.level;
  return (
    <section className="ws-sec result" data-result>
      <h2 className="ws-h">结果</h2>
      <p data-result-head><b>终态 {terminalWord(vm.terminal)}</b>；根结论等级上限 {lv ? `${lv} ${vm.goal.levelWord}` : "无等级"}</p>
      <p className="t2" data-result-authority>判定来源：{AUTHORITY_WORD[vm.goal.authority]}{vm.terminal === "accepted" ? "。人工验收不提升等级，不写“已证明”，也不计入 solved。" : ""}</p>
      {vm.goal.acceptLog.length > 0 && (
        <ul className="rows" data-result-accept>
          {vm.goal.acceptLog.map((e) => (
            <li key={e.seq}>seq {e.seq} {e.decision === "accept" ? "验收通过" : "拒收"}：{e.checks.map((c) => `${c.id} ${c.verdict === "pass" ? "过" : "不过"}`).join("、")}</li>
          ))}
        </ul>
      )}
      {facts.length === 0 ? <p className="t2">没有登记事实。</p> : (
        <ol className="rows" data-result-facts>
          {facts.map((f) => <li key={f.id} data-fact={f.id}><span className="k-mono">{f.id}</span> {f.levelWord} · <Text t={f.title} block={false} /></li>)}
        </ol>
      )}
      {gave.length > 0 && <p className="t2" data-result-abandoned>已放弃：{gave.map((g) => g.id).join("、")}</p>}
    </section>
  );
}
