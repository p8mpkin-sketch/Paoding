// 结果页（地图 Q22，工作台设计 C6）：关闭的任务在主区顶部给出结构化报告，与 `pd report` 同源同序。
// 确定性投影，不调用模型；未解出时同样产出。首行：终态与根结论的等级上限；随后判定来源、
// 人工验收的历次记录（只在人工验收的任务上）、按等级排的事实（E3 在前，已证伪在后）、已放弃的尝试。
import { ShieldAlert, ShieldCheck } from "lucide-react";
import type { ViewModel } from "../model/viewmodel";
import { terminalWord } from "../model/levels";
import { Text } from "./registers";

const RANK: Record<string, number> = { E3: 0, E3d: 1, E2: 2, E1: 3, E0: 4, X: 5 };
export const AUTHORITY_WORD = { local: "本地判定", external: "外部判定", human: "人工验收", self: "自述（开放道，未经判定）" } as const;

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
  const settled = vm.terminal === "solved" || vm.terminal === "accepted";
  return (
    <div className="tk-result" data-result>
      {/* 一句话的结论：终态、等级上限、谁判的 */}
      <section className="tk-verdict tk-report-head" data-terminal={vm.terminal ?? ""} aria-label="结果">
        {settled ? <ShieldCheck className="tk-verdict-ic ok" aria-hidden="true" /> : <ShieldAlert className="tk-verdict-ic" aria-hidden="true" />}
        <div className="tk-verdict-t">
          <h2 className="tk-report-h" data-result-head><b>终态 {terminalWord(vm.terminal)}</b>；根结论等级上限 {lv ? `${lv} ${vm.goal.levelWord}` : "无等级"}</h2>
          <span data-result-authority>判定来源：{AUTHORITY_WORD[vm.goal.authority]}{vm.terminal === "accepted" ? "。人工验收不提升等级，也不计入 solved。" : vm.goal.authority === "self" ? "。开放道的交付不计入 solved。" : ""}</span>
        </div>
        <ul className="tk-verdict-nums" aria-label="概要">
          <li><span className="tk-vstat"><b className="num">{facts.length}</b><span>条登记的事实</span></span></li>
          {vm.goal.acceptLog.length > 0 && <li><span className="tk-vstat"><b className="num">{vm.goal.acceptLog.length}</b><span>次人工验收</span></span></li>}
          {gave.length > 0 && <li><span className="tk-vstat"><b className="num">{gave.length}</b><span>个放弃的尝试</span></span></li>}
        </ul>
      </section>
      {vm.goal.acceptLog.length > 0 && (
        <section className="tk-sec">
          <h2>人工验收记录</h2>
          <ul className="tk-li" data-result-accept>
            {vm.goal.acceptLog.map((e) => (
              <li key={e.seq} data-decision={e.decision}><span className="grow">seq {e.seq} {e.decision === "accept" ? "验收通过" : "拒收"}：{e.checks.map((c) => `${c.id} ${c.verdict === "pass" ? "过" : "不过"}`).join("、")}</span></li>
            ))}
          </ul>
        </section>
      )}
      <section className="tk-sec">
        <h2>事实<small>等级高的在前，同级按登记先后</small></h2>
        {facts.length === 0 ? <p className="tk-none t2">没有登记事实。</p> : (
          <ol className="tk-li" data-result-facts>
            {facts.map((f) => <li key={f.id} data-fact={f.id}><span className="tk-ref tk-ref-static k-mono">{f.id}</span><span className="tk-lv" data-level={f.level ?? ""}>{f.levelWord}</span><span className="grow"> · <Text t={f.title} block={false} /></span></li>)}
          </ol>
        )}
      </section>
      {gave.length > 0 && <p className="tk-fb t2" data-result-abandoned>已放弃：{gave.map((g) => g.id).join("、")}</p>}
    </div>
  );
}
