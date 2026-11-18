// 时间轴刻度（HMI 设计 §10.4）。刻度只来自事件，位置只用 seq。
import type { Event } from "../api/types";

export type TickKind = "H" | "A" | "50%" | "80%" | "J✓" | "J✗" | "J?" | "!" | "L" | "C";
export type Tick = { seq: number; ts: number; kind: TickKind; label: string };

export const TICK_LEGEND: Record<TickKind, string> = {
  H: "Hint", A: "审批或拒绝", "50%": "预算 50% 标记", "80%": "预算 80% 标记",
  "J✓": "判官裁决：通过", "J✗": "判官裁决：失败", "J?": "判官裁决：无结论",
  "!": "告警或越界", L: "租约起止", C: "关题",
};

function kindOf(ev: Event): TickKind | null {
  const b = ev.body as Record<string, unknown>;
  switch (ev.kind) {
    case "hint": return "H";
    case "approve": return "A";
    case "budget_mark": return b.mark === 80 ? "80%" : b.mark === 50 ? "50%" : "!";
    case "judge_verdict": return b.result === "pass" ? "J✓" : b.result === "fail" ? "J✗" : "J?";
    case "alert": case "scope_violation": return "!";
    case "lease": case "release": case "expire_lease": return "L";
    case "accept": case "close_problem": case "case_sealed": return "C";
    default: return null;
  }
}

export function ticksOf(events: readonly Event[], asOf: number): Tick[] {
  const out: Tick[] = [];
  for (const ev of events) {
    if (ev.seq > asOf) continue;
    const kind = kindOf(ev);
    if (kind) out.push({ seq: ev.seq, ts: ev.ts, kind, label: `${TICK_LEGEND[kind]} · ${ev.kind} · seq ${ev.seq}` });
  }
  return out.sort((a, b) => a.seq - b.seq);
}
