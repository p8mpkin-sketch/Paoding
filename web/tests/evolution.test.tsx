// 能力配置的演进读数（焚决 04 §7）：在假后端上排版；只读，没有写按钮。
import { cleanup, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { hrefOf, parseRoute } from "../src/app/router";
import { Evolution } from "../src/pages/Evolution";
import { navOf } from "../src/shell/AppShell";
import { renderWith, rig } from "./helpers";

afterEach(cleanup);
const $ = (c: ParentNode, sel: string) => c.querySelector<HTMLElement>(sel);

describe("能力配置页", () => {
  it("路由与侧栏：/capability", () => {
    expect(hrefOf({ page: "evolution" })).toBe("/capability");
    expect(parseRoute("/capability", "")).toEqual({ page: "evolution" });
    expect(navOf({ page: "evolution" })).toEqual({ key: "evolution", crumbs: ["能力配置"] });
  });

  it("版本历史、结论统计、集成记录（点开看读数）、Holdout 两臂与各版本的任务", async () => {
    const r = rig();
    const { container } = renderWith(r, <Evolution />);
    await waitFor(() => expect($(container, "[data-ev-history]")).not.toBeNull());
    expect($(container, "[data-ev-version]")!.textContent).toBe("v2");
    expect(container.querySelectorAll("[data-ev-history] [data-ev-jie]")).toHaveLength(3);
    expect($(container, '[data-ev-jie="2"]')!.textContent).toContain("新增能力");
    expect($(container, '[data-chart="ev-outcomes"]')!.textContent).toMatch(/新增能力.*无增益/s);
    expect($(container, '[data-ev-dossier="002"] [data-ev-outcome="binghuo"]')!.textContent).toContain("无增益");
    expect($(container, '[data-ev-more="001"]')).toBeNull();
    fireEvent.click($(container, '[data-ev-dossier="001"] [data-action="ev-dossier"]')!);
    expect($(container, '[data-ev-more="001"]')!.textContent).toContain("实时所见可回放率");
    const h = $(container, '[data-ev-holdout="H6:h6.activity@1"]')!;
    expect(h.textContent).toContain("可观测性");
    expect($(h, '[data-ev-metric="done-rate"]')!.textContent).toMatch(/75%.*100%/);
    expect($(h, "[data-ev-few]")).not.toBeNull(); // 一臂只有 1 个已结束的任务：只提示样本少
    expect(container.querySelectorAll("[data-ev-versions] [data-ev-digest]")).toHaveLength(3);
    expect(container.querySelectorAll("button:not([data-action=ev-dossier]):not([data-action=chart-table])")).toHaveLength(0);
  });
});
