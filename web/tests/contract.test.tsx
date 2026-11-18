// 契约测试：tests/fixtures/real/ 是真图服务（graph 的 HTTP 绑定）录下的应答（tools/record_fixtures.py）。
// 一、前端的类型与视图模型吃得下真应答；二、开发用的假后端与真图服务同形（同一端点、同一组键）。
import { cleanup, render, waitFor } from "@testing-library/react";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { ApiError, createApi, newIdemKey } from "../src/api/client";
import { ops } from "../src/api/ops";
import type { ArtifactView, BudgetResponse, CardResponse, Event, GraphView, HintTrace, NodeEvidence, ProblemsView, ProfilePreview, StatusView, WorkView } from "../src/api/types";
import { EventLog } from "../src/model/eventlog";
import { buildViewModel } from "../src/model/viewmodel";
import { ApprovalCard } from "../src/ui/ApprovalCard";
import { ExtensionDialog } from "../src/ui/ExtensionDialog";
import { Frontier } from "../src/ui/Frontier";
import { GraphView as Graph } from "../src/ui/GraphView";
import { ArtifactCard } from "../src/ui/registers";
import { pendingIntent, playToEnd, renderWith, rig } from "./helpers";

afterEach(cleanup);

const DIR = join(process.cwd(), "tests", "fixtures", "real");
type Fx = { path?: string; status: number; body: unknown };
const fx = Object.fromEntries(readdirSync(DIR).map((f) => [f.replace(/\.json$/, ""), JSON.parse(readFileSync(join(DIR, f), "utf8")) as Fx]));
const body = <T,>(name: string) => fx[name].body as T;

/** 用录下的应答答复请求：按路径（不看查询串）匹配。 */
const replay: typeof fetch = async (input) => {
  const path = new URL(String(input), "http://x").pathname;
  const hit = Object.values(fx).find((f) => f.path && new URL(f.path, "http://x").pathname === path);
  return hit ? new Response(JSON.stringify(hit.body), { status: hit.status }) : new Response(JSON.stringify({ ok: false, code: "unknown_ref", detail: path }), { status: 404 });
};
const real = { cfg: { base: "", token: "t", fetch: replay }, api: createApi({ base: "", token: "t", fetch: replay }) };

const vmOf = (pid: string) =>
  buildViewModel(pid, { status: body<StatusView>(`${pid}-status`), view: body<GraphView>(`${pid}-view`), budget: body<BudgetResponse>(`${pid}-budget`), work: body<WorkView>(`${pid}-work`) }, body<{ events: Event[] }>(`${pid}-events`).events);

/** 一个对象的键集合（数组取并集）。 */
function keys(v: unknown): string[] {
  const items = Array.isArray(v) ? v : [v];
  return [...new Set(items.flatMap((x) => (x && typeof x === "object" ? Object.keys(x) : [])))].sort();
}

describe("真图服务的应答", () => {
  it("视图模型：走完的题", () => {
    const vm = vmOf("p1");
    expect(vm.terminal).toBe("solved");
    expect(vm.closed).toBe(true);
    expect(vm.goal.badge.label).toBe("exact_match@1");
    expect(vm.goal.predicate.verdicts.map((v) => v.result)).toEqual(["pass"]);
    expect(vm.rows.map((r) => r.kind).sort()).toEqual(["fact", "intent", "intent"]);
    expect(vm.hints).toHaveLength(1);
    expect(vm.hints[0].ts).not.toBeNull();
    expect(vm.ticks.map((t) => t.kind)).toEqual(expect.arrayContaining(["H", "J✓", "C"]));
    expect(vm.budget.cap).toBe(5000);
    expect(vm.layout.nodes.length).toBe(vm.rows.length + vm.hints.length);
    const { container } = render(<Frontier vm={vm} selected={null} onSelect={() => {}} />);
    expect(container.querySelectorAll("[data-node-row]").length).toBeGreaterThan(0);
    expect(render(<Graph vm={vm} selected={null} onSelect={() => {}} />).container.querySelectorAll("[data-graph-node]").length).toBe(vm.layout.nodes.length);
  });

  it("视图模型：等人审批的题", () => {
    const vm = vmOf("p2");
    expect(vm.terminal).toBeNull();
    expect(vm.todo).toEqual([{ kind: "human", target: expect.stringMatching(/^i_/), why: "needs_human" }]);
    expect(vm.frontier.find((g) => g.key === "human")!.ids).toEqual([vm.todo[0].target]);
    expect(vm.rows.find((r) => r.id === vm.todo[0].target)!.state).toBe("needs_human");
  });

  it("事件：按题的哈希链接得上", () => {
    for (const pid of ["p1", "p2"]) {
      const log = new EventLog();
      expect(log.fill(body<{ events: Event[] }>(`${pid}-events`).events)).toBe(true);
      expect(log.events.every((e) => e.problem_id === pid)).toBe(true);
    }
  });

  it("审批卡与 Artifact 卡排得出来", async () => {
    const card = body<CardResponse>("p2-approval");
    const { container } = renderWith({ ...real } as never, <ApprovalCard pid="p2" intentId={card.card.target} head={card.head} canWrite />);
    await waitFor(() => expect(container.querySelector('[data-card="approval"]')).not.toBeNull());
    expect(container.querySelector("[data-card-hash]")!.getAttribute("data-card-hash")).toBe(card.card_hash);
    expect(container.querySelector(".scope-diff")!.textContent).toContain("+ target  second  read  r1");
    expect(container.querySelector<HTMLButtonElement>('[data-action="approve"]')!.disabled).toBe(false);
    cleanup();
    const exec = renderWith({ ...real } as never, <ArtifactCard a={body<ArtifactView>("p1-artifact-exec")} />).container;
    expect(exec.querySelector('[data-register="evidence"] .evidence-first')!.textContent).toContain("cat /etc/hostname");
    cleanup();
    const cand = renderWith({ ...real } as never, <ArtifactCard a={body<ArtifactView>("p1-artifact-candidate")} />).container;
    expect(cand.querySelector('[data-register="evidence"]')).toBeNull();
  });

  it("M0 没有续期卡：not_enabled 如实显示", async () => {
    expect(fx["p2-extension"].status).toBe(404);
    const { container } = renderWith({ ...real } as never, <ExtensionDialog pid="p2" head={1} canWrite />);
    await waitFor(() => expect(container.querySelector("[data-not-enabled]")).not.toBeNull());
  });

  it("错误与被拒的批次：错误码原样传到调用方", async () => {
    await expect(real.api.status("nope")).rejects.toMatchObject({ status: 404, code: "unknown_ref" });
    for (const name of ["proposal-rejected", "proposal-unknown-op"]) {
      const f = fx[name];
      expect(f.status).toBe(200);
      const api = createApi({ base: "", token: "t", fetch: async () => new Response(JSON.stringify(f.body), { status: 200 }) });
      const err = await api.propose("p2", [ops.hintAdd("x")], newIdemKey()).catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).code).toBe("schema_error");
    }
    expect(fx["proposal-no-token"].status).toBe(401);
    expect(fx["proposal-no-token"].body).toMatchObject({ ok: false, code: "forbidden_op" });
  });
});

describe("假后端与真图服务同形", () => {
  it("各端点的键集合相同", async () => {
    const r = rig();
    await playToEnd(r);
    const pid = r.mock.demoPid;
    const m = { status: await r.api.status(pid), view: await r.api.view(pid), budget: await r.api.budget(pid), work: await r.api.work(pid), problems: await r.api.problems() };
    const st = body<StatusView>("p1-status-asof");
    const same = (what: string, a: unknown, b: unknown) => expect(keys(a), what).toEqual(keys(b));

    same("status", m.status, st);
    same("status.problem", m.status.problem, st.problem);
    same("status.goal", m.status.goal, st.goal);
    same("predicate", m.status.goal.predicate, st.goal.predicate);
    same("fact", m.status.facts, [...st.facts, ...body<StatusView>("p2-status").facts]);
    same("intent", m.status.intents, [...body<StatusView>("p1-status").intents, ...body<StatusView>("p2-status").intents]);
    same("hint", m.status.hints, body<StatusView>("p1-status").hints);
    same("verdict", m.status.goal.predicate.verdicts, body<StatusView>("p1-status").goal.predicate.verdicts);
    same("view", m.view, body<GraphView>("p1-view"));
    same("frontier", m.view.frontier, body<GraphView>("p1-view").frontier);
    same("budget", m.budget, body<BudgetResponse>("p1-budget"));
    same("work", m.work, body<WorkView>("p1-work"));
    same("problems", m.problems, body<ProblemsView>("problems"));
    same("problems.items", m.problems.items, body<ProblemsView>("problems").items);
    same("problems.totals", m.problems.totals, body<ProblemsView>("problems").totals);
    same("event", r.mock.eventsOf(pid), body<{ events: Event[] }>("p1-events").events);

    const fact = m.status.facts.find((f) => f.grounds.length > 0)!;
    const ev = await r.api.node(fact.id);
    const realEv = body<NodeEvidence>("p1-fact-evidence");
    same("node(fact)", ev, realEv);
    same("ground", (ev as { grounds: unknown[] }).grounds, (realEv as { grounds: unknown[] }).grounds);
    same("node(intent)", await r.api.node(m.status.intents[0].id), body<NodeEvidence>("p1-intent-evidence"));
    same("artifact", await r.api.artifact(fact.grounds[0]), body<ArtifactView>("p1-artifact-exec"));
    same("exec", (await r.api.artifact(fact.grounds[0])).exec, body<ArtifactView>("p1-artifact-exec").exec);
    const trace = await r.api.hintTrace(m.status.hints[0].id);
    same("hint trace", trace, body<HintTrace>("p1-hint-trace"));
    same("hint trace.exposure", trace.exposure, body<HintTrace>("p1-hint-trace").exposure);

    const r2 = rig();
    const card = await r2.api.card(r2.mock.demoPid, "approval", await pendingIntent(r2, r2.mock.demoPid));
    const realCard = body<CardResponse>("p2-approval");
    same("card", card, realCard);
    same("card.card", card.card, realCard.card);
    same("card.fields", card.card.fields, realCard.card.fields);
    same("card.display", card.display, realCard.display);
    same("card.fields.premises", card.card.fields.premises, realCard.card.fields.premises);
    same("card.display.premises", card.display.premises, realCard.display.premises);

    const pv = await r.api.profilePreview({ scope: [{ resource: "net", pattern: "*", actions: ["connect"], risk: "r1" }], goal: { check: { judge_id: "exact_match" } } });
    const realPv = body<ProfilePreview>("profile-preview");
    same("preview", pv, realPv);
    for (const axis of ["reversibility", "judge", "info"] as const) same(`preview.${axis}`, pv.basis[axis], realPv.basis[axis]);
    same("judges", (await r.api.judges()).items, body<{ items: unknown[] }>("judges").items);
    same("templates", await r.api.templates(), body("templates"));
  });

  it("错误的形状与错误码相同", async () => {
    const r = rig();
    await expect(r.api.status("nope")).rejects.toMatchObject({ status: fx.missing.status, code: (fx.missing.body as { code: string }).code });
    const raw = await r.fetch(`/v1/problems/${r.mock.demoPid}/proposals`, { method: "POST", body: JSON.stringify({ idem_key: "x", ops: [{ op: "hint", body: { text: "t" } }] }) });
    expect(raw.status).toBe(fx["proposal-no-token"].status);
    expect(await raw.json()).toMatchObject({ ok: false, code: "forbidden_op" });
  });
});
