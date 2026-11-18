// 等级词表（HMI 设计 §3.3）。词由图服务给出（level_word，与 pd 同源），前端不另造说法；
// E3、E3d、X 三档按词表要求带上判官名。
import type { Badge, Level, Terminal } from "../api/types";

export function levelWord(level: Level | null, word: string | null, badge: Pick<Badge, "label"> | null): string {
  if (!level) return "无等级";
  const base = word ?? level;
  return (level === "E3" || level === "E3d" || level === "X") && badge ? `${base}（${badge.label}）` : base;
}

/** 终态三值。accepted 在任何地方不得显示为"已证明"。 */
export function terminalWord(t: Terminal | null): string {
  switch (t) {
    case "solved": return "solved · 判官确认";
    case "accepted": return "accepted · 人验收";
    case "unsolved": return "unsolved";
    case null: return "进行中";
  }
}

export const GRADE_WORD = { decisive: "判定性", consistent: "相符性", advisory: "建议性" } as const;
export const INTENT_STATE_WORD = {
  open: "待做", blocked: "等前提", leased: "在做", done: "已结束", achieved: "已达成", needs_human: "待人处理", abandoned: "已放弃",
} as const;
