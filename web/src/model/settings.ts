// 设置页的纯函数（宪章 03 §5）：三道硬顶的次序、刻度尺的对数长度、单位换算、改了哪些键。
// 服务端在写入时做同样的校验（scripts/settings_hub.py），这里只是让人在点保存之前就看见问题，不是闸门。
import type { Caps, ModelRole, RiskRule, Settings } from "../api/settings-types";

export const ROLES: { role: ModelRole; word: string }[] = [
  { role: "draft", word: "起草" },
  { role: "bootstrap", word: "Bootstrap" },
  { role: "reason", word: "Reason" },
  { role: "explore", word: "Explore" },
  { role: "verify", word: "Verify" },
];
export const TIERS = [
  { tier: "strong", word: "强" },
  { tier: "mid", word: "中" },
  { tier: "light", word: "轻" },
] as const;
export const SLOT_RE = /^[a-z0-9][a-z0-9_-]{0,31}$/;
export const KEY_NOTE = "密钥重启后失效，可用环境变量持久注入";

/** 金额：内部是千分之一美元，输入框里写美元。 */
export const toUsdInput = (milli: number) => String(milli / 1000);
export function fromUsdInput(s: string): number | null {
  const v = Number(s.trim());
  return s.trim() && Number.isFinite(v) && v > 0 ? Math.round(v * 1000) : null;
}
/** 墙钟：内部是秒，输入框里写分钟。 */
export const toMinInput = (s: number) => String(s / 60);
export function fromMinInput(s: string): number | null {
  const v = Number(s.trim());
  return s.trim() && Number.isFinite(v) && v > 0 ? Math.round(v * 60) : null;
}

/** 三道顶的次序：练习 ≤ 单任务 ≤ 全局（金额），练习 ≤ 单任务（墙钟）。返回人看得懂的问题清单，空即可保存。 */
export function capIssues(c: Caps): string[] {
  const out: string[] = [];
  for (const [k, v] of Object.entries(c)) if (!Number.isInteger(v) || v <= 0) out.push(`${k} 须为正数`);
  if (out.length) return out;
  if (c.open_usd_milli > c.global_usd_milli) out.push("单任务硬顶超过全局硬顶");
  if (c.practice_usd_milli > c.open_usd_milli) out.push("练习上限超过单任务硬顶");
  if (c.practice_wall_s > c.open_wall_s) out.push("练习墙钟上限超过单任务墙钟硬顶");
  return out;
}

export function settingsIssues(s: Settings): string[] {
  const out = capIssues(s.caps);
  const names = s.models.profiles.map((p) => p.name.trim());
  if (names.length === 0) out.push("至少要有一个模型档案");
  if (names.some((n) => !n)) out.push("模型档案名不能空");
  if (new Set(names).size !== names.length) out.push("模型档案不能重名");
  for (const p of s.models.profiles) if (!SLOT_RE.test(p.key_slot)) out.push(`档案 ${p.name || "（未命名）"} 的密钥槽名只取小写字母、数字、- 与 _`);
  for (const { role, word } of ROLES) if (!names.includes(s.models.routes[role])) out.push(`角色 ${word} 指向的档案不存在`);
  s.risk.forEach((r, i) => {
    if (!r.resource.trim() || !r.pattern.trim() || r.actions.length === 0) out.push(`风险表第 ${i + 1} 行要写资源、模式和动作`);
  });
  return out;
}

/** 刻度尺：对数长度，最小刻度 $0.01、最大取全局硬顶的十倍，三根条在同一把尺上可比。 */
export function rulerFraction(milli: number, maxMilli: number): number {
  const lo = Math.log10(10), hi = Math.log10(Math.max(maxMilli * 10, 100));
  return Math.min(1, Math.max(0, (Math.log10(Math.max(milli, 10)) - lo) / (hi - lo)));
}

/** 两份设置之间改了哪些键（与服务端变更日志同一种写法）。 */
export function changedKeys(a: unknown, b: unknown, prefix = ""): string[] {
  if (isObj(a) && isObj(b)) {
    const keys = [...new Set([...Object.keys(a), ...Object.keys(b)])].sort();
    return keys.flatMap((k) => changedKeys(a[k], b[k], `${prefix}${k}.`));
  }
  return JSON.stringify(a) === JSON.stringify(b) ? [] : [prefix.slice(0, -1)];
}
const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

export const parseActions = (s: string) => s.split(/[,，\s]+/).map((x) => x.trim()).filter(Boolean);
export const emptyRule = (): RiskRule => ({ resource: "", pattern: "*", actions: ["read"], risk: "r1" });
