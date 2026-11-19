// 一句话开题的视图模型（设计 docs/design/kaiti §7）。这里只排版起草服务给出的校验结果，不推导任何字段：
// 抽取、校验、分道都在服务端的同一个纯函数里（qicao 的 vet），前端没有第二份规则。
import type { Op, ProblemInput, Risk, VaultRef } from "../api/types";
import type { KaitiRow, KaitiSource, KaitiSpan, KaitiVetted } from "../api/kaiti";
import type { MarkTone } from "../kit";
import type { Draft, MarkedField } from "./wizard";

/** 出处记号：形状加文字，不靠颜色。朱色不用在这里（朱只标"需要你"）。 */
export const SOURCE: Record<KaitiSource, { ch: string; tone: MarkTone; word: string }> = {
  span: { ch: "摘", tone: "jie", word: "逐字摘自原文" },
  table: { ch: "表", tone: "wei", word: "查表得出" },
  prior: { ch: "估", tone: "cao", word: "预算先验的估值" },
  model: { ch: "草", tone: "yan", word: "起草模型写的" },
  human: { ch: "人", tone: "jie", word: "你改的" },
};

const CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳";
export const circled = (n: number): string => (n >= 1 && n <= CIRCLED.length ? CIRCLED[n - 1] : `(${n})`);

/** 被出处账引用的区间按在原文里的位置编号（①②…），字段与原文靠这个编号对上。 */
export function spanNumbers(spans: KaitiSpan[], rows: KaitiRow[]): Map<string, number> {
  const used = new Set(rows.flatMap((r) => r.spans ?? []));
  const out = new Map<string, number>();
  spans.filter((s) => used.has(s.id)).sort((a, b) => a.start - b.start || b.end - a.end).forEach((s, i) => out.set(s.id, i + 1));
  return out;
}

export type Segment = { text: string; sentence: boolean; token: boolean; ends: number[] };

/**
 * 把原文切成段：每段知道自己是否落在被引用的句子里、是否落在被引用的词元里，以及在它末尾结束的区间编号。
 * 句子与词元会重叠（句子里含地址），所以按全部边界切，不嵌套。
 */
export function segments(text: string, spans: KaitiSpan[], nums: Map<string, number>): Segment[] {
  const used = spans.filter((s) => nums.has(s.id) && s.start >= 0 && s.end <= text.length && s.start < s.end);
  const cuts = [...new Set([0, text.length, ...used.flatMap((s) => [s.start, s.end])])].sort((a, b) => a - b);
  const out: Segment[] = [];
  for (let i = 0; i + 1 < cuts.length; i++) {
    const [a, b] = [cuts[i], cuts[i + 1]];
    const cover = used.filter((s) => s.start <= a && s.end >= b);
    out.push({
      text: text.slice(a, b),
      sentence: cover.some((s) => s.kind === "sentence"),
      token: cover.some((s) => s.kind !== "sentence"),
      ends: used.filter((s) => s.end === b).map((s) => nums.get(s.id)!).sort((x, y) => x - y),
    });
  }
  return out;
}

/** 字段名 → 人话。scope[i].* 按规则编号。 */
export function fieldWord(field: string): string {
  const m = field.match(/^scope\[(\d+)\](?:\.(pattern|risk))?$/);
  if (m) return m[2] === "risk" ? `规则 ${Number(m[1]) + 1} 风险` : m[2] === "pattern" ? `规则 ${Number(m[1]) + 1} 地址` : "授权";
  return ({
    title: "任务名", "goal.statement": "目标", deliverable: "交付物", materials: "参考材料", "goal.check": "判定",
    "goal.max_attempts": "最多尝试", "budget.usd_milli": "成本上限", "budget.wall_s": "时间上限", "budget.shares": "占比", "draft.model": "起草档案",
    "scope.mention": "原文提到的地址",
    "goal.binding.task": "平台任务号", "goal.check.ack": "命令确认", deadline: "截止时刻",
  } as Record<string, string>)[field] ?? field;
}

/** 任务单按 Problem 的四组字段排（设计 §7.3）。 */
export const GROUPS = ["目标与题面", "判据", "授权", "预算"] as const;
export type Group = (typeof GROUPS)[number];
export function groupOf(field: string): Group | null {
  if (field.startsWith("scope")) return "授权";
  if (field.startsWith("budget") || field === "deadline") return "预算";
  if (field.startsWith("goal.check") || field.startsWith("goal.binding") || field === "goal.max_attempts") return "判据";
  if (field === "draft.model") return null;
  return "目标与题面";
}

export const usdOf = (milli: number) => `$${(milli / 1000).toFixed(2)}`;
export function wallOf(s: number): string {
  if (s % 3600 === 0) return `${s / 3600} 小时`;
  if (s >= 60 && s % 60 === 0) return `${s / 60} 分钟`;
  return `${s} 秒`;
}

export function valueText(r: KaitiRow): string {
  if (r.field === "budget.usd_milli" && typeof r.value === "number") return usdOf(r.value);
  if (r.field === "budget.wall_s" && typeof r.value === "number") return wallOf(r.value);
  if (r.value !== null && typeof r.value === "object") return Object.entries(r.value as Record<string, unknown>).map(([k, v]) => `${k}=${String(v)}`).join(" · ");
  return String(r.value);
}

/** 原文里的目标句（拒绝页引用）：校验认下的目标句，没有就是草案指认的。 */
export function goalSentences(v: KaitiVetted): string[] {
  const ids = v.derivation.find((r) => r.field === "goal.statement")?.spans ?? [];
  const fromDraft = Array.isArray(v.draft?.goal_sentence) ? (v.draft.goal_sentence as string[]) : [];
  const want = new Set(ids.length ? ids : fromDraft);
  return v.spans.filter((s) => want.has(s.id)).map((s) => s.text);
}

/** 把批次里的 "$answer" 换成保密库返回的引用。其余原样。 */
export function sealOps(ops: Op[], ref: VaultRef | null): Op[] {
  const copy = JSON.parse(JSON.stringify(ops)) as Op[];
  const open = copy.at(-1);
  if (!open || open.op !== "open_problem") throw new Error("批次最后一条须是 open_problem");
  const check = (open.body as unknown as ProblemInput).goal.check as { sealed?: unknown[] };
  if (check.sealed) {
    if (!ref) throw new Error("有答案时须先写保密库");
    check.sealed = check.sealed.map((x) => (x === "$answer" ? ref : x));
  }
  if (JSON.stringify(copy).includes('"$answer"')) throw new Error("批次里还有没换掉的答案占位");
  return copy;
}

/**
 * 带着草案进高级模式（设计 §7.5）：四步向导的草稿，每个预填字段带出处记号；人改过的记号变为"人"。
 * 材料按文字存（题面、参考地址、检查命令），提交时与向导同一条路先存成 Blob。答案不进草稿：已写进保密库，只带引用。
 */
export function wizardDraftOf(v: KaitiVetted, ref: VaultRef | null): Draft {
  const p = v.input!;
  const blob = (n: string) => v.blobs.find((b) => b.name === n);
  const src = (f: string): KaitiSource => v.derivation.find((r) => r.field === f)?.source ?? "table";
  const text = (slot: string, t: string, required = false): Draft["materials"][number] =>
    ({ slot, required, name: null, hash: null, size: 0, media_type: "", kind: "text", text: t });
  const mats: Draft["materials"] = [text("题面", blob("statement")?.text ?? v.text, true)];
  const refs = blob("references");
  if (refs) mats.push(text("参考地址", refs.text));
  const spec = blob("spec");
  if (spec) mats.push(text("检查命令", spec.text));
  const nums = spanNumbers(v.spans, v.derivation);
  const numbered = v.spans.filter((s) => nums.has(s.id)).map((s) => ({ ...s, n: nums.get(s.id)! }));
  const fieldNos = fieldRefs(v, nums);
  const edited = p.scope.some((_, i) => src(`scope[${i}].risk`) === "human");
  const scopeSrc: KaitiSource = edited ? "human" : p.scope[0]?.resource === "workspace" ? "table" : "span";
  return {
    template: "",
    id: v.pid,
    title: p.title,
    statement: p.goal.statement,
    materials: mats,
    judge: p.goal.check.judge_id,
    lockJudge: false,
    expect: p.goal.check.expect ? JSON.stringify(p.goal.check.expect) : "",
    specSlot: spec ? String(mats.length - 1) : "",
    accept: "judge",
    maxAttempts: String(p.goal.max_attempts),
    scope: p.scope.map((r) => ({ resource: r.resource, pattern: r.pattern, actions: r.actions.join(","), risk: r.risk as Risk })),
    usd: String(p.budget.usd_milli / 1000),
    wall_s: String(p.budget.wall_s),
    verify_share: String(p.budget.verify_share),
    bootstrap_share: String(p.budget.bootstrap_share),
    env: { ...p.env },
    judgeFilter: [],
    b1CapMilli: null,
    hint: "",
    ...(ref ? { sealed: [ref] } : {}),
    marks: {
      title: src("title"), statement: src("goal.statement"), judge: src("goal.check"), maxAttempts: src("goal.max_attempts"),
      scope: scopeSrc, usd: src("budget.usd_milli"), wall_s: src("budget.wall_s"), materials: "span",
    },
    kaiti: { text: v.text, spans: numbered, refs: fieldNos },
  };
}

/** 向导字段 → 确认卡出处行的字段名（scope 取全部 scope 行，materials 取参考材料行）。 */
const FIELD_ROWS: Record<MarkedField, (f: string) => boolean> = {
  title: (f) => f === "title",
  statement: (f) => f === "goal.statement",
  judge: (f) => f === "goal.check",
  maxAttempts: (f) => f === "goal.max_attempts",
  scope: (f) => f.startsWith("scope"),
  usd: (f) => f === "budget.usd_milli",
  wall_s: (f) => f === "budget.wall_s",
  materials: (f) => f === "materials",
};

/** 每个向导字段摘自原文第几段（与确认卡同一套编号）。 */
export function fieldRefs(v: KaitiVetted, nums: Map<string, number>): Partial<Record<MarkedField, number[]>> {
  const out: Partial<Record<MarkedField, number[]>> = {};
  for (const f of Object.keys(FIELD_ROWS) as MarkedField[]) {
    const ns = [...new Set(v.derivation.filter((r) => FIELD_ROWS[f](r.field)).flatMap((r) => (r.spans ?? []).map((id) => nums.get(id))))]
      .filter((n): n is number => n !== undefined).sort((a, b) => a - b);
    if (ns.length) out[f] = ns;
  }
  return out;
}
