// 待办（守门官的载体；HMI 设计 §4 左栏）：/work 的 human 项。类别取自服务端给的 why，前端不推断。
import type { TodoItem } from "../model/viewmodel";

export const WHY: Record<string, string> = {
  needs_human: "审批", extension: "续期门", dispute: "争议待裁决", closeout: "验收与四顾", stalled: "停滞：等待指导或人工关闭",
  scope_request: "申请访问", acceptance: "人工验收",
  // 开放道（地图 Q37）：交付了等你看；受阻了要你补东西。都在任务页的“结果”一栏处理
  delivered: "做完了，等你看", blocked: "受阻，要你补",
};
/** F1 实现了卡片的待办类别；其余只列出，处理走 pd。 */
export const HAS_CARD = new Set(["needs_human", "extension", "scope_request", "acceptance"]);
/** 在任务页“结果”一栏处理的人工项（不开卡片）。 */
export const IN_RESULT = new Set(["delivered", "blocked"]);

export const todoKey = (t: TodoItem) => `${t.why}:${t.target}`;

export function Todo({ items, open, onOpen }: { items: TodoItem[]; open: string | null; onOpen: (key: string | null) => void }) {
  return (
    <div className="todo" data-todo>
      {items.length === 0 ? <p className="t2">没有等你处理的事。</p> : (
        <ul>
          {items.map((t) => {
            const k = todoKey(t);
            const word = WHY[t.why] ?? t.why;
            return (
              <li key={k} data-todo-item={k}>
                {IN_RESULT.has(t.why) ? (
                  <div className="todo-card off"><span className="todo-word">{word}</span><span className="t2">在“结果”里看，采纳、不采纳或接着问</span></div>
                ) : HAS_CARD.has(t.why) ? (
                  <button type="button" className="todo-card" aria-pressed={open === k} onClick={() => onOpen(open === k ? null : k)}>
                    <span className="todo-word">{word} <span className="k-mono">{t.target}</span></span>
                    <span className="t2">{open === k ? "卡片已在主区打开" : "点开在主区处理"}</span>
                  </button>
                ) : (
                  <div className="todo-card off"><span className="todo-word">{word} <span className="k-mono">{t.target}</span></span><span className="t2">网页暂不处理这一类，请用 pd</span></div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
