// 会话活动面板（开放道进度可见性）：开放道在跑时显示工具调用序列与最后一条自述；右栏会话点开同一面板；严格道没有这块面板。
import { cleanup, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Cockpit } from "../src/pages/Cockpit";
import { renderWith, rig } from "./helpers";

afterEach(cleanup);

const $ = (c: HTMLElement, sel: string) => c.querySelector<HTMLElement>(sel);

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

  it("严格道（demo-1）：没有会话活动面板，右栏会话行上也没有“看活动”", async () => {
    const r = rig();
    const { container } = renderWith(r, <Cockpit pid="demo-1" asOf={null} node={null} />);
    await waitFor(() => expect(container.querySelectorAll("[data-lease]").length).toBeGreaterThan(0));
    expect($(container, "[data-activity]")).toBeNull();
    expect($(container, '[data-action="lease-activity"]')).toBeNull();
    expect(r.fetch.calls.some((c) => c.url.includes("/activity"))).toBe(false);
  });
});
