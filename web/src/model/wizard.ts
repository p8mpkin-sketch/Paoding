// 开题向导的草稿 → 提交体（HMI 设计 §3.2、§10.1）。草稿只在本机；提交体里没有 profile 字段。
// 材料先把字节传成 Blob，登记与开题在同一批里原子提交：Origin 用 "$<下标>" 指向同批前面的登记。
import { ops } from "../api/ops";
import type { ArtifactView, BudgetResponse, CatalogItem, JudgeEntry, Op, ProblemInput, Risk, ScopeRule, StatusView, VaultRef } from "../api/types";
import type { KaitiSource, KaitiSpan } from "../api/kaiti";

export type DraftRule = { resource: string; pattern: string; actions: string; risk: Risk | "" };
/**
 * 材料槽位。kind：file 上传文件；text 贴一段文字；link 填一个网址（只当文字存，不抓取）。
 * text 与 link 存成 Blob 时媒体类型分别是 text/plain、text/uri-list；hash 非空即已存好、会进批次。
 */
export type MaterialKind = "file" | "text" | "link";
export type DraftMaterial = { slot: string; required: boolean; name: string | null; hash: string | null; size: number; media_type: string; kind?: MaterialKind; text?: string };
export type Draft = {
  /** 模板名；空串即不用模板。 */
  template: string;
  id: string;
  title: string;
  statement: string;
  materials: DraftMaterial[];
  judge: string;
  lockJudge: boolean;
  expect: string;
  /** 指向某个材料槽位的下标；空串即不挂。 */
  specSlot: string;
  accept: "judge" | "human";
  maxAttempts: string;
  scope: DraftRule[];
  usd: string;
  wall_s: string;
  verify_share: string;
  bootstrap_share: string;
  env: ProblemInput["env"];
  /** 模板限定的判官；空即注册表全部。 */
  judgeFilter: string[];
  b1CapMilli: number | null;
  /** 初始指导：开题成功后作为第一条 Hint 提交（人的判断语域；异议 web-workbench 第 3 条）。不进开题批次。 */
  hint?: string;
  /** 克隆来源题目 id；只用于显示。 */
  clonedFrom?: string;
  /** 从一句话开题带进来的答案引用（答案已在保密库，草稿里只有引用）。 */
  sealed?: VaultRef[];
  /** 从一句话开题带进来的出处记号（设计 §7.5）：字段名 → 出处；人改过即为 human。 */
  marks?: Partial<Record<MarkedField, KaitiSource>>;
  /**
   * 一句话开题的原文（已剪去答案），向导左栏顶部折叠显示。spans 是被引用的区间（带确认卡上的同一编号 n），
   * refs 是各字段摘自原文第几段（宪章 Q11）；人改过的字段记号变“人”，编号随之不再显示。
   */
  kaiti?: { text: string; spans?: (KaitiSpan & { n: number })[]; refs?: Partial<Record<MarkedField, number[]>> };
};

/** 带出处记号的字段。 */
export type MarkedField = "title" | "statement" | "judge" | "maxAttempts" | "scope" | "usd" | "wall_s" | "materials";
const MARKED: readonly string[] = ["title", "statement", "judge", "maxAttempts", "scope", "usd", "wall_s", "materials"];

/** 人改了带记号的字段：记号变为"人"。没有记号的草稿原样。 */
export function touch(d: Draft, patch: Partial<Draft>): Draft {
  if (!d.marks) return { ...d, ...patch };
  const marks = { ...d.marks };
  for (const k of Object.keys(patch)) if (MARKED.includes(k) && k in marks) marks[k as MarkedField] = "human";
  return { ...d, ...patch, marks };
}

/**
 * 六页（异议 web-workbench 第 2 条）：中间四页就是 HMI §3.2 的 Origin、判据、授权、预算，不增不藏；
 * “基本信息”只是把 id、题名、目标陈述单独成页，“复核”放画像预览、批次预览与初始指导。
 */
export const STEPS = ["基本信息", "起点", "终点", "资源", "预算", "复核"] as const;

const obj = (v: unknown): Record<string, unknown> => (v !== null && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown, d = ""): string => (typeof v === "string" ? v : d);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const RISKS = new Set(["r0", "r1", "r2"]);

/**
 * 从模板生成草稿。模板的 data 是目录里一段任意 JSON（图服务不解释它）；这里按 F1 的暂行字段名取预填值，
 * 取不到的一律留空，不猜。t 为 null 即不用模板。
 */
export function draftFromTemplate(t: CatalogItem | null, keep?: Pick<Draft, "id" | "title">): Draft {
  const data = obj(t?.data);
  const f = obj(data.fields);
  const goal = obj(f.goal);
  const check = obj(goal.check);
  const budget = obj(f.budget);
  const env = obj(f.env);
  const mats = arr(f.materials).map(obj).filter((m) => str(m.slot) !== "");
  return {
    template: t?.name ?? "",
    id: keep?.id ?? "",
    title: keep?.title ?? "",
    statement: str(goal.statement),
    materials: (mats.length ? mats : [{ slot: "题面", required: true }]).map((m) => ({ slot: str(m.slot), required: m.required === true, name: null, hash: null, size: 0, media_type: "", kind: "file" as const, text: "" })),
    judge: str(check.judge_id),
    lockJudge: goal.lock_judge === true,
    expect: check.expect !== undefined ? JSON.stringify(check.expect) : "",
    specSlot: "",
    accept: "judge",
    maxAttempts: String(num(goal.max_attempts) ?? 5),
    scope: arr(f.scope).map(obj).map((r) => ({
      resource: str(r.resource), pattern: str(r.pattern), actions: arr(r.actions).map((a) => str(a)).join(","),
      risk: RISKS.has(str(r.risk)) ? (r.risk as Risk) : "",
    })),
    usd: num(budget.usd_milli) !== null ? String(num(budget.usd_milli)! / 1000) : "",
    wall_s: num(budget.wall_s) !== null ? String(budget.wall_s) : "",
    verify_share: String(num(budget.verify_share) ?? 0.2),
    bootstrap_share: String(num(budget.bootstrap_share) ?? 0.333),
    env: { base: str(env.base, "default"), baseline_ref: str(env.baseline_ref) },
    judgeFilter: arr(data.judges).map((j) => str(j)).filter(Boolean),
    b1CapMilli: num(f.b1_cap_usd_milli),
    hint: "",
  };
}

/** 这份草稿可选的判官：注册表里的，按模板过滤。 */
export function judgesFor(d: Draft, registry: JudgeEntry[]): JudgeEntry[] {
  return d.judgeFilter.length ? registry.filter((j) => d.judgeFilter.includes(j.judge_id)) : registry;
}

/** 未标风险的规则按 r2 提交（规格 3.1.2：缺省 r2）。 */
export function scopeOf(d: Draft): ScopeRule[] {
  return d.scope
    .filter((r) => r.resource.trim() !== "" || r.pattern.trim() !== "")
    .map((r) => ({
      resource: r.resource.trim(),
      pattern: r.pattern.trim(),
      actions: r.actions.split(",").map((a) => a.trim()).filter(Boolean),
      risk: r.risk === "" ? "r2" : r.risk,
    }));
}

function parseExpect(s: string): Record<string, unknown> | undefined | Error {
  if (s.trim() === "") return undefined;
  try {
    const v: unknown = JSON.parse(s);
    if (v === null || typeof v !== "object" || Array.isArray(v)) return new Error("expect 必须是 JSON 对象");
    return v as Record<string, unknown>;
  } catch {
    return new Error("expect 不是合法的 JSON");
  }
}

/** 已上传的材料，按槽位顺序；它们在批次里的下标就是这里的下标。 */
export const uploadedOf = (d: Draft) => d.materials.map((m, slot) => ({ m, slot })).filter((x) => x.m.hash !== null);
const refOf = (d: Draft, slot: number): string | null => {
  const i = uploadedOf(d).findIndex((x) => x.slot === slot);
  return i < 0 ? null : `$${i}`;
};

export function goalOf(d: Draft): ProblemInput["goal"] {
  const expect = parseExpect(d.expect);
  const spec = d.specSlot === "" ? null : refOf(d, Number(d.specSlot));
  return {
    statement: d.statement,
    check: {
      judge_id: d.judge,
      ...(spec ? { spec_ref: spec } : {}),
      ...(expect && !(expect instanceof Error) ? { expect } : {}),
      ...(d.sealed?.length ? { sealed: d.sealed } : {}),
    },
    max_attempts: Number(d.maxAttempts),
    accept: d.accept,
  };
}

const ID_OK = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/;

/** 每一页的问题清单；空即可进下一页。 */
export function problemsOf(d: Draft): string[][] {
  // 填了文字或网址的槽位算有材料：提交时先存成 Blob（app/submit.ts），再进批次
  const has = (m: DraftMaterial) => m.hash !== null || ((m.kind ?? "file") !== "file" && (m.text ?? "").trim() !== "");
  const mats = d.materials.filter((m) => m.required && !has(m)).map((m) => `材料槽位"${m.slot}"必填`);
  const basics = [
    ...(d.id.trim() === "" ? ["任务 id 必填"] : ID_OK.test(d.id.trim()) ? [] : ["任务 id 只能用字母、数字、点、下划线与连字符"]),
    ...(d.title.trim() ? [] : ["名称必填"]),
    ...(d.statement.trim() ? [] : ["目标陈述必填"]),
  ];
  const origin = [...(d.materials.some(has) ? [] : mats.length ? [] : ["至少一份起点材料"]), ...mats];
  const e = parseExpect(d.expect);
  const criterion = [
    ...(d.judge ? [] : ["必须选目标判定器"]),
    ...(e instanceof Error ? [e.message] : []),
    ...(Number.isInteger(Number(d.maxAttempts)) && Number(d.maxAttempts) > 0 ? [] : ["max_attempts 必须是正整数"]),
  ];
  const sc = scopeOf(d);
  const scope = [
    ...(sc.length ? [] : ["scope 至少一条规则"]),
    ...sc.flatMap((r, i) => (r.actions.length ? [] : [`第 ${i + 1} 条规则缺 actions`])),
    ...(d.env.base.trim() ? [] : ["环境 base 必填"]),
  ];
  const share = (v: string) => Number(v) >= 0 && Number(v) <= 1 && v.trim() !== "";
  const budget = [
    ...(Number(d.usd) > 0 ? [] : ["usd 为正"]),
    ...(Number.isInteger(Number(d.wall_s)) && Number(d.wall_s) > 0 ? [] : ["wall_s 为正整数"]),
    ...(share(d.verify_share) ? [] : ["verify_share 在 0 到 1 之间"]),
    ...(share(d.bootstrap_share) ? [] : ["bootstrap_share 在 0 到 1 之间"]),
  ];
  const review = (d.hint ?? "").length > 2000 ? ["初始指导不超过 2000 字"] : [];
  return [basics, origin, criterion, scope, budget, review];
}

const enc = new TextEncoder();
/** 文字或网址材料要存的字节与媒体类型。网址只当文字存，前端不去抓。 */
export function textMaterial(m: DraftMaterial): { bytes: Uint8Array; media_type: string; name: string } | null {
  const t = (m.text ?? "").trim();
  if (!t) return null;
  return m.kind === "link"
    ? { bytes: enc.encode(`${t}\r\n`), media_type: "text/uri-list", name: "链接" }
    : { bytes: enc.encode(m.text ?? ""), media_type: "text/plain; charset=utf-8", name: "文字" };
}

/**
 * 克隆：从一道已有的题预填草稿（scope、判据、预算、env、判官），材料按哈希重新登记为 input 类
 * （Blob 按内容寻址，字节已在服务端）。id 留空让人重填，题名加“副本”。
 */
export function draftFromProblem(st: StatusView, b: BudgetResponse, arts: ArtifactView[]): Draft {
  const p = st.problem;
  const pred = st.goal.predicate;
  const byId = new Map(arts.map((a) => [a.id, a]));
  const refs = [p.origin.statement_ref, ...p.origin.materials];
  const materials: DraftMaterial[] = refs.map((id, i) => {
    const a = byId.get(id);
    return { slot: i === 0 ? "题面" : `材料 ${i}`, required: i === 0, name: a ? `克隆自 ${id}` : null, hash: a?.hash ?? null, size: a?.size ?? 0, media_type: a?.media_type ?? "", kind: "file" };
  });
  const specSlot = pred.spec_ref ? refs.indexOf(pred.spec_ref) : -1;
  return {
    template: "",
    id: "",
    title: `${p.title.value}（副本）`,
    statement: st.goal.statement.value,
    materials,
    judge: pred.judge_id,
    lockJudge: false,
    expect: Object.keys(pred.expect ?? {}).length ? JSON.stringify(pred.expect) : "",
    specSlot: specSlot >= 0 ? String(specSlot) : "",
    accept: st.goal.accept,
    maxAttempts: String(pred.max_attempts ?? 5),
    scope: p.scope.map((r) => ({ resource: r.resource, pattern: r.pattern, actions: r.actions.join(","), risk: r.risk })),
    usd: b.cap.usd_milli !== undefined ? String(b.cap.usd_milli / 1000) : "",
    wall_s: String(b.wall.cap_s),
    verify_share: String(b.verify_share),
    bootstrap_share: String(b.bootstrap_share),
    env: { ...p.env },
    judgeFilter: [],
    b1CapMilli: null,
    hint: "",
    clonedFrom: p.id,
  };
}

/** 开题批次：若干条 input 类登记，加 open_problem 的事件体。题目 id 在批次外层，不在事件体里。 */
export function buildOpen(d: Draft): { id: string; materials: Op[]; problem: ProblemInput } {
  const up = uploadedOf(d);
  const refs = up.map((_, i) => `$${i}`);
  return {
    id: d.id.trim(),
    materials: up.map(({ m }) => ops.registerInput(m.hash!, m.size, m.media_type || "application/octet-stream")),
    problem: {
      title: d.title.trim(),
      origin: { statement_ref: refs[0] ?? "", materials: refs.slice(1) },
      goal: goalOf(d),
      scope: scopeOf(d),
      budget: {
        usd_milli: Math.round(Number(d.usd) * 1000),
        wall_s: Number(d.wall_s),
        verify_share: Number(d.verify_share),
        bootstrap_share: Number(d.bootstrap_share),
      },
      env: d.env,
      judges: [...new Set([d.judge, ...d.judgeFilter])].filter(Boolean),
    },
  };
}
