// 开题向导的草稿 → 提交体（HMI 设计 §3.2、§10.1）。草稿只在本机；提交体里没有 profile 字段。
// 材料先把字节传成 Blob，登记与开题在同一批里原子提交：Origin 用 "$<下标>" 指向同批前面的登记。
import { ops } from "../api/ops";
import type { CatalogItem, JudgeEntry, Op, ProblemInput, Risk, ScopeRule } from "../api/types";

export type DraftRule = { resource: string; pattern: string; actions: string; risk: Risk | "" };
export type DraftMaterial = { slot: string; required: boolean; name: string | null; hash: string | null; size: number; media_type: string };
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
};

export const STEPS = ["Origin", "判据", "授权", "预算"] as const;

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
    materials: (mats.length ? mats : [{ slot: "题面", required: true }]).map((m) => ({ slot: str(m.slot), required: m.required === true, name: null, hash: null, size: 0, media_type: "" })),
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
    },
    max_attempts: Number(d.maxAttempts),
    accept: d.accept,
  };
}

const ID_OK = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/;

/** 每一步的问题清单；空即可进下一步。 */
export function problemsOf(d: Draft): string[][] {
  const mats = d.materials.filter((m) => m.required && !m.hash).map((m) => `材料槽位"${m.slot}"必填`);
  const s1 = [
    ...(d.id.trim() === "" ? ["题目 id 必填"] : ID_OK.test(d.id.trim()) ? [] : ["题目 id 只能用字母、数字、点、下划线与连字符"]),
    ...(d.title.trim() ? [] : ["题名必填"]),
    ...(uploadedOf(d).length ? [] : mats.length ? [] : ["至少上传一份材料作题面"]),
    ...mats,
  ];
  const e = parseExpect(d.expect);
  const s2 = [
    ...(d.judge ? [] : ["必须选 Goal 判官"]),
    ...(d.statement.trim() ? [] : ["目标陈述必填"]),
    ...(e instanceof Error ? [e.message] : []),
    ...(Number.isInteger(Number(d.maxAttempts)) && Number(d.maxAttempts) > 0 ? [] : ["max_attempts 必须是正整数"]),
  ];
  const sc = scopeOf(d);
  const s3 = [...(sc.length ? [] : ["scope 至少一条规则"]), ...sc.flatMap((r, i) => (r.actions.length ? [] : [`第 ${i + 1} 条规则缺 actions`]))];
  const share = (v: string) => Number(v) >= 0 && Number(v) <= 1 && v.trim() !== "";
  const s4 = [
    ...(Number(d.usd) > 0 ? [] : ["usd 为正"]),
    ...(Number.isInteger(Number(d.wall_s)) && Number(d.wall_s) > 0 ? [] : ["wall_s 为正整数"]),
    ...(share(d.verify_share) ? [] : ["verify_share 在 0 到 1 之间"]),
    ...(share(d.bootstrap_share) ? [] : ["bootstrap_share 在 0 到 1 之间"]),
  ];
  return [s1, s2, s3, s4];
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
