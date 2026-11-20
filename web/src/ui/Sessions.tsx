// 会话流（工作区左栏）：status.leases 原样排版。在途与否、结局都取服务端字段，前端不推断进度。
import type { LeaseRow } from "../api/types";
import { usd } from "../model/text";

export const LEASE_WORD: Record<string, string> = { bootstrap: "起步", reason: "推理", explore: "探索", judge: "判定", rejudge: "复判", solve: "求解" };

/** 开放道的会话：点开看它的实时活动（工作区的“会话活动”面板）。严格道不传，行上就没有这个按钮。 */
type Open = { onOpen?: (id: string) => void; openId?: string | null };

function SessionRow({ l, onSelect, onOpen, openId }: { l: LeaseRow; onSelect: (id: string) => void } & Open) {
  return (
    <li className={`sess${l.active ? " on" : ""}${openId === l.id ? " picked" : ""}`} data-lease={l.id} data-active={l.active}>
      <div className="sess-head">
        <span className={`pulse${l.active ? "" : " off"}`} aria-hidden="true" />
        <b>{LEASE_WORD[l.kind] ?? l.kind}</b>
        <span className="k-mono ink3">{l.id}</span>
        <span className="grow" />
        {onOpen && <button type="button" className="sess-target" data-action="lease-activity" aria-pressed={openId === l.id} onClick={() => onOpen(l.id)} aria-label={`看会话 ${l.id} 的活动`}>看活动</button>}
        {l.target && <button type="button" className="sess-target k-mono" data-action="lease-target" onClick={() => onSelect(l.target!)} aria-label={`检视 ${l.target}`}>{l.target}</button>}
      </div>
      <div className="t2 sess-meta">
        <span>预留 {usd(l.reserve.usd_milli)}</span>
        <span>seq {l.issued_seq}{l.ended_seq !== undefined ? `–${l.ended_seq}` : " 起"}</span>
        {!l.active && <span>{l.outcome ?? "已结束"}</span>}
        {l.reflect && <span>反思</span>}
      </div>
    </li>
  );
}

export function Sessions({ leases, onSelect, onOpen, openId }: { leases: LeaseRow[]; onSelect: (id: string) => void } & Open) {
  const live = leases.filter((l) => l.active);
  const done = leases.filter((l) => !l.active).reverse();
  return (
    <div className="sessions" data-sessions>
      {live.length === 0 ? <p className="t2">没有在途的会话。</p> : <ul className="sess-list">{live.map((l) => <SessionRow key={l.id} l={l} onSelect={onSelect} onOpen={onOpen} openId={openId} />)}</ul>}
      {done.length > 0 && (
        <details className="sess-done">
          <summary>已结束 {done.length}</summary>
          <ul className="sess-list">{done.slice(0, 30).map((l) => <SessionRow key={l.id} l={l} onSelect={onSelect} onOpen={onOpen} openId={openId} />)}</ul>
        </details>
      )}
    </div>
  );
}
