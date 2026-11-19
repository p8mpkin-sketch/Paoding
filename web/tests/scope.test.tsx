// 运行时扩权的网页一侧（runtime-grants §7，第三步）：扩权卡、待办、横幅、时间轴节点。数据来自假图服务的 demo-4。
import { cleanup, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ApiError, createApi, newIdemKey } from "../src/api/client";
import { ops } from "../src/api/ops";
import type { CardResponse, ScopeCardFields, ScopeDisplay } from "../src/api/types";
import { mentionsOf, paraMark, profileChanges, riskSource } from "../src/model/scope";
import { ticksOf } from "../src/model/ticks";
import { Cockpit } from "../src/pages/Cockpit";
import { ScopeCard } from "../src/ui/ScopeCard";
import { liveSession, renderWith, rig, type Rig } from "./helpers";

afterEach(cleanup);
const PID = "demo-4";

async function asks(r: Rig): Promise<string[]> {
  const w = await r.api.work(PID);
  return w.items.flatMap((x) => (x.kind === "human" && x.why === "scope_request" ? [x.target] : []));
}
async function statementRef(r: Rig): Promise<string> {
  return (await r.api.status(PID)).problem.origin.statement_ref;
}
const card = (r: Rig, rid: string, ui: { head?: number; canWrite?: boolean; ref?: string } = {}) =>
  renderWith(r, <ScopeCard pid={PID} requestId={rid} head={ui.head ?? r.mock.head(PID)} canWrite={ui.canWrite ?? true} statementRef={ui.ref} />);

describe("纯函数", () => {
  it("原文对照：先找 host:port 原样，再退到主机名；段号从 1 起", () => {
    const st = "第一段。\n\n接口在 q7.lab:8443。\n\n镜像在 mirror.example.org 上。\n";
    expect(mentionsOf(st, "q7.lab:8443")).toEqual([{ para: 2, text: "接口在 q7.lab:8443。", exact: true }]);
    expect(mentionsOf(st, "mirror.example.org:443")).toEqual([{ para: 3, text: "镜像在 mirror.example.org 上。", exact: false }]);
    expect(mentionsOf(st, "other.host:1")).toEqual([]);
    expect(paraMark(2)).toBe("②");
  });
  it("风险来源与画像变化", () => {
    expect(riskSource([4, null], 0)).toBe("风险表第 4 条");
    expect(riskSource([4, null], 1)).toBe("风险表未命中，按缺省 r2");
    expect(riskSource(null, 0)).toContain("旧申请");
    expect(profileChanges({ info: "complete", judge: "hard", reversibility: "r0" }, { info: "partial", judge: "hard", reversibility: "r1" }))
      .toEqual([["info", "complete", "partial"], ["reversibility", "r0", "r1"]]);
  });
});

describe("扩权卡", () => {
  it("差异视图、风险来源、批准后画像、没有自动批准的原因、原文对照", async () => {
    const r = rig();
    const [mirror] = await asks(r);
    const { container } = card(r, mirror, { ref: await statementRef(r) });
    await waitFor(() => expect(container.querySelector('[data-card="scope"]')).not.toBeNull());
    const rows = [...container.querySelectorAll("[data-rule]")].map((e) => [e.getAttribute("data-rule"), e.textContent]);
    expect(rows[0][0]).toBe("new");
    expect(rows[0][1]).toContain("mirror.example.org:443");
    expect(rows.filter(([k]) => k === "held").map(([, t]) => t).join("|")).toContain("q7.lab:8443"); // 自动批过的也在现有范围里
    expect(container.querySelector("[data-risk-source]")!.textContent).toContain("风险表未命中，按缺省 r2");
    expect(container.querySelector("[data-profile-change]")!.textContent).toBe("可逆性 r0 → r2");
    expect(container.querySelector('[data-zone="blockers"]')!.textContent).toContain("不在练习道信封的地址段里");
    await waitFor(() => expect(container.querySelector("[data-mention]")).not.toBeNull());
    expect(container.querySelector("[data-mention]")!.textContent).toContain("②");
    expect(container.querySelector("[data-mention]")!.textContent).toContain("只对上主机名");
    // 理由是申请方写的：叙述语域，不是证据样式
    expect(container.querySelector('[data-zone="why"] [data-register]')!.getAttribute("data-register")).toBe("narrative");
  });

  it("批准带所见的 seq 与 card_hash；上调风险时带 risk；批准后规则进范围、待办清掉", async () => {
    const r = rig();
    const [, q9] = await asks(r);
    const { container } = card(r, q9);
    await waitFor(() => expect(container.querySelector('[data-action="approve"]')).not.toBeNull());
    expect(container.querySelector("[data-risk-source]")!.textContent).toContain("风险表第 1 条");
    const sel = container.querySelector<HTMLSelectElement>('[data-action="risk"]')!;
    expect([...sel.options].map((o) => o.value)).toEqual(["r0", "r1", "r2"]);
    fireEvent.change(sel, { target: { value: "r1" } });
    const hash = container.querySelector("[data-card-hash]")!.getAttribute("data-card-hash");
    fireEvent.click(container.querySelector('[data-action="approve"]')!);
    await waitFor(() => expect(container.querySelector("[data-done]")).not.toBeNull());
    const post = r.fetch.calls.find((c) => c.method === "POST")!;
    const body = JSON.parse(post.body!) as { ops: { op: string; body: Record<string, unknown> }[] };
    expect(body.ops).toEqual([{ op: "grant_scope", body: { request: q9, decision: "approve", seen: { seq: r.mock.globalHead() - 1, card_hash: hash }, risk: ["r1"] } }]);
    const st = await r.api.status(PID);
    expect(st.problem.scope.at(-1)).toMatchObject({ pattern: "q9.lab:9000", risk: "r1", granted: { request: q9 } });
    expect(await asks(r)).not.toContain(q9);
  });

  it("拒绝要写理由；只可上调：申请里最高档以下的选项不出现", async () => {
    const r = rig();
    const [mirror] = await asks(r);
    const { container } = card(r, mirror);
    await waitFor(() => expect(container.querySelector('[data-action="deny"]')).not.toBeNull());
    expect([...container.querySelector<HTMLSelectElement>('[data-action="risk"]')!.options].map((o) => o.value)).toEqual(["r2"]);
    const deny = container.querySelector<HTMLButtonElement>('[data-action="deny"]')!;
    expect(deny.disabled).toBe(true);
    fireEvent.change(container.querySelector(".deny textarea")!, { target: { value: "镜像不可信" } });
    fireEvent.click(deny);
    await waitFor(() => expect(container.querySelector("[data-done]")).not.toBeNull());
    const after = await r.api.card<ScopeCardFields, ScopeDisplay>(PID, "scope", mirror);
    expect(after.display.decision).toMatchObject({ decision: "deny", reason: { value: "镜像不可信" } });
  });

  it("卡片在查看期间变了：禁用批准，列出变了的字段；服务端以 stale_view 兜底", async () => {
    const r = rig();
    const [mirror] = await asks(r);
    let changed = false;
    const shifting: typeof fetch = async (input, init) => {
      const res = await r.fetch(input, init);
      if (!changed || !String(input).includes("/cards/scope/")) return res;
      const c = (await res.json()) as CardResponse<ScopeCardFields, ScopeDisplay>;
      c.card.fields.scope = [...c.card.fields.scope, { resource: "net", pattern: "x.lab:1", actions: ["connect"], risk: "r0" }];
      c.card_hash = "e".repeat(64);
      return new Response(JSON.stringify(c), { status: 200 });
    };
    const cfg = { ...r.cfg, fetch: shifting };
    const rr = { ...r, cfg, api: createApi(cfg) };
    const view = renderWith(rr, <ScopeCard pid={PID} requestId={mirror} head={10} canWrite />);
    const q = (sel: string) => view.container.querySelector<HTMLButtonElement>(sel);
    await waitFor(() => expect(q('[data-action="approve"]')).not.toBeNull());
    changed = true;
    const { ServicesContext } = await import("../src/app/context");
    view.rerender(<ServicesContext.Provider value={{ api: rr.api, cfg }}><ScopeCard pid={PID} requestId={mirror} head={11} canWrite /></ServicesContext.Provider>);
    await waitFor(() => expect(q("[data-stale]")).not.toBeNull());
    expect(q('[data-action="approve"]')!.disabled).toBe(true);
    expect([...view.container.querySelectorAll("[data-stale] li")].map((e) => e.textContent).some((p) => p!.startsWith("scope"))).toBe(true);

    const err = await r.api.propose(PID, [ops.grantScope(mirror, { seq: 1, card_hash: "0".repeat(64) })], newIdemKey()).catch((e: unknown) => e);
    expect((err as ApiError).code).toBe("stale_view");
    expect((err as ApiError).extra).toMatchObject({ card: { kind: "scope", target: mirror } });
  });

  it("已决定的申请：自动批准写明按哪一版信封，没有决定按钮", async () => {
    const r = rig();
    const st = await r.api.status(PID);
    const auto = st.problem.scope.find((x) => x.pattern === "q7.lab:8443")!.granted!.request;
    const { container } = card(r, auto);
    await waitFor(() => expect(container.querySelector("[data-decided]")).not.toBeNull());
    expect(container.querySelector("[data-decided]")!.textContent).toContain("按练习道信封 v3 自动批准");
    expect(container.querySelector('[data-action="approve"]')).toBeNull();
  });
});

describe("待办、横幅与时间轴", () => {
  it("工作区：会话面板上方的横幅数出待批的地址，点开是同一张扩权卡", async () => {
    const r = rig();
    const { container } = renderWith(r, <Cockpit pid={PID} asOf={null} node={null} />);
    await waitFor(() => expect(container.querySelector('[data-banner="scope"]')).not.toBeNull());
    expect(container.querySelector('[data-banner="scope"]')!.textContent).toContain("等你批准访问 2 个地址");
    expect(container.querySelectorAll('[data-todo-item^="scope_request:"]')).toHaveLength(2);
    fireEvent.click(container.querySelector('[data-banner="scope"]')!);
    await waitFor(() => expect(container.querySelector('[data-sheet="todo"] [data-card="scope"]')).not.toBeNull());
  });

  it("时间轴：扩权、撤销、自动批准各占一个节点；自动批准写明信封版本", async () => {
    const r = rig();
    const [, q9] = await asks(r);
    const c = await r.api.card(PID, "scope", q9);
    await r.api.propose(PID, [ops.grantScope(q9, { seq: c.as_of, card_hash: c.card_hash })], newIdemKey());
    const st = await r.api.status(PID);
    await r.api.propose(PID, [ops.revokeScope(st.problem.scope.length - 1, "用完了")], newIdemKey());
    const s = await liveSession(r, PID);
    const ticks = ticksOf((await r.api.ticks(PID)).ticks, s.getState().head).filter((t) => t.kind === "S");
    s.close();
    expect(ticks.map((t) => t.label.split(" · ")[0])).toEqual(["按练习道信封 v3 自动批准访问", "批准访问", "撤销授权"]);
  });
});
