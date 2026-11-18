// 应用外壳（视觉重做第一期）：导航与路由对应、状态行只排版服务端给的量、⌘K 与 C 两个全局快捷键。
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "../src/App";
import { navOf } from "../src/shell/AppShell";
import { rig } from "./helpers";

// jsdom 没有 ResizeObserver 与 scrollIntoView，命令面板要用
globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
Element.prototype.scrollIntoView ??= function () {};

afterEach(() => { cleanup(); window.history.replaceState(null, "", "/"); });

describe("导航归属", () => {
  it("每个路由归到一个导航项和一卷；工作区不占导航项", () => {
    expect(navOf({ page: "home" })).toMatchObject({ key: "home", vol: "卷一" });
    expect(navOf({ page: "new" }).key).toBe("tasks");
    expect(navOf({ page: "new", from: "x" }).crumbs).toEqual(["任务", "克隆"]);
    expect(navOf({ page: "import" }).key).toBe("tasks");
    expect(navOf({ page: "readings" }).key).toBe("readings");
    expect(navOf({ page: "problem", pid: "p1", asOf: null, node: null })).toMatchObject({ key: null, crumbs: ["任务", "p1"] });
  });
});

describe("外壳", () => {
  it("状态行：连接、令牌、在途与等你处理都来自题目列表", async () => {
    const r = rig();
    const { container } = render(<App cfg={r.cfg} />);
    await waitFor(() => expect(container.querySelector(".shell-status")!.textContent).toContain("已连接"));
    const status = container.querySelector(".shell-status")!.textContent!;
    const items = (await r.api.problems()).items;
    const running = items.filter((p) => !p.closed);
    expect(status).toContain("可写");
    expect(status).toContain(`在途 ${running.length}`);
    expect(status).toContain(`等你 ${running.reduce((a, p) => a + p.human_todo, 0)}`);
    expect(container.querySelectorAll(".shell-pins li")).toHaveLength(running.length);
  });

  it("没有令牌时状态行写只读", async () => {
    const { container } = render(<App cfg={rig(null).cfg} />);
    await waitFor(() => expect(container.querySelector(".shell-status")!.textContent).toContain("只读"));
  });

  it("Ctrl+K 打开命令面板，选一页即跳转；C 去新建任务", async () => {
    const r = rig();
    render(<App cfg={r.cfg} />);
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = await screen.findByPlaceholderText("搜任务、页面或操作…");
    fireEvent.change(input, { target: { value: "读数" } });
    fireEvent.click(await screen.findByText("读数", { selector: "[cmdk-item] span" }));
    await waitFor(() => expect(window.location.pathname).toBe("/readings"));
    fireEvent.keyDown(document.body, { key: "c" });
    await waitFor(() => expect(window.location.pathname).toBe("/new"));
  });
});
