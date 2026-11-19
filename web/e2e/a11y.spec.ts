// 可访问性（95 分计划阶段二第 10 项）：每个页面在亮、暗、高对比三套主题下跑 axe（WCAG 2.1 AA）。
// 只查外壳与页面上真实可交互、可读的部分；装饰（界栏、刻度、印、朱圈）都对读屏器隐藏。
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const TOKEN = "mock-human-token";
const PAGES = ["/", "/inbox", "/problems", "/new", "/import", "/import/platform", "/readings", "/settings", "/p/demo-1", "/p/demo-3", "/p/demo-4", "/p/demo-5"];
const THEMES = ["light", "dark", "contrast"];

test.beforeEach(async ({ page, request }) => {
  await request.post("/__e2e/reset");
  await page.addInitScript((t) => {
    sessionStorage.setItem("paoding.human_token", JSON.stringify({ token: t, expires_at: Date.now() + 3600_000 }));
  }, TOKEN);
});

for (const theme of THEMES) {
  for (const path of PAGES) {
    test(`axe：${path}（${theme}）`, async ({ page }) => {
      await page.addInitScript((t) => localStorage.setItem("paoding.theme", t), theme);
      await page.goto(path);
      await expect(page.locator(".shell-status")).toContainText("已连接");
      await page.waitForTimeout(300);
      const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      const found = r.violations.map((v) => `${v.id}（${v.impact}）× ${v.nodes.length}：${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
      expect(found).toEqual([]);
    });
  }
}

for (const theme of THEMES) {
  test(`axe：命令面板打开（${theme}）`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("paoding.theme", t), theme);
    await page.goto("/problems");
    await expect(page.locator(".shell-status")).toContainText("已连接");
    await page.keyboard.press("Control+k");
    await expect(page.locator("[cmdk-input]")).toBeFocused();
    await page.waitForTimeout(200);
    const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    expect(r.violations.map((v) => `${v.id}（${v.impact}）× ${v.nodes.length}：${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
  });
}

// 工作区的几个状态：审批卡打开、图视图、给出指导打开（第三期）
for (const theme of THEMES) {
  test(`axe：工作区卡片、图与指导（${theme}）`, async ({ page }) => {
    await page.addInitScript((t) => { localStorage.setItem("paoding.theme", t); localStorage.setItem("paoding.graph_view", "always"); }, theme);
    await page.goto("/p/demo-1?node=goal");
    await expect(page.locator("[data-conn-label]")).toHaveText("实时");
    const scan = async (what: string) => {
      await page.waitForTimeout(200);
      const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      expect(r.violations.map((v) => `${what} ${v.id}（${v.impact}）× ${v.nodes.length}：${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
    };
    await page.locator("[data-todo-item] button").first().click();
    await expect(page.locator(".main > .sheet")).toBeVisible();
    await scan("卡片");
    await page.locator('[data-action="tab-graph"]').click();
    await expect(page.locator(".graph-wrap")).toBeVisible();
    await scan("图");
    await page.locator('[data-action="open-inject"]').click();
    await expect(page.locator('[data-card="hint-inject"]')).toBeVisible();
    await scan("指导");
  });
}

// L2：读数页“按判定来源分列”表、人工验收卡（demo-5，逐条判到一半）、关闭任务的结果页（demo-3）
for (const theme of THEMES) {
  test(`axe：判定来源分列、人工验收卡与结果页（${theme}）`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("paoding.theme", t), theme);
    const scan = async (what: string, include?: string) => {
      await page.waitForTimeout(200);
      const b = new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]);
      const r = await (include ? b.include(include) : b).analyze();
      expect(r.violations.map((v) => `${what} ${v.id}（${v.impact}）× ${v.nodes.length}：${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
    };
    await page.goto("/readings");
    await expect(page.locator('[data-by-authority] [data-authority="human"]')).toBeVisible();
    await scan("判定来源表", "[data-by-authority]");
    await page.goto("/p/demo-5");
    await expect(page.locator("[data-conn-label]")).toHaveText("实时");
    await page.locator('[data-todo-item="acceptance:demo-5"] button').click();
    await expect(page.locator('[data-card="acceptance"] [data-accept-item]')).toHaveCount(3);
    await expect(page.locator('[data-card="acceptance"] [data-four]')).not.toHaveCount(0);
    await scan("验收卡（未判）");
    await page.locator('[data-accept-item="a1"] [data-verdict="pass"]').check();
    await page.locator('[data-accept-item="a2"] [data-verdict="fail"]').check();
    await expect(page.locator('[data-field="reject-reason"]')).toBeVisible();
    await scan("验收卡（拒收）");
    await page.goto("/p/demo-3");
    await expect(page.locator("[data-result]")).toBeVisible();
    await scan("结果页", "[data-result]");
  });
}
