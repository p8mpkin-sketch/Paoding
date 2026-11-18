// 浏览器里的驾驶舱、审批卡、时间轴回放与窄屏（P2-2）。后端是假后端（e2e/server.ts），剧本由测试推进。
import { expect, test, type Page } from "@playwright/test";

const TOKEN = "mock-human-token";

test.beforeEach(async ({ page, request }) => {
  await request.post("/__e2e/reset");
  // 令牌只在本标签页的 sessionStorage，带到期时间（与界面里填写的效果相同）
  await page.addInitScript((t) => {
    sessionStorage.setItem("paoding.human_token", JSON.stringify({ token: t, expires_at: Date.now() + 3600_000 }));
  }, TOKEN);
});

async function openCockpit(page: Page, pid: string) {
  await page.goto("/");
  await page.locator(`[data-problem="${pid}"] a`).first().click();
  await expect(page.locator(".cockpit")).toBeVisible();
  await expect(page.locator("[data-conn-label]")).toHaveText("实时");
}

test("驾驶舱：顶栏分主次，事件到来时视图跟着走，一条事件至多一次 snapshot 请求", async ({ page, request }) => {
  const snaps: string[] = [];
  page.on("request", (r) => { if (r.url().includes("/snapshot")) snaps.push(r.url()); });
  await openCockpit(page, "demo-1");
  const primary = page.locator(".topbar-primary");
  await expect(primary.locator("[data-terminal]")).toBeVisible();
  await expect(primary.locator(".cost")).toBeVisible();
  await expect(page.locator("[data-goal-attempts]")).toBeHidden();       // 次要信息收在“详情”里
  await page.locator('[data-topbar="secondary"] > summary').click();
  await expect(page.locator("[data-goal-attempts]")).toBeVisible();

  // 演示题停在等人审批：先在卡上批准，剧本才能往下走
  await page.locator("[data-todo-item] button").filter({ hasText: "审批" }).first().click();
  await page.locator('[data-card="approval"] [data-action="approve"]').click();
  await expect(page.locator("[data-todo-item]").filter({ hasText: "审批" })).toHaveCount(0);
  await page.waitForTimeout(300);
  const seq0 = Number(await page.locator(".cockpit").getAttribute("data-seq"));
  const before = snaps.length;
  let moved = 0;
  for (let i = 0; i < 3; i++) if ((await (await request.post("/__e2e/step")).json()).moved) moved++;
  expect(moved).toBeGreaterThan(0);
  await expect(page.locator(".cockpit")).toHaveAttribute("data-seq", String(seq0 + moved));
  await page.waitForTimeout(300);
  expect(snaps.length - before).toBeLessThanOrEqual(moved);
  expect(snaps.slice(before).every((u) => u.includes("parts="))).toBe(true);
});

test("审批卡：r2 缺回退时卡面标出，批准后待办消失", async ({ page }) => {
  await openCockpit(page, "demo-2");
  const item = page.locator("[data-todo-item]").filter({ hasText: "审批" }).first();
  await expect(item).toBeVisible();
  const before = await page.locator("[data-todo-item]").count();
  await item.locator("button").click();
  const card = page.locator('[data-card="approval"]');
  await expect(card).toBeVisible();
  await expect(card.locator('[data-flag="no-rollback"]')).toContainText("未声明回退");
  const approve = card.locator('[data-action="approve"]');
  await expect(approve).toBeEnabled();                                      // 能否批准只听 approve_enabled
  await approve.click();
  await expect(page.locator("[data-todo-item]")).toHaveCount(before - 1);
  await expect(page.locator("[data-todo-item]").filter({ hasText: "审批" })).toHaveCount(0);
});

test("时间轴回放：跳到早先的序号，写操作禁用，链接带 as_of；回到实时", async ({ page }) => {
  await openCockpit(page, "demo-1");
  const head = Number(await page.locator(".cockpit").getAttribute("data-seq"));
  const target = Math.max(1, head - 5);
  await page.locator(".seq-input").fill(String(target));
  await page.getByRole("button", { name: "跳到" }).click();
  await expect(page).toHaveURL(new RegExp(`as_of=${target}`));
  await expect(page.locator(".cockpit")).toHaveAttribute("data-conn", "replay");
  await expect(page.locator("[data-timeline-pos]")).toContainText(`回放于 seq=${target}`);
  await expect(page.locator("[data-readonly-note]")).toContainText("回放中");
  // 刷新页面得到同一个回放（链接可分享）
  await page.reload();
  await expect(page.locator("[data-timeline-pos]")).toContainText(`回放于 seq=${target}`);
  await page.getByRole("button", { name: "回到实时" }).click();
  await expect(page.locator("[data-conn-label]")).toHaveText("实时");
  await expect(page).not.toHaveURL(/as_of=/);
});

test("窄屏（< 1024px）：一栏显示，按钮切换面板，选中节点跳到检视", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openCockpit(page, "demo-1");
  const sw = page.locator(".panel-switch");
  await expect(sw).toBeVisible();
  await expect(page.locator(".main")).toBeVisible();
  await expect(page.locator(".left")).toBeHidden();
  await expect(page.locator(".right")).toBeHidden();
  await page.locator('[data-panel-switch="left"]').click();
  await expect(page.locator(".left")).toBeVisible();
  await expect(page.locator(".main")).toBeHidden();
  await page.locator('[data-panel-switch="main"]').click();
  await page.locator('[data-action="select-node"]').first().click();
  await expect(page.locator(".right")).toBeVisible();
  await expect(page.locator(".main")).toBeHidden();
  // 没有横向滚动
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("宽屏：三栏并排，面板切换按钮不显示", async ({ page }) => {
  await openCockpit(page, "demo-1");
  await expect(page.locator(".panel-switch")).toBeHidden();
  for (const c of [".left", ".main", ".right"]) await expect(page.locator(c)).toBeVisible();
});

test("图：键盘聚焦节点、Enter 检视，+ − 缩放", async ({ page }) => {
  await openCockpit(page, "demo-1");
  await page.locator('[data-action="graph-always"]').check();
  await page.locator('[data-action="tab-graph"]').click();
  const vp = page.locator("[data-graph-viewport]");
  await vp.focus();
  await page.keyboard.press("+");
  await expect(page.locator("[data-zoom]")).toHaveAttribute("data-zoom", "1.25");
  await page.keyboard.press("0");
  await expect(page.locator("[data-zoom]")).toHaveAttribute("data-zoom", "1.00");
  const box = (await vp.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  const scrollY = await page.evaluate(() => window.scrollY);
  await page.mouse.wheel(0, -200);
  await expect(page.locator("[data-zoom]")).toHaveAttribute("data-zoom", "1.25");     // 滚轮缩放
  expect(await page.evaluate(() => window.scrollY)).toBe(scrollY);                   // 页面不跟着滚
  await page.keyboard.press("0");
  await page.keyboard.press("Tab");
  const focused = await page.evaluate(() => document.activeElement?.getAttribute("data-graph-node"));
  expect(focused).toBeTruthy();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`node=${focused}`));
});
