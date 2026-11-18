// 导入题集（工作台设计 §1 模块二）：JSON 与 CSV 在本机解析成向导草稿，再逐题走与向导相同的提交路径。
// 这里只做格式转换，不补任何画像字段；校验仍用 problemsOf，提交体仍由 buildOpen 生成（HT-2 照样成立）。
import type { Risk } from "../api/types";
import type { Draft, DraftMaterial } from "./wizard";

const obj = (v: unknown): Record<string, unknown> => (v !== null && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {});
const str = (v: unknown, d = ""): string => (typeof v === "string" ? v : typeof v === "number" ? String(v) : d);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const RISKS = new Set(["r0", "r1", "r2"]);

const textSlot = (slot: string, text: string, kind: "text" | "link" = "text", required = false): DraftMaterial =>
  ({ slot, required, name: null, hash: null, size: 0, media_type: "", kind, text });

/** JSON 题集的一项 → 草稿。没给的字段沿用 base（通常是“不用模板”或某个模板的草稿）。 */
export function draftFromJson(x: unknown, base: Draft): Draft {
  const o = obj(x);
  const mats = Array.isArray(o.materials) ? o.materials.map(obj) : [];
  const budget = obj(o.budget);
  const env = obj(o.env);
  const scope = Array.isArray(o.scope) ? o.scope.map(obj) : null;
  return {
    ...base,
    id: str(o.id),
    title: str(o.title),
    statement: str(o.statement),
    materials: mats.length
      ? mats.map((m, i) => textSlot(str(m.slot, i === 0 ? "题面" : `材料 ${i}`), str(m.text), m.kind === "link" ? "link" : "text", i === 0))
      : base.materials.map((m) => ({ ...m })),
    judge: str(o.judge, base.judge),
    expect: o.expect !== undefined ? JSON.stringify(o.expect) : base.expect,
    maxAttempts: num(o.max_attempts) !== null ? String(o.max_attempts) : base.maxAttempts,
    accept: o.accept === "human" ? "human" : o.accept === "judge" ? "judge" : base.accept,
    scope: scope
      ? scope.map((r) => ({ resource: str(r.resource), pattern: str(r.pattern), actions: (Array.isArray(r.actions) ? r.actions.map((a) => str(a)) : []).join(","), risk: RISKS.has(str(r.risk)) ? (r.risk as Risk) : "" }))
      : base.scope.map((r) => ({ ...r })),
    usd: num(budget.usd_milli) !== null ? String(num(budget.usd_milli)! / 1000) : base.usd,
    wall_s: num(budget.wall_s) !== null ? String(budget.wall_s) : base.wall_s,
    verify_share: num(budget.verify_share) !== null ? String(budget.verify_share) : base.verify_share,
    bootstrap_share: num(budget.bootstrap_share) !== null ? String(budget.bootstrap_share) : base.bootstrap_share,
    env: { base: str(env.base, base.env.base), baseline_ref: str(env.baseline_ref, base.env.baseline_ref) },
    hint: str(o.hint),
  };
}

export function parseJsonBatch(text: string, base: Draft): Draft[] | Error {
  let v: unknown;
  try {
    v = JSON.parse(text);
  } catch {
    return new Error("不是合法的 JSON");
  }
  const list = Array.isArray(v) ? v : Array.isArray(obj(v).problems) ? (obj(v).problems as unknown[]) : null;
  if (!list) return new Error("要一个数组，或 {\"problems\": [...]}");
  return list.map((x) => draftFromJson(x, base));
}

/** RFC 4180 的 CSV：逗号分隔，双引号包字段，字段里的双引号写两遍，引号里可以换行。空行跳过。 */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [], cell = "", quoted = false;
  const s = text.replace(/^\uFEFF/, "");
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (quoted) {
      if (c === '"' && s[i + 1] === '"') { cell += '"'; i++; }
      else if (c === '"') quoted = false;
      else cell += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") { row.push(cell); cell = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && s[i + 1] === "\n") i++;
      row.push(cell); cell = "";
      if (row.some((x) => x !== "")) rows.push(row);
      row = [];
    } else cell += c;
  }
  row.push(cell);
  if (row.some((x) => x !== "")) rows.push(row);
  return rows;
}

/** CSV 列 → 草稿字段。-1 即不映射。只映射文字类字段；判官、scope、预算等取自 base（模板或手填的那一份）。 */
export type CsvMapping = { id: number; title: number; statement: number; material: number };
export const CSV_TARGETS: { key: keyof CsvMapping; word: string }[] = [
  { key: "id", word: "题目 id" },
  { key: "title", word: "题名" },
  { key: "statement", word: "目标陈述" },
  { key: "material", word: "材料：题面（文字）" },
];

/** 按表头名猜一个初始映射（只是方便，人可改）。 */
export function guessMapping(header: string[]): CsvMapping {
  const find = (...names: string[]) => header.findIndex((h) => names.includes(h.trim().toLowerCase()));
  return { id: find("id", "题目id", "题目 id"), title: find("title", "name", "题名", "名称"), statement: find("statement", "goal", "目标", "目标陈述"), material: find("question", "text", "题面", "描述", "description") };
}

export function draftsFromCsv(rows: string[][], m: CsvMapping, base: Draft): Draft[] {
  const at = (r: string[], i: number) => (i >= 0 ? (r[i] ?? "").trim() : "");
  return rows.slice(1).map((r, k) => ({
    ...base,
    id: at(r, m.id) || (base.id ? `${base.id}-${k + 1}` : ""),
    title: at(r, m.title),
    statement: at(r, m.statement) || base.statement,
    materials: m.material >= 0 ? [textSlot("题面", r[m.material] ?? "", "text", true)] : base.materials.map((x) => ({ ...x })),
    scope: base.scope.map((x) => ({ ...x })),
  }));
}
