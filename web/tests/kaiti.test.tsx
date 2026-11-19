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

const rec = (k: "practice" | "command" | "refuse") => KAITI.drafts[k];
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

  it("卡上改风险与预算：重新校验不再调模型，出处变“人”", async () => {
    const { r, container } = await drafted(rec("command").text);
    const card = () => container.querySelector("[data-kaiti-card]")!;
    expect(card().querySelector('[data-field="command-note"]')?.textContent).toMatch(/唯一标准/);
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
    fireEvent.change(w.querySelector('[data-field="title"]')!, { target: { value: "我自己的题名" } });
    expect(w.querySelector('[data-src="title"]')?.getAttribute("data-source")).toBe("human");
  });
});

describe("拒绝页", () => {
  it("说不清怎样算做完：引用目标句，三条路，人工验收灰显；输入框保留原文", async () => {
    const { container } = await drafted(rec("refuse").text);
    const page = container.querySelector("[data-kaiti-refuse]")!;
    expect(page.textContent).toContain("这件事还说不清怎样算做完");
    expect(page.querySelector(".kt-quote")?.textContent).toBeTruthy();
    expect(page.querySelectorAll(".kt-ways > li")).toHaveLength(3);
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
