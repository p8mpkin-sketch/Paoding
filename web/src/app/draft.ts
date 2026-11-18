// 向导草稿只存本机（HMI §2 禁令 2：草稿不影响任何派生量）。已上传材料的哈希一并存，字节在服务端。
import type { Draft } from "../model/wizard";

const KEY = "paoding.wizard_draft";

export function loadDraft(): { draft: Draft; step: number } | null {
  try {
    const raw = globalThis.localStorage?.getItem(KEY);
    if (!raw) return null;
    const v = JSON.parse(raw) as { draft?: Draft; step?: number };
    return v.draft && Array.isArray(v.draft.materials) ? { draft: v.draft, step: Number.isInteger(v.step) ? v.step! : 0 } : null;
  } catch {
    return null;
  }
}

export function saveDraft(draft: Draft, step: number): void {
  try {
    globalThis.localStorage?.setItem(KEY, JSON.stringify({ draft, step }));
  } catch {
    /* 存不了就只在本页 */
  }
}

export function clearDraft(): void {
  try {
    globalThis.localStorage?.removeItem(KEY);
  } catch {
    /* 无所谓 */
  }
}
