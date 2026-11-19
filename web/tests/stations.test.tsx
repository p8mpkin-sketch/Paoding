// 站位条（宪章 Q27、AC6.3）：status、在途会话、人工项、关闭的纯函数，逐个组合快照。
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { stationsOf } from "../src/model/stations";
import { StationCell, StationStrip } from "../src/ui/StationStrip";

afterEach(cleanup);

describe("stationsOf", () => {
  const cases: [string, Parameters<typeof stationsOf>[0], ReturnType<typeof stationsOf>][] = [
    ["开着、没有会话、没有待办：等下一个会话", { closed: false, active: [], todo: [] }, { current: "S6", waiting: {} }],
    ["有会话在跑", { closed: false, active: ["reason", "explore"], todo: [] }, { current: "S6", waiting: {} }],
    ["判定会话在跑", { closed: false, active: ["verify"], todo: [] }, { current: "S7", waiting: {} }],
    ["在跑又有审批：执行亮，人介入写数", { closed: false, active: ["explore"], todo: ["needs_human", "scope_request"] }, { current: "S6", waiting: { S8: 2 } }],
    ["没有会话、只等人", { closed: false, active: [], todo: ["stalled"] }, { current: "S8", waiting: { S8: 1 } }],
    ["验收与四顾在等人", { closed: false, active: [], todo: ["closeout"] }, { current: "S10", waiting: { S10: 1 } }],
    ["验收与审批同时", { closed: false, active: ["verify"], todo: ["closeout", "extension"] }, { current: "S10", waiting: { S8: 1, S10: 1 } }],
    ["已关闭", { closed: true, active: [], todo: [] }, { current: "S11", waiting: {} }],
    ["任务库只有个数：按人介入算", { closed: false, active: [], todo: 3 }, { current: "S8", waiting: { S8: 3 } }],
  ];
  for (const [name, input, out] of cases) it(name, () => expect(stationsOf(input)).toEqual(out));
});

describe("站位条", () => {
  it("十二格，当前站 aria-current，等人的站写“等你 n”（不只靠颜色）", () => {
    const { container } = render(<StationStrip st={{ current: "S6", waiting: { S8: 2 } }} />);
    const items = container.querySelectorAll("[data-station]");
    expect(items).toHaveLength(12);
    expect(container.querySelector('[aria-current="step"]')?.getAttribute("data-station")).toBe("S6");
    const s8 = container.querySelector('[data-station="S8"]')!;
    expect(s8.className).toContain("wait");
    expect(s8.textContent).toMatch(/^人介入S8等你 2$/); // 无障碍名称以可见文字开头（WCAG 2.5.3）
  });
  it("任务库一格：当前站与等你几件", () => {
    const { container } = render(<StationCell st={{ current: "S8", waiting: { S8: 3 } }} />);
    expect(container.textContent).toBe("S8 人介入 · 等你 3");
  });
});
