// 事件回放时间轴（HMI 设计 §10.4）。刻度只来自事件。
// 拖动中只移动游标，松手后取一次 as_of 视图，不逐帧请求。
import { useEffect, useState } from "react";
import type { Event } from "../api/types";
import { TICK_LEGEND, ticksOf, type TickKind } from "../model/ticks";

type Props = {
  events: readonly Event[];
  head: number;
  /** null 即实时。 */
  asOf: number | null;
  onSeek: (asOf: number | null) => void;
  link: string;
};

export function Timeline({ events, head, asOf, onSeek, link }: Props) {
  const seqs = events.map((e) => e.seq);
  const cur = asOf ?? head;
  const idxOf = (seq: number) => { let i = 0; while (i < seqs.length - 1 && seqs[i + 1] <= seq) i++; return i; };
  const [drag, setDrag] = useState<number | null>(null);
  const [showLeases, setShowLeases] = useState(false);
  const [jump, setJump] = useState<TickKind>("H");
  const [input, setInput] = useState(String(cur));
  const [copied, setCopied] = useState(false);
  useEffect(() => setInput(String(cur)), [cur]);

  const ticks = ticksOf(events, head).filter((t) => showLeases || t.kind !== "L");
  const idx = drag ?? idxOf(cur);
  const last = Math.max(seqs.length - 1, 1);
  const commit = (i: number) => { setDrag(null); const seq = seqs[i]; if (seq !== undefined) onSeek(seq >= head ? null : seq); };
  const neighbor = (dir: -1 | 1) => {
    const same = ticks.filter((t) => t.kind === jump).map((t) => t.seq);
    const target = dir < 0 ? [...same].reverse().find((s) => s < cur) : same.find((s) => s > cur);
    if (target !== undefined) onSeek(target >= head ? null : target);
  };

  return (
    <div className="timeline" data-timeline>
      <div className="timeline-track">
        <div className="ticks" aria-hidden="true">
          {ticks.map((t) => (
            <span key={`${t.seq}`} className="tick" data-tick={t.kind} data-seq={t.seq} title={t.label} style={{ left: `${(idxOf(t.seq) / last) * 100}%` }}>{t.kind}</span>
          ))}
        </div>
        <input
          type="range" min={0} max={Math.max(seqs.length - 1, 0)} step={1} value={idx} aria-label="as_of"
          onChange={(e) => setDrag(Number(e.target.value))}
          onPointerUp={() => drag !== null && commit(drag)}
          onKeyUp={() => drag !== null && commit(drag)}
          onBlur={() => drag !== null && commit(drag)}
        />
      </div>
      <div className="timeline-ctl">
        <span data-timeline-pos>{asOf === null ? `●实时 · 链头 seq=${head}` : `回放于 seq=${asOf} · 链头 seq=${head}`}{drag !== null ? ` · 游标 seq=${seqs[drag]}（松手后读取）` : ""}</span>
        <label>同类刻度
          <select value={jump} onChange={(e) => setJump(e.target.value as TickKind)}>
            {(Object.keys(TICK_LEGEND) as TickKind[]).map((k) => <option key={k} value={k}>{k} {TICK_LEGEND[k]}</option>)}
          </select>
        </label>
        <button type="button" className="btn-small" onClick={() => neighbor(-1)}>上一个</button>
        <button type="button" className="btn-small" onClick={() => neighbor(1)}>下一个</button>
        <form className="inline" onSubmit={(e) => { e.preventDefault(); const n = Number(input); if (Number.isInteger(n) && n > 0) onSeek(n >= head ? null : n); }}>
          <label>as_of <input className="seq-input" inputMode="numeric" value={input} onChange={(e) => setInput(e.target.value)} /></label>
          <button type="submit" className="btn-small">跳到</button>
        </form>
        <button type="button" className="btn-small" onClick={() => onSeek(null)} disabled={asOf === null}>回到实时</button>
        <button type="button" className="btn-small" data-action="copy-link" onClick={() => { void navigator.clipboard?.writeText(link).then(() => setCopied(true), () => setCopied(false)); }}>
          复制链接{copied ? " ✓" : ""}
        </button>
        <label><input type="checkbox" checked={showLeases} onChange={(e) => setShowLeases(e.target.checked)} /> 显示租约刻度（L）</label>
      </div>
      <details className="legend"><summary>刻度图例</summary>
        <ul>{(Object.keys(TICK_LEGEND) as TickKind[]).map((k) => <li key={k}><b>{k}</b> {TICK_LEGEND[k]}</li>)}</ul>
      </details>
    </div>
  );
}
