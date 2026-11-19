// 一句话开题第二期（设计 docs/design/kaiti §7）：输入框、确认卡、拒绝页、高级模式的出处记号。
// 假服务只回放真 qicao 录下的应答（mock/kaiti.json），前端没有第二份抽取与校验规则。
import { cleanup, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { KAITI } from "../mock/kaiti";
import type { ProblemInput } from "../src/api/types";
import { loadDraft } from "../src/app/draft";
import { parseRoute, hrefOf } from "../src/app/router";
import { sealOps, segments, spanNumbers, wizardDraftOf } from "../src/model/kaiti";
import { buildOpen, touch } from "../src/model/wizard";
import { Kaiti } from "../src/pages/Kaiti";
import { Wizard } from "../src/pages/Wizard";
import { renderWith, rig, until } from "./helpers";

beforeEach(() => { localStorage.clear(); window.history.pushState(null, "", "/new"); });
afterEach(cleanup);

const rec = (k: "practice" | "command" | "refuse" | "outbound" | "external") => KAITI.drafts[k];
const SECRET = "PD-7Q2M9XKD";

describe("视图模型", () => {
  it("原文切段不丢字；被引用的区间按位置编号，字段与原文能对上", () => {
    for (const k of ["practice", "command"] as const) {
      const v = rec(k).out;
      const nums = spanNumbers(v.spans, v.derivation);
      const segs = segments(v.text, v.spans, nums);
      expect(segs.map((s) => s.text).join("")).toBe(v.text);
      const ends = segs.flatMap((s) => s.ends).sort((a, b) => a - b);
      expect(ends).toEqual([...nums.values()].sort((a, b) => a - b));
      for (const r of v.derivation) for (const id of r.spans ?? []) expect(nums.has(id), `${r.field} → ${id}`).toBe(true);
    }
  });

  it("批次里的答案占位只能换成保密库引用", () => {
    const v = rec("practice").out;
    expect(() => sealOps(v.ops!, null)).toThrow(/保密库/);
    const ops = sealOps(v.ops!, { vault: "kt-x", digest: "d".repeat(64) });
    expect((ops.at(-1)!.body as unknown as ProblemInput).goal.check.sealed).toEqual([{ vault: "kt-x", digest: "d".repeat(64) }]);
    expect(JSON.stringify(v.ops)).toContain('"$answer"'); // 原批次不被改
  });

  it("路由：/new 是输入框，/new/advanced 是向导，克隆进高级模式", () => {
    expect(parseRoute("/new", "")).toEqual({ page: "new" });
    expect(parseRoute("/new/advanced", "")).toEqual({ page: "new", advanced: true });
    expect(parseRoute("/new", "?from=p1")).toEqual({ page: "new", advanced: true, from: "p1" });
    expect(hrefOf({ page: "new", advanced: true, from: "p1" })).toBe("/new/advanced?from=p1");
    expect(hrefOf({ page: "new" })).toBe("/new");
  });

  it("带进高级模式的草稿：字段带出处，人改过即为“人”；答案只以引用出现", () => {
    const v = rec("practice").out;
    const d = wizardDraftOf(v, { vault: "kt-1", digest: "e".repeat(64) });
    expect(d.marks).toMatchObject({ title: "model", statement: "span", judge: "table", scope: "span", wall_s: "span" });
    expect(JSON.stringify(d)).not.toContain(SECRET);
    expect(buildOpen(d).problem.goal.check.sealed).toEqual([{ vault: "kt-1", digest: "e".repeat(64) }]);
    const t = touch(d, { title: "改过的题名" });
    expect(t.marks?.title).toBe("human");
    expect(t.marks?.statement).toBe("span");
    expect(touch({ ...d, marks: undefined }, { title: "x" }).marks).toBeUndefined();
    const nums = spanNumbers(v.spans, v.derivation);
    expect(d.kaiti?.spans?.map((x) => x.n).sort((x, y) => x - y)).toEqual([...nums.values()].sort((x, y) => x - y));
    expect(d.kaiti?.refs?.wall_s).toEqual(v.derivation.find((x) => x.field === "budget.wall_s")!.spans!.map((id) => nums.get(id)));
  });
});

async function drafted(text: string) {
  const r = rig();
  const { container } = renderWith(r, <Kaiti />);
  fireEvent.change(container.querySelector('[data-field="kaiti-text"]')!, { target: { value: text } });
  fireEvent.keyDown(container.querySelector('[data-field="kaiti-text"]')!, { key: "Enter" });
  await waitFor(() => expect(container.querySelector("[data-kaiti-card], [data-kaiti-refuse]")).not.toBeNull());
  return { r, container };
}

describe("输入框与确认卡", () => {
  it("输入时实时显示前置抽取；答案行只报“已收起”", async () => {
    const r = rig();
    const { container } = renderWith(r, <Kaiti />);
    fireEvent.change(container.querySelector('[data-field="kaiti-text"]')!, { target: { value: rec("practice").text } });
    await waitFor(() => expect(container.querySelector("[data-kaiti-extract]")).not.toBeNull(), { timeout: 2000 });
    const box = container.querySelector("[data-kaiti-extract]")!;
    expect(box.querySelector('[data-kind="addr"]')?.textContent).toContain("q1:8080");
    expect(box.querySelector('[data-kind="answer"]')?.textContent).toMatch(/已收起/);
    expect(box.textContent).not.toContain(SECRET);
  });

  it("⇧回车只换行，不起草", async () => {
    const r = rig();
    const { container } = renderWith(r, <Kaiti />);
    const box = container.querySelector('[data-field="kaiti-text"]')!;
    fireEvent.change(box, { target: { value: "x" } });
    const before = r.fetch.calls.length;
    fireEvent.keyDown(box, { key: "Enter", shiftKey: true });
    await new Promise((res) => setTimeout(res, 30));
    expect(r.fetch.calls.slice(before).some((c) => String(c.url).endsWith("/v1/drafts"))).toBe(false);
  });

  it("练习道候选：零确认没放行，走确认卡；开题后答案只在保密库", async () => {
    const { r, container } = await drafted(rec("practice").text);
    const card = container.querySelector("[data-kaiti-card]")!;
    expect(container.querySelector("[data-kaiti]")?.getAttribute("data-lane")).toBe("confirm");
    expect(card.querySelector("[data-eligible]")?.textContent).toMatch(/零确认尚未放行/);
    expect(card.querySelector('[data-note="zero_confirm_off"]')).not.toBeNull();
    expect(card.querySelector("[data-answer-sealed]")).not.toBeNull();
    expect(card.textContent).not.toContain(SECRET);
    // 每个带原文区间的字段都有编号，原文里有同一编号
    const nos = [...card.querySelectorAll("[data-span-no]")].map((x) => x.getAttribute("data-span-no"));
    expect(nos.length).toBeGreaterThan(1);
    expect(card.querySelector('[data-field="scope[0].pattern"] [data-source="span"]')?.textContent).toMatch(/[①-⑳]/);
    fireEvent.keyDown(card, { key: "Enter", metaKey: true });
    await waitFor(() => expect(window.location.pathname).toBe(`/p/${rec("practice").out.pid}`));
    const st = await r.api.status(rec("practice").out.pid);
    expect(st.goal.predicate.judge_id).toBe("exact_match");
    expect(st.goal.predicate.sealed).toHaveLength(1);
    const key = st.goal.predicate.sealed[0].vault;
    expect(new TextDecoder().decode(r.mock.vault.get(key))).toBe(SECRET);
    const stmt = await r.api.artifact(st.problem.origin.statement_ref);
    expect(new TextDecoder().decode(await r.api.blob(stmt.hash))).not.toContain(SECRET);
  });

  it("模型一块：起草用只列已登记档案，选了即重新起草、出处记“人”；会话用按全局路由", async () => {
    const { r, container } = await drafted(rec("practice").text);
    const block = () => container.querySelector("[data-model-block]")!;
    const sel = await waitFor(() => { const el = block().querySelector<HTMLSelectElement>('[data-action="pick-draft-profile"]'); expect(el).not.toBeNull(); return el!; });
    expect([...sel.options].filter((o) => !o.disabled).map((o) => o.value)).toEqual(["default"]);
    expect(block().querySelector("[data-session-routes]")!.textContent).toBe("Bootstrap → default · Reason → default · Explore → default · Verify → default");
    fireEvent.change(sel, { target: { value: "default" } });
    await waitFor(() => expect(block().querySelector('[data-field="draft.model"] [data-source]')?.getAttribute("data-source")).toBe("human"));
    const posts = r.fetch.calls.filter((c) => c.method === "POST" && c.url === "/v1/drafts");
    expect(JSON.parse(posts.at(-1)!.body!)).toMatchObject({ profile: "default" });
    expect(JSON.parse(posts.at(-1)!.body!).draft).toBeUndefined(); // 换档案是重新起草，不是重新校验
  });

  it("卡上改风险与预算：重新校验不再调模型，出处变“人”", async () => {
    const { r, container } = await drafted(rec("command").text);
    const card = () => container.querySelector("[data-kaiti-card]")!;
    expect(card().querySelector('[data-field="command-note"]')?.textContent).toMatch(/重放/);
    const sent = () => r.fetch.calls.filter((c) => String(c.url).endsWith("/v1/drafts")).map((c) => JSON.parse(String(c.body)) as Record<string, unknown>);
    fireEvent.change(card().querySelector('[data-risk="0"]')!, { target: { value: "r1" } });
    await waitFor(() => expect(card().querySelector('[data-field="scope[0].risk"] [data-source="human"]')).not.toBeNull());
    fireEvent.change(card().querySelector('[data-field="usd"]')!, { target: { value: "3" } });
    fireEvent.blur(card().querySelector('[data-field="usd"]')!);
    await waitFor(() => expect(card().querySelector('[data-field="budget.usd_milli"] [data-source="human"]')).not.toBeNull());
    const [, second, third] = sent();
    expect(second.draft).toEqual(rec("command").out.draft);
    expect(second.nonce).toBe(rec("command").out.nonce);
    expect(third.overrides).toEqual({ risk: { 0: "r1" }, usd_milli: 3000 });
    expect(card().querySelector('[data-note="human_edit"]')).not.toBeNull();
  });

  it("超过单题硬顶：写在字段下面，数字框回到原值", async () => {
    const { container } = await drafted(rec("command").text);
    const usd = () => container.querySelector('[data-field="usd"]') as HTMLInputElement;
    fireEvent.change(usd(), { target: { value: "999" } });
    fireEvent.blur(usd());
    await waitFor(() => expect(container.querySelector("[data-field-error]")).not.toBeNull());
    expect(usd().value).toBe(String(rec("command").out.input!.budget.usd_milli / 1000));
  });

  it("在高级模式里改：先写保密库，草稿里只带引用与出处", async () => {
    const { r, container } = await drafted(rec("practice").text);
    fireEvent.click(container.querySelector('[data-action="to-advanced"]')!);
    await waitFor(() => expect(window.location.pathname).toBe("/new/advanced"));
    const saved = loadDraft()!;
    expect(saved.draft.sealed).toHaveLength(1);
    expect(r.mock.vault.size).toBe(1);
    expect(JSON.stringify(saved)).not.toContain(SECRET);
    cleanup();
    const w = renderWith(r, <Wizard />).container;
    await waitFor(() => expect(w.querySelector("[data-kaiti-origin]")).not.toBeNull());
    expect(w.querySelector('[data-src="title"]')?.getAttribute("data-source")).toBe("model");
    // 逐字段的出处编号与确认卡同一套（宪章 Q11）：原文带编号，摘自原文的字段写第几段
    const v = rec("practice").out;
    const nums = spanNumbers(v.spans, v.derivation);
    const stmt = v.derivation.find((x) => x.field === "goal.statement")!.spans!.map((id) => nums.get(id));
    expect(w.querySelector('[data-src="statement"] [data-refs]')?.getAttribute("data-refs")).toBe(stmt.join(","));
    expect(w.querySelectorAll("[data-kaiti-origin] [data-span-no]")).toHaveLength(nums.size);
    fireEvent.change(w.querySelector('[data-field="title"]')!, { target: { value: "我自己的题名" } });
    expect(w.querySelector('[data-src="title"]')?.getAttribute("data-source")).toBe("human");
    fireEvent.change(w.querySelector('[data-field="statement"]')!, { target: { value: "我自己写的目标" } });
    expect(w.querySelector('[data-src="statement"] [data-refs]')).toBeNull(); // 人改过：不再写摘自第几段
  });
});

describe("拒绝页", () => {
  it("说不清怎样算做完：引用目标句，四条路，人工验收灰显；输入框保留原文", async () => {
    const { container } = await drafted(rec("refuse").text);
    const page = container.querySelector("[data-kaiti-refuse]")!;
    expect(page.textContent).toContain("这件事还说不清怎样算做完");
    expect(page.querySelector(".kt-quote")?.textContent).toBeTruthy();
    expect(page.querySelectorAll(".kt-ways > li")).toHaveLength(4);
    expect(page.querySelector('[data-way="register_platform"] [data-action="refuse-register"]')?.getAttribute("href")).toBe("/settings");
    expect(page.querySelector('[data-way="human"]')?.getAttribute("aria-disabled")).toBe("true");
    expect((page.querySelector('[data-way="human"] button') as HTMLButtonElement).disabled).toBe(true);
    expect((container.querySelector('[data-field="kaiti-text"]') as HTMLTextAreaElement).value).toBe(rec("refuse").text);
    expect(container.querySelector("[data-kaiti-card]")).toBeNull();
  });

  it("进高级模式：带着原文，从第二步开始", async () => {
    const { container } = await drafted(rec("refuse").text);
    fireEvent.click(container.querySelector('[data-action="refuse-advanced"]')!);
    await waitFor(() => expect(window.location.pathname).toBe("/new/advanced"));
    const saved = loadDraft()!;
    expect(saved.step).toBe(1);
    expect(saved.draft.kaiti?.text).toBe(rec("refuse").text);
    expect(saved.draft.materials[0].text).toBe(rec("refuse").text);
  });

  it("假服务不认的原文按“起草结果不可用”拒绝", async () => {
    const { container } = await drafted("随便写一句");
    expect(container.querySelector('[data-note="bad_draft"]')).not.toBeNull();
    expect(container.querySelector("[data-kaiti-refuse]")?.textContent).toContain("没有创建任务");
  });
});

describe("令牌", () => {
  it("没有人的令牌：输入框只读，不发起草请求", async () => {
    const r = rig(null);
    const { container } = renderWith(r, <Kaiti />);
    expect((container.querySelector('[data-field="kaiti-text"]') as HTMLTextAreaElement).disabled).toBe(true);
    expect(container.textContent).toMatch(/人的令牌/);
    await until(() => true);
    expect(r.fetch.calls.length).toBe(0);
  });
});

describe("外部判定与命令警告（external-verdict §5.8）", () => {
  it("认出已登记的平台：卡上写外部判定；按创建才领题，用导入的批次新建任务", async () => {
    const { r, container } = await drafted(rec("external").text);
    expect(container.querySelector("[data-external]")?.textContent).toContain("plat-a");
    const go = container.querySelector('[data-action="open-problem"]') as HTMLButtonElement;
    expect(go.textContent).toContain("领题");
    fireEvent.click(go);
    await waitFor(() => expect(container.querySelector("[data-reject]")?.textContent ?? window.location.pathname).toBe(`/p/${KAITI.imports["T-17"].pid}`));
    const calls = r.fetch.calls.map((c) => `${c.method} ${new URL(c.url, "http://m").pathname}`);
    expect(calls).toContain("POST /v1/connectors/plat-a/import");
    expect(calls.indexOf("POST /v1/connectors/plat-a/import")).toBeLessThan(calls.indexOf("POST /v1/problems"));
  });

  it("命令有外发的形状：不勾“只检查、不提交”不能创建；勾了出处记“人”", async () => {
    const { container } = await drafted(rec("outbound").text);
    const go = () => container.querySelector('[data-action="open-problem"]') as HTMLButtonElement;
    expect(go().disabled).toBe(true);
    expect(container.querySelector('[data-note="command_outbound"]')).not.toBeNull();
    fireEvent.click(container.querySelector('[data-action="ack-command"]')!);
    await waitFor(() => expect(go().disabled).toBe(false));
    expect(container.querySelector('[data-field="goal.check.ack"] [data-source="human"]')).not.toBeNull();
  });
});

describe("从平台导入页", () => {
  it("只有一个平台时直接列清单；领题出确认卡，创建走同一条提交路", async () => {
    const { PlatformImport } = await import("../src/pages/PlatformImport");
    window.history.pushState(null, "", "/import/platform");
    const r = rig();
    const { container } = renderWith(r, <PlatformImport />);
    await waitFor(() => expect(container.querySelector('[data-task="T-17"]')).not.toBeNull());
    expect(r.fetch.calls.some((c) => c.url.endsWith("/import"))).toBe(false); // 列清单不领题
    fireEvent.click(container.querySelector('[data-task="T-17"] [data-action="claim"]')!);
    await waitFor(() => expect(container.querySelector("[data-kaiti-card]")).not.toBeNull());
    expect(container.querySelector('[data-note="external_platform"]')).not.toBeNull();
    fireEvent.click(container.querySelector('[data-action="open-problem"]')!);
    await waitFor(() => expect(window.location.pathname).toBe(`/p/${KAITI.imports["T-17"].pid}`));
    expect(parseRoute("/import/platform", "?id=plat-a")).toEqual({ page: "platform", id: "plat-a" });
    expect(hrefOf({ page: "platform", id: "plat-a" })).toBe("/import/platform?id=plat-a");
  });
});
