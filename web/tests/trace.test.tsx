// 任务详情 v6：轨迹合并（纯函数）与任务页的过程追踪、执行图、文件两栏、概要条、右栏模型调用。
import { cleanup, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { ActItem } from "../src/api/activity-types";
import type { Event } from "../src/api/types";
import { buildTrace, dur, layoutGraph, matches, tok } from "../src/model/trace";
import { Cockpit } from "../src/pages/Cockpit";
import { renderWith, rig } from "./helpers";

afterEach(cleanup);

const $ = (c: ParentNode, sel: string) => c.querySelector<HTMLElement>(sel);
let seq = 0;
const ev = (kind: string, body: Record<string, unknown>, actor: Partial<Event["actor"]> = { kind: "sinan", id: "sinan" }, ts?: number): Event => {
  seq++;
  return { v: 1, seq, problem_id: "p", ts: ts ?? seq * 1000, actor: { kind: "sinan", id: "sinan", ...actor } as Event["actor"], kind, body, idem_key: `k${seq}`, prev_hash: "", hash: "" } as unknown as Event;
};

describe("轨迹合并（纯函数）", () => {
  it("事件与活动按时刻合成；exec 留档并进那次工具调用；cost 与 turn 数目相同时按序号配对；会话中途的指导排进那个会话", () => {
    seq = 0;
    const open = ev("open_problem", { title: "t" }, { kind: "human", id: "me" });
    const lease = ev("lease", { kind: "solve", holder: "sinan" });
    const L = `l_${lease.seq}`;
    const art = ev("register_artifact", { class: "exec", size: 10, producer: { actor: "executor", session: L }, exec: { tool: "shell", command: "ls", exit_code: 0 } }, { kind: "executor", id: "x" });
    const hint = ev("hint", { text: "看看 README" }, { kind: "human", id: "me" });
    const c1 = ev("cost", { task_id: L, model: "m", tokens_in: 100, tokens_cached: 0, tokens_out: 10, usd_milli: 5 }, { kind: "adapter", id: "a", session: L });
    const c2 = ev("cost", { task_id: L, model: "m", tokens_in: 200, tokens_cached: 50, tokens_out: 20, usd_milli: 7 }, { kind: "adapter", id: "a", session: L });
    const rel = ev("release", { lease: L, outcome: "done" });
    const items: ActItem[] = [
      { n: 1, round: 1, kind: "think", text: "先列目录", t: 100 },
      { n: 2, round: 1, kind: "turn", model: "m", in: 100, out: 10, cache_read: 0, cache_write: 0, stop: "tool_use", t: 200 },
      { n: 3, round: 1, kind: "call", tool: "exec", gist: "ls", id: "c1", t: 300 },
      { n: 4, round: 1, kind: "result", id: "c1", ok: true, gist: "a b", artifact: `a_${art.seq}`, size: 3, t: 1100 },
      { n: 5, round: 1, kind: "turn", model: "m", in: 200, out: 20, cache_read: 50, cache_write: 0, stop: "end_turn", t: 3000 },
      { n: 6, round: 1, kind: "say", text: "做完了", t: 3100 },
    ];
    const tr = buildTrace([open, lease, art, hint, c1, c2, rel], { [L]: { items, anchored: 6, live: false, now: null } });
    // exec 留档并进工具调用，不重复列；cost 不单列
    expect(tr.entries.filter((x) => x.artifact === `a_${art.seq}`)).toHaveLength(1);
    expect(tr.entries.some((x) => x.kind === "cost")).toBe(false);
    const call = tr.entries.find((x) => x.kind === "call")!;
    expect(call).toMatchObject({ state: "ok", dur: 800, tool: "exec", lease: L });
    const turns = tr.entries.filter((x) => x.kind === "turn");
    expect(turns.map((x) => x.cost?.usd_milli)).toEqual([5, 7]);
    // 指导发生在会话进行中：排进会话，归属仍是任务级
    const h = tr.entries.find((x) => x.ev?.kind === "hint")!;
    expect(h).toMatchObject({ lease: null, during: L });
    const g = tr.sessions[0];
    expect(g).toMatchObject({ lease: L, kind: "solve", active: false, outcome: "done", turns: 2, calls: 1, failed: 0, usd_milli: 12, model: "m" });
    expect(g.tokens).toEqual({ in: 300, out: 30, cache_read: 50 });
    expect(tr.totals).toMatchObject({ sessions: 1, live: 0, turns: 2, calls: 1, tokensIn: 300, usd_milli: 12, models: ["m"] });
    expect(tr.counts).toMatchObject({ think: 1, turn: 2, tool: 1, exec: 1, error: 0, human: 2 });
    // 块：新建在前，会话一块
    expect(tr.blocks.map((b) => b.type)).toEqual(["entry", "session"]);
    // 筛选与搜索
    expect(tr.entries.filter((x) => matches(x, "exec", "", null))).toHaveLength(1);
    expect(tr.entries.filter((x) => matches(x, "all", "README", null)).map((x) => x.ev?.kind)).toEqual(["hint"]);
    expect(tr.entries.filter((x) => matches(x, "all", "", L)).length).toBe(g.entries.length);
  });

  it("cost 与 turn 对不上就各自单列；没有活动的会话以代理计量算模型调用；回放（没有 t）跟着留档的时刻排", () => {
    seq = 0;
    const lease = ev("lease", { kind: "solve" });
    const L = `l_${lease.seq}`;
    const art = ev("register_artifact", { class: "exec", producer: { session: L }, exec: { tool: "shell", command: "make", exit_code: 2 } }, { kind: "executor", id: "x" }, 50_000);
    const c = ev("cost", { task_id: L, model: "m", tokens_in: 900, tokens_cached: 0, tokens_out: 90, usd_milli: 40 }, { kind: "adapter", id: "a", session: L }, 60_000);
    const items: ActItem[] = [
      { n: 1, round: 1, kind: "turn", model: "m", in: 1, out: 1, cache_read: 0, cache_write: 0, stop: "max_tokens" },
      { n: 2, round: 1, kind: "turn", model: "m", in: 1, out: 1, cache_read: 0, cache_write: 0, stop: "tool_use" },
      { n: 3, round: 1, kind: "call", tool: "exec", gist: "make", id: "c" },
      { n: 4, round: 1, kind: "result", id: "c", ok: false, gist: "error", artifact: `a_${art.seq}` },
    ];
    const tr = buildTrace([lease, art, c], { [L]: { items, anchored: 4, live: true, now: null } });
    const cost = tr.entries.find((x) => x.kind === "cost")!;
    expect(cost.cost!.usd_milli).toBe(40);
    expect(tr.entries.filter((x) => x.kind === "turn").every((x) => !x.cost)).toBe(true);
    const call = tr.entries.find((x) => x.kind === "call")!;
    expect(call.state).toBe("bad");
    expect(call.dur).toBeNull();
    expect(call.at).toBe(50_000 - 1); // 没有 t：跟着留档登记的时刻
    expect(tr.counts.error).toBe(2); // 出错的命令 + 输出到上限被截断
    expect(tr.sessions[0].active).toBe(true);

    seq = 0;
    const l2 = ev("lease", { kind: "reason" });
    const c2 = ev("cost", { task_id: `l_${l2.seq}`, model: "x", tokens_in: 10, tokens_cached: 4, tokens_out: 2, usd_milli: 3 }, { kind: "adapter", id: "a", session: `l_${l2.seq}` });
    const t2 = buildTrace([l2, c2], {});
    expect(t2.sessions[0]).toMatchObject({ turns: 1, usd_milli: 3, model: "x", tokens: { in: 10, out: 2, cache_read: 4 } });
  });

  it("执行图布局：“你”泳道在最上；一个跑完再起的会话之间连接力；人的操作连到它之后的第一步；完整档挂出留档", () => {
    seq = 0;
    const a = ev("lease", { kind: "explore", target: "i_1" });
    const A = `l_${a.seq}`;
    const art = ev("register_artifact", { class: "exec", producer: { session: A }, exec: { tool: "http_get", command: "get /", exit_code: 0 } }, { kind: "executor", id: "x" });
    const ra = ev("release", { lease: A, outcome: "done" });
    const h = ev("hint", { text: "换个端口" }, { kind: "human", id: "me" });
    const b = ev("lease", { kind: "explore", target: "i_1" });
    const B = `l_${b.seq}`;
    const art2 = ev("register_artifact", { class: "exec", producer: { session: B }, exec: { tool: "http_get", command: "get /2", exit_code: 0 } }, { kind: "executor", id: "x" });
    const tr = buildTrace([a, art, ra, h, b, art2], {});
    expect(tr.sessions.map((g) => g.after)).toEqual([null, A]);
    const compact = layoutGraph(tr, "compact", () => ({ label: "", sub: "" }));
    expect(compact.lanes.map((l) => l.key)).toEqual(["you", A, B]);
    expect(compact.edges.filter((e) => e.kind === "relay")).toHaveLength(1);
    const hn = compact.nodes.find((n) => n.lane === 0)!;
    expect(compact.edges.find((e) => e.kind === "human")).toMatchObject({ from: hn.id });
    expect(compact.nodes.every((n, i, xs) => i === 0 || n.col >= xs[i - 1].col)).toBe(true);
    const full = layoutGraph(buildTrace([a, art], { [A]: { items: [{ n: 1, round: 1, kind: "call", tool: "exec", gist: "x", id: "c" }, { n: 2, round: 1, kind: "result", id: "c", ok: true, gist: "", artifact: `a_${art.seq}` }], anchored: null, live: false, now: null } }), "full", () => ({ label: "", sub: "" }));
    expect(full.nodes.filter((n) => n.below)).toHaveLength(1);
    expect(full.edges.some((e) => e.kind === "file")).toBe(true);
  });

  it("短写：token 与耗时", () => {
    expect([tok(812), tok(4200), tok(84_000), tok(312_000), tok(1_500_000)]).toEqual(["812", "4.2k", "84k", "312k", "1.5M"]);
    expect([dur(null), dur(420), dur(2400), dur(61_000)]).toEqual(["—", "420ms", "2.4s", "1m01s"]);
  });
});

describe("任务页：过程追踪、执行图、文件、概要条", () => {
  it("开放道在跑（demo-7）：过程里有思考、模型调用（token、停止原因、按序号配上的花费）、进行中的命令；可筛可搜", async () => {
    const r = rig();
    const { container } = renderWith(r, <Cockpit pid="demo-7" asOf={null} node={null} />);
    const sum = await waitFor(() => { const s = $(container, "[data-trace-summary]"); expect(s?.textContent).toContain("模型调用4"); return s!; });
    expect(sum.textContent).toContain("失败 1");
    fireEvent.click($(container, '[data-task-tab="steps"]')!);
    const trace = await waitFor(() => { const t = $(container, "[data-trace]"); expect(t?.querySelectorAll('[data-kind="turn"]').length).toBe(4); return t!; });
    expect(trace.querySelectorAll('[data-kind="think"]')).toHaveLength(2);
    expect($(trace, '[data-kind="turn"] [data-turn-cost]')!.textContent).toBe("$0.05");
    expect($(trace, '[data-kind="turn"] [data-stop]')!.textContent).toBe("要调工具");
    expect(trace.querySelector('[data-call-state="now"]')).not.toBeNull();
    expect($(trace, '[data-trace-session]')!.getAttribute("data-active")).toBe("true");
    expect($(trace, '[data-action="trace-follow"]')!.getAttribute("aria-pressed")).toBe("true");
    // 只看出错
    fireEvent.click($(trace, '[data-filter="error"]')!);
    await waitFor(() => expect(trace.querySelectorAll("[data-step]")).toHaveLength(1));
    expect($(trace, "[data-step]")!.textContent).toContain("python -m pytest -q");
    // 搜索思考全文
    fireEvent.click($(trace, '[data-filter="all"]')!);
    fireEvent.change($(trace, "[data-trace-search]")!, { target: { value: "时区" } });
    await waitFor(() => expect(trace.querySelectorAll("[data-step]")).toHaveLength(1));
    expect($(trace, "[data-step]")!.getAttribute("data-kind")).toBe("think");
    // 概要：只看思考与模型调用之外的
    fireEvent.change($(trace, "[data-trace-search]")!, { target: { value: "" } });
    fireEvent.click($(trace, '[data-action="trace-brief"]')!);
    await waitFor(() => expect(trace.querySelectorAll('[data-kind="turn"], [data-kind="think"]')).toHaveLength(0));
  });

  it("概要条的数字点了跳到过程并套上筛选；右栏列出模型调用、token 与缓存命中", async () => {
    const r = rig();
    const { container } = renderWith(r, <Cockpit pid="demo-7" asOf={null} node={null} />);
    const btn = await waitFor(() => { const b = $(container, '[data-summary="tool"]'); expect(b?.textContent).toContain("4"); return b!; });
    fireEvent.click(btn);
    await waitFor(() => expect($(container, "[data-trace]")?.getAttribute("data-filter")).toBe("tool"));
    const rail = await waitFor(() => { const s = $(container, "[data-rail-calls]"); expect(s).not.toBeNull(); return s!; });
    expect(rail.textContent).toContain("4 次");
    expect($(rail, "[data-rail-tokens-in]")!.textContent).toBe("21.9k");
    expect($(rail, "[data-rail-cache]")!.textContent).toMatch(/^\d+%$/);
  });

  it("结构（demo-7）：执行图有你、会话两条泳道；在做的命令闪动；点节点在检视里看详情，“在过程里定位”跳回过程选中那一条", async () => {
    const r = rig();
    const { container } = renderWith(r, <Cockpit pid="demo-7" asOf={null} node={null} />);
    await waitFor(() => expect($(container, '[data-task-tab="struct"]')).not.toBeNull());
    fireEvent.click($(container, '[data-task-tab="struct"]')!);
    const g = await waitFor(() => { const x = $(container, "[data-exec-graph]"); expect(x?.querySelectorAll("[data-node]").length).toBeGreaterThan(6); return x!; });
    expect(g.querySelectorAll("[data-lane]")).toHaveLength(2);
    expect(g.querySelector('[data-node-state="now"]')).not.toBeNull();
    expect(g.querySelectorAll('[data-node-kind="think"]')).toHaveLength(0); // 紧凑档只画模型调用与工具调用
    fireEvent.click($(g, '[data-action="xg-full"]')!);
    await waitFor(() => expect(g.querySelectorAll('[data-node-kind="think"]').length).toBe(2));
    expect(g.querySelectorAll('[data-node-kind="file"]').length).toBe(3); // 两次 exec 的留档挂在下面，加上你给的原话
    const node = $(g, '[data-node-state="now"]')!;
    fireEvent.click(node);
    await waitFor(() => expect($(g, "[data-exec-inspect]")!.textContent).toContain("git checkout 71aa03b"));
    fireEvent.click($(g, '[data-action="xg-locate"]')!);
    const trace = await waitFor(() => { const t = $(container, "[data-trace]"); expect(t).not.toBeNull(); return t!; });
    await waitFor(() => expect($(trace, '[data-step][data-selected="true"]')?.textContent).toContain("git checkout 71aa03b"));
  });

  it("严格判定（demo-1）：结构缺省是推理图，可以切到执行图", async () => {
    const r = rig();
    const { container } = renderWith(r, <Cockpit pid="demo-1" asOf={null} node={null} />);
    await waitFor(() => expect($(container, '[data-task-tab="struct"]')).not.toBeNull());
    fireEvent.click($(container, '[data-task-tab="struct"]')!);
    await waitFor(() => expect($(container, ".tk-struct .main")).not.toBeNull());
    fireEvent.click($(container, '[data-action="struct-exec"]')!);
    await waitFor(() => expect($(container, "[data-exec-graph] [data-node]")).not.toBeNull());
    expect($(container, ".tk-struct")).toBeNull();
  });

  it("文件（demo-6）：左边按来源分组，右边预览选中的那份；可搜命令", async () => {
    const r = rig();
    const { container } = renderWith(r, <Cockpit pid="demo-6" asOf={null} node={null} />);
    await waitFor(() => expect($(container, '[data-task-tab="files"]')).not.toBeNull());
    fireEvent.click($(container, '[data-task-tab="files"]')!);
    const files = await waitFor(() => { const f = $(container, "[data-files-two]"); expect(f?.querySelectorAll("[data-file]").length).toBeGreaterThan(5); return f!; });
    expect([...files.querySelectorAll("[data-file-group]")].map((x) => x.getAttribute("data-file-group"))).toEqual(["exec", "authored", "input", "knowledge"]);
    await waitFor(() => expect($(files, "[data-file-preview] [data-artifact]")).not.toBeNull());
    const second = files.querySelectorAll<HTMLElement>("[data-file]")[1];
    fireEvent.click(second);
    await waitFor(() => expect($(files, "[data-file-preview]")!.getAttribute("data-file-preview")).toBe(second.getAttribute("data-file")));
    fireEvent.change($(files, "[data-file-search]")!, { target: { value: "crewai" } });
    await waitFor(() => expect(files.querySelectorAll("[data-file]")).toHaveLength(1));
  });
});
