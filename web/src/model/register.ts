// 四语域（HMI 设计 §3.4）。语域由数据来源确定性决定，不由内容决定。
// 来源 → 语域的表在图服务里（views.REGISTER），每段文字都带着 register 送来；pd 的行首标记读同一张表。
// 前端只认 register，不看内容，也不自己再造一张来源表。
import type { ArtifactClass, RegisterName } from "../api/types";

export type Register = "evidence" | "narrative" | "human" | "estimate";

const KEY: Record<RegisterName, Register> = { 证据: "evidence", 叙述: "narrative", 人: "human", 估: "estimate" };

/** 不认识的语域名按叙述处理：宁可把证据显示成叙述，也不把叙述显示成证据。 */
export const registerOf = (name: string): Register => KEY[name as RegisterName] ?? "narrative";

export const REGISTER_LABEL: Record<Register, string> = {
  evidence: "证据",
  narrative: "模型撰写",
  human: "人",
  estimate: "估",
};

/**
 * 证据样式的入口守卫（HT-5）：语域必须是"证据"，而且出处类别不能是 authored。
 * 第二个条件是纵深防御：即使服务端的标注出了错，authored 类也进不了证据框。
 */
export function isEvidence(a: { register: string; class: ArtifactClass }): boolean {
  return registerOf(a.register) === "evidence" && a.class !== "authored";
}
