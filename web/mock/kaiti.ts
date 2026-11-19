// 假服务里的起草服务：只回放 tools/record_kaiti.py 从真 qicao 录下的应答（mock/kaiti.json），不另写一份抽取与校验规则。
// 录下的原文之外的输入一律当作"起草结果不可用"拒绝（与没有配置起草模型时真服务的应答同形）。
import type { KaitiExtract, KaitiVetted, PlatformEntry, PlatformTask } from "../src/api/kaiti";
import RECORDED from "./kaiti.json" with { type: "json" };

type Rec = {
  extract: Record<string, { text: string; out: KaitiExtract }>; drafts: Record<string, { text: string; out: KaitiVetted }>; overrides: { name: string; overrides: unknown; out: KaitiVetted }[];
  /** 拒绝页第 02 条路：人给验收清单之后的确认卡。 */
  acceptance: { name: string; acceptance: unknown; out: KaitiVetted }[];
  /** 从平台导入：一个假平台 plat-a，清单一题，领题回来的确认卡（qicao 的 import_view 录下）。 */
  platforms: PlatformEntry[]; tasks: PlatformTask[]; imports: Record<string, KaitiVetted>;
};
export const KAITI = RECORDED as unknown as Rec;

const byText = <T extends { text: string }>(m: Record<string, T>, text: string): [string, T] | undefined => Object.entries(m).find(([, x]) => x.text === text);

const sorted = (v: unknown): string => JSON.stringify(v, (_, x: unknown) =>
  x && typeof x === "object" && !Array.isArray(x) ? Object.fromEntries(Object.entries(x as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b))) : x);

export function kaitiExtract(text: string): KaitiExtract {
  return byText(KAITI.extract, text)?.[1].out ?? { text, spans: [], answers: 0 };
}

export function kaitiDraft(body: { text: string; draft?: unknown; overrides?: unknown; acceptance?: unknown }): KaitiVetted | Error {
  const hit = byText(KAITI.drafts, body.text);
  if (!hit) {
    const refuse = KAITI.drafts.refuse.out;
    return {
      ...refuse, text: body.text, spans: [], draft: null, pid: "kt-mock",
      notes: [{ code: "bad_draft", field: "draft", text: "起草结果不可用：假服务只认录下的几段原文", lane: "refuse" }],
    };
  }
  const [name, rec] = hit;
  if (Array.isArray(body.acceptance) && body.acceptance.length) {
    const a = KAITI.acceptance.find((x) => x.name === name && sorted(x.acceptance) === sorted(body.acceptance));
    return a ? a.out : new Error("假服务只认录下的那一份验收清单");
  }
  const ov = body.overrides && Object.keys(body.overrides as object).length ? body.overrides : null;
  if (!ov) return rec.out;
  const o = KAITI.overrides.find((x) => x.name === name && sorted(x.overrides) === sorted(ov));
  if (o) return o.out;
  return new Error("假服务只认录下的那一组改动");
}

/** 假平台的三个端点（/v1/connectors…）：只回放录下的应答。 */
export function platformRoute(method: string, path: string, body: () => any): { code: number; body: unknown } | null {
  if (method === "GET" && path === "/v1/connectors") return { code: 200, body: { items: KAITI.platforms } };
  const m = path.match(/^\/v1\/connectors\/([^/]+)\/(tasks|import)$/);
  if (!m) return null;
  const id = decodeURIComponent(m[1]);
  if (!KAITI.platforms.some((p) => p.id === id)) return { code: 400, body: { ok: false, code: "schema_error", detail: `没有登记平台 ${id}` } };
  if (method === "GET" && m[2] === "tasks") return { code: 200, body: { items: KAITI.tasks } };
  if (method === "POST" && m[2] === "import") {
    const hit = KAITI.imports[String(body()?.task ?? "")];
    return hit ? { code: 200, body: hit } : { code: 400, body: { ok: false, code: "schema_error", detail: "平台清单里没有这个任务" } };
  }
  return null;
}
