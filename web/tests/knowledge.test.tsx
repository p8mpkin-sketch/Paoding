// 知识页（v5 第四期）：记忆一栏列出通鉴条目与派生状态；钉住、忘掉都要写理由并交回所见的卡；资料一栏在后端做好前只作说明。
import { cleanup, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Knowledge } from "../src/pages/Knowledge";
import { renderWith, rig } from "./helpers";

afterEach(cleanup);
const $ = (sel: string) => document.querySelector<HTMLElement>(sel);

async function memoryPage(token?: string | null) {
  const r = token === undefined ? rig() : rig(token);
  renderWith(r, <Knowledge tab="memory" />);
  await waitFor(() => expect($("[data-mem]")).not.toBeNull());
  return r;
}

describe("知识页：记忆", () => {
  it("列出在用的条目与状态；核对没过的钉不住；退役的收在下面", async () => {
    await memoryPage();
    expect(document.querySelectorAll("[data-memory] > .md-tbl [data-mem]")).toHaveLength(4);
    expect($('[data-mem="m-env-1"]')!.textContent).toContain("在用");
    expect($('[data-mem="m-env-1"]')!.textContent).toContain("核对 1 次，最近一次核对通过");
    expect($('[data-mem="m-sp-1"]')!.textContent).toContain("不用核对");
    expect($('[data-mem="m-env-2"]')!.getAttribute("data-state")).toBe("stale");
    expect(($('[data-mem="m-env-2"] [data-action="mem-pin"]') as HTMLButtonElement).disabled).toBe(true);
    expect($("[data-retired]")).toBeNull();
    expect($('[data-kn-tab="memory"]')!.textContent).toContain("4");
  });

  it("钉住：看卡、写理由才能确认，交回 seen；之后行上标出钉住了", async () => {
    const r = await memoryPage();
    fireEvent.click($('[data-mem="m-ex-1"] [data-action="mem-pin"]')!);
    await waitFor(() => expect($('[data-mem-card="m-ex-1"]')).not.toBeNull());
    const ok = $('[data-action="confirm-mem"]') as HTMLButtonElement;
    expect(ok.disabled).toBe(true);
    fireEvent.change($('[data-field="mem-reason"]')!, { target: { value: "以后同类环境都用得上" } });
    expect(ok.disabled).toBe(false);
    fireEvent.click(ok);
    await waitFor(() => expect($('[data-mem="m-ex-1"]')?.getAttribute("data-pinned")).toBe("true"));
    const call = r.fetch.calls.filter((c) => c.url === "/v1/memory/items/m-ex-1/pin").at(-1)!;
    const body = JSON.parse(String(call.body));
    expect(body.reason).toBe("以后同类环境都用得上");
    expect(body.seen.card_hash).toMatch(/^[0-9a-f]{64}$/);
  });

  it("忘掉：确认后条目退役，收进“已退役”", async () => {
    await memoryPage();
    fireEvent.click($('[data-mem="m-env-2"] [data-action="mem-forget"]')!);
    await waitFor(() => expect($('[data-mem-card="m-env-2"]')).not.toBeNull());
    fireEvent.change($('[data-field="mem-reason"]')!, { target: { value: "环境换了" } });
    fireEvent.click($('[data-action="confirm-mem"]')!);
    await waitFor(() => expect($("[data-retired]")).not.toBeNull());
    expect($('[data-retired] [data-mem="m-env-2"]')!.getAttribute("data-state")).toBe("retired");
    expect($('[data-retired] [data-action="mem-forget"]')).toBeNull();
  });

  it("没有人的令牌：只读，钉住与忘掉都不能点", async () => {
    await memoryPage(null);
    expect($("[data-memory] .md-tip")!.textContent).toContain("只读");
    for (const b of document.querySelectorAll<HTMLButtonElement>('[data-action="mem-pin"], [data-action="mem-forget"]')) expect(b.disabled).toBe(true);
  });

  it("所见的卡变了：服务端回 409，弹层里换成最新的卡", async () => {
    const r = await memoryPage();
    fireEvent.click($('[data-mem="m-ex-1"] [data-action="mem-forget"]')!);
    await waitFor(() => expect($('[data-mem-card="m-ex-1"]')).not.toBeNull());
    // 另一处先钉住了它：卡的内容变了
    const card = await r.api.memoryCard("m-ex-1");
    await r.api.memoryDecide("m-ex-1", "pin", "别处", card.seen);
    fireEvent.change($('[data-field="mem-reason"]')!, { target: { value: "不要了" } });
    fireEvent.click($('[data-action="confirm-mem"]')!);
    await waitFor(() => expect($(".kn-note")?.textContent).toContain("刚变了"));
    expect($('[data-mem-card="m-ex-1"]')!.textContent).toContain("钉住了");
  });
});

describe("知识页：资料", () => {
  it("后端做好之前只作说明", async () => {
    renderWith(rig(), <Knowledge tab="sources" />);
    await waitFor(() => expect($("[data-sources]")).not.toBeNull());
    expect($("[data-sources]")!.textContent).toContain("资料库还在做");
  });
});
