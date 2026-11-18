// 工作区的新面板（工作台设计 §1 模块三、线框 f4）：在途会话、事件时间线、日志、成本、快捷操作。
// 都是 view(as_of) 与刻度表的排版；写操作只有追加预算一个，走提议通道，图服务回 not_enabled 时如实显示。
import { useMemo, useState } from "react";
import { newIdemKey } from "../api/client";
import { ops } from "../api/ops";
import type { WireTick } from "../api/types";
import { useServices } from "../app/context";
import { TICK_LEGEND, ticksOf } from "../model/ticks";
import { usd } from "../model/text";
import type { SessionRow, ViewModel } from "../model/viewmodel";
import { CostMeter } from "./CostMeter";
import { Plain } from "./registers";
import { rejectText } from "./useProposal";

const dur = (ms: number) => { const s = Math.floor(ms / 1000); return s < 60 ? `${s} 秒` : s < 3600 ? `${Math.floor(s / 60)} 分 ${s % 60} 秒` : `${Math.floor(s / 3600)} 时 ${Math.floor((s % 3600) / 60)} 分`; };
const hms = (ts: number) => new Date(ts).toLocaleTimeString("zh-CN", { hour12: false });

/** 在途会话：角色（租约种类）、目标、持有者、已用（事件时钟）、预留。每会话已花要新字段（设计 §6 C1）。 */
export function Sessions({ rows, onSelect }: { rows: SessionRow[]; onSelect: (id: string) => void }) {
  return (
    <section className="sessions" data-sessions>
      <h3>在途会话（{rows.length}）</h3>
      {rows.length === 0 ? <p className="muted">没有在途会话。</p> : (
        <ul className="session-list">
          {rows.map((s) => (
            <li key={s.id} data-session={s.id} data-kind={s.kind}>
              <b>{s.kind}</b>{s.target && <> · <button type="button" className="linkish" onClick={() => onSelect(s.target!)}>{s.target}</button></>}
              <div className="muted"><Plain text={s.holder} /> · {s.since_ms === null ? "—" : `已 ${dur(s.since_ms)}`} · 预留 {usd(s.reserve_usd_milli)}</div>
            </li>
          ))}
        </ul>
      )}
      <p className="muted small">每会话已花：要后端按租约归集（设计 §6 C1）。</p>
    </section>
  );
}

/** 事件时间线视图：本题每条事件一行（seq、时刻、种类），点任一行即回放到该 seq。只读刻度表，不读事件体。 */
export function EventTimeline({ ticks, seq, head, onSeek }: { ticks: readonly WireTick[]; seq: number; head: number; onSeek: (asOf: number | null) => void }) {
  const marked = new Map(ticksOf(ticks, head).map((t) => [t.seq, t.kind]));
  return (
    <ol className="event-timeline" data-event-timeline>
      {ticks.map((t, i) => {
        const prev = ticks[i - 1];
        const gap = prev ? t.ts - prev.ts : 0;
        const m = marked.get(t.seq);
        return (
          <li key={t.seq} data-tick-seq={t.seq} aria-current={t.seq === seq} className={t.seq > seq ? "future" : undefined}>
            {gap >= 60_000 && <div className="gap muted">… 间隔 {dur(gap)}</div>}
            <button type="button" className="tl-row" data-action="seek" onClick={() => onSeek(t.seq >= head ? null : t.seq)}>
              <span className="tl-seq">seq {t.seq}</span>
              <span className="tl-time">{hms(t.ts)}</span>
              <span className="tl-kind">{t.kind}{t.result ? ` · ${t.result}` : ""}{t.mark ? ` · ${t.mark}%` : ""}</span>
              {m && <span className="badge" title={TICK_LEGEND[m]}>{m}</span>}
            </button>
          </li>
        );
      })}
    </ol>
  );
}

/** 日志 Tab：事件流按种类过滤，新的在上。种类名原样显示，不解释。 */
export function EventLogPanel({ ticks, seq }: { ticks: readonly WireTick[]; seq: number }) {
  const kinds = useMemo(() => [...new Set(ticks.map((t) => t.kind))].sort(), [ticks]);
  const [off, setOff] = useState<Set<string>>(new Set());
  const list = ticks.filter((t) => t.seq <= seq && !off.has(t.kind)).slice(-300).reverse();
  const toggle = (k: string) => setOff((cur) => { const n = new Set(cur); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  return (
    <section className="event-log" data-event-log>
      <div className="seg" role="group" aria-label="按种类过滤">
        {kinds.map((k) => <button key={k} type="button" className="btn-small" aria-pressed={!off.has(k)} data-log-kind={k} onClick={() => toggle(k)}>{k}</button>)}
      </div>
      <table className="mini wide">
        <thead><tr><th>seq</th><th>时刻</th><th>种类</th></tr></thead>
        <tbody>{list.map((t) => <tr key={t.seq} data-log-row={t.seq}><td>{t.seq}</td><td>{hms(t.ts)}</td><td>{t.kind}{t.result ? ` · ${t.result}` : ""}{t.mark ? ` · ${t.mark}%` : ""}</td></tr>)}</tbody>
      </table>
      <p className="muted">最多显示最近 300 条；完整日志见 <code>/v1/problems/…/events</code> 或 <code>pd</code>。</p>
    </section>
  );
}

/** 成本 Tab：仪表、按角色分项、验证池与墙钟。量具：只显示，不驱动任何默认值。 */
export function CostPanel({ vm }: { vm: ViewModel }) {
  const b = vm.budget;
  const total = Math.max(1, b.byKind.reduce((a, k) => a + k.usd_milli, 0));
  return (
    <section className="cost-panel" data-cost-panel>
      <CostMeter b={b} />
      <h4>按角色分项</h4>
      <table className="mini wide">
        <thead><tr><th>角色</th><th>花费</th><th>占比</th></tr></thead>
        <tbody>{b.byKind.map((k) => (
          <tr key={k.kind} data-by-kind={k.kind}><td>{k.kind}</td><td>{usd(k.usd_milli)}</td>
            <td><div className="bar slim" aria-hidden="true"><div className="bar-spent" style={{ width: `${(k.usd_milli * 100) / total}%` }} /></div>{Math.round((k.usd_milli * 100) / total)}%</td></tr>
        ))}</tbody>
      </table>
      <dl className="kv">
        <dt>验证池</dt><dd>{usd(b.verifySpent)} / {usd(b.verifyCap)}</dd>
        <dt>墙钟</dt><dd>{b.wallSpent}s / {b.wallCap}s</dd>
        <dt>预算标记</dt><dd>{b.marks.length ? b.marks.map((m) => `${m}%`).join(" ") : "未越过"}{b.review ? " · 预算复盘期" : ""}</dd>
      </dl>
      <p className="muted">预算消耗曲线要服务端按 seq 出序列（设计 §6 C2），暂不可用。</p>
    </section>
  );
}

/** 快捷操作栏：注入 Hint（打开对话）、追加预算（budget_add，随 M1；M0 图服务拒绝时如实显示）。 */
export function QuickActions({ pid, canWrite, onInject }: { pid: string; canWrite: boolean; onInject: () => void }) {
  const { api } = useServices();
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function add() {
    setBusy(true); setMsg(null);
    try {
      const r = await api.propose(pid, [ops.budgetAdd(Math.round(Number(amount) * 1000))], newIdemKey());
      setMsg(`已提交 seq ${r[0]?.seq}`); setAmount(""); setOpen(false);
    } catch (e) {
      const t = rejectText(e as Error) ?? "";
      setMsg(/not_enabled|schema_error/.test(t) ? `暂不可用（随 M1）：${t}` : t);
    } finally { setBusy(false); }
  }
  return (
    <div className="quick-actions" role="toolbar" aria-label="快捷操作" data-quick-actions>
      <button type="button" className="btn-small" data-action="quick-hint" onClick={onInject}>注入 Hint…</button>
      <button type="button" className="btn-small" data-action="quick-budget" aria-expanded={open} disabled={!canWrite} onClick={() => setOpen(!open)}>追加预算…</button>
      {open && (
        <form className="inline-form" onSubmit={(e) => { e.preventDefault(); void add(); }}>
          <label>美元 <input inputMode="decimal" value={amount} data-field="budget-add" onChange={(e) => setAmount(e.target.value)} /></label>
          <button type="submit" className="btn-small" disabled={busy || !(Number(amount) > 0)} data-action="budget-add">提交</button>
        </form>
      )}
      {msg && <span className="muted" data-quick-msg><Plain text={msg} /></span>}
      <span className="muted small">暂停、恢复随 M1（裁决 005-3）；更换模型、终止会话、改优先级还不是人的操作（异议 web-workbench 第 5 条）。</span>
    </div>
  );
}
