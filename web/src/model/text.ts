// 渲染安全（HMI 设计 §13.1 第 4 条）：控制字符、双向文本控制符与超长行在渲染前可见化。
// 一切文本按纯文本渲染（由 React 的文本节点保证）；这里只负责"看得见"。

const MAX_LINE = 400;

/** C0（除换行与制表）、DEL、C1、零宽字符、双向控制符、行与段分隔符、BOM。 */
function invisible(cp: number): boolean {
  return (
    (cp <= 0x1f && cp !== 0x0a && cp !== 0x09) ||
    (cp >= 0x7f && cp <= 0x9f) ||
    cp === 0x061c ||
    (cp >= 0x200b && cp <= 0x200f) ||
    (cp >= 0x2028 && cp <= 0x202e) ||
    (cp >= 0x2060 && cp <= 0x2069) ||
    cp === 0xfeff
  );
}

export function visible(text: string): string {
  let out = "";
  for (const ch of text.split("\r\n").join("\n")) {
    const cp = ch.codePointAt(0)!;
    out += invisible(cp) ? `\\u{${cp.toString(16).toUpperCase().padStart(4, "0")}}` : ch;
  }
  return out
    .split("\n")
    .map((line) => (line.length > MAX_LINE ? `${line.slice(0, MAX_LINE)}⟪行长 ${line.length}，余下已折叠⟫` : line))
    .join("\n");
}

/** 截断输出只显示头尾（全文按区间读取）。 */
export function headTail(text: string, lines = 20): { head: string; tail: string | null; omitted: number } {
  const all = text.split("\n");
  if (all.length <= lines * 2) return { head: text, tail: null, omitted: 0 };
  return { head: all.slice(0, lines).join("\n"), tail: all.slice(-lines).join("\n"), omitted: all.length - lines * 2 };
}

export const shortHash = (h: string) => (h.length > 16 ? `${h.slice(0, 8)}…${h.slice(-4)}` : h);
/** 金额（美元；内部单位是千分之一美元）。阅读质量轮第 9 条：两位小数加千分位，不足一分写“< $0.01”，
 *  始终带“$”、从不写三位小数，免得读成“元·角·分”。 */
export function usd(milli: number): string {
  if (milli === 0) return "$0.00";
  const sign = milli < 0 ? "-" : "";
  const a = Math.abs(milli);
  if (a < 10) return `${sign}< $0.01`;
  const cents = Math.round(a / 10);
  const whole = Math.floor(cents / 100).toLocaleString("en-US");
  return `${sign}$${whole}.${String(cents % 100).padStart(2, "0")}`;
}
