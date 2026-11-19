// 总览与题库（工作台设计 §1 模块一、二）：只排版服务端给的字段，不推断等级或“阶段”。
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { ProblemItem } from "../src/api/types";
import { applyTheme, loadTheme } from "../src/app/theme";
import { dailySeries, dayStart, leaseKinds, recentOf, solvedToday, terminalCounts } from "../src/model/dashboard";
import { Inbox } from "../src/pages/Inbox";
import { Dashboard, Trend } from "../src/pages/Dashboard";
import { filterBank, Problems } from "../src/pages/Problems";
import { playToEnd, renderWith, rig, until } from "./helpers";

afterEach(cleanup);

const NOW = new Date(2026, 10, 18, 15, 0).getTime();
const H = 3600_000;
function item(id: string, patch: Partial<ProblemItem> = {}): ProblemItem {
  return {
    id, authority: "local", title: { src: "title", register: "叙述", value: `题 ${id}` }, closed: false, terminal: null,
    terminal_badge: { judge_id: "exact_match", version: "1", grade: "decisive", kind: "hard", label: "exact_match@1" },
    opened_seq: 1, opened_ts: NOW - 5 * H, closed_seq: null, profile: { info: "complete", judge: "hard", reversibility: "r0" },
    spent_usd_milli: 100, cap_usd_milli: 1000, closed_ts: null, goal_level: "E0", active: [], human_todo: 0, wall: { cap_s: 7200, elapsed_s: 60 },
    ...patch,
  };
}
const done = (id: string, terminal: ProblemItem["terminal"], ts: number, seq: number) => item(id, { closed: true, terminal, closed_ts: ts, closed_seq: seq });

describe("总览的纯函数", () => {
  const items = [
    item("r1", { active: [{ kind: "explore", target: "i_3" }, { kind: "judge", target: "goal" }, { kind: "explore", target: "i_4" }] }),
    done("a", "solved", NOW - 1 * H, 10),
    done("b", "unsolved", NOW - 2 * H, 12),
    done("c", "solved", NOW - 30 * H, 5),
    done("d", "accepted", NOW - 9 * 24 * H, 3), // 7 天以外
    item("e", { closed: true, terminal: "solved", closed_seq: 20, closed_ts: null }), // 老图服务没有 closed_ts
  ];
  it("在途租约按种类计数，保持服务端给的先后", () => {
    expect(leaseKinds(items[0])).toEqual([{ kind: "explore", n: 2 }, { kind: "judge", n: 1 }]);
  });
  it("最近完成：后关的在前，可按终态筛", () => {
    expect(recentOf(items, null).map((p) => p.id)).toEqual(["e", "b", "a", "c", "d"]);
    expect(recentOf(items, "solved").map((p) => p.id)).toEqual(["e", "a", "c"]);
    expect(terminalCounts(items)).toEqual({ solved: 3, accepted: 1, unsolved: 1 });
  });
  it("按本机时区分日；没有 closed_ts 的不进趋势也不算今日", () => {
    const s = dailySeries(items, NOW);
    expect(s).toHaveLength(7);
    expect(s[6]).toEqual({ day: dayStart(NOW), closed: 2, solved: 1 });
    expect(s[5]).toMatchObject({ closed: 1, solved: 1 });
    expect(s.slice(0, 5).every((b) => b.closed === 0)).toBe(true);
    expect(solvedToday(items, NOW)).toBe(1);
  });
  it("题库筛选：搜索题名或 id、终态、判官", () => {
    expect(filterBank(items, { q: "题 A", terminal: "", judge: "" }).map((p) => p.id)).toEqual(["a"]);
    expect(filterBank(items, { q: "", terminal: "running", judge: "" }).map((p) => p.id)).toEqual(["r1"]);
    expect(filterBank(items, { q: "", terminal: "", judge: "nope" })).toEqual([]);
  });
});

describe("总览页（假后端）", () => {
  it("进行中卡片列在途租约种类与待人项，关题后移到最近完成", async () => {
    const r = rig();
    const { container } = renderWith(r, <Dashboard now={NOW} />);
    const pid = r.mock.demoPid;
    await until(() => container.querySelector(`.run-card[data-problem="${pid}"]`) !== null, "演示题卡片");
    const card = container.querySelector(`.run-card[data-problem="${pid}"]`)!;
    expect(card.querySelector("[data-human-todo]")?.textContent).toBe("等你处理"); // 件数只在等你处理清单里出现一次
    expect(container.querySelector("[data-waiting]")).not.toBeNull();
    // 卡片上不出现前端自造的“阶段”词
    expect(card.textContent).not.toMatch(/探索中|推理中|执行中|判定中/);
    await playToEnd(r);
    cleanup();
    const again = renderWith(r, <Dashboard now={NOW} />).container;
    await until(() => again.querySelector(`.dash-recent tr[data-problem="${pid}"]`) !== null, "关题后进最近完成");
    expect(again.querySelector(`.run-card[data-problem="${pid}"]`)).toBeNull();
  });

  it("近七日：没有结束的任务时只一句话、不列空位；有数据时可切表格，无完成的日子不写百分比", () => {
    const day = 86_400_000;
    const empty = Array.from({ length: 7 }, (_, i) => ({ day: i * day, closed: 0, solved: 0 }));
    const a = render(<Trend series={empty} />).container;
    expect(a.querySelector("[data-trend-empty]")).not.toBeNull();
    expect(a.textContent).not.toContain("—");
    expect(screen.queryByRole("button", { name: /^表格/ })).toBeNull();
    cleanup();
    const some = empty.map((b, i) => (i === 3 ? { ...b, closed: 2, solved: 1 } : b));
    const b = render(<Trend series={some} />).container;
    expect([...b.querySelectorAll(".t-tick")].map((t) => t.textContent).filter((t) => t!.endsWith("%"))).toEqual(["50%"]);
    fireEvent.click(screen.getByRole("button", { name: /^表格/ }));
    expect(b.querySelector("[data-trend-table] tbody")?.children).toHaveLength(7);
    expect(b.textContent).not.toContain("—");
  });

  it("题库按 URL 里的条件筛选", async () => {
    const r = rig();
    const { container } = renderWith(r, <Problems filter={{ q: "", terminal: "solved", judge: "" }} />);
    await until(() => container.querySelector("[data-page=bank] table, [data-page=bank] .k-empty") !== null, "题库");
    for (const row of container.querySelectorAll("tr[data-problem] td[data-terminal]")) expect(row.getAttribute("data-terminal")).toBe("solved");
  });
});

describe("待办页（假后端）", () => {
  it("按任务列出等人处理的事，每件带去处理链接，指向工作区的对应节点", async () => {
    const r = rig();
    const { container } = renderWith(r, <Inbox />);
    const pid = r.mock.demoPid;
    await until(() => container.querySelector(`[data-inbox-problem="${pid}"] [data-inbox-item]`) !== null, "待办项");
    const item = container.querySelector(`[data-inbox-problem="${pid}"] [data-inbox-item]`)!;
    const target = item.getAttribute("data-inbox-item")!.split(":").slice(1).join(":");
    const href = new URL(item.querySelector("a")!.getAttribute("href")!, "http://x");
    expect(href.pathname).toBe(`/p/${pid}`);
    expect(href.searchParams.get("node")).toBe(target);
  });
});

describe("主题", () => {
  it("写在 <html> 上并存本机；跟随系统时去掉属性", () => {
    applyTheme("contrast");
    expect(document.documentElement.getAttribute("data-theme")).toBe("contrast");
    expect(loadTheme()).toBe("contrast");
    applyTheme("system");
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    expect(loadTheme()).toBe("system");
  });
});
