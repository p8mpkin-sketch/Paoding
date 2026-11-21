// 方案分析界面一期（docs/design/engine-ui）：纯函数、路由，以及在假后端上回放引擎真跑的产物——列表、详情、第 1 次确认、候选方案、待你处理。
import { cleanup, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { hrefOf, parseRoute, type Route } from "../src/app/router";
import { budgetAdd, g1Block, g1Problems, plain, stateOf, stepper } from "../src/model/analysis";
import { Analyses, Analysis } from "../src/pages/Analyses";
import { Candidates } from "../src/pages/Candidates";
import { Inbox } from "../src/pages/Inbox";
import { navOf } from "../src/shell/AppShell";
import { renderWith, rig } from "./helpers";

afterEach(cleanup);
const $ = (c: ParentNode, sel: string) => c.querySelector<HTMLElement>(sel);
const DELTA = "p_fixture_delta_code";
const ALPHA = "p_fixture_alpha_code";

describe("方案分析：纯函数", () => {
  it("决定块照引擎 decision.render 的顺序与写法：选、排除（带理由）、改、备注", () => {
    const order = ["C1", "C2", "C3"];
    const block = g1Block(order, { pick: ["C2", "C1", "C3"], exclude: { C3: "已在待办里" }, title: { C2: "分阶段验收" }, note: "先看压缩" });
    expect(block).toBe("【决定 v1】闸点 1\n选：C1，C2\n排除：C3（已在待办里）\n改：C2.title = 分阶段验收\n备注：先看压缩");
    expect(g1Block(order, { pick: [], exclude: {}, title: {}, note: "" })).toBe("【决定 v1】闸点 1\n选：无");
  });

  it("理由、标题、备注里会打断解析的字符被换掉，不会多出一行或一个候选", () => {
    const block = g1Block(["C1", "C2"], { pick: ["C1"], exclude: { C2: "重复（见 C1）；不做\n下一行" }, title: { C1: "新名\n选：C9" }, note: "a\nb" });
    expect(block.split("\n")).toHaveLength(5);
    expect(block).toContain("排除：C2（重复〔见 C1〕，不做 下一行）");
    expect(block).toContain("改：C1.title = 新名 选：C9");
  });

  it("提交前还差什么、追加预算的换算", () => {
    expect(g1Problems(["C1"], { pick: [], exclude: {}, title: {}, note: "" })).toEqual(["至少选一个候选"]);
    expect(g1Problems(["C1", "C2"], { pick: ["C1"], exclude: { C2: " " }, title: { C1: "" }, note: "" })).toEqual(["C2 的排除理由没写", "C1 的新标题是空的"]);
    expect(budgetAdd("")).toBe(0);
    expect(budgetAdd("2.5")).toBe(2500);
    expect(budgetAdd("101")).toBeNull();
    expect(budgetAdd("-1")).toBeNull();
  });

  it("引擎自由文本里的内部名词换成常规词", () => {
    expect(plain("请在下列候选中挑选（闸点 1）")).toBe("请在下列候选中挑选（第 1 次确认）");
    expect(plain("体质改动预计为 0；已在异火榜 Y-002；剖面 h4.compress = 0；能力剖面不变")).toBe("内核改动预计为 0；已在候选方案 Y-002；能力剖面 h4.compress = 0；能力剖面不变");
    expect(plain("请逐个确认火意")).toBe("请逐个确认核心机制");
  });

  it("状态与十步进度条：停在确认点是琥珀，提交后是蓝", () => {
    expect(stateOf({ step: "G1", mode: "formal", waiting: { gate: "G1", deliver_seq: 1, submitted: false } })).toMatchObject({ tone: "need", word: "待你确认 · 第 1 次" });
    expect(stateOf({ step: "G1", mode: "formal", waiting: { gate: "G1", deliver_seq: 1, submitted: true } }).tone).toBe("live");
    expect(stateOf({ step: "S3", mode: "formal", waiting: null })).toMatchObject({ tone: "live", word: "发现中" });
    const s = stepper("G1", true);
    expect(s.map((x) => x.cls)).toEqual(["done", "done", "done", "done", "wait", "", "", "", "", ""]);
    expect(stepper("done", false).every((x) => x.cls === "done")).toBe(true);
  });

  it("路由：能力配置下的方案分析与候选方案", () => {
    const rs: Route[] = [{ page: "analyses" }, { page: "analysis", run: DELTA, tab: "now" }, { page: "analysis", run: DELTA, tab: "files" }, { page: "candidates" }, { page: "candidates", id: "Y-002" }];
    for (const r of rs) {
      const href = hrefOf(r);
      const i = href.indexOf("?");
      expect(parseRoute(i < 0 ? href : href.slice(0, i), i < 0 ? "" : href.slice(i))).toEqual(r);
    }
    expect(navOf({ page: "analysis", run: DELTA, tab: "now" }).key).toBe("evolution");
  });
});

describe("方案分析：页面（假后端回放引擎在验收夹具上真跑的产物）", () => {
  it("列表：三次分析，在等你的标琥珀并汇总在顶上", async () => {
    const r = rig();
    const { container } = renderWith(r, <Analyses />);
    await waitFor(() => expect(container.querySelectorAll("[data-an-run]")).toHaveLength(3));
    expect($(container, "[data-an-waiting]")!.textContent).toContain("3 个分析在等你");
    expect($(container, `[data-an-run="${DELTA}"]`)!.textContent).toMatch(/只借思路.*3 个候选/);
    expect($(container, `[data-an-run="${ALPHA}"]`)!.textContent).toContain("第 2 次");
    expect($(container, '[data-cap-tab="analyses"]')!.getAttribute("aria-selected")).toBe("true");
  });

  it("第 1 次确认：勾选、排除要写理由、改名、看依据与观察记录，生成的原文提交后记下", async () => {
    const r = rig();
    const { container } = renderWith(r, <Analysis run={DELTA} tab="now" />);
    await waitFor(() => expect(container.querySelectorAll("[data-an-cand]")).toHaveLength(3));
    expect($(container, "[data-an-license]")!.textContent).toContain("只借思路");
    expect($(container, "[data-an-injection]")).not.toBeNull();
    expect($(container, "[data-an-need]")!.textContent).toContain("疑似写给智能体的指令");
    expect($(container, '[data-an-cand="C1"] [data-an-dedupe]')!.textContent).toContain("Y-003");
    const submit = $(container, '[data-action="an-submit"]') as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    expect($(container, "[data-an-problems]")!.textContent).toContain("至少选一个候选");

    fireEvent.click($(container, '[data-an-cand="C1"] [data-field="an-pick"]')!);
    fireEvent.click($(container, '[data-an-cand="C2"] [data-field="an-pick"]')!);
    fireEvent.click($(container, '[data-an-cand="C3"] [data-action="an-exclude"]')!);
    expect($(container, "[data-an-problems]")!.textContent).toContain("C3 的排除理由没写");
    fireEvent.change($(container, '[data-an-exclude="C3"] input')!, { target: { value: "已在待办里，不必走分析" } });
    fireEvent.click($(container, '[data-an-cand="C2"] [data-action="an-rename"]')!);
    fireEvent.change($(container, '[data-field="an-title"]')!, { target: { value: "分阶段验收" } });
    fireEvent.click($(container, '[data-action="an-title-ok"]')!);
    expect($(container, '[data-an-cand="C2"] .an-title.edited')!.textContent).toBe("分阶段验收");

    fireEvent.click($(container, '[data-an-cand="C2"] [data-action="an-basis"]')!);
    const basis = $(container, '[data-an-basis="C2"]')!;
    expect(basis.textContent).toContain("h1.staged");
    expect(basis.textContent).not.toMatch(/异火|功法|体质|火位/);
    fireEvent.click($(basis, '[data-action="an-obs"]')!);
    expect(basis.querySelectorAll("[data-an-obs]").length).toBeGreaterThan(0);
    expect(basis.textContent).toContain("README.md:1–26");

    expect($(container, "[data-an-block]")!.textContent).toBe("【决定 v1】闸点 1\n选：C1，C2\n排除：C3（已在待办里，不必走分析）\n改：C2.title = 分阶段验收");
    expect($(container, "[data-an-problems]")).toBeNull();
    fireEvent.click($(container, '[data-action="an-submit"]')!);
    await waitFor(() => expect($(container, "[data-an-submitted]")).not.toBeNull());
    expect($(container, "[data-an-submitted]")!.textContent).toContain("排除：C3（已在待办里，不必走分析）");
    expect($(container, '[data-an-cand="C3"]')!.getAttribute("data-picked")).toBe("false");
    const d = await r.api.analysis(DELTA);
    expect(d.waiting?.submitted).toBe(true);
    await expect(r.api.analysisDecide(DELTA, { block: "【决定 v1】闸点 1\n选：C1", deliver_seq: 1 })).rejects.toMatchObject({ status: 409, code: "already_submitted" });
  });

  it("提交端点的校验与引擎同口径：只认人的令牌、读不懂的行、没有的候选、所见交付变了", async () => {
    const r = rig();
    const ro = rig(null);
    await expect(ro.api.analysisDecide(DELTA, { block: "【决定 v1】闸点 1\n选：C1", deliver_seq: 1 })).rejects.toMatchObject({ status: 401 });
    await expect(r.api.analysisDecide(DELTA, { block: "【决定 v1】闸点 1\n选个好的", deliver_seq: 1 })).rejects.toMatchObject({ code: "unparsed" });
    await expect(r.api.analysisDecide(DELTA, { block: "【决定 v1】闸点 1\n选：C9", deliver_seq: 1 })).rejects.toMatchObject({ code: "unknown_candidate" });
    await expect(r.api.analysisDecide(DELTA, { block: "【决定 v1】闸点 1\n选：C1\n排除：C1（重复）", deliver_seq: 1 })).rejects.toMatchObject({ code: "pick_and_exclude" });
    await expect(r.api.analysisDecide(DELTA, { block: "【决定 v1】闸点 1\n选：C1", deliver_seq: 2 })).rejects.toMatchObject({ status: 409, code: "stale_view" });
    await expect(r.api.analysisDecide(ALPHA, { block: "【决定 v1】闸点 2\n确认：C1", deliver_seq: 3 })).rejects.toMatchObject({ status: 409, code: "not_yet" });
  });

  it("没有令牌时只读：能看，不能提交", async () => {
    const r = rig(null);
    const { container } = renderWith(r, <Analysis run={DELTA} tab="now" />);
    await waitFor(() => expect($(container, '[data-action="an-submit"]')).not.toBeNull());
    fireEvent.click($(container, '[data-an-cand="C1"] [data-field="an-pick"]')!);
    expect(($(container, '[data-action="an-submit"]') as HTMLButtonElement).disabled).toBe(true);
    expect($(container, "[data-an-decide]")!.textContent).toContain("只读");
  });

  it("第 2 次确认先只读；过程按检查点排出单元与两次确认；文件分三类、点开看内容；报告按交付排", async () => {
    const r = rig();
    const g2 = renderWith(r, <Analysis run={ALPHA} tab="now" />);
    await waitFor(() => expect($(g2.container, '[data-an-essence="C1"]')).not.toBeNull());
    expect($(g2.container, '[data-an-gate="G2"]')!.textContent).toContain("二期");
    cleanup();
    const p = renderWith(r, <Analysis run={ALPHA} tab="process" />);
    await waitFor(() => expect($(p.container, "[data-an-process]")).not.toBeNull());
    expect(p.container.querySelectorAll('[data-an-unit^="read:"]')).toHaveLength(8);
    expect($(p.container, '[data-an-proc="G1:1"]')!.textContent).toContain("选 C1");
    expect($(p.container, '[data-an-unit="cuiyi:C1"]')!.textContent).toContain("完成");
    cleanup();
    const f = renderWith(r, <Analysis run={DELTA} tab="files" />);
    await waitFor(() => expect($(f.container, '[data-an-file="candidates.json"]')).not.toBeNull());
    expect(f.container.querySelectorAll("[data-an-file]")).toHaveLength(12);
    fireEvent.click($(f.container, '[data-an-file="candidates.json"] [data-action="an-file"]')!);
    await waitFor(() => expect($(f.container, "[data-an-artifact] pre")!.textContent).toContain("plain_summary"));
    cleanup();
    const rep = renderWith(r, <Analysis run={ALPHA} tab="report" />);
    await waitFor(() => expect(rep.container.querySelectorAll("[data-an-report]")).toHaveLength(2));
    expect($(rep.container, '[data-an-report="G1"]')!.textContent).toContain("方案分析：候选做法");
  });

  it("候选方案：按状态筛选，点开看核心机制与状态史", async () => {
    const r = rig();
    const { container } = renderWith(r, <Candidates id="Y-001" />);
    await waitFor(() => expect(container.querySelectorAll("[data-bang]").length).toBeGreaterThan(0));
    const all = container.querySelectorAll("[data-bang]").length;
    fireEvent.click($(container, '[data-bang-filter="done"]')!);
    expect(container.querySelectorAll("[data-bang]").length).toBeLessThan(all);
    expect($(container, '[data-bang="Y-001"]')!.textContent).toContain("已集成");
    const drawer = document.querySelector<HTMLElement>('[data-bang-detail="Y-001"]')!;
    expect(drawer.textContent).toContain("可回放的实时性");
    expect(drawer.textContent).not.toMatch(/火莲|炼档|第 2 阶/);
  });

  it("待你处理：方案分析单列一组，每件直达那次分析", async () => {
    const r = rig();
    const { container } = renderWith(r, <Inbox />);
    await waitFor(() => expect($(container, "[data-inbox-analyses]")).not.toBeNull());
    expect(container.querySelectorAll("[data-inbox-analysis]")).toHaveLength(3);
    expect($(container, `[data-inbox-analysis="${DELTA}"]`)!.textContent).toContain("3 个候选做法");
  });
});
