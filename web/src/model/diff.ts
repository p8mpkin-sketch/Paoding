// 两张卡片字段的差异路径。只是前端的便利（P-H3）：判定以服务端的 stale_view 为准。
export function diffPaths(a: unknown, b: unknown, path = ""): string[] {
  if (a === b) return [];
  if (a === null || b === null || typeof a !== "object" || typeof b !== "object" || Array.isArray(a) !== Array.isArray(b)) {
    return [path || "(整张卡)"];
  }
  const ao = a as Record<string, unknown>;
  const bo = b as Record<string, unknown>;
  const keys = [...new Set([...Object.keys(ao), ...Object.keys(bo)])].sort();
  return keys.flatMap((k) => diffPaths(ao[k], bo[k], path ? `${path}.${k}` : k));
}
