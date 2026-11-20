// 任务列表（v5 第三期）：分组、置顶在前、搜索、软删（先停再删，同一批）、回收站恢复、改名、批量归档。
import { cleanup, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { ProblemItem } from "../src/api/types";
import { NO_FILTER, useRoute } from "../src/app/router";
import { filterBank, groupOf, Problems, sortRows } from "../src/pages/Problems";
import { renderWith, rig } from "./helpers";

beforeEach(() => window.history.pushState(null, "", "/tasks"));
afterEach(cleanup);

const $ = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel);
const $$ = (sel: string) => [...document.querySelectorAll(sel)];
const ids = (sel = "[data-list] [data-problem]") => $$(sel).map((x) => x.getAttribute("data-problem"));
async function menuItem(pid: string, what: string) {
  fireEvent.click($(`[data-problem="${pid}"] [data-action="row-menu"]`)!);
  const b = await waitFor(() => { const x = $<HTMLButtonElement>(`[data-row-menu="${pid}"] [data-menu="${what}"]`); expect(x).not.toBeNull(); return x!; });
  return b;
}

/** 与 App 一样从 URL 取筛选条件：点分类会改 URL。 */
function Page() {
  const r = useRoute();
  return <Problems filter={r.page === "problems" ? { q: r.q ?? "", terminal: r.terminal ?? "", judge: r.judge ?? "" } : NO_FILTER} />;
}

function item(id: string, patch: Partial<ProblemItem> = {}): ProblemItem {
  return {
    id, authority: "local", title: { src: "title", register: "叙述", value: `题 ${id}` }, closed: false, terminal: null,
    terminal_badge: { judge_id: "exact_match", version: "1", grade: "decisive", kind: "hard", label: "exact_match@1" },
    opened_seq: 1, opened_ts: 0, closed_seq: null, profile: { info: "complete", judge: "hard", reversibility: "r0" },
    spent_usd_milli: 100, cap_usd_milli: 1000, closed_ts: null, goal_level: "E0", active: [], human_todo: 0, wall: { cap_s: 7200, elapsed_s: 60 },
    shelf: "active", pinned: false, trash_until: null, ...patch,
  };
}

describe("排版纯函数", () => {
  it("分组：关了的已结束，有待办的要你处理，其余正在做", () => {
    expect(groupOf(item("a", { closed: true, human_todo: 2 }))).toBe("end");
    expect(groupOf(item("b", { human_todo: 1 }))).toBe("need");
    expect(groupOf(item("c"))).toBe("live");
  });
  it("置顶永远在前；其余按最近或花费", () => {
    const xs = [item("a", { opened_seq: 1, spent_usd_milli: 900 }), item("b", { opened_seq: 5 }), item("c", { opened_seq: 3, pinned: true })];
    expect(sortRows(xs, "recent").map((p) => p.id)).toEqual(["c", "b", "a"]);
    expect(sortRows(xs, "cost").map((p) => p.id)).toEqual(["c", "a", "b"]);
  });
  it("归档与回收站各是一类，不进“全部”；过期的哪儿都不出现", () => {
    const xs = [item("a"), item("b", { shelf: "archived" }), item("c", { shelf: "trash", closed: true }), item("d", { shelf: "purged", closed: true })];
    const f = (terminal: string) => filterBank(xs, { q: "", terminal, judge: "" }).map((p) => p.id);
    expect(f("")).toEqual(["a"]);
    expect(f("archived")).toEqual(["b"]);
    expect(f("trash")).toEqual(["c"]);
  });
});

describe("任务列表（假后端）", () => {
  it("按状态分组，顺序固定；搜索不到时给“清空搜索”", async () => {
    renderWith(rig(), <Page />);
    await waitFor(() => expect(ids().length).toBeGreaterThan(0));
    const groups = $$("[data-list] [data-group]").map((g) => g.getAttribute("data-group"));
    expect(groups.length).toBeGreaterThan(0);
    expect(["need", "live", "end"].filter((g) => groups.includes(g))).toEqual(groups);
    fireEvent.change($('[data-field="q"]')!, { target: { value: "不存在的字" } });
    await waitFor(() => expect($('[data-action="clear-q"]')).not.toBeNull());
    fireEvent.click($('[data-action="clear-q"]')!);
    await waitFor(() => expect(ids().length).toBeGreaterThan(0));
  });

  it("删除正在跑的任务：确认框写明后果，同一批先停再进回收站；回收站里能恢复", async () => {
    const r = rig();
    renderWith(r, <Page />);
    const live = await waitFor(() => { const el = $('[data-list] [data-group-of="live"], [data-list] [data-group-of="need"]'); expect(el).not.toBeNull(); return el!; });
    const pid = live.getAttribute("data-problem")!;
    fireEvent.click(await menuItem(pid, "delete"));
    const dlg = await waitFor(() => { const d = $("[data-confirm-delete]"); expect(d).not.toBeNull(); return d!; });
    expect(dlg.textContent).toContain("30 天内可以恢复");
    expect(dlg.textContent).toContain("会先停下来");
    fireEvent.click($('[data-action="confirm-delete"]')!);
    await waitFor(() => expect(ids()).not.toContain(pid));
    const batch = r.fetch.calls.filter((c) => c.url === `/v1/problems/${pid}/proposals`).at(-1)!;
    expect(JSON.parse(String(batch.body)).ops.map((o: { op: string }) => o.op)).toEqual(["close_problem", "curate"]);
    const row = (await r.api.problems()).items.find((p) => p.id === pid)!;
    expect(row.shelf).toBe("trash");
    expect(row.trash_until).not.toBeNull();
    fireEvent.click($('[data-tab="trash"]')!);
    await waitFor(() => expect(ids()).toContain(pid));
    fireEvent.click(await menuItem(pid, "restore"));
    await waitFor(async () => expect((await r.api.problems()).items.find((p) => p.id === pid)!.shelf).toBe("active"));
  });

  it("改名与置顶：置顶的排到最前", async () => {
    const r = rig();
    renderWith(r, <Page />);
    await waitFor(() => expect(ids().length).toBeGreaterThan(1));
    fireEvent.change($('[data-field="sort"]')!, { target: { value: "recent" } });
    const pid = ids().at(-1)!;
    fireEvent.click(await menuItem(pid, "pin"));
    await waitFor(() => expect(ids()[0]).toBe(pid));
    fireEvent.click(await menuItem(pid, "rename"));
    const input = await waitFor(() => { const i = $<HTMLInputElement>('[data-field="rename"]'); expect(i).not.toBeNull(); return i!; });
    fireEvent.change(input, { target: { value: "我起的名字" } });
    fireEvent.click($('[data-action="save-rename"]')!);
    await waitFor(() => expect($(`[data-problem="${pid}"]`)!.textContent).toContain("我起的名字"));
    const p = (await r.api.problems()).items.find((x) => x.id === pid)!;
    expect(p.pinned).toBe(true);
    expect(p.title.value).toBe("我起的名字");
  });

  it("选择模式：平时没有方框；选两个批量归档，进“归档”一类", async () => {
    const r = rig();
    renderWith(r, <Page />);
    await waitFor(() => expect(ids().length).toBeGreaterThan(1));
    expect($$("[data-pick]")).toHaveLength(0);
    fireEvent.click($('[data-action="select-mode"]')!);
    const picks = $$("[data-pick]") as HTMLInputElement[];
    expect(picks.length).toBe(ids().length);
    const two = picks.slice(0, 2).map((x) => x.getAttribute("data-pick")!);
    picks.slice(0, 2).forEach((x) => fireEvent.click(x));
    expect($("[data-bulk]")!.textContent).toContain("选了 2 个");
    fireEvent.click($('[data-action="bulk-archive"]')!);
    await waitFor(async () => {
      const items = (await r.api.problems()).items;
      expect(two.map((x) => items.find((p) => p.id === x)!.shelf)).toEqual(["archived", "archived"]);
    });
    fireEvent.click($('[data-tab="archived"]')!);
    await waitFor(() => expect(ids().sort()).toEqual([...two].sort()));
  });

  it("没有人的令牌：没有“选择”，菜单里整理项不可用、“再跑一次”可用", async () => {
    renderWith(rig(null), <Page />);
    await waitFor(() => expect(ids().length).toBeGreaterThan(0));
    expect($('[data-action="select-mode"]')).toBeNull();
    const pid = ids()[0]!;
    expect((await menuItem(pid, "delete")).disabled).toBe(true);
    expect($<HTMLButtonElement>(`[data-row-menu="${pid}"] [data-menu="clone"]`)!.disabled).toBe(false);
  });
});
