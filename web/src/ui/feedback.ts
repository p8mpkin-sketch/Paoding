// 操作反馈三段式：提交中 → 已记录（带 seq）→ 被拒（拒绝码翻成人话，原文放在说明里）。
// 不做乐观更新：界面只在服务端推来新状态后才变，提示条填补这段等待。
import { toast } from "sonner";

export type Pending = string | number;

export function pending(what: string): Pending {
  return toast.loading(`${what}：提交中…`);
}

export function recorded(id: Pending, what: string, seq: number | null, note?: string): void {
  toast.success(seq === null ? `${what}：已记录` : `${what}：已记录 · seq ${seq}`, { id, description: note, duration: 5000 });
}

export function rejected(id: Pending, what: string, reason: string): void {
  toast.error(`${what}：没成功`, { id, description: reason, duration: 9000 });
}
