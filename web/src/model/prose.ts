// 答案正文的排版模型（任务页“结果”一栏）。会话写的答案多半是 Markdown：这里把它切成块（标题、段落、列表、表格、
// 代码、引文、分隔线）和行内片段（代码、加粗、哈希），交给 ui/Prose.tsx 排版。
// 只切文本，不产出任何标记：每个片段最后都作为纯文本节点放进页面，不解析 HTML，不把网址变成链接。
// 纯函数，不读时钟、不发请求；认不出的写法一律按段落原样留着。

export type Inline = { k: "text" | "code" | "strong" | "hash"; v: string };
export type Align = "left" | "right" | "center" | null;
/** 列的种类：由整列的内容看出来，决定对齐、换行与单元格的样式。
 *  key 行的名字（首列、短）；num 数；tag 短的档位词（高/中/低、P0…）；hash 摘要值；text 其余。 */
export type ColKind = "key" | "num" | "tag" | "hash" | "text";
export type ListItem = { inl: Inline[]; children: ListBlock | null };
export type ListBlock = { k: "list"; ordered: boolean; start: number; items: ListItem[] };
export type TableBlock = { k: "table"; head: Inline[][]; align: Align[]; kinds: ColKind[]; rows: Inline[][][] };
export type Block =
  | { k: "p"; inl: Inline[] }
  | { k: "h"; level: 1 | 2 | 3; inl: Inline[] }
  | ListBlock
  | TableBlock
  | { k: "code"; lang: string; text: string }
  | { k: "quote"; inl: Inline[] }
  | { k: "hr" };

/** 摘要值：32 到 64 位十六进制（md5、sha1、sha256），可带 “sha256:” 这类前缀；必须同时有数字和字母。 */
const HASH = /^(?:[a-z0-9]{2,8}:)?([0-9a-f]{32,64})$/i;
export function hashOf(s: string): string | null {
  const m = HASH.exec(s.trim());
  if (!m || ![32, 40, 56, 64].includes(m[1].length)) return null;
  return /[0-9]/.test(m[1]) && /[a-f]/i.test(m[1]) ? m[1] : null;
}

const INLINE = /(`+)([^`\n]+?)\1|\*\*([^*\n]+?)\*\*|__([^_\n]+?)__|(?<![0-9a-zA-Z_])((?:[a-z0-9]{2,8}:)?[0-9a-f]{32,64})(?![0-9a-zA-Z_])/gi;

export function inline(text: string): Inline[] {
  const out: Inline[] = [];
  const push = (k: Inline["k"], v: string) => {
    if (!v) return;
    const last = out.at(-1);
    if (k === "text" && last?.k === "text") last.v += v;
    else out.push({ k, v });
  };
  let at = 0;
  for (const m of text.matchAll(INLINE)) {
    const i = m.index;
    push("text", text.slice(at, i));
    if (m[2] !== undefined) push(hashOf(m[2]) ? "hash" : "code", m[2].trim());
    else if (m[3] !== undefined || m[4] !== undefined) push("strong", m[3] ?? m[4]);
    else if (hashOf(m[5])) push("hash", m[5]);
    else push("text", m[0]);
    at = i + m[0].length;
  }
  push("text", text.slice(at));
  return out;
}

export const plainOf = (inl: Inline[]): string => inl.map((x) => x.v).join("");

/** 表格的一行切成格：反引号里的竖线与 “\|” 不算分隔。 */
export function cells(line: string): string[] {
  const s = line.trim().replace(/^\|/, "").replace(/\|\s*$/, (m, off: number, all: string) => (all[off - 1] === "\\" ? m : ""));
  const out: string[] = [];
  let cur = "";
  let tick = false;
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (c === "\\" && s[i + 1] === "|") { cur += "|"; i++; continue; }
    if (c === "`") tick = !tick;
    if (c === "|" && !tick) { out.push(cur.trim()); cur = ""; continue; }
    cur += c;
  }
  out.push(cur.trim());
  return out;
}

const SEP = /^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$/;
const NUM = /^[-+−]?[$¥€£]?\s?\d[\d,]*(\.\d+)?\s?(%|‰|[a-zA-Zµ]{1,5}|[秒分时天次个条行元倍])?$/;
/** 档位词分三级（只表示“多少”，不表示好坏：置信高是好事，风险高不是）。 */
const LEVEL: Record<string, "hi" | "mid" | "lo"> = {
  高: "hi", 很高: "hi", 极高: "hi", 强: "hi", 大: "hi", high: "hi", h: "hi", p0: "hi", 严重: "hi", 紧急: "hi",
  中: "mid", 中等: "mid", 中高: "mid", 中低: "mid", 一般: "mid", medium: "mid", med: "mid", m: "mid", p1: "mid",
  低: "lo", 很低: "lo", 极低: "lo", 弱: "lo", 小: "lo", low: "lo", l: "lo", p2: "lo", p3: "lo", 无: "lo",
};
export const levelOf = (s: string): "hi" | "mid" | "lo" | null => LEVEL[s.trim().toLowerCase()] ?? null;
const len = (s: string) => [...s].length;

function kindsOf(rows: Inline[][][], n: number): ColKind[] {
  return Array.from({ length: n }, (_, c) => {
    const vals = rows.map((r) => plainOf(r[c] ?? []).trim()).filter(Boolean);
    if (vals.length === 0) return "text";
    if (vals.every((v) => hashOf(v))) return "hash";
    if (vals.every((v) => NUM.test(v))) return "num";
    if (c === 0) return vals.every((v) => len(v) <= 16) ? "key" : "text";
    // 档位列：都很短、取值不多，且至少有一个认得的档位词（免得把“有/无”以外的短词误当档位）
    if (vals.every((v) => len(v) <= 4) && new Set(vals).size <= 6 && vals.some((v) => levelOf(v))) return "tag";
    return "text";
  });
}

function table(lines: string[]): TableBlock {
  const hasSep = lines.length >= 2 && SEP.test(lines[1]);
  const head = cells(lines[0]);
  const n = head.length;
  const align: Align[] = hasSep
    ? cells(lines[1]).map((c) => (/^:-+:$/.test(c) ? "center" : /-:$/.test(c) ? "right" : /^:-/.test(c) ? "left" : null))
    : [];
  // 每行补齐或并到表头的列数：多出来的格并进最后一列，不丢字
  const rows = lines.slice(hasSep ? 2 : 1).map((l) => {
    const c = cells(l);
    const fit = c.length > n ? [...c.slice(0, n - 1), c.slice(n - 1).join(" | ")] : [...c, ...Array<string>(n - c.length).fill("")];
    return fit.map(inline);
  });
  return { k: "table", head: head.map(inline), align: Array.from({ length: n }, (_, i) => align[i] ?? null), kinds: kindsOf(rows, n), rows };
}

const ITEM = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/;
const FENCE = /^\s*(```+|~~~+)\s*([\w+#.-]*)\s*$/;
const HEAD = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
const RULE = /^\s{0,3}([-*_])(\s*\1){2,}\s*$/;
const QUOTE = /^\s{0,3}>\s?(.*)$/;
const isRow = (l: string) => l.trim().startsWith("|");

/** 列表嵌套的层数上限（含最外一层）。 */
export const LIST_DEPTH = 32;

function list(lines: string[]): ListBlock {
  type Raw = { indent: number; ordered: boolean; start: number; text: string };
  const raw: Raw[] = [];
  for (const l of lines) {
    const m = ITEM.exec(l);
    if (m) raw.push({ indent: m[1].replace(/\t/g, "    ").length, ordered: /\d/.test(m[2]), start: Number.parseInt(m[2], 10) || 1, text: m[3] });
    else if (raw.length) raw[raw.length - 1].text += `\n${l.trim()}`;      // 续行并进上一项
  }
  // 用一个栈按缩进搭树，不递归：缩进每行多一格的畸形答案可以有上万层，递归会把调用栈撑爆。
  // 嵌套最多 LIST_DEPTH 层；更深的缩进并进最深的那一层，当作它的同级项，内容一个字不丢。
  const root: ListBlock = { k: "list", ordered: raw[0].ordered, start: raw[0].start, items: [] };
  const stack: { block: ListBlock; indent: number }[] = [{ block: root, indent: raw[0].indent }];
  for (const r of raw) {
    while (stack.length > 1 && r.indent < stack[stack.length - 1].indent) stack.pop();
    const top = stack[stack.length - 1];
    if (r.indent > top.indent && top.block.items.length > 0 && stack.length < LIST_DEPTH) {
      const child: ListBlock = { k: "list", ordered: r.ordered, start: r.start, items: [{ inl: inline(r.text), children: null }] };
      top.block.items[top.block.items.length - 1].children = child;
      stack.push({ block: child, indent: r.indent });
    } else {
      top.block.items.push({ inl: inline(r.text), children: null });
    }
  }
  return root;
}

export function parse(text: string): Block[] {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const out: Block[] = [];
  let para: string[] = [];
  const flush = () => { if (para.length) { out.push({ k: "p", inl: inline(para.join("\n")) }); para = []; } };
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    const f = FENCE.exec(l);
    if (f) {
      flush();
      const body: string[] = [];
      let j = i + 1;
      for (; j < lines.length && !(lines[j].trim().startsWith(f[1]) && lines[j].trim().replace(/[`~]/g, "") === ""); j++) body.push(lines[j]);
      out.push({ k: "code", lang: f[2], text: body.join("\n") });
      i = j;
      continue;
    }
    if (l.trim() === "") { flush(); continue; }
    const h = HEAD.exec(l);
    if (h) { flush(); out.push({ k: "h", level: Math.min(h[1].length, 3) as 1 | 2 | 3, inl: inline(h[2]) }); continue; }
    if (RULE.test(l)) { flush(); out.push({ k: "hr" }); continue; }
    if (isRow(l) && i + 1 < lines.length && isRow(lines[i + 1])) {
      flush();
      let j = i;
      while (j < lines.length && isRow(lines[j])) j++;
      out.push(table(lines.slice(i, j)));
      i = j - 1;
      continue;
    }
    if (ITEM.test(l)) {
      flush();
      let j = i + 1;
      // 列表一直到空行为止；空行后面紧跟着还是列表项的，算同一个列表
      for (; j < lines.length; j++) {
        if (lines[j].trim() === "") { if (j + 1 < lines.length && ITEM.test(lines[j + 1])) continue; break; }
        if (FENCE.test(lines[j]) || HEAD.test(lines[j]) || (isRow(lines[j]) && !ITEM.test(lines[j]))) break;
      }
      out.push(list(lines.slice(i, j).filter((x) => x.trim() !== "")));
      i = j - 1;
      continue;
    }
    const q = QUOTE.exec(l);
    if (q) {
      flush();
      const body = [q[1]];
      let j = i + 1;
      for (; j < lines.length && QUOTE.test(lines[j]); j++) body.push(QUOTE.exec(lines[j])![1]);
      out.push({ k: "quote", inl: inline(body.join("\n")) });
      i = j - 1;
      continue;
    }
    para.push(l);
  }
  flush();
  return out;
}

/** 表格抄成制表符分隔的文本（贴进表格软件用）：格里的换行与制表符换成空格。 */
export function tsv(t: TableBlock): string {
  const cell = (inl: Inline[]) => plainOf(inl).replace(/[\t\n]+/g, " ");
  return [t.head, ...t.rows].map((r) => r.map(cell).join("\t")).join("\n");
}
