// 时间轴刻度（HMI 设计 §10.4）。刻度只来自事件，位置只用 seq。
// 冷启动时刻度取自 /ticks（每条事件只有 seq、ts、种类），之后从事件流逐条追加；两条路得到同一份刻度（HT-10）。
import type { Event, WireTick } from "../api/types";

export type TickKind = "H" | "A" | "50%" | "80%" | "J✓" | "J✗" | "J?" | "!" | "L" | "C";
export type Tick = { seq: number; ts: number; kind: TickKind; label: string };

export const TICK_LEGEND: Record<TickKind, string> = {
  H: "Hint", A: "审批或拒绝", "50%": "预算 50% 标记", "80%": "预算 80% 标记",
  "J✓": "判官裁决：通过", "J✗": "判官裁决：失败", "J?": "判官裁决：无结论",
  "!": "告警或越界", L: "租约起止", C: "关题",
};

/** 一条事件在时间轴上需要的全部字段（与 /ticks 的一项同形）。 */
export function toWireTick(ev: Event): WireTick {
  const b = ev.body as Record<string, unknown>;
  const t: WireTick = { seq: ev.seq, ts: ev.ts, kind: ev.kind };
  if (ev.kind === "judge_verdict" && typeof b.result === "string") t.result = b.result as WireTick["result"];
  if (ev.kind === "budget_mark" && typeof b.mark === "number") t.mark = b.mark;
  return t;
}

function kindOf(t: WireTick): TickKind | null {
  switch (t.kind) {
    case "hint": return "H";
    case "approve": return "A";
    case "budget_mark": return t.mark === 80 ? "80%" : t.mark === 50 ? "50%" : "!";
    case "judge_verdict": return t.result === "pass" ? "J✓" : t.result === "fail" ? "J✗" : "J?";
    case "alert": case "scope_violation": return "!";
    case "lease": case "release": case "expire_lease": return "L";
    case "accept": case "close_problem": case "case_sealed": return "C";
    default: return null;
  }
}

export function ticksOf(items: readonly WireTick[], asOf: number): Tick[] {
  const out: Tick[] = [];
  for (const t of items) {
    if (t.seq > asOf) continue;
    const kind = kindOf(t);
    if (kind) out.push({ seq: t.seq, ts: t.ts, kind, label: `${TICK_LEGEND[kind]} · ${t.kind} · seq ${t.seq}` });
  }
  return out.sort((a, b) => a.seq - b.seq);
}
