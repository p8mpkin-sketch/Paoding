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

test("预评估表：未过的说明占整行，三种宽度下都读得顺；都过时表宽不变", async ({ page }) => {
  const long = "K1（特征 write_outside_reducer 映到 T4，冲突栏里没有对应的冲突记录）；K8（核心机制第 2 步的原语“对照”在前提栏里找不到它依赖的输入，融合栏写的涌现能力与步骤对不上）；K3（代价栏里写的额外调用次数与实现线索里的不一致）";
  const url = "/capability/analyses/p_fixture_delta_code.dry";
  const WIDTHS = [1280, 1366, 390];
  const measure = () => page.evaluate(() => {
    const wrap = document.querySelector<HTMLElement>(".an-tblwrap")!;
    const table = document.querySelector<HTMLElement>("[data-an-dry]")!;
    const row = document.querySelector<HTMLElement>("[data-an-dry-detail]");
    const cell = row?.querySelector<HTMLElement>("td") ?? null;
    const above = row?.previousElementSibling as HTMLElement | null;
    const below = row?.nextElementSibling as HTMLElement | null;
    const top = (tr: HTMLElement | null) => (tr ? parseFloat(getComputedStyle(tr.children[0]!).borderTopWidth) : -1);
    return {
      wrap: wrap.clientWidth,
      scrolls: wrap.scrollWidth > wrap.clientWidth + 1,
      table: Math.round(table.getBoundingClientRect().width),
      detail: cell ? Math.round(cell.getBoundingClientRect().width) : 0,
      clipped: cell ? cell.scrollWidth > cell.clientWidth + 1 || cell.scrollHeight > cell.clientHeight + 1 || getComputedStyle(cell).overflow !== "visible" : false,
      text: cell?.innerText.replace(/\s+/g, "") ?? "",
      lineAbove: top(row), lineBelow: top(below), lineOfItem: top(above),
      check: document.querySelector<HTMLElement>('[data-an-dry-item="C2"] [data-an-dry-check]')!.innerText.trim(),
      checkWidth: Math.round(document.querySelector<HTMLElement>('[data-an-dry-item="C2"] [data-an-dry-check]')!.getBoundingClientRect().width),
    };
  });
  // 一、都过：桌面两种宽度下表正好占满外框、不出滚动条（与改动前相同）；记下各宽度的表宽作对照
  const allOk: Record<number, Awaited<ReturnType<typeof measure>>> = {};
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(url);
    await expect(page.locator('[data-an-dry-check="ok"]')).toHaveCount(3);
    await expect(page.locator("[data-an-dry-detail]")).toHaveCount(0);
    allOk[width] = await measure();
    if (width !== 390) {
      expect(allOk[width]!.scrolls, String(width)).toBe(false);
      expect(allOk[width]!.table, String(width)).toBe(allOk[width]!.wrap);
    }
  }
  // 二、C2 未过且说明很长
  await page.route("**/v1/analyses/p_fixture_delta_code.dry", async (route) => {
    const res = await route.fetch();
    const d = await res.json();
    d.dry_run.items = d.dry_run.items.map((it: { candidate: string }) => (it.candidate === "C2" ? { ...it, unpassed: long } : it));
    await route.fulfill({ response: res, json: d });
  });
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(url);
    await expect(page.locator('[data-an-dry-detail="C2"]')).toBeVisible();
    const bad = await measure();
    expect(bad.text, String(width)).toBe(`未过的检验${long}`.replace(/\s+/g, ""));   // 一字不少
    expect(bad.check, String(width)).toBe("未过");                                   // 格子里只有徽标
    expect(bad.checkWidth, String(width)).toBeLessThan(90);                          // 这一列只有一个徽标的宽
    expect(bad.clipped, String(width)).toBe(false);
    expect(bad.detail, String(width)).toBeGreaterThanOrEqual(bad.table * 0.9);       // 说明行占满表宽
    expect(bad.lineAbove, String(width)).toBe(0);                                    // 与上面那一行之间没有线
    expect(bad.lineOfItem, String(width)).toBeGreaterThan(0);                        // 做法行自己的上边线照常
    expect(bad.lineBelow, String(width)).toBeGreaterThan(0);                         // 与下一行之间照常有线
    if (width === 390) expect(Math.abs(bad.table - allOk[width]!.table), String(width)).toBeLessThanOrEqual(20);
    else {
      expect(bad.scrolls, String(width)).toBe(false);                                // 桌面：不出滚动条
      expect(bad.table, String(width)).toBe(allOk[width]!.table);
    }
  }
});
