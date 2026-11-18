// 增强工作区（工作台设计 §1 模块三）：在途会话、三视图、日志与成本、聚焦与高亮、快捷操作。
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { NodeRow } from "../src/model/viewmodel";
import { byLevel, emphasisOf } from "../src/model/viewmodel";
import { Cockpit } from "../src/pages/Cockpit";
import { GraphView } from "../src/ui/GraphView";
import { liveSession, playToEnd, renderWith, rig, until } from "./helpers";

beforeEach(() => { localStorage.clear(); window.history.replaceState(null, "", "/"); });
afterEach(cleanup);

const row = (id: string, premises: string[], level: NodeRow["level"] = null) => ({ id, premises, level } as unknown as NodeRow);

describe("聚焦与高亮（只沿 premises 取闭包）", () => {
  const rows = [row("a", []), row("b", ["a"]), row("c", ["b"]), row("d", ["c"]), row("x", []), row("y", ["x", "c"])];
  it("支撑链：自身与全部上游", () => {
    expect([...emphasisOf(rows, "c", "chain")].sort()).toEqual(["a", "b", "c"]);
  });
  it("聚焦子图：再加全部下游", () => {
    expect([...emphasisOf(rows, "c", "focus")].sort()).toEqual(["a", "b", "c", "d", "y"]);
  });
  it("按等级分组：顺序固定，空组不出", () => {
    const g = byLevel([row("1", [], "E0"), row("2", [], "E3"), row("3", [], null), row("4", [], "E0")]);
    expect(g.map((x) => [x.level, x.rows.map((r) => r.id)])).toEqual([["E3", ["2"]], ["E0", ["1", "4"]], [null, ["3"]]]);
  });
});

describe("视图模型的在途会话", () => {
  it("取 status.leases 里 active 的，已用时长按事件时钟算", async () => {
    const r = rig();
    const s = await liveSession(r, r.mock.demoPid);
    const vm = s.getState().vm!;
    const st = await r.api.status(r.mock.demoPid, vm.seq);
    expect(vm.sessions.map((x) => x.id)).toEqual(st.leases.filter((l) => l.active).map((l) => l.id));
    for (const x of vm.sessions) expect(x.since_ms === null || x.since_ms >= 0).toBe(true);
    s.close();
  });
});

describe("图的突出显示不改坐标（HT-14）", () => {
  it("淡出其余节点，data-x/data-y 不变", async () => {
    const r = rig();
    await playToEnd(r);
    const s = await liveSession(r, r.mock.demoPid);
    const vm = s.getState().vm!;
    s.close();
    const target = vm.rows.find((x) => x.premises.length > 0)!;
    const coords = (c: HTMLElement) => [...c.querySelectorAll("[data-graph-node]")].map((n) => `${n.getAttribute("data-x")},${n.getAttribute("data-y")}`);
    const plain = render(<GraphView vm={vm} selected={target.id} onSelect={() => {}} />).container;
    const before = coords(plain);
    cleanup();
    const lit = render(<GraphView vm={vm} selected={target.id} onSelect={() => {}} emphasis={emphasisOf(vm.rows, target.id, "chain")} />).container;
    expect(coords(lit)).toEqual(before);
    expect(lit.querySelector(`[data-graph-node="${target.id}"]`)!.getAttribute("class")).toMatch(/\blit\b/);
    expect(lit.querySelectorAll(".gnode.dim").length).toBeGreaterThan(0);
  });
});

describe("工作区页", () => {
  it("时间线视图点一行即回放到该 seq；日志可按种类过滤；成本 Tab 有分项", async () => {
    const r = rig();
    const pid = r.mock.demoPid;
    const { container } = renderWith(r, <Cockpit pid={pid} asOf={null} node={null} />);
    await waitFor(() => expect(container.querySelector(".cockpit")).not.toBeNull());
    expect(container.querySelector("[data-sessions]")).not.toBeNull();
    fireEvent.click(container.querySelector('[data-center="timeline"]')!);
    const rows = container.querySelectorAll<HTMLButtonElement>('[data-event-timeline] [data-action="seek"]');
    expect(rows.length).toBeGreaterThan(3);
    fireEvent.click(rows[2]);
    const seq = rows[2].closest("[data-tick-seq]")!.getAttribute("data-tick-seq");
    expect(new URLSearchParams(window.location.search).get("as_of")).toBe(seq);

    fireEvent.click(container.querySelector('[data-right-tab="log"]')!);
    const kinds = [...container.querySelectorAll<HTMLButtonElement>("[data-log-kind]")];
    expect(kinds.length).toBeGreaterThan(1);
    const k = kinds[0].getAttribute("data-log-kind")!;
    const total = container.querySelectorAll("[data-log-row]").length;
    fireEvent.click(kinds[0]);
    expect(container.querySelectorAll("[data-log-row]").length).toBeLessThan(total);
    expect([...container.querySelectorAll("[data-log-row] td:nth-child(3)")].some((td) => td.textContent!.startsWith(k))).toBe(false);

    fireEvent.click(container.querySelector('[data-right-tab="cost"]')!);
    expect(container.querySelector("[data-cost-panel] [data-by-kind]")).not.toBeNull();
    // 布局偏好存本机
    expect(JSON.parse(localStorage.getItem("paoding.workspace")!)).toMatchObject({ center: "timeline", tab: "cost" });
  });

  it("收起左右栏；按等级分组", async () => {
    const r = rig();
    const { container } = renderWith(r, <Cockpit pid={r.mock.demoPid} asOf={null} node={null} />);
    await waitFor(() => expect(container.querySelector(".cockpit")).not.toBeNull());
    fireEvent.click(container.querySelector('[data-action="toggle-left"]')!);
    expect(container.querySelector(".cockpit")!.getAttribute("data-left")).toBe("closed");
    expect(container.querySelector("[data-sessions]")).toBeNull();
    fireEvent.click(container.querySelector('[data-action="group-by-level"]')!);
    expect(container.querySelector("[data-level-groups] [data-level-group]")).not.toBeNull();
  });

  it("追加预算走提议通道，结果带 seq", async () => {
    const r = rig();
    const pid = r.mock.demoPid;
    const { container } = renderWith(r, <Cockpit pid={pid} asOf={null} node={null} />);
    await waitFor(() => expect(container.querySelector("[data-quick-actions]")).not.toBeNull());
    await until(() => !container.querySelector<HTMLButtonElement>('[data-action="quick-budget"]')!.disabled, "可写");
    fireEvent.click(container.querySelector('[data-action="quick-budget"]')!);
    fireEvent.change(container.querySelector('[data-field="budget-add"]')!, { target: { value: "1.5" } });
    fireEvent.click(container.querySelector('[data-action="budget-add"]')!);
    await until(() => /seq|暂不可用/.test(container.querySelector("[data-quick-msg]")?.textContent ?? ""), "结果");
    const call = r.fetch.calls.find((c) => c.method === "POST" && c.url.endsWith("/proposals"))!;
    expect(JSON.parse(call.body!).ops).toEqual([{ op: "budget_add", body: { usd_milli: 1500 } }]);
  });
});
