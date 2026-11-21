// 读数与今日的小图（docs/design/pages-v6 §4）：单一系列的横条、竖条，与分段条。
// 规矩：一个系列只用墨色一种颜色（标题即图例）；数值写在旁边用正文墨色；每个图都有表格视图；悬停有读数；不画双轴。
import { useEffect, useState } from "react";

/** 容器的像素宽：图按真实像素画，字号不随缩放变大。jsdom 没有 ResizeObserver，退回默认宽。 */
function useWidth(fallback: number) {
  const [el, ref] = useState<HTMLDivElement | null>(null);
  const [w, setW] = useState(fallback);
  useEffect(() => {
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => { const x = Math.round(e.contentRect.width); if (x > 0) setW(x); });
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);
  return [ref, w] as const;
}

export type Bar = { key: string; label: React.ReactNode; value: number; text: string; title?: string; sub?: React.ReactNode; onClick?: () => void };

function Frame({ title, note, children, table, data }: { title: string; note?: React.ReactNode; children: React.ReactNode; table: React.ReactNode; data?: string }) {
  const [tab, setTab] = useState(false);
  return (
    <figure className="ch" data-chart={data ?? title}>
      <figcaption className="ch-h">
        <b>{title}</b>
        {note && <span className="t2">{note}</span>}
        <span className="grow" />
        <button type="button" className="btn-small" aria-pressed={tab} data-action="chart-table" onClick={() => setTab(!tab)}>表格</button>
      </figcaption>
      {tab ? table : children}
    </figure>
  );
}

/** 横条：一行一项，条长按最大值归一；点行可跳转。 */
export function HBars({ title, note, rows, empty, data }: { title: string; note?: React.ReactNode; rows: Bar[]; empty: string; data?: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  const table = (
    <table className="mini wide" data-chart-table><tbody>{rows.map((r) => <tr key={r.key}><td>{r.label}</td><td className="r k-mono">{r.text}</td></tr>)}</tbody></table>
  );
  return (
    <Frame title={title} note={note} table={table} data={data}>
      {rows.length === 0 ? <p className="t2">{empty}</p> : (
        <ul className="ch-hb">
          {rows.map((r) => (
            <li key={r.key} title={r.title ?? `${typeof r.label === "string" ? r.label : r.key}：${r.text}`} data-bar={r.key} className={r.onClick ? "click" : undefined} onClick={r.onClick}>
              <span className="ch-l">{r.label}{r.sub && <span className="t2"> {r.sub}</span>}</span>
              <span className="ch-track" aria-hidden="true"><b style={{ width: `${Math.max(r.value > 0 ? 1.5 : 0, (r.value * 100) / max)}%` }} /></span>
              <span className="ch-v k-mono">{r.text}</span>
            </li>
          ))}
        </ul>
      )}
    </Frame>
  );
}

/** 竖条（按天、按桶）：柱上悬停看读数，柱下是标签；最高柱写出数值。 */
export function VBars({ title, note, bars, empty, data }: { title: string; note?: React.ReactNode; bars: Bar[]; empty: string; data?: string }) {
  const [hover, setHover] = useState<string | null>(null);
  const max = Math.max(1, ...bars.map((b) => b.value));
  const flat = bars.every((b) => b.value === 0);
  const [ref, W] = useWidth(320);
  const H = 96, n = Math.max(1, bars.length), gap = n > 30 ? 2 : n > 14 ? 4 : n > 6 ? 10 : 28;
  const bw = Math.min(56, (W - gap * (n - 1)) / n);
  const x0 = (W - (bw * n + gap * (n - 1))) / 2; // 柱少时整体居中，不画成一整块
  const top = bars.reduce((a, b) => (b.value > (a?.value ?? -1) ? b : a), null as Bar | null);
  const h = bars.find((b) => b.key === hover);
  const table = (
    <table className="mini wide" data-chart-table><tbody>{bars.map((b) => <tr key={b.key}><td>{b.label}</td><td className="r k-mono">{b.text}</td></tr>)}</tbody></table>
  );
  const every = Math.ceil(bars.length / Math.max(2, Math.floor(W / 48)));
  return (
    <Frame title={title} note={note} table={table} data={data}>
      {flat ? <p className="t2">{empty}</p> : (
        <div className="ch-vb" ref={ref}>
          <p className="ch-read t2" aria-live="polite">{h ? <><b className="k-mono">{h.text}</b> · {h.title ?? h.label}</> : top ? <>最高 <b className="k-mono">{top.text}</b> · {top.title ?? top.label}</> : null}</p>
          <svg viewBox={`0 0 ${W} ${H + 18}`} width={W} height={H + 18} role="img" aria-label={bars.map((b) => `${b.title ?? b.key} ${b.text}`).join("；")}>
            <line x1={0} y1={H} x2={W} y2={H} className="t-axis" />
            {bars.map((b, i) => {
              const bh = (b.value / max) * (H - 6);
              const x = x0 + i * (bw + gap);
              return (
                <g key={b.key} data-vbar={b.key} onMouseEnter={() => setHover(b.key)} onMouseLeave={() => setHover(null)} className={hover === b.key ? "on" : undefined}>
                  <title>{`${b.title ?? b.key}：${b.text}`}</title>
                  <rect x={x} y={0} width={bw} height={H} className="t-hit" />
                  {b.value > 0 && <path d={`M${x},${H} V${H - bh + Math.min(3, bh)} Q${x},${H - bh} ${x + Math.min(3, bw / 2)},${H - bh} H${x + bw - Math.min(3, bw / 2)} Q${x + bw},${H - bh} ${x + bw},${H - bh + Math.min(3, bh)} V${H} Z`} className="t-mark" />}
                  {i % every === 0 && <text x={x + bw / 2} y={H + 13} textAnchor="middle" className="t-tick">{typeof b.label === "string" ? b.label : b.key}</text>}
                </g>
              );
            })}
          </svg>
        </div>
      )}
    </Frame>
  );
}

export type Seg = { key: string; label: string; n: number; cls: string };

/** 分段条：一行一个分组，段按类别，段内写数字；图例在上，颜色之外另有纹理与文字。 */
export function SegBars({ title, note, rows, cats, data }: { title: string; note?: React.ReactNode; rows: { key: string; label: string; segs: Seg[] }[]; cats: { key: string; label: string; cls: string }[]; data?: string }) {
  const table = (
    <table className="mini wide" data-chart-table>
      <thead><tr><th />{cats.map((c) => <th key={c.key} className="r">{c.label}</th>)}</tr></thead>
      <tbody>{rows.map((r) => <tr key={r.key}><td>{r.label}</td>{cats.map((c) => <td key={c.key} className="r k-mono">{r.segs.find((s) => s.key === c.key)?.n ?? 0}</td>)}</tr>)}</tbody>
    </table>
  );
  return (
    <Frame title={title} note={note} table={table} data={data}>
      <p className="ch-legend t2">{cats.map((c) => <span key={c.key}><i className={`sw ${c.cls}`} />{c.label}</span>)}</p>
      <ul className="ch-seg">
        {rows.map((r) => {
          const total = r.segs.reduce((a, s) => a + s.n, 0);
          return (
            <li key={r.key} data-seg-row={r.key}>
              <span className="ch-l">{r.label}<span className="t2 k-mono"> {total}</span></span>
              <span className="ch-segbar">
                {total === 0 ? <span className="t2">—</span> : r.segs.filter((s) => s.n > 0).map((s) => (
                  <b key={s.key} className={s.cls} style={{ flexGrow: s.n }} title={`${r.label} · ${s.label}：${s.n}`} data-seg={s.key}>{s.n}</b>
                ))}
              </span>
            </li>
          );
        })}
      </ul>
    </Frame>
  );
}

/** 指标格：大数字、标签与一行注；可点。 */
export function Tile({ label, value, sub, onClick, data }: { label: string; value: React.ReactNode; sub?: React.ReactNode; onClick?: () => void; data?: string }) {
  const body = <><span className="k-cap">{label}</span><span className="big num">{value}</span>{sub && <span className="t2">{sub}</span>}</>;
  return onClick
    ? <button type="button" className="tile click" onClick={onClick} data-tile={data ?? label}>{body}</button>
    : <div className="tile" data-tile={data ?? label}>{body}</div>;
}
