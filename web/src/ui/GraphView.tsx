// 图可视化（感知官，T-1；HMI 设计 §3.8、§3.9）。坐标全部来自 model/layout.ts 的确定性布局。
// 三种节点形状不同：论断是直角矩形，Intent 是圆角矩形，Hint 是菱形（Hint 只能用 about 边指向节点）。
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { CELL } from "../model/layout";
import type { ViewModel } from "../model/viewmodel";
import { visible } from "../model/text";

/** 按显示宽度截断：非 ASCII 字符算两格。 */
function clip(s: string, cells: number): string {
  let used = 0;
  let out = "";
  for (const ch of visible(s)) {
    used += ch.codePointAt(0)! > 0x7f ? 2 : 1;
    if (used > cells) return `${out}…`;
    out += ch;
  }
  return out;
}

/** 视口：缩放倍数与平移量（屏幕像素）。只是本机的看法，不进任何派生量。 */
export type Viewport = { k: number; x: number; y: number };
export const ZOOM = { min: 0.25, max: 4, step: 1.25 } as const;
const clampK = (k: number) => Math.min(ZOOM.max, Math.max(ZOOM.min, k));
/** 以屏幕点 (cx, cy) 为中心缩放：这一点下的图坐标不动。 */
export function zoomAt(v: Viewport, factor: number, cx: number, cy: number): Viewport {
  const k = clampK(v.k * factor);
  const r = k / v.k;
  return { k, x: cx - (cx - v.x) * r, y: cy - (cy - v.y) * r };
}
const PAN = 60;

export function GraphView({ vm, selected, onSelect }: { vm: ViewModel; selected: string | null; onSelect: (id: string) => void }) {
  const { layout } = vm;
  const pos = new Map(layout.nodes.map((n) => [n.id, n]));
  const rows = new Map(vm.rows.map((r) => [r.id, r]));
  const hints = new Map(vm.hints.map((h) => [h.id, h]));
  const [v, setV] = useState<Viewport>({ k: 1, x: 0, y: 0 });
  const drag = useRef<{ id: number; x: number; y: number; moved: boolean } | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const center = () => {
    const r = box.current?.getBoundingClientRect();
    return r && r.width ? { cx: r.width / 2, cy: r.height / 2 } : { cx: 0, cy: 0 };
  };
  const zoom = useCallback((f: number) => setV((cur) => { const { cx, cy } = center(); return zoomAt(cur, f, cx, cy); }), []);
  const fit = () => {
    const r = box.current?.getBoundingClientRect();
    if (!r || !r.width || !layout.width) return setV({ k: 1, x: 0, y: 0 });
    const k = clampK(Math.min(r.width / layout.width, r.height / layout.height));
    setV({ k, x: (r.width - layout.width * k) / 2, y: (r.height - layout.height * k) / 2 });
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.target !== e.currentTarget) return;                     // 节点上的 Enter 归节点
    const d: Record<string, () => void> = {
      "+": () => zoom(ZOOM.step), "=": () => zoom(ZOOM.step), "-": () => zoom(1 / ZOOM.step), "0": () => setV({ k: 1, x: 0, y: 0 }),
      ArrowLeft: () => setV((c) => ({ ...c, x: c.x + PAN })), ArrowRight: () => setV((c) => ({ ...c, x: c.x - PAN })),
      ArrowUp: () => setV((c) => ({ ...c, y: c.y + PAN })), ArrowDown: () => setV((c) => ({ ...c, y: c.y - PAN })),
    };
    if (d[e.key]) { e.preventDefault(); d[e.key](); }
  };
  // 滚轮缩放要拦下页面滚动：React 的 onWheel 是被动监听，preventDefault 不生效，所以直接挂原生监听
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      setV((c) => zoomAt(c, e.deltaY < 0 ? ZOOM.step : 1 / ZOOM.step, e.clientX - r.left, e.clientY - r.top));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);
  const onDown = (e: PointerEvent) => { drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, moved: false }; };
  const onMove = (e: PointerEvent) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (!d.moved && Math.abs(dx) + Math.abs(dy) < 4) return;      // 小于 4 像素算点击，不算拖
    if (!d.moved) (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
    d.moved = true;
    d.x = e.clientX;
    d.y = e.clientY;
    setV((c) => ({ ...c, x: c.x + dx, y: c.y + dy }));
  };
  const onUp = () => { drag.current = null; };
  const activate = (id: string) => (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(id); }
  };
  return (
    <div className="graph-block">
      <div className="graph-ctl" role="toolbar" aria-label="图的缩放">
        <button type="button" className="btn-small" data-action="zoom-in" aria-label="放大" onClick={() => zoom(ZOOM.step)}>＋</button>
        <button type="button" className="btn-small" data-action="zoom-out" aria-label="缩小" onClick={() => zoom(1 / ZOOM.step)}>－</button>
        <button type="button" className="btn-small" data-action="zoom-fit" onClick={fit}>适合窗口</button>
        <button type="button" className="btn-small" data-action="zoom-reset" onClick={() => setV({ k: 1, x: 0, y: 0 })}>原大</button>
        <span className="muted" data-zoom={v.k.toFixed(2)}>{Math.round(v.k * 100)}%</span>
      </div>
      <div
        className="graph-wrap" ref={box} tabIndex={0} data-graph-viewport aria-label="图：方向键平移，+ − 缩放，0 复原；Tab 逐个节点，Enter 检视"
        onKeyDown={onKey} onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}
      >
        <svg className="graph" width="100%" height="100%" role="group" aria-label={`解牛图，seq ${vm.seq}`}>
          <g data-graph-transform transform={`translate(${v.x} ${v.y}) scale(${v.k})`}>
            {layout.edges.map((e) => {
              const a = pos.get(e.from)!;
              const b = pos.get(e.to)!;
              const about = e.kind === "about";
              const x1 = about ? a.x + CELL.w / 2 : a.x + CELL.w;
              const y1 = about ? a.y + 40 : a.y + CELL.h / 2;
              const x2 = about ? b.x + CELL.w / 2 : b.x;
              const y2 = about ? b.y : b.y + CELL.h / 2;
              return <line key={`${e.from}>${e.to}`} x1={x1} y1={y1} x2={x2} y2={y2} className={`edge edge-${e.kind}`} data-edge={`${e.from}>${e.to}`} />;
            })}
            {layout.nodes.map((n) => {
              if (n.kind === "hint") {
                const h = hints.get(n.id);
                const cx = n.x + CELL.w / 2;
                return (
                  <g key={n.id} data-graph-node={n.id} data-x={n.x} data-y={n.y} className={`gnode gnode-hint${h?.closed ? " closed" : ""}`}>
                    <polygon points={`${cx},${n.y} ${cx + 60},${n.y + 20} ${cx},${n.y + 40} ${cx - 60},${n.y + 20}`} />
                    <text x={cx} y={n.y + 24} textAnchor="middle">{n.id} · 人</text>
                  </g>
                );
              }
              const r = rows.get(n.id)!;
              // 可见的三行原样放在名字开头（WCAG 2.5.3 名称含可见文字），再补全称
              const l1 = clip(`${n.id}${r.level ? ` · ${r.level}` : ""}${r.predicate ? ` · ${r.predicate.label}` : ""}`, 22);
              const l2 = clip(r.predicateText ?? (n.kind === "fact" ? "推断" : "尝试"), 22);
              const l3 = `“${clip(r.title.value, 22)}”`;
              return (
                <g
                  key={n.id} data-graph-node={n.id} data-x={n.x} data-y={n.y} className={`gnode gnode-${n.kind}${selected === n.id ? " selected" : ""} level-${r.level ?? "none"}`}
                  tabIndex={0} role="button" aria-pressed={selected === n.id} aria-label={`${l1} ${l2} ${l3}；${n.kind === "fact" ? "论断" : "尝试"}，全称：${visible(r.title.value)}`}
                  onClick={() => { if (!drag.current?.moved) onSelect(n.id); }} onKeyDown={activate(n.id)}
                >
                  <rect x={n.x} y={n.y} width={CELL.w} height={CELL.h} rx={n.kind === "intent" ? 18 : 0} />
                  <text>
                    <tspan x={n.x + 8} y={n.y + 18} className="g-id">{l1}</tspan>{" "}
                    <tspan x={n.x + 8} y={n.y + 36} className="g-pred">{l2}</tspan>{" "}
                    <tspan x={n.x + 8} y={n.y + 54} className="g-title">{l3}</tspan>
                  </text>
                </g>
              );
            })}
          </g>
        </svg>
      </div>
      <p className="muted">布局只由创建 seq 决定：同一 as_of 坐标相同，时间轴向前拖时只增不挪。直角 = 论断，圆角 = 尝试，菱形 = 指导。滚轮或 + − 缩放，拖动或方向键平移。</p>
    </div>
  );
}
