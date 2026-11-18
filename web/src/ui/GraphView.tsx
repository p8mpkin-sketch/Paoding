// 图可视化（感知官，T-1；HMI 设计 §3.8、§3.9）。坐标全部来自 model/layout.ts 的确定性布局。
// 三种节点形状不同：论断是直角矩形，Intent 是圆角矩形，Hint 是菱形（Hint 只能用 about 边指向节点）。
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

export function GraphView({ vm, selected, onSelect }: { vm: ViewModel; selected: string | null; onSelect: (id: string) => void }) {
  const { layout } = vm;
  const pos = new Map(layout.nodes.map((n) => [n.id, n]));
  const rows = new Map(vm.rows.map((r) => [r.id, r]));
  const hints = new Map(vm.hints.map((h) => [h.id, h]));
  return (
    <div className="graph-wrap">
      <svg className="graph" width={layout.width} height={layout.height} viewBox={`0 0 ${layout.width} ${layout.height}`} role="img" aria-label={`解牛图，seq ${vm.seq}`}>
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
          return (
            <g key={n.id} data-graph-node={n.id} data-x={n.x} data-y={n.y} className={`gnode gnode-${n.kind}${selected === n.id ? " selected" : ""} level-${r.level ?? "none"}`} onClick={() => onSelect(n.id)}>
              <rect x={n.x} y={n.y} width={CELL.w} height={CELL.h} rx={n.kind === "intent" ? 18 : 0} />
              <text x={n.x + 8} y={n.y + 18} className="g-id">{clip(`${n.id}${r.level ? ` · ${r.level}` : ""}${r.predicate ? ` · ${r.predicate.label}` : ""}`, 22)}</text>
              <text x={n.x + 8} y={n.y + 36} className="g-pred">{clip(r.predicateText ?? (n.kind === "fact" ? "推断" : "Intent"), 22)}</text>
              <text x={n.x + 8} y={n.y + 54} className="g-title">“{clip(r.title.value, 22)}”</text>
            </g>
          );
        })}
      </svg>
      <p className="muted">布局只由创建 seq 决定：同一 as_of 坐标相同，时间轴向前拖时只增不挪。直角 = 论断，圆角 = Intent，菱形 = Hint。</p>
    </div>
  );
}
