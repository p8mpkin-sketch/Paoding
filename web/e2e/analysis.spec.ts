// 方案分析界面一期（docs/design/engine-ui）：从侧栏进能力配置 › 方案分析，做完第 1 次确认；后面几种停法只读；手机宽度不横向滚动。
import { expect, test } from "@playwright/test";

const TOKEN = "mock-human-token";

test.beforeEach(async ({ page, request }) => {
  await request.post("/__e2e/reset");
  await page.addInitScript((t) => {
    sessionStorage.setItem("paoding.human_token", JSON.stringify({ token: t, expires_at: Date.now() + 3600_000 }));
  }, TOKEN);
});

test("从侧栏角标进到分析，勾选、排除带理由、改名，提交第 1 次确认", async ({ page }) => {
  await page.goto("/today");
  await expect(page.locator('[data-nav="evolution"] .ct')).toHaveText(/^3/);
  await page.click('[data-nav="evolution"]');
  await page.click('[data-cap-tab="analyses"]');
  await expect(page).toHaveURL(/\/capability\/analyses$/);
  await page.click('[data-an-run="p_fixture_delta_code"] .an-name a');
  await expect(page.locator("[data-an-cand]")).toHaveCount(3);
  await page.click('[data-an-cand="C1"] [data-field="an-pick"]');
  await page.click('[data-an-cand="C3"] [data-action="an-exclude"]');
  await page.fill('[data-an-exclude="C3"] input', "已在待办里");
  await page.click('[data-an-cand="C1"] [data-action="an-rename"]');
  await page.fill('[data-field="an-title"]', "结论旁挂执行记录");
  await page.click('[data-action="an-title-ok"]');
  await page.click(".an-raw summary");
  await expect(page.locator("[data-an-block]")).toHaveText("【决定 v1】闸点 1\n选：C1\n排除：C3（已在待办里）\n改：C1.title = 结论旁挂执行记录");
  await page.click('[data-action="an-submit"]');
  await expect(page.locator("[data-an-submitted]")).toContainText("第 1 次确认已提交");
  await page.click('[data-an-tab="process"]');
  await expect(page.locator('[data-an-proc="G1:1"]')).toContainText("已提交");
  await page.goto("/capability/analyses");
  await expect(page.locator('[data-an-run="p_fixture_delta_code"]')).toHaveAttribute("data-state", "submitted");
  await expect(page.locator('[data-nav="evolution"] .ct')).toHaveText(/^2/);
});

// 只量页面内容区（外壳顶栏在手机宽度下的令牌框另有其事）；宽表在自己的横向滚动框里，不算
test("手机宽度：分析详情与候选方案的内容不超出屏宽", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of ["/capability/analyses", "/capability/analyses/p_fixture_delta_code", "/capability/analyses/p_fixture_gamma_code", "/capability/analyses/p_fixture_beta_code", "/capability/analyses/p_fixture_delta_code.dry", "/capability/candidates"]) {
    await page.goto(path);
    await expect(page.locator(".shell-status")).toContainText("已连接");
    await page.waitForTimeout(300);
    const over = await page.evaluate(() => {
      const w = document.documentElement.clientWidth;
      return [...document.querySelectorAll("#content *")].filter((e) => !e.closest(".rd-tbl, .an-tblwrap") && e.getBoundingClientRect().right > w + 1).map((e) => `${e.tagName}.${e.className}`).slice(0, 5);
    });
    expect(over, path).toEqual([]);
  }
});

test("后面几种停法只读：停在第 3 次确认、交接完成、预评估走完（地址带点号也能直达）", async ({ page }) => {
  await page.goto("/capability/analyses");
  await expect(page.locator("[data-an-run]")).toHaveCount(5);
  await page.click('[data-an-run="p_fixture_gamma_code"] .an-name a');
  await expect(page.locator('[data-an-gate="G3"]')).toContainText("第 3 次确认：映射与集成顺序");
  await expect(page.locator('[data-an-placement="C1"] .an-dtbl tbody tr').first()).toBeVisible();
  await expect(page.locator('[data-action="an-submit"]')).toHaveCount(0);
  await page.click("[data-an-steps] summary");
  await expect(page.locator("[data-an-steps] ol li").first()).toContainText("验收：");
  await page.click('[data-an-tab="report"]');
  await expect(page.locator("[data-an-report]")).toHaveCount(3);

  await page.goto("/capability/analyses/p_fixture_beta_code");
  await expect(page.locator('[data-an-done="handoff"]')).toContainText("已交接 · 1 个做法交给实现线");
  await expect(page.locator("[data-an-next]")).toContainText("import");
  await expect(page.locator('[data-an-step="S6"]')).toHaveClass(/done/);

  await page.goto("/capability/analyses/p_fixture_delta_code.dry");
  await expect(page.locator('[data-an-done="dry_run"]')).toContainText("预评估报告已出");
  await expect(page.locator("[data-an-dry-item]")).toHaveCount(3);
  await expect(page.locator('[data-an-step="G1"]')).toHaveClass(/skip/);
  await page.reload();
  await expect(page.locator("[data-an-dry-item]")).toHaveCount(3);
  await page.click('[data-an-tab="files"]');
  await page.click('[data-an-file="dry_run.json"] [data-action="an-file"]');
  await expect(page.locator("[data-an-artifact] pre")).toContainText("auto_picked");
});
