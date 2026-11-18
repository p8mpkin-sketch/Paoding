// 图的缩放、平移与键盘焦点（P2-2）。视口只是本机的看法：不改布局坐标，不进视图模型。
import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GraphView, ZOOM, zoomAt } from "../src/ui/GraphView";
import { liveSession, playToEnd, rig } from "./helpers";

afterEach(cleanup);

async function vmOf() {
  const r = rig();
  await playToEnd(r);
  const s = await liveSession(r, r.mock.demoPid);
  const vm = s.getState().vm!;
  s.close();
  return vm;
}

const transform = (c: HTMLElement) => c.querySelector("[data-graph-transform]")!.getAttribute("transform");

describe("图的视口", () => {
  it("以某点为中心缩放时，这一点下的图坐标不动；倍数有上下限", () => {
    const v = zoomAt({ k: 1, x: 10, y: 20 }, 2, 100, 50);
    expect((100 - v.x) / v.k).toBeCloseTo((100 - 10) / 1);
    expect((50 - v.y) / v.k).toBeCloseTo((50 - 20) / 1);
    let w = { k: 1, x: 0, y: 0 };
    for (let i = 0; i < 50; i++) w = zoomAt(w, ZOOM.step, 0, 0);
    expect(w.k).toBe(ZOOM.max);
    for (let i = 0; i < 50; i++) w = zoomAt(w, 1 / ZOOM.step, 0, 0);
    expect(w.k).toBe(ZOOM.min);
  });

  it("按钮与键盘缩放、平移、复原；节点坐标（布局）不变", async () => {
    const vm = await vmOf();
    const { container } = render(<GraphView vm={vm} selected={null} onSelect={() => {}} />);
    const coords = () => [...container.querySelectorAll("[data-graph-node]")].map((n) => `${n.getAttribute("data-x")},${n.getAttribute("data-y")}`);
    const before = coords();
    expect(transform(container)).toBe("translate(0 0) scale(1)");
    fireEvent.click(container.querySelector('[data-action="zoom-in"]')!);
    expect(transform(container)).toContain(`scale(${ZOOM.step})`);
    const vp = container.querySelector<HTMLElement>("[data-graph-viewport]")!;
    expect(vp.tabIndex).toBe(0);
    fireEvent.keyDown(vp, { key: "0" });
    expect(transform(container)).toBe("translate(0 0) scale(1)");
    fireEvent.keyDown(vp, { key: "ArrowRight" });
    fireEvent.keyDown(vp, { key: "ArrowDown" });
    expect(transform(container)).toBe("translate(-60 -60) scale(1)");
    fireEvent.keyDown(vp, { key: "-" });
    expect(container.querySelector("[data-zoom]")!.getAttribute("data-zoom")).toBe((1 / ZOOM.step).toFixed(2));
    expect(coords()).toEqual(before);
  });

  it("拖动平移；拖过之后松手不算点击节点", async () => {
    const vm = await vmOf();
    const onSelect = vi.fn();
    const { container } = render(<GraphView vm={vm} selected={null} onSelect={onSelect} />);
    const vp = container.querySelector<HTMLElement>("[data-graph-viewport]")!;
    const node = container.querySelector<SVGGElement>("[data-graph-node]:not(.gnode-hint)")!;
    fireEvent.pointerDown(node, { pointerId: 1, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(vp, { pointerId: 1, clientX: 140, clientY: 90 });
    fireEvent.click(node);
    fireEvent.pointerUp(vp, { pointerId: 1 });
    expect(transform(container)).toBe("translate(40 -10) scale(1)");
    expect(onSelect).not.toHaveBeenCalled();
    fireEvent.click(node);                                              // 不拖就是点击
    expect(onSelect).toHaveBeenCalledWith(node.getAttribute("data-graph-node"));
  });

  it("每个论断与 Intent 节点都能用 Tab 聚焦，Enter 或空格检视，读屏器读得到名称", async () => {
    const vm = await vmOf();
    const onSelect = vi.fn();
    const { container } = render(<GraphView vm={vm} selected={null} onSelect={onSelect} />);
    const nodes = [...container.querySelectorAll<SVGGElement>("[data-graph-node]:not(.gnode-hint)")];
    expect(nodes.length).toBe(vm.rows.length);
    for (const n of nodes) {
      expect(n.getAttribute("tabindex")).toBe("0");
      expect(n.getAttribute("role")).toBe("button");
      expect(n.getAttribute("aria-label")).toContain(n.getAttribute("data-graph-node")!);
    }
    fireEvent.keyDown(nodes[0], { key: "Enter" });
    fireEvent.keyDown(nodes[1], { key: " " });
    expect(onSelect.mock.calls.map((c) => c[0])).toEqual([nodes[0].getAttribute("data-graph-node"), nodes[1].getAttribute("data-graph-node")]);
  });
});
