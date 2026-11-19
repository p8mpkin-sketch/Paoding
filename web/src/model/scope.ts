// 扩权卡的纯函数（runtime-grants §7.1）。只帮人读，不替人判：原文对照只是字面查找，不作任何判断依据。

/** 题面按空行分段，找出提到申请地址的段：先找 host:port 原样，找不到再找 host。段号从 1 起。 */
export function mentionsOf(statement: string, target: string): { para: number; text: string; exact: boolean }[] {
  const host = target.includes(":") ? target.slice(0, target.lastIndexOf(":")) : target;
  const paras = statement.split(/\n\s*\n/).map((p) => p.trim()).filter((p) => p !== "");
  const hit = (needle: string) => paras.flatMap((text, i) => (needle && text.includes(needle) ? [{ para: i + 1, text }] : []));
  const exact = hit(target);
  if (exact.length) return exact.map((m) => ({ ...m, exact: true }));
  return host === target ? [] : hit(host).map((m) => ({ ...m, exact: false }));
}

/** 段号写成带圈数字（① 到 ⑳），更多的写成 §n。 */
export const paraMark = (n: number): string => (n >= 1 && n <= 20 ? String.fromCodePoint(0x245f + n) : `§${n}`);

/** 风险从哪来，给人读的一句。rows 为 null 是旧事件（申请时没有记下）。 */
export function riskSource(rows: (number | null)[] | null, k: number): string {
  if (rows === null) return "风险表查得（旧申请未记行号）";
  const r = rows[k];
  return r === null || r === undefined ? "风险表未命中，按缺省 r2" : `风险表第 ${r} 条`;
}

/** 画像哪几轴变了：[轴, 前, 后]。 */
export function profileChanges<P extends Record<string, string>>(before: P, after: P): [string, string, string][] {
  return (Object.keys(before) as (keyof P & string)[]).filter((k) => before[k] !== after[k]).map((k) => [k, before[k], after[k]]);
}
