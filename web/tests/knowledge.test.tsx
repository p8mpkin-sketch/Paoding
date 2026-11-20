// 知识页（v5 第四期）：记忆一栏列出通鉴条目与派生状态；钉住、忘掉都要写理由并交回所见的卡；
// 资料一栏列出导入作业与五段进度、已有资料、“试一下”，导入抽屉收文件或粘贴的文字。
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

async function sourcesPage(token?: string | null) {
  const r = token === undefined ? rig() : rig(token);
  renderWith(r, <Knowledge tab="sources" />);
  await waitFor(() => expect($("[data-source]")).not.toBeNull());
  return r;
}

describe("知识页：资料", () => {
  it("正在导入：五段进度、失败的写原因可重试；已有资料按状态排；页签带数目", async () => {
    await sourcesPage();
    const run = $('[data-job="s_runbk01"]')!;
    expect(run.querySelector('[data-at="now"]')!.textContent).toBe("切分");
    expect(run.querySelectorAll('[data-at="done"]')).toHaveLength(2);
    const bad = $('[data-job="s_scan01"]')!;
    expect(bad.getAttribute("data-failed")).toBe("true");
    expect(bad.querySelector('[data-at="failed"]')!.textContent).toBe("解析");
    expect(bad.textContent).toContain("第三期");
    expect(bad.querySelector('[data-action="kn-retry"]')).not.toBeNull();
    expect($('[data-source="s_team01"]')!.textContent).toContain("可用");
    expect($('[data-source="s_team01"]')!.textContent).toContain("28 KB");
    expect($('[data-source="s_olddep1"]')!.textContent).toContain("已停用");
    expect($('[data-kn-tab="sources"]')!.textContent).toContain("5");
  });

  it("取消导入：作业消失", async () => {
    const r = await sourcesPage();
    fireEvent.click($('[data-job="s_scan01"] [data-action="kn-cancel"]')!);
    await waitFor(() => expect($('[data-job="s_scan01"]')).toBeNull());
    expect(r.fetch.calls.some((c) => c.url === "/v1/knowledge/jobs/s_scan01/1/cancel")).toBe(true);
  });

  it("停用、删除进回收站、恢复", async () => {
    await sourcesPage();
    fireEvent.click($('[data-source="s_team01"] [data-action="kn-disable"]')!);
    await waitFor(() => expect($('[data-source="s_team01"]')!.getAttribute("data-disabled")).toBe("true"));
    fireEvent.click($('[data-source="s_team01"] [data-action="kn-delete"]')!);
    await waitFor(() => expect($('[data-trash] [data-source="s_team01"]')).not.toBeNull());
    fireEvent.click($('[data-trash] [data-source="s_team01"] [data-action="kn-restore"]')!);
    await waitFor(() => expect($("[data-trash]")).toBeNull());
  });

  it("试一下：查到的段落带资料名与得分", async () => {
    await sourcesPage();
    fireEvent.change($('[data-field="kn-query"]')!, { target: { value: "回滚怎么做" } });
    fireEvent.click($('[data-action="kn-search"]')!);
    await waitFor(() => expect($("[data-hit]")).not.toBeNull());
    expect($("[data-hit]")!.textContent).toContain("团队约定.md");
    expect($(".kn-via")!.textContent).toContain("hash-512-v1");
  });

  it("导入粘贴的文字：要名称与内容；提交后出现新作业", async () => {
    const r = await sourcesPage();
    fireEvent.click($('[data-action="kn-import"]')!);
    await waitFor(() => expect($("[data-kn-import]")).not.toBeNull());
    fireEvent.click($('[data-mode="url"]')!);
    expect($("[data-kn-import]")!.textContent).toContain("下一期");
    fireEvent.click($('[data-mode="text"]')!);
    const go = $('[data-action="kn-start"]') as HTMLButtonElement;
    expect(go.disabled).toBe(true);
    fireEvent.change($('[data-field="kn-name"]')!, { target: { value: "值班约定" } });
    fireEvent.change($('[data-field="kn-text"]')!, { target: { value: "交接时写清楚未关的告警。" } });
    fireEvent.click($('[data-scope="pick"]')!);
    expect(go.disabled).toBe(false);
    fireEvent.click(go);
    await waitFor(() => expect($("[data-kn-import]")).toBeNull());
    const call = r.fetch.calls.filter((c) => c.url === "/v1/knowledge/sources" && c.method === "POST").at(-1)!;
    expect(JSON.parse(String(call.body))).toMatchObject({ name: "值班约定", scope: "pick", text: "交接时写清楚未关的告警。" });
    await waitFor(() => expect(document.querySelector('[data-job] b')?.textContent ?? "").toBeTruthy());
    expect([...document.querySelectorAll("[data-job]")].some((e) => e.textContent!.includes("值班约定"))).toBe(true);
  });

  it("导入文件：先传 Blob，再交 file", async () => {
    const r = await sourcesPage();
    fireEvent.click($('[data-action="kn-import"]')!);
    await waitFor(() => expect($("[data-kn-import]")).not.toBeNull());
    const f = new File(["# 告警\n\n延迟超过 300ms 报警。"], "告警规则.md", { type: "text/markdown" });
    fireEvent.change($('[data-field="kn-files"]')!, { target: { files: [f] } });
    expect($('[data-picked="告警规则.md"]')).not.toBeNull();
    fireEvent.click($('[data-action="kn-start"]')!);
    await waitFor(() => expect($("[data-kn-import]")).toBeNull());
    expect(r.fetch.calls.some((c) => c.url === "/v1/blobs" && c.method === "PUT")).toBe(true);
    const call = r.fetch.calls.filter((c) => c.url === "/v1/knowledge/sources" && c.method === "POST").at(-1)!;
    expect(JSON.parse(String(call.body)).file).toMatchObject({ name: "告警规则.md", media_type: "text/markdown" });
  });

  it("没有人的令牌：只读，导入与行操作都不能点", async () => {
    await sourcesPage(null);
    expect($("[data-sources] .md-tip")!.textContent).toContain("只读");
    expect(($('[data-action="kn-import"]') as HTMLButtonElement).disabled).toBe(true);
    for (const b of document.querySelectorAll<HTMLButtonElement>('[data-source] button, [data-job] button')) expect(b.disabled).toBe(true);
  });
});
