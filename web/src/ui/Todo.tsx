// 待办（守门官的载体；HMI 设计 §4 左栏）：/work 的 human 项。类别取自服务端给的 why，前端不推断。
import type { TodoItem } from "../model/viewmodel";

export const WHY: Record<string, string> = {
  needs_human: "审批", extension: "续期门", dispute: "争议待裁决", closeout: "验收与四顾", stalled: "停滞：等待 Hint 或人工关闭",
};
/** F1 实现了卡片的待办类别；其余只列出，处理走 pd。 */
export const HAS_CARD = new Set(["needs_human", "extension"]);

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
                {HAS_CARD.has(t.why) ? (
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
