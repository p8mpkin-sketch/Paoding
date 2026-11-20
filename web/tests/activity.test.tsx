// 会话活动面板（开放道进度可见性）：开放道在跑时显示工具调用序列与最后一条自述；右栏会话点开同一面板；严格道没有这块面板。
import { cleanup, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Cockpit } from "../src/pages/Cockpit";
import { renderWith, rig } from "./helpers";

afterEach(cleanup);

const $ = (c: HTMLElement, sel: string) => c.querySelector<HTMLElement>(sel);

async function firstSolve(r: ReturnType<typeof rig>, pid: string): Promise<string> {
  for (let i = 0; i < 200; i++) {
    const e = (await r.api.events(pid, 0).catch(() => null))?.events.find((x) => x.kind === "lease" && (x.body as { kind?: string }).kind === "solve");
    if (e) return `l_${e.seq}`;
    await new Promise((res) => setTimeout(res, 5));
  }
  throw new Error(`${pid} 没有求解会话`);
}

describe("会话活动", () => {
  it("开放道在跑（demo-7）：面板显示正在做的工具调用、最近自述、工具调用序列、耗时与花费", async () => {
    const r = rig();
    const { container } = renderWith(r, <Cockpit pid="demo-7" asOf={null} node={null} />);
    const panel = await waitFor(() => { const p = $(container, "[data-activity]"); expect(p?.getAttribute("data-live")).toBe("true"); return p!; });
    await waitFor(() => expect(panel.querySelectorAll('[data-act="call"]').length).toBe(4));
    expect($(panel, "[data-act-now]")!.textContent).toContain("git checkout 71aa03b");
    expect(panel.querySelector('[data-act="call"][data-state="now"]')).not.toBeNull();
    expect(panel.querySelectorAll('[data-act="call"][data-state="bad"]')).toHaveLength(1); // 跑测试那步退出码非零
    expect($(panel, "[data-act-said]")!.textContent).toContain("先对比这个函数");
    expect($(panel, "[data-act-spent]")!.textContent).toBe("$0.24"); // 与右栏“钱花在哪个会话”同一行
    expect($(panel, "[data-act-elapsed]")!.textContent).toBe("00:26");
    expect(r.fetch.calls.some((c) => c.url.includes("/activity"))).toBe(true);
  });

  it("会话已结束（demo-6）：面板默认收起不挡结果；右栏会话点“看活动”打开同一面板，收起后横幅可再点开", async () => {
    const r = rig();
    const { container } = renderWith(r, <Cockpit pid="demo-6" asOf={null} node={null} />);
    const banner = await waitFor(() => { const b = $(container, '[data-action="activity-show"]'); expect(b).not.toBeNull(); return b!; });
    expect($(container, "[data-activity]")).toBeNull();
    const btn = await waitFor(() => { const b = $(container, '[data-lease] [data-action="lease-activity"]'); expect(b).not.toBeNull(); return b!; });
    const lid = btn.closest("[data-lease]")!.getAttribute("data-lease")!;
    fireEvent.click(btn);
    const panel = await waitFor(() => { const p = $(container, "[data-activity]"); expect(p?.getAttribute("data-lease")).toBe(lid); return p!; });
    await waitFor(() => expect($(panel, "[data-act-status]")!.textContent).toBe("已结束"));
    expect($(panel, "[data-act-now]")!.textContent).toContain("没有在做的事");
    fireEvent.click($(container, '[data-action="activity-close"]')!);
    expect($(container, "[data-activity]")).toBeNull();
    expect(banner.isConnected || $(container, '[data-action="activity-show"]') !== null).toBe(true);
    fireEvent.click($(container, '[data-action="activity-show"]')!);
    await waitFor(() => expect($(container, "[data-activity]")).not.toBeNull());
  });

  it("可回放的实时性（demo-7 在跑）：exec 行可点开那次执行的留档；还没入账的条目标“未入账”", async () => {
    const r = rig();
    const { container } = renderWith(r, <Cockpit pid="demo-7" asOf={null} node={null} />);
    const panel = await waitFor(() => { const p = $(container, "[data-activity]"); expect(p?.getAttribute("data-ledger")).toBe("true"); return p!; });
    await waitFor(() => expect(panel.querySelectorAll('[data-act="call"]').length).toBe(4));
    const chips = [...panel.querySelectorAll<HTMLElement>('[data-action="act-evidence"]')];
    expect(chips).toHaveLength(2); // 两次 exec 已返回；Read 不是执行，没有留档
    expect(chips.every((c) => c.closest('[data-act="call"]')!.getAttribute("data-tool") === "exec")).toBe(true);
    // 入账到第二次 exec 返回为止：之后的自述、Read、在做的 exec 都标未入账；自述不可点
    const calls = [...panel.querySelectorAll<HTMLElement>('[data-act="call"]')];
    expect(calls.map((c) => c.getAttribute("data-anchored"))).toEqual(["yes", "yes", "no", "no"]);
    expect($(panel, '[data-act="say"][data-anchored="no"] [data-act-pending]')).not.toBeNull();
    expect(panel.querySelector('[data-act="say"] button')).toBeNull();
    expect($(panel, "[data-act-ledger]")!.textContent).toContain("已入账 8 / 15");
    fireEvent.click(chips[1]);
    const id = chips[1].getAttribute("data-artifact-ref")!;
    await waitFor(() => expect(document.querySelector(`[data-evidence="${id}"]`)).not.toBeNull());
  });

  it("回放（demo-7 拨到第一次 exec 入账那一刻）：只排那一刻已入账的条目，不轮询、不标未入账", async () => {
    const r = rig();
    const live = await r.api.activity((await firstSolve(r, "demo-7")), 0);
    const first = live.items.find((x) => x.kind === "result" && x.artifact)! as { artifact: string };
    const seq = Number(first.artifact.slice(2));
    const { container } = renderWith(r, <Cockpit pid="demo-7" asOf={seq} node={null} />);
    const panel = await waitFor(() => { const p = $(container, "[data-activity]"); expect(p?.getAttribute("data-replay")).toBe("true"); return p!; });
    await waitFor(() => expect($(panel, "[data-act-status]")!.textContent).toBe(`回放到 seq=${seq}`));
    expect(panel.querySelectorAll('[data-act="call"]')).toHaveLength(1);
    expect(panel.querySelector("[data-act-pending]")).toBeNull();
    expect(panel.getAttribute("data-live")).toBe("false");
    const before = r.fetch.calls.filter((c) => c.url.includes("/activity")).length;
    await new Promise((res) => setTimeout(res, 50));
    expect(r.fetch.calls.filter((c) => c.url.includes("/activity")).length).toBe(before);
    // 拨到入账之前：那一刻还没有入账的活动
    const early = await r.api.activity(await firstSolve(r, "demo-7"), 0, seq - 1);
    expect(early.items).toEqual([]);
    expect(early.status).toBe("none");
  });

  it("严格道（demo-1）：没有会话活动面板，右栏会话行上也没有“看活动”；过程追踪仍读各会话的活动（判定会话除外）", async () => {
    const r = rig();
    const { container } = renderWith(r, <Cockpit pid="demo-1" asOf={null} node={null} />);
    await waitFor(() => expect(container.querySelectorAll("[data-lease]").length).toBeGreaterThan(0));
    expect($(container, "[data-activity]")).toBeNull();
    expect($(container, '[data-action="lease-activity"]')).toBeNull();
    // 判定会话在判定箱里跑，没有 CLI 活动，不去读
    const judges = (await r.api.status("demo-1")).leases.filter((l) => l.kind === "judge" || l.kind === "rejudge").map((l) => l.id);
    expect(r.fetch.calls.filter((c) => judges.some((j) => c.url.includes(`/leases/${j}/activity`)))).toEqual([]);
  });
});
