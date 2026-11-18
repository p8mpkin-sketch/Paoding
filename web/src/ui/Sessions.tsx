// 会话流（工作区左栏）：status.leases 原样排版。在途与否、结局都取服务端字段，前端不推断进度。
import type { LeaseRow } from "../api/types";
import { usd } from "../model/text";

export const LEASE_WORD: Record<string, string> = { bootstrap: "起步", reason: "推理", explore: "探索", judge: "判定", rejudge: "复判" };

function SessionRow({ l, onSelect }: { l: LeaseRow; onSelect: (id: string) => void }) {
  return (
    <li className={`sess${l.active ? " on" : ""}`} data-lease={l.id} data-active={l.active}>
      <div className="sess-head">
        <span className={`pulse${l.active ? "" : " off"}`} aria-hidden="true" />
        <b>{LEASE_WORD[l.kind] ?? l.kind}</b>
        <span className="k-mono ink3">{l.id}</span>
        <span className="grow" />
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

export function Sessions({ leases, onSelect }: { leases: LeaseRow[]; onSelect: (id: string) => void }) {
  const live = leases.filter((l) => l.active);
  const done = leases.filter((l) => !l.active).reverse();
  return (
    <div className="sessions" data-sessions>
      {live.length === 0 ? <p className="t2">没有在途的会话。</p> : <ul className="sess-list">{live.map((l) => <SessionRow key={l.id} l={l} onSelect={onSelect} />)}</ul>}
      {done.length > 0 && (
        <details className="sess-done">
          <summary>已结束 {done.length}</summary>
          <ul className="sess-list">{done.slice(0, 30).map((l) => <SessionRow key={l.id} l={l} onSelect={onSelect} />)}</ul>
        </details>
      )}
    </div>
  );
}
