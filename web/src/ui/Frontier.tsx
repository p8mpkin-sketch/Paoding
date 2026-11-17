// 前沿列表（规格 3.1.4 的摘要层；HMI 设计 §10.2 中栏）。主区默认是它，不是图。
// 节点行的固定格式：[等级徽章] [判据徽章] 谓词摘要 ｜ 叙述标题（引文样式）｜ [估值，折叠]
import { INTENT_STATE_WORD } from "../model/levels";
import type { HintRow, NodeRow, ViewModel } from "../model/viewmodel";
import { CriterionBadge, LevelBadge } from "./criterion";
import { Text } from "./registers";

export function NodeRowView({ row, selected, onSelect }: { row: NodeRow; selected: boolean; onSelect: (id: string) => void }) {
  return (
    <li className={`node-row${selected ? " selected" : ""}`} data-node-row={row.id}>
      <button type="button" className="row-main" data-action="select-node" onClick={() => onSelect(row.id)} aria-pressed={selected}>
        <span className="row-id">{row.id}</span>
        <LevelBadge level={row.level} word={row.levelWord} />
        <CriterionBadge badge={row.predicate} />
        {row.state && <span className="badge">{INTENT_STATE_WORD[row.state]}</span>}
        {row.risk && <span className="badge">{row.risk}</span>}
        {row.flags.disputed && <span className="badge">争议</span>}
        {row.flags.stale && <span className="badge">stale</span>}
        {row.flags.unstable && <span className="badge">unstable</span>}
        <span className="predicate">{row.predicateText ?? (row.kind === "fact" ? "推断（无谓词）" : "无 done 判据")}</span>
      </button>
      <Text t={row.title} block={false} />
      {row.expected_gain && (
        <details className="estimates"><summary>估</summary><Text t={row.expected_gain} meta={{ what: "期望增益" }} /></details>
      )}
    </li>
  );
}

export function HintRowView({ hint, onOpen }: { hint: HintRow; onOpen?: (id: string) => void }) {
  return (
    <li className={`hint-row${hint.closed ? " closed" : ""}`} data-hint-row={hint.id}>
      <Text t={hint.text} meta={{ author: hint.author, ts: hint.ts, note: `${hint.id}${hint.about ? ` · about ${hint.about}` : ""}${hint.closed ? " · 已关闭" : ""}` }} />
      {onOpen && <button type="button" className="btn-small" data-action="open-hint" onClick={() => onOpen(hint.id)}>效果追溯</button>}
    </li>
  );
}

export function Frontier({ vm, selected, onSelect, onOpenHint }: { vm: ViewModel; selected: string | null; onSelect: (id: string) => void; onOpenHint?: (id: string) => void }) {
  const rows = new Map(vm.rows.map((r) => [r.id, r]));
  const hints = new Map(vm.hints.map((h) => [h.id, h]));
  return (
    <div className="frontier">
      {vm.frontier.map((g) => (
        <section key={g.key} data-frontier={g.key}>
          <h4>{g.title} <span className="muted">{g.ids.length}</span></h4>
          {g.ids.length === 0 ? <p className="muted">无</p> : (
            <ul className="rows">
              {g.ids.map((id) => {
                const r = rows.get(id);
                const h = hints.get(id);
                return r ? <NodeRowView key={id} row={r} selected={selected === id} onSelect={onSelect} /> : h ? <HintRowView key={id} hint={h} onOpen={onOpenHint} /> : null;
              })}
            </ul>
          )}
        </section>
      ))}
      <section data-frontier="all">
        <h4>全部节点 <span className="muted">{vm.rows.length}，按创建序号倒序</span></h4>
        <ul className="rows">
          {[...vm.rows].reverse().map((r) => <NodeRowView key={r.id} row={r} selected={selected === r.id} onSelect={onSelect} />)}
        </ul>
        {vm.hints.some((h) => h.closed) && (
          <>
            <h4>已关闭的 Hint</h4>
            <ul className="rows">{vm.hints.filter((h) => h.closed).map((h) => <HintRowView key={h.id} hint={h} onOpen={onOpenHint} />)}</ul>
          </>
        )}
      </section>
    </div>
  );
}
