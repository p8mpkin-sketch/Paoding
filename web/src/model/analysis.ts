// 方案分析的纯函数（界面一期）：步骤与状态的说法、预算分段、决定块的生成、引擎自由文本里内部名词的替换。
// 用词照 docs/design/engine-ui §6：界面里不出现设计名词；决定块的关键字是引擎的解析格式，原样保留，只放在折叠的“原文”里。
import type { AnCandidate, AnGate, AnStep, AnalysisDetail, AnalysisRow } from "../api/analysis-types";

export const STEP_ORDER = ["S0", "S1", "S2", "S3", "G1", "S4", "G2", "S5", "G3", "S6"] as const;
export const STEP_WORD: Record<(typeof STEP_ORDER)[number], string> = {
  S0: "立项", S1: "快照", S2: "勘察", S3: "发现", G1: "待你确认", S4: "抽象", G2: "待你确认", S5: "映射", G3: "待你确认", S6: "交接",
};
export const GATE_N: Record<AnGate, 1 | 2 | 3> = { G1: 1, G2: 2, G3: 3 };
/** 每一步的预算软上限按比例分（引擎 budget.STAGE_SHARE，服务端给出）；这三步之外的步骤不单独计。 */
export const STAGE_WORD: Record<string, string> = { S3: "发现", S4: "抽象", S5: "映射" };
export const MODE_WORD: Record<string, string> = { formal: "正式", dry_run: "预评估", from_bang: "从候选方案取", replace: "重新映射" };
export const VIA_WORD: Record<string, string> = { upload: "上传归档", library: "资料库已有", repo: "仓库地址", service: "服务地址", doc: "文档地址", statement: "写在描述里" };
export const FORM_WORD: Record<string, string> = { code: "代码", docs: "文档", service: "在线服务", description: "描述" };

export const SLOT_WORD: Record<string, string> = {
  H1: "会话策略", H2: "调度编排", H3: "工具集", H4: "上下文管理", H5: "知识检索", H6: "可观测性", H7: "结果呈现", H8: "任务解析",
};
/** 模块的中文名（能力配置里在用的那几个）；没有登记的显示 id。 */
export const MODULE_WORD: Record<string, string> = {
  "h1.solo": "单会话执行", "h1.triad": "三角色编排", "h1.recall": "新任务召回", "h2.sinan": "调度器", "h3.base": "基础工具集", "h3.kb": "资料库工具",
  "h4.views-notes": "三层视图和接力笔记", "h5.shuku": "资料库检索", "h5.tongjian-recall": "记忆召回", "h6.workbench": "工作台视图",
  "h6.activity-ledger": "可回放的实时活动流", "h6.pd": "命令行", "h7.result": "结果页", "h8.kaiti": "一句话新建任务", "h1.tunshi": "方案分析",
};
export const moduleName = (ref: string) => MODULE_WORD[ref.split("@")[0]] ?? ref.split("@")[0];

export const GAP_WORD: Record<string, string> = { missing: "缺失", weaker: "更弱", new_dim: "新维度" };
export const STOP_WORD: Record<string, string> = { saturated: "读够了", weak_signal: "信号太弱", budget: "预算到线", focus_excluded: "不在关注范围", budget_cut: "预算截断" };
export const REC_WORD: Record<string, { word: string; tone: "ok" | "" | "off" }> = {
  recommend: { word: "推荐", tone: "ok" }, optional: { word: "可选", tone: "" }, not_recommended: { word: "不推荐", tone: "off" },
};
export const FLAG_WORD: Record<string, string> = {
  license_restricted: "许可证受限，只借思路", injection_flagged_sources: "来源含疑似指令（已忽略）", self_ref: "涉及分析本身",
  profile_stale: "能力剖面过期", needs_new_slot: "需要新模块槽", needs_kernel_split: "需拆出内核变更",
};
export const UNIT_WORD: Record<string, { word: string; tone: "ok" | "live" | "need" | "bad" | "" }> = {
  todo: { word: "未开始", tone: "" }, doing: { word: "进行中", tone: "live" }, done: { word: "完成", tone: "ok" },
  failed: { word: "失败", tone: "bad" }, budget_cut: { word: "预算截断", tone: "need" }, void: { word: "作废（重做）", tone: "" },
};
export const OBS_KIND_WORD: Record<string, string> = { mechanism: "机制", doc_claim: "文档声称", behavior: "行为", interface: "接口", config: "配置" };
export const TIER_WORD: Record<string, string> = { light: "轻量", mid: "标准", heavy: "高性能" };
/** 校验器 V1–V12（10 §12）与核心机制自检 K1–K8 的常规说法。 */
export const CHECK_WORD: Record<string, string> = {
  V1: "结构", V2: "编号", V3: "引用真实", V4: "公式复算", V5: "禁词", V6: "不抄写", V7: "许可证", V8: "模块清单", V9: "内核", V10: "预登记", V11: "与你的决定一致", V12: "金丝雀",
  K1: "结构", K2: "无来源专有名词", K3: "不引用代码结构", K4: "不抄写", K5: "有据", K6: "去来源独立（盲审）", K7: "多种实现", K8: "无指令痕迹",
};
export const BANG_WORD: Record<string, { word: string; tone: "ok" | "live" | "need" | "off" | "" }> = {
  identified: { word: "已识别", tone: "" }, dry_run: { word: "预评估过", tone: "" }, selected: { word: "选中", tone: "live" },
  handed_off: { word: "已交实现线", tone: "live" }, absorbed: { word: "已集成", tone: "ok" }, rejected: { word: "不采纳", tone: "off" },
  excluded: { word: "已排除", tone: "off" }, superseded: { word: "已并入", tone: "off" }, reverted: { word: "已回滚", tone: "off" },
};
/** 置信与难度的拆项（08 §3）。 */
export const PART_WORD: Record<string, string> = {
  c0: "基础", cover: "覆盖", corro: "互证", cap: "上限",
  base: "基础", behavior_slots_minus_1: "多模块槽", extra_ports: "额外接口", new_tool: "新工具", kernel_split: "拆内核变更",
  a1_infeasible: "无法照搬", run_only_emergent: "新增指标只能运行时量",
};
export const ARTIFACT_KIND_WORD = { material: "你给的材料", exec: "执行输出", analysis: "分析写的" } as const;

/** 引擎自由文本里混着的内部名词 → 常规词（E-U4 之前的过渡；引擎线把禁词扩到所有自由文本后，这张表只是兜底）。长词在前。 */
const PLAIN: [RegExp, string][] = [
  [/闸点\s*([123])/g, "第 $1 次确认"],
  [/体质改动/g, "内核改动"], [/体质/g, "内核"],
  [/异火榜/g, "候选方案"], [/火意/g, "核心机制"], [/火序/g, "集成顺序"], [/火位/g, "模块槽"], [/火组/g, "模块组"],
  [/功法/g, "能力配置"], [/(?<!能力)剖面/g, "能力剖面"], [/炼档/g, "集成记录"],
  [/识火/g, "发现"], [/萃意/g, "抽象"], [/入位/g, "映射"], [/吞噬引擎/g, "方案分析"], [/试算/g, "预评估"],
  [/盲审丹/g, "盲审"], [/萃丹/g, "抽取模型"], [/主丹/g, "主模型"], [/读丹/g, "读取模型"], [/位丹/g, "映射模型"], [/丹方/g, "模型配置"],
  [/新生维/g, "新增指标"], [/第\s*(\d+)\s*阶/g, "v$1"], [/取 main\b/g, "取主模型那一稿"], [/火莲/g, "新增能力"], [/合炼/g, "全面提升"], [/并火/g, "无增益"],
];
export function plain(text: string): string {
  let s = text;
  for (const [re, to] of PLAIN) s = s.replace(re, to);
  return s;
}

// ------------------------------------------------------------ 状态

export type Tone = "ok" | "live" | "need" | "bad" | "off" | "";
export function stateOf(r: Pick<AnalysisRow, "step" | "waiting" | "mode">): { word: string; tone: Tone; at: string } {
  const step = r.step;
  if (r.waiting) {
    const n = GATE_N[r.waiting.gate];
    return r.waiting.submitted
      ? { word: `第 ${n} 次确认已提交`, tone: "live", at: "等分析接着做" }
      : { word: `待你确认 · 第 ${n} 次`, tone: "need", at: `第 ${n} 次确认` };
  }
  if (step === "done") return { word: r.mode === "dry_run" ? "报告已出" : "已交接", tone: "ok", at: "已完成" };
  if (step === "paused_budget") return { word: "预算用完，已暂停", tone: "need", at: "暂停" };
  if (step === "failed") return { word: "失败", tone: "bad", at: "失败" };
  if (step === "halted") return { word: "已叫停", tone: "off", at: "叫停" };
  const w = step && step in STEP_WORD ? STEP_WORD[step as keyof typeof STEP_WORD] : "排队";
  return { word: `${w}中`, tone: "live", at: w };
}

/** 十步进度条：每一格是 done / now / wait（确认点停着等你）/ 空。 */
export function stepper(step: AnStep | null, waiting: boolean): { key: string; word: string; gate: boolean; cls: "done" | "now" | "wait" | "" }[] {
  const i = step === "done" ? STEP_ORDER.length : step ? STEP_ORDER.indexOf(step as (typeof STEP_ORDER)[number]) : -1;
  return STEP_ORDER.map((k, j) => ({
    key: k,
    word: STEP_WORD[k],
    gate: k.startsWith("G"),
    cls: j < i ? "done" : j === i ? (k.startsWith("G") && waiting ? "wait" : "now") : "",
  }));
}

/** 预算三段（发现、抽象、映射）的已花与软上限；整题上限由引擎 engine.json 给出。 */
export function stages(d: Pick<AnalysisDetail, "spent" | "budget_usd_milli" | "stage_share">): { key: string; word: string; spent: number; cap: number }[] {
  return Object.entries(d.stage_share).map(([k, share]) => ({
    key: k, word: STAGE_WORD[k] ?? k, spent: d.spent.by_step[k] ?? 0, cap: Math.round(d.budget_usd_milli * share),
  }));
}

/** 列表第一句做标题：原话的第一句（句号、问号、换行为界）。 */
export function titleOf(statement: string): string {
  const s = statement.trim().split(/[。！？\n]/)[0] ?? "";
  return s || "（没有写原话）";
}

/** 优先级的拆项一行：V 价值 · C 置信 · D 难度 · R 风险。 */
export const parts = (c: AnCandidate) => `V${fmt(c.value)} · C${c.confidence.toFixed(1)} · D${c.difficulty} · ${c.risk}`;
export const fmt = (x: number) => (Number.isInteger(x) ? String(x) : x.toFixed(1));

// ------------------------------------------------------------ 第 1 次确认的决定块

export type G1Choice = {
  /** 勾选的候选（不含排除的）。 */
  pick: string[];
  /** 排除的候选与理由（理由必填）。 */
  exclude: Record<string, string>;
  /** 改过的标题。 */
  title: Record<string, string>;
  note: string;
};

/** 理由、标题、备注里会打断解析的字符换掉：换行、分号（排除的分隔符）、括号（理由的界）。 */
const clean = (s: string) => s.replace(/[\r\n]+/g, " ").replace(/[；;]/g, "，").replace(/[（(]/g, "〔").replace(/[）)]/g, "〕").trim();
const cleanLine = (s: string) => s.replace(/[\r\n]+/g, " ").trim();

/** 照引擎 decision.render 的顺序生成：选、排除、改、备注（09 §2.4）。候选按清单顺序。 */
export function g1Block(order: string[], c: G1Choice): string {
  const lines = ["【决定 v1】闸点 1"];
  const ex = order.filter((id) => id in c.exclude);
  const pick = order.filter((id) => c.pick.includes(id) && !(id in c.exclude));
  lines.push(`选：${pick.length ? pick.join("，") : "无"}`);
  if (ex.length) lines.push(`排除：${ex.map((id) => `${id}（${clean(c.exclude[id]) || "未写理由"}）`).join("，")}`);
  for (const id of order) {
    const t = c.title[id];
    if (t !== undefined && cleanLine(t)) lines.push(`改：${id}.title = ${cleanLine(t)}`);
  }
  if (c.note.trim()) lines.push(`备注：${cleanLine(c.note)}`);
  return lines.join("\n");
}

/** 提交前还差什么（按钮旁直接写出来，不让人提交了再被拒）。 */
export function g1Problems(order: string[], c: G1Choice): string[] {
  const out: string[] = [];
  const pick = order.filter((id) => c.pick.includes(id) && !(id in c.exclude));
  if (pick.length === 0) out.push("至少选一个候选");
  for (const id of order) if (id in c.exclude && !clean(c.exclude[id])) out.push(`${id} 的排除理由没写`);
  for (const id of order) if (c.title[id] !== undefined && !cleanLine(c.title[id])) out.push(`${id} 的新标题是空的`);
  return out;
}

/** 追加预算：输入的是美元，交给服务端的是千分之一美元；空串即 0，非法返回 null。 */
export function budgetAdd(input: string): number | null {
  const t = input.trim();
  if (!t) return 0;
  if (!/^\d+(\.\d{1,3})?$/.test(t)) return null;
  const m = Math.round(Number(t) * 1000);
  return m <= 100_000 ? m : null;
}
