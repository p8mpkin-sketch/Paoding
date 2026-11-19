// 假服务里的起草服务：只回放 tools/record_kaiti.py 从真 qicao 录下的应答（mock/kaiti.json），不另写一份抽取与校验规则。
// 录下的原文之外的输入一律当作"起草结果不可用"拒绝（与没有配置起草模型时真服务的应答同形）。
import type { KaitiExtract, KaitiVetted } from "../src/api/kaiti";
import RECORDED from "./kaiti.json" with { type: "json" };

type Rec = { extract: Record<string, { text: string; out: KaitiExtract }>; drafts: Record<string, { text: string; out: KaitiVetted }>; overrides: { name: string; overrides: unknown; out: KaitiVetted }[] };
export const KAITI = RECORDED as unknown as Rec;

const byText = <T extends { text: string }>(m: Record<string, T>, text: string): [string, T] | undefined => Object.entries(m).find(([, x]) => x.text === text);

const sorted = (v: unknown): string => JSON.stringify(v, (_, x: unknown) =>
  x && typeof x === "object" && !Array.isArray(x) ? Object.fromEntries(Object.entries(x as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b))) : x);

export function kaitiExtract(text: string): KaitiExtract {
  return byText(KAITI.extract, text)?.[1].out ?? { text, spans: [], answers: 0 };
}

export function kaitiDraft(body: { text: string; draft?: unknown; overrides?: unknown }): KaitiVetted | Error {
  const hit = byText(KAITI.drafts, body.text);
  if (!hit) {
    const refuse = KAITI.drafts.refuse.out;
    return {
      ...refuse, text: body.text, spans: [], draft: null, pid: "kt-mock",
      notes: [{ code: "bad_draft", field: "draft", text: "起草结果不可用：假服务只认录下的几段原文", lane: "refuse" }],
    };
  }
  const [name, rec] = hit;
  const ov = body.overrides && Object.keys(body.overrides as object).length ? body.overrides : null;
  if (!ov) return rec.out;
  const o = KAITI.overrides.find((x) => x.name === name && sorted(x.overrides) === sorted(ov));
  if (o) return o.out;
  return new Error("假服务只认录下的那一组改动");
}
