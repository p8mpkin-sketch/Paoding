// 错误边界（cz 2026-11-24 审 PR 144）：答案排版抛错时只换掉答案卡片，任务页其余部分照常可用；
// 以前应用里没有错误边界，一份排不出来的答案会让这道题的任务页每次打开都白屏。
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Cockpit } from "../src/pages/Cockpit";
import { Boundary } from "../src/ui/Boundary";
import { renderWith, rig } from "./helpers";

// 让排版在 demo-8 的答案上抛错（别的文本照常排）
const blow = vi.hoisted(() => ({ on: false }));
vi.mock("../src/model/prose", async (orig) => {
  const real = await orig<typeof import("../src/model/prose")>();
  return { ...real, parse: (t: string) => { if (blow.on && t.includes("class RetryPolicy")) throw new RangeError("Maximum call stack size exceeded"); return real.parse(t); } };
});

const $ = (c: HTMLElement, sel: string) => c.querySelector<HTMLElement>(sel);
let errors: ReturnType<typeof vi.spyOn>;
beforeEach(() => { errors = vi.spyOn(console, "error").mockImplementation(() => {}); });
afterEach(() => { cleanup(); blow.on = false; errors.mockRestore(); vi.unstubAllGlobals(); });

describe("答案显示不出来时", () => {
  it("卡片里写明“答案显示不出来”和原因、原文可复制；概要、要你补的、依据、四栏、时间轴与输入框都还在，换栏照常", async () => {
    blow.on = true;
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    const r = rig();
    const { container } = renderWith(r, <Cockpit pid="demo-8" asOf={null} node={null} />);
    const broken = await waitFor(() => { const b = $(container, "[data-answer] [data-answer-broken]"); expect(b).not.toBeNull(); return b!; });
    expect(broken.getAttribute("role")).toBe("alert");
    expect(broken.textContent).toContain("答案显示不出来");
    expect(broken.textContent).toContain("原因：Maximum call stack size exceeded");
    expect($(container, "[data-answer] [data-prose]")).toBeNull();
    fireEvent.click(broken.querySelector('[data-action="copy"]')!);
    expect(writeText).toHaveBeenCalledTimes(1);
    expect(String(writeText.mock.calls[0])).toContain("class RetryPolicy");             // 复制到的是完整的原文
    // 页面其余部分
    expect($(container, ".tk-head h1")!.textContent).toContain("梳理重试与超时的写法");
    expect($(container, '[data-verdict="self"]')!.textContent).toContain("没有经过独立判定");
    expect(container.querySelectorAll("[data-needs] [data-need]")).toHaveLength(3);
    expect(container.querySelectorAll("[data-claim]")).toHaveLength(4);
    expect($(container, "[data-timeline]")).not.toBeNull();
    expect($(container, '[data-field="follow-up"]')).not.toBeNull();
    expect($(container, "[data-pane-broken]")).toBeNull();                                // 只换掉了答案卡片，不是整栏
    for (const tab of ["steps", "files", "struct", "result"]) {
      fireEvent.click($(container, `[data-task-tab="${tab}"]`)!);
      expect($(container, '[role="tabpanel"]')!.getAttribute("data-pane")).toBe(tab);
    }
    await waitFor(() => expect($(container, "[data-answer-broken]")).not.toBeNull());
    expect(errors).toHaveBeenCalled();                                                    // 错误记在控制台，没有吞掉
  });

  it("排得出来的答案不受影响", async () => {
    const r = rig();
    const { container } = renderWith(r, <Cockpit pid="demo-8" asOf={null} node={null} />);
    await waitFor(() => expect($(container, "[data-answer] [data-prose-table]")).not.toBeNull());
    expect($(container, "[data-answer-broken]")).toBeNull();
  });
});

describe("错误边界本身", () => {
  const Bomb = ({ on }: { on: boolean }) => { if (on) throw new Error("炸了"); return <p data-ok>好的</p>; };

  it("子树抛错时显示替代内容并拿到错误；resetKey 变了就重新试一次；不抛错时原样渲染", () => {
    const view = (on: boolean, key: string) => <div><span data-outside>外面</span><Boundary resetKey={key} fallback={(e) => <p data-fallback>{e.message}</p>}><Bomb on={on} /></Boundary></div>;
    const { container, rerender } = render(view(false, "a"));
    expect($(container, "[data-ok]")).not.toBeNull();
    rerender(view(true, "a"));
    expect($(container, "[data-fallback]")!.textContent).toBe("炸了");
    expect($(container, "[data-outside]")).not.toBeNull();
    rerender(view(false, "a"));                       // 同一个 key：停在替代内容上，不反复重试
    expect($(container, "[data-fallback]")).not.toBeNull();
    rerender(view(false, "b"));                       // 内容换了：重新试，这次排得出来
    expect($(container, "[data-ok]")).not.toBeNull();
    expect($(container, "[data-fallback]")).toBeNull();
  });

  it("抛出来的不是 Error 也接得住", () => {
    const Odd = () => { throw "一个字符串"; };
    const { container } = render(<Boundary fallback={(e) => <p data-fallback>{e.message}</p>}><Odd /></Boundary>);
    expect($(container, "[data-fallback]")!.textContent).toBe("一个字符串");
  });
});
