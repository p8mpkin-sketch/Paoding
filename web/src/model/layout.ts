// 图布局（HMI 设计 §3.9，P-H2）。坐标是视图模型的纯函数：
// - 排序键只有节点的创建 seq（并列时比 id），不用随机初值，不用计时；
// - 列 = 1 + 前提里最大的列。前提在创建时写定、只能指向更早的节点，所以一个节点的列永不改变；
// - 行 = 同列里比它早的节点数。新节点只追加在各列末尾，不挪动已有节点。
// 所以同一 as_of 两次渲染坐标逐点相同，时间轴向前拖时图只长大、不重排（HT-14）。

export type LayoutInput = {
  nodes: { id: string; kind: "fact" | "intent"; created_seq: number; premises: string[] }[];
  hints: { id: string; created_seq: number; about?: string }[];
};
export type Placed = { id: string; kind: "fact" | "intent" | "hint"; x: number; y: number; col: number; row: number };
export type Edge = { from: string; to: string; kind: "premise" | "about" };
export type Layout = { nodes: Placed[]; edges: Edge[]; width: number; height: number };

export const CELL = { w: 190, h: 64, gapX: 50, gapY: 22, pad: 20, hintLane: 70 } as const;

const bySeq = <T extends { created_seq: number; id: string }>(a: T, b: T) =>
  a.created_seq - b.created_seq || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);

export function layout(input: LayoutInput): Layout {
  const placed = new Map<string, Placed>();
  const rows: number[] = [];
  const edges: Edge[] = [];
  const out: Placed[] = [];
  const hints = [...input.hints].sort(bySeq);

  hints.forEach((h, k) => {
    const p: Placed = { id: h.id, kind: "hint", col: k, row: -1, x: CELL.pad + k * (CELL.w + CELL.gapX), y: CELL.pad };
    placed.set(h.id, p);
    out.push(p);
  });

  for (const n of [...input.nodes].sort(bySeq)) {
    let col = 0;
    for (const pr of n.premises) {
      const p = placed.get(pr);
      if (!p || p.kind === "hint") continue; // 未知的引用不参与布局；Hint 不能作前提
      col = Math.max(col, p.col + 1);
      edges.push({ from: pr, to: n.id, kind: "premise" });
    }
    const row = rows[col] ?? 0;
    rows[col] = row + 1;
    const p: Placed = {
      id: n.id, kind: n.kind, col, row,
      x: CELL.pad + col * (CELL.w + CELL.gapX),
      y: CELL.pad + CELL.hintLane + row * (CELL.h + CELL.gapY),
    };
    placed.set(n.id, p);
    out.push(p);
  }

  for (const h of hints) {
    const t = h.about ? placed.get(h.about) : undefined;
    if (t && t.kind !== "hint") edges.push({ from: h.id, to: t.id, kind: "about" });
  }

  let maxRows = 1;
  for (let c = 0; c < rows.length; c++) maxRows = Math.max(maxRows, rows[c] ?? 0);
  const cols = Math.max(rows.length, hints.length, 1);
  return {
    nodes: out,
    edges,
    width: CELL.pad * 2 + cols * CELL.w + (cols - 1) * CELL.gapX,
    height: CELL.pad * 2 + CELL.hintLane + maxRows * (CELL.h + CELL.gapY),
  };
}
