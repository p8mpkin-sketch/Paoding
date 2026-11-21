// 今日、任务库、读数 v6（docs/design/pages-v6）：纯函数与三页在假后端上的排版。
import { cleanup, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { BudgetPoint, ProblemItem } from "../src/api/types";
import { dayStart, doneRate, spendByDay, spendDeltas, spendSince, wallHistogram } from "../src/model/dashboard";
import { Dashboard } from "../src/pages/Dashboard";
import { filterMore, Problems, toCsv } from "../src/pages/Problems";
import { Readings } from "../src/pages/Readings";
import { renderWith, rig } from "./helpers";

afterEach(cleanup);

const $ = (c: ParentNode, sel: string) => c.querySelector<HTMLElement>(sel);
const NOW = new Date(2026, 10, 18, 15, 0).getTime();
const H = 3600_000;
const pt = (ts: number | null, usd: number, tokens = usd * 10): BudgetPoint => ({ seq: 1, ts, usd_milli: usd, tokens, by_lease: {} });
function item(id: string, patch: Partial<ProblemItem> = {}): ProblemItem {
  return {
    id, authority: "local", title: { src: "title", register: "叙述", value: `题 ${id}` }, closed: false, terminal: null,
    terminal_badge: { judge_id: "exact_match", version: "1", grade: "decisive", kind: "hard", label: "exact_match@1" },
    opened_seq: 1, opened_ts: NOW - 5 * H, closed_seq: null, profile: { info: "complete", judge: "hard", reversibility: "r0" },
    spent_usd_milli: 100, cap_usd_milli: 1000, closed_ts: null, goal_level: "E0", active: [], human_todo: 0, wall: { cap_s: 7200, elapsed_s: 60 }, shelf: "active", pinned: false, trash_until: null,
    ...patch,
  };
}

describe("花费序列的算术（纯函数）", () => {
  const a = [pt(NOW - 30 * H, 100), pt(NOW - 2 * H, 250), pt(null, 300), pt(NOW - H, 380)];
  const b = [pt(NOW - 3 * 24 * H, 40)];
  it("拆成每点比前一点多花的钱；没有时刻的点不计入、算进 untimed", () => {
    expect(spendDeltas(a).map((x) => x.usd)).toEqual([100, 150, 80]);
    expect(spendSince([a, b], dayStart(NOW))).toEqual({ usd: 230, tasks: 1, untimed: 50 });
  });
  it("按天合计：当天花费、令牌与当天有花费的任务数；七天以外不计", () => {
    const d = spendByDay([a, b, [pt(NOW - 20 * 24 * H, 999)]], NOW, 7);
    expect(d).toHaveLength(7);
    expect(d[6]).toMatchObject({ usd: 230, tasks: 1 });
    expect(d[5]).toMatchObject({ usd: 100, tasks: 1 });
    expect(d[3]).toMatchObject({ usd: 40, tasks: 1 });
    expect(d.reduce((x, y) => x + y.usd, 0)).toBe(370);
  });
  it("用时分桶与做成率只看已结束的", () => {
    const xs = [item("a", { closed: true, terminal: "solved", wall: { cap_s: 1, elapsed_s: 30 } }), item("b", { closed: true, terminal: "unsolved", wall: { cap_s: 1, elapsed_s: 400 } }),
      item("c", { closed: true, terminal: "delivered", wall: { cap_s: 1, elapsed_s: 4000 } }), item("d")];
    expect(wallHistogram(xs)).toEqual([1, 0, 1, 0, 1]);
    expect(doneRate(xs)).toBeCloseTo(2 / 3);
    expect(doneRate([item("x")])).toBeNull();
  });
});

describe("任务库的筛选与导出（纯函数）", () => {
  const xs = [
    item("a", { authority: "self", opened_ts: NOW - H }),
    item("b", { authority: "local", opened_ts: NOW - 3 * 24 * H }),
    item("c", { authority: "local", opened_ts: NOW - 40 * 24 * H, closed: true, terminal: "solved", closed_ts: NOW - 2 * H }),
    item("d", { authority: "human", opened_ts: NOW - 40 * 24 * H, closed: true, terminal: "accepted", closed_ts: NOW - 20 * 24 * H }),
  ];
  it("判定方式与时间范围：已结束的按结束时刻算", () => {
    expect(filterMore(xs, "local", "", NOW).map((p) => p.id)).toEqual(["b", "c"]);
    expect(filterMore(xs, "", "today", NOW).map((p) => p.id)).toEqual(["a", "c"]);
    expect(filterMore(xs, "", "7", NOW).map((p) => p.id)).toEqual(["a", "b", "c"]);
    expect(filterMore(xs, "", "30", NOW).map((p) => p.id)).toEqual(["a", "b", "c", "d"]);
  });
  it("CSV：表头、引号与逗号转义、美元三位小数", () => {
    const csv = toCsv([item("x", { title: { src: "title", register: "叙述", value: "含,逗号 \"引号\"" }, spent_usd_milli: 1234 })]);
    const [head, row] = csv.trim().split("\n");
    expect(head).toBe("编号,标题,状态,判定方式,花费(美元),上限(美元),用时(秒),开始,结束");
    expect(row.startsWith('x,"含,逗号 ""引号""",执行中,local,1.234,1.000,60,')).toBe(true);
  });
});

describe("三页（假后端）", () => {
  it("今日：在跑的开放道任务写出智能体正在做的命令、最近自述与模型/工具调用次数；今天花费有读数", async () => {
    const r = rig();
    const { container } = renderWith(r, <Dashboard now={1_794_000_000_000 + 3 * H} />);
    const card = await waitFor(() => { const c = $(container, '.run-card [data-agent-now] code'); expect(c?.textContent).toContain("git checkout 71aa03b"); return c!.closest(".run-card")!; });
    expect($(card, "[data-agent-say]")!.textContent).toContain("先对比这个函数");
    expect($(card, "[data-agent-counts]")!.textContent).toContain("模型调用 4");
    await waitFor(() => expect($(container, '[data-cell="today-spend"] .big')!.textContent).toMatch(/^\$\d/));
    expect($(container, '[data-chart="spend7"]')).not.toBeNull();
  });

  it("今日：等你处理按种类列出，每一件都能直达任务页", async () => {
    const r = rig();
    const { container } = renderWith(r, <Dashboard now={1_794_000_000_000 + 3 * H} />);
    const it = await waitFor(() => { const x = $(container, "[data-waiting] [data-ask-item]"); expect(x).not.toBeNull(); return x!; });
    expect(it.querySelector("a")!.getAttribute("href")).toMatch(/^\/p\//);
    expect($(container, "[data-ask-kinds]")!.textContent!.length).toBeGreaterThan(0);
  });

  it("任务库：判定方式筛到开放道；合计条跟着变；点“预览”在右侧看会话与最近几步；j 把焦点移到第一行", async () => {
    const r = rig();
    const { container } = renderWith(r, <Problems now={1_794_000_000_000 + 3 * H} />);
    await waitFor(() => expect(container.querySelectorAll("[data-list] [data-problem]").length).toBeGreaterThan(3));
    const all = container.querySelectorAll("[data-list] [data-problem]").length;
    fireEvent.change($(container, '[data-field="auth"]')!, { target: { value: "self" } });
    await waitFor(() => expect(container.querySelectorAll("[data-list] [data-problem]").length).toBeLessThan(all));
    const ids = [...container.querySelectorAll("[data-list] [data-problem]")].map((x) => x.getAttribute("data-problem"));
    expect(ids).toContain("demo-7");
    expect($(container, "[data-bank-sum]")!.textContent).toContain(`${ids.length} 个任务`);
    fireEvent.click($(container, '[data-problem="demo-7"] [data-action="preview"]')!);
    const pv = await waitFor(() => { const p = $(container, '[data-preview="demo-7"]'); expect(p).not.toBeNull(); return p!; });
    await waitFor(() => expect(pv.querySelectorAll("[data-preview-steps] li").length).toBeGreaterThan(2));
    await waitFor(() => expect($(pv, "[data-preview-turns]")?.textContent).toContain("4 次"));
    fireEvent.keyDown(window, { key: "j" });
    expect(document.activeElement?.getAttribute("data-problem")).toBe(ids[0]);
    expect($(container, '[data-action="export-csv"]')).not.toBeNull();
  });

  it("读数：指标、每天花费、结局按判定来源、钱花在哪；明细可排序；服务端口径的判定来源表还在", async () => {
    const r = rig();
    const { container } = renderWith(r, <Readings now={1_794_000_000_000 + 3 * H} />);
    await waitFor(() => expect($(container, '[data-chart="by-kind"] [data-bar]')).not.toBeNull());
    expect($(container, '[data-tile="tasks"] .big')!.textContent).toMatch(/^\d+$/);
    expect($(container, '[data-chart="outcomes"] [data-seg-row="self"]')).not.toBeNull();
    expect($(container, '[data-chart="by-model"]')!.textContent).toContain("model-a");
    expect($(container, "[data-by-authority] [data-authority=\"human\"]")).not.toBeNull();
    // 开放道单独成表（地图 Q35）：交付、采纳、复核读数（demo-6 的交付有一份复核）
    await waitFor(() => expect($(container, '[data-open-readings] [data-tile="open-review"] .big')?.textContent).toBe("1"));
    expect($(container, '[data-tile="open-review"]')!.textContent).toContain("有据 4");
    expect($(container, '[data-tile="open-deliveries"] .big')!.textContent).toBe("1");
    const first = () => $(container, "[data-rd-row]")!.getAttribute("data-rd-row");
    const before = first();
    fireEvent.click($(container, '[data-sort="spent"]')!);
    await waitFor(() => expect(first()).not.toBe(before));
    fireEvent.click($(container, '[data-chart="by-kind"] [data-action="chart-table"]')!);
    expect($(container, '[data-chart="by-kind"] [data-chart-table]')).not.toBeNull();
  });
});
