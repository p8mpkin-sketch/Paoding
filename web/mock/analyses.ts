// 假服务里的方案分析（界面一期）：只回放 scripts/analysis_mock.py 用引擎在验收夹具上真跑、再经 analysis_hub 读出的应答
// （mock/analyses.json），不另写一份引擎。提交第 1 次确认时做与 analysis_hub 同口径的几项校验，收下后标“已提交”。
import RECORDED from "./analyses.json" with { type: "json" };
import type { AnDecision, AnSubmitted, AnalysesView, AnalysisDetail, BangView } from "../src/api/analysis-types";

type Res = { status: number; body: unknown };
const err = (status: number, code: string, detail: string): Res => ({ status, body: { ok: false, code, detail } });

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x)) as T;
const HEAD = /【决定\s*v1】\s*闸点\s*([123])/;

/** 与引擎 decision.parse 同形的最小解析：只认第 1 次确认的四个关键字，读不懂的行原样列出。 */
function parseG1(block: string): { dec: AnDecision } | { error: [string, string] } {
  const lines = block.split("\n");
  const at = lines.findIndex((l) => HEAD.test(l));
  if (at < 0) return { error: ["no_block", "正文里没有【决定 v1】闸点 N 这一行"] };
  const gate = `G${HEAD.exec(lines[at])![1]}` as AnDecision["gate"];
  if (gate !== "G1") return { error: ["wrong_gate", `决定块写的是${gate}，现在等的是第 1 次确认`] };
  const out: AnDecision = { v: 1, gate };
  const bad: string[] = [];
  for (const raw of lines.slice(at + 1)) {
    const line = raw.trim();
    if (!line) continue;
    const [k, v] = line.split(/[：:](.*)/s);
    const val = (v ?? "").trim();
    if (k === "选") {
      const ids = val === "无" ? [] : val.split(/[，,、\s]+/).filter(Boolean);
      if (ids.some((x) => !/^C\d+$/.test(x))) bad.push(line); else out.pick = [...(out.pick ?? []), ...ids];
    } else if (k === "排除") {
      const rows = val.split(/[；;]|(?<=[）)])\s*[，,、]\s*/).map((p) => p.trim()).filter(Boolean).map((p) => /^(C\d+)\s*[（(](.+)[）)]$/.exec(p));
      if (rows.some((r) => !r)) bad.push(line); else out.exclude = [...(out.exclude ?? []), ...rows.map((r) => ({ candidate: r![1], why: r![2].trim() }))];
    } else if (k === "改") {
      const m = /^(C\d+(?:\.\w+)+)\s*=\s*(.+)$/.exec(val);
      if (!m) bad.push(line); else out.edit = [...(out.edit ?? []), { pointer: m[1], value: m[2].trim() }];
    } else if (k === "备注") out.note = out.note ? `${out.note}\n${val}` : val;
    else bad.push(line);
  }
  if (bad.length) return { error: ["unparsed", `这几行没读懂：${bad.join("；")}`] };
  return { dec: out };
}

export function analysesMock(now: () => number) {
  const doc = clone(RECORDED) as unknown as { list: AnalysesView; details: Record<string, AnalysisDetail>; artifacts: Record<string, Record<string, unknown>>; bang: BangView };

  const list = (): AnalysesView => ({
    ...doc.list,
    items: doc.list.items.map((it) => {
      const d = doc.details[it.run];
      return { ...it, waiting: d.waiting };
    }),
  });

  function decide(run: string, body: { block?: unknown; deliver_seq?: unknown; budget_add_usd_milli?: unknown }): Res {
    const d = doc.details[run];
    if (!d) return err(404, "unknown_ref", `没有这次分析：${run}`);
    if (typeof body.block !== "string" || typeof body.deliver_seq !== "number") return err(400, "schema_error", "请求体是 {block: 决定块原文, deliver_seq: 你看的那次交付, budget_add_usd_milli?}");
    const add = body.budget_add_usd_milli ?? 0;
    if (typeof add !== "number" || !Number.isInteger(add) || add < 0 || add > 100_000) return err(400, "schema_error", "budget_add_usd_milli 取 0 到 100000 的整数");
    const w = d.waiting;
    if (!w) return err(409, "not_at_gate", `这次分析现在不在等你确认（${d.step}）`);
    if (w.gate !== "G1") return err(409, "not_yet", "第 2、3 次确认的提交在界面后续几期，这一期只读");
    if (body.deliver_seq !== w.deliver_seq) return err(409, "stale_view", "你看的不是最新一次交付，请刷新");
    if (w.submitted) return err(409, "already_submitted", "这一次确认已经提交过，等引擎续做");
    const parsed = parseG1(body.block);
    if ("error" in parsed) return err(400, parsed.error[0], parsed.error[1]);
    const dec = parsed.dec;
    const ids = new Set((d.candidates_doc?.candidates ?? []).map((c) => c.id));
    const picked = dec.pick ?? [];
    const excluded = (dec.exclude ?? []).map((r) => r.candidate);
    const unknown = [...new Set([...picked, ...excluded])].filter((x) => !ids.has(x)).sort();
    if (unknown.length) return err(400, "unknown_candidate", `没有候选 ${unknown.join(", ")}`);
    if (!picked.length) return err(400, "nothing_picked", "请至少选一个候选");
    if (picked.some((x) => excluded.includes(x))) return err(400, "pick_and_exclude", "同一个候选不能既选又排除");
    for (const e of dec.edit ?? []) {
      const [cid, fld] = e.pointer.split(".");
      if (!ids.has(cid) || fld !== "title" || !e.value.trim()) return err(400, "bad_edit", `第 1 次确认只能改候选的标题：${e.pointer}`);
    }
    const row: AnSubmitted = {
      run, gate: "G1", deliver_seq: w.deliver_seq, block: body.block, block_sha256: "", decision: dec,
      budget_add_usd_milli: add, by: "human", at: new Date(now()).toISOString().replace(/\.\d+Z$/, "Z"), forwarded: false,
    };
    d.submitted = [row];
    d.history = [...d.history, row];
    d.waiting = { ...w, submitted: true };
    return { status: 200, body: { ok: true, submitted: row } };
  }

  /** 返回 null 表示不归这里管。 */
  return function route(method: string, path: string, authorized: () => Res | null, parse: () => unknown): Res | null {
    if (path === "/v1/fenjue/bang") return method === "GET" ? { status: 200, body: doc.bang } : err(405, "schema_error", "只读");
    if (path === "/v1/analyses") return method === "GET" ? { status: 200, body: list() } : err(405, "schema_error", "只读");
    const m = path.match(/^\/v1\/analyses\/([^/]+)(?:\/(decision)|\/artifacts\/([0-9a-f]{64}))?$/);
    if (!m) return path.startsWith("/v1/analyses/") ? err(404, "unknown_ref", `没有端点 ${path}`) : null;
    const run = decodeURIComponent(m[1]);
    const d = doc.details[run];
    if (m[2]) {
      if (method !== "POST") return err(405, "schema_error", "只收 POST");
      const no = authorized();
      if (no) return no;
      const b = parse();
      return decide(run, b && typeof b === "object" ? (b as Record<string, unknown>) : {});
    }
    if (method !== "GET") return err(405, "schema_error", "只读");
    if (!d) return err(404, "unknown_ref", `没有这次分析：${run}`);
    if (m[3]) {
      const a = d.artifacts.find((x) => x.sha256 === m[3]);
      if (!a) return err(404, "unknown_ref", "这次分析没有这份产物");
      return { status: 200, body: { name: a.name, sha256: a.sha256, kind: a.kind, content: doc.artifacts[run]?.[a.sha256] ?? null } };
    }
    return { status: 200, body: d };
  };
}
