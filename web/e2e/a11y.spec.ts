// 可访问性（95 分计划阶段二第 10 项）：每个页面在亮、暗、高对比三套主题下跑 axe（WCAG 2.1 AA）。
// 只查外壳与页面上真实可交互、可读的部分；标志图形对读屏器隐藏。
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const TOKEN = "mock-human-token";
const PAGES = ["/", "/today", "/inbox", "/problems", "/new", "/import", "/import/platform", "/readings", "/capability", "/capability/analyses", "/capability/analyses/p_fixture_delta_code", "/capability/analyses/p_fixture_alpha_code/process", "/capability/candidates", "/models", "/knowledge", "/knowledge/memory", "/settings", "/p/demo-1", "/p/demo-3", "/p/demo-4", "/p/demo-5"];
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
    await expect(page.locator(".tk-col > .sheet")).toBeVisible();
    await scan("卡片");
    await page.locator('[data-action="tab-graph"]').click();
    await expect(page.locator(".graph-wrap")).toBeVisible();
    await scan("图");
    await page.locator('[data-action="open-inject"]').click();
    await expect(page.locator('[data-card="hint-inject"]')).toBeVisible();
    await scan("指导");
  });
}

// 开放道任务页（v5 第三期）：结果一栏、依据抽屉、采纳确认框、过程一栏
for (const theme of THEMES) {
  test(`axe：开放道任务页（${theme}）`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("paoding.theme", t), theme);
    const scan = async (what: string) => {
      await page.waitForTimeout(200);
      const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      expect(r.violations.map((v) => `${what} ${v.id}（${v.impact}）× ${v.nodes.length}：${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
    };
    await page.goto("/p/demo-6");
    await expect(page.locator("[data-answer]")).toContainText("LangGraph");
    await scan("结果");
    await page.locator("[data-claim] [data-ref]").first().click();
    await expect(page.locator("[data-evidence] [data-artifact]")).toBeVisible();
    await scan("依据抽屉");
    await page.keyboard.press("Escape");
    await page.locator('[data-ref-class="knowledge"]').click();
    await expect(page.locator("[data-evidence] [data-knowledge]")).toContainText("团队约定");
    await scan("引用的资料");
    await page.keyboard.press("Escape");
    await page.locator('[data-action="adopt-delivery"]').click();
    await expect(page.locator("[data-four]").first()).toBeVisible();
    await scan("采纳确认");
    await page.keyboard.press("Escape");
    await page.locator('[data-task-tab="steps"]').click();
    await expect(page.locator("[data-step]").first()).toBeVisible();
    await scan("过程");
  });
}

// 知识页的记忆一栏：钉住 / 忘掉的确认弹层（v5 第四期）
for (const theme of THEMES) {
  test(`axe：记忆的确认弹层（${theme}）`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("paoding.theme", t), theme);
    await page.goto("/knowledge/memory");
    await page.locator('[data-mem="m-ex-1"] [data-action="mem-forget"]').click();
    await expect(page.locator('[data-mem-card="m-ex-1"]')).toBeVisible();
    await page.waitForTimeout(200);
    const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    expect(r.violations.map((v) => `${v.id}（${v.impact}）× ${v.nodes.length}：${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
  });
}

// 知识页的资料一栏：导入抽屉与“试一下”的结果（v5 第四期）
for (const theme of THEMES) {
  test(`axe：资料的导入抽屉与检索结果（${theme}）`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("paoding.theme", t), theme);
    await page.goto("/knowledge");
    await page.locator('[data-field="kn-query"]').fill("回滚怎么做");
    await page.locator('[data-action="kn-search"]').click();
    await expect(page.locator("[data-hit]").first()).toBeVisible();
    const scan = async () => {
      await page.waitForTimeout(200);
      const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      expect(r.violations.map((v) => `${v.id}（${v.impact}）× ${v.nodes.length}：${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
    };
    await scan();
    await page.locator('[data-action="kn-import"]').click();
    await expect(page.locator("[data-kn-import]")).toBeVisible();
    await scan();
    await page.locator('[data-mode="text"]').click();
    await scan();
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

// v5 第二期：模型页的添加抽屉（测过一次，结果条显示着）
for (const theme of THEMES) {
  test(`axe：模型页添加抽屉（${theme}）`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("paoding.theme", t), theme);
    await page.goto("/models");
    await expect(page.locator(".shell-status")).toContainText("已连接");
    await page.locator('[data-action="add-model"]').click();
    await page.locator('[data-field="model.name"]').fill("备用");
    await page.locator('[data-field="model.model"]').fill("bad-1");
    await page.locator('[data-action="probe-model"]').click();
    await expect(page.locator("[data-probe-result]")).toHaveAttribute("data-probe-result", "not_found");
    await page.waitForTimeout(200);
    const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    expect(r.violations.map((v) => `${v.id}（${v.impact}）× ${v.nodes.length}：${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
  });
}

// v5 第三期：任务列表的行菜单、删除确认与选择模式
for (const theme of THEMES) {
  test(`axe：任务列表菜单、删除确认与批量栏（${theme}）`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("paoding.theme", t), theme);
    await page.goto("/tasks");
    await expect(page.locator(".shell-status")).toContainText("已连接");
    const scan = async (what: string) => {
      await page.waitForTimeout(200);
      const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      expect(r.violations.map((v) => `${what} ${v.id}（${v.impact}）× ${v.nodes.length}：${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
    };
    await page.locator('[data-list] [data-problem] [data-action="row-menu"]').first().click();
    await expect(page.locator("[data-row-menu]")).toBeVisible();
    await scan("行菜单");
    await page.locator('[data-menu="delete"]').click();
    await expect(page.locator("[data-confirm-delete]")).toBeVisible();
    await scan("删除确认");
    await page.keyboard.press("Escape");
    await page.locator('[data-action="select-mode"]').click();
    await page.locator("[data-pick]").first().check();
    await scan("批量栏");
  });
}

// v5 第三期：首页输入框的预算选项展开、严格判定打开
for (const theme of THEMES) {
  test(`axe：首页输入框的选项与严格判定（${theme}）`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("paoding.theme", t), theme);
    await page.goto("/");
    await expect(page.locator(".shell-status")).toContainText("已连接");
    const scan = async (what: string) => {
      await page.waitForTimeout(200);
      const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      expect(r.violations.map((v) => `${what} ${v.id}（${v.impact}）× ${v.nodes.length}：${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
    };
    await page.locator('button[data-field="budget-tier"]').click();
    await expect(page.locator('[data-pop="budget-tier"]')).toBeVisible();
    await scan("预算选项");
    await page.keyboard.press("Escape");
    await page.locator('[data-action="strict"]').click();
    await expect(page.locator('[data-field="kaiti-answer"]')).toBeVisible();
    await scan("严格判定");
  });
}
