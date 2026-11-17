// 本地哈希：视图模型哈希（HT-10）与 Blob 的本地校验（HT-6）共用。
export async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", bytes as BufferSource);
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** 键排序的 JSON。只用于前端自己的视图模型哈希，不冒充 JCS，也不用来算 card_hash。 */
export function stableJson(v: unknown): string {
  if (v === null || typeof v !== "object") return JSON.stringify(v) ?? "null";
  if (Array.isArray(v)) return `[${v.map(stableJson).join(",")}]`;
  const o = v as Record<string, unknown>;
  const keys = Object.keys(o).filter((k) => o[k] !== undefined).sort();
  return `{${keys.map((k) => `${JSON.stringify(k)}:${stableJson(o[k])}`).join(",")}}`;
}

export const hashOf = (v: unknown): Promise<string> => sha256Hex(new TextEncoder().encode(stableJson(v)));
