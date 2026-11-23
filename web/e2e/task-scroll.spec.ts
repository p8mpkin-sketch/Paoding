// 任务页的滚动与结果一栏的排版（cz 2026-11-21 实测报告的问题）：
// 原来外壳把任务页主区设成不滚（overflow: hidden），页内又没有自己的滚动区，超出一屏的内容用滚轮滚不到。
// 这里用真滚轮验：四栏都滚得到底、标签条吸顶、时间轴与输入条不动、内容短时不多出空白、右栏自己滚、
// 中等宽度与手机宽度各有一个滚动区；宽表横向滚动且首列不动、键盘能滚。
import { expect, test, type Page } from "@playwright/test";

const TOKEN = "mock-human-token";

test.beforeEach(async ({ page, request }) => {
  await request.post("/__e2e/reset");
  await page.addInitScript((t) => {
    sessionStorage.setItem("paoding.human_token", JSON.stringify({ token: t, expires_at: Date.now() + 3600_000 }));
  }, TOKEN);
});

async function open(page: Page, pid: string) {
  await page.goto(`/p/${pid}`);
  await expect(page.locator("[data-conn-label]")).toHaveText("实时");
}
const box = (page: Page) => page.locator("[data-task-scroll]");
const metrics = (page: Page) => box(page).evaluate((e) => ({ top: e.scrollTop, max: e.scrollHeight - e.clientHeight, y: e.getBoundingClientRect().top, bottom: e.getBoundingClientRect().bottom }));
/** 整个文档不许比视口长或宽（任务页自己管滚动）。 */
const pageGrew = (page: Page) => page.evaluate(() => ({ h: document.documentElement.scrollHeight - innerHeight, w: document.documentElement.scrollWidth - innerWidth }));
async function wheel(page: Page, over: string, dy: number) {
  const b = (await page.locator(over).first().boundingBox())!;
  await page.mouse.move(b.x + Math.min(b.width / 2, 300), b.y + Math.min(b.height / 2, 200));
  await page.mouse.wheel(0, dy);
  await page.waitForTimeout(150);
}

test("长结果：滚轮能一路滚到最后一节；标签条吸在顶上；时间轴与输入条留在原地；文档本身不变长", async ({ page }) => {
  await open(page, "demo-8");
  await expect(page.locator("[data-answer] [data-prose-table]").first()).toBeVisible();
  const m0 = await metrics(page);
  expect(m0.max).toBeGreaterThan(1500);                                    // 内容远多于一屏
  const dock0 = (await page.locator("[data-dock]").boundingBox())!;
  const tl0 = (await page.locator("[data-timeline]").boundingBox())!;
  await expect(page.locator("[data-unverified]")).not.toBeInViewport();
  await wheel(page, "[data-task-scroll]", 600);
  const m1 = await metrics(page);
  expect(m1.top).toBe(600);
  // 标签条吸顶：它的上沿贴着滚动区的上沿
  expect(Math.abs((await page.locator(".tk-tabs").boundingBox())!.y - m1.y)).toBeLessThanOrEqual(1);
  await wheel(page, "[data-task-scroll]", 100_000);
  const m2 = await metrics(page);
  expect(m2.top).toBe(m2.max);
  await expect(page.locator("[data-unverified] li").last()).toBeInViewport({ ratio: 1 });
  // 最后一节下面只有面板自己的留白，没有大片空白
  const last = (await page.locator("[data-unverified]").boundingBox())!;
  expect(m2.bottom - (last.y + last.height)).toBeLessThan(48);
  // 底部两条没有跟着滚
  expect((await page.locator("[data-dock]").boundingBox())!.y).toBe(dock0.y);
  expect((await page.locator("[data-timeline]").boundingBox())!.y).toBe(tl0.y);
  expect(await pageGrew(page)).toEqual({ h: 0, w: 0 });
});

test("四栏都在同一个滚动区里滚得到底；标签条吸顶时换栏，新的一栏从头看起且标签条不跳走", async ({ page }) => {
  await page.setViewportSize({ width: 1360, height: 620 });
  await open(page, "demo-6");
  for (const tab of ["result", "steps", "struct", "files"]) {
    await page.locator(`[data-task-tab="${tab}"]`).click();
    await expect(page.locator('[role="tabpanel"]')).toHaveAttribute("data-pane", tab);
    await page.waitForTimeout(200);
    const m = await metrics(page);
    expect(m.max, tab).toBeGreaterThan(0);
    await wheel(page, "[data-task-scroll]", 100_000);
    const end = await metrics(page);
    expect(end.top, tab).toBe(end.max);
    // 面板的最后一个元素完整露出来
    const tail = await page.locator('[role="tabpanel"]').evaluate((p, bottom) => p.getBoundingClientRect().bottom <= bottom + 1, end.bottom);
    expect(tail, tab).toBe(true);
    // 这一栏够长（滚得过标签条原来的位置）时标签条吸在顶上；不够长时它留在原位，底下也不补空白
    const stuck = await page.locator('[role="tabpanel"]').evaluate((p, top) => top >= (p as HTMLElement).offsetTop - 37, end.top);
    if (stuck) expect(Math.abs((await page.locator(".tk-tabs").boundingBox())!.y - end.y), tab).toBeLessThanOrEqual(1);
    else expect(end.top, tab).toBe(end.max);
  }
  await page.locator('[data-task-tab="files"]').click();
  await wheel(page, "[data-task-scroll]", 100_000);
  // 停在“文件”栏的底部，换到“结果”：标签条还在顶上，面板从头开始
  await page.locator('[data-task-tab="result"]').click();
  const m = await metrics(page);
  expect(Math.abs((await page.locator(".tk-tabs").boundingBox())!.y - m.y)).toBeLessThanOrEqual(1);
  const paneTop = (await page.locator('[role="tabpanel"]').boundingBox())!.y;
  const tabs = (await page.locator(".tk-tabs").boundingBox())!;
  expect(Math.abs(paneTop - (tabs.y + tabs.height))).toBeLessThanOrEqual(1);
  expect(await pageGrew(page)).toEqual({ h: 0, w: 0 });
});

test("内容短的任务：没有多出来的滚动与空白页，时间轴贴着视口底", async ({ page }) => {
  await open(page, "demo-3");
  await expect(page.locator("[data-result]")).toBeVisible();
  expect((await metrics(page)).max).toBe(0);
  const tl = (await page.locator(".tk-col > .bottom").boundingBox())!;
  expect(Math.abs(tl.y + tl.height - 900)).toBeLessThanOrEqual(1);
  expect(await pageGrew(page)).toEqual({ h: 0, w: 0 });
});

test("右栏自己滚，不带着正文走；各节从上往下排，不被拉开", async ({ page }) => {
  await page.setViewportSize({ width: 1360, height: 480 });
  await open(page, "demo-6");
  const rail = page.locator(".tk-rail");
  const max = await rail.evaluate((e) => e.scrollHeight - e.clientHeight);
  expect(max).toBeGreaterThan(0);
  await wheel(page, ".tk-rail", 100_000);
  expect(await rail.evaluate((e) => e.scrollTop)).toBe(max);
  expect((await metrics(page)).top).toBe(0);
  await expect(page.locator(".tk-rail > :last-child")).toBeInViewport();
  // 视口很高时各节之间只有固定的间距（原来会被拉开成一大片空白）
  await page.setViewportSize({ width: 1360, height: 2000 });
  const gaps = await rail.evaluate((e) => [...e.children].map((c) => c.getBoundingClientRect()).map((r, i, a) => (i ? r.top - a[i - 1].bottom : 0)));
  expect(Math.max(...gaps)).toBeLessThanOrEqual(19);
});

test("中等宽度（右栏排到下面）：整页一个滚动区，滚得到右栏；输入条吸在底部", async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 700 });
  await open(page, "demo-8");
  const pageBox = page.locator(".cockpit.task");
  await wheel(page, ".cockpit.task", 500);
  expect(await pageBox.evaluate((e) => e.scrollTop)).toBe(500);
  expect((await page.locator(".tk-tabs").boundingBox())!.y).toBeLessThanOrEqual(1);
  const dock = (await page.locator("[data-dock]").boundingBox())!;
  expect(Math.abs(dock.y + dock.height - 700)).toBeLessThanOrEqual(1);
  await wheel(page, ".cockpit.task", 100_000);
  await expect(page.locator(".tk-rail > :last-child")).toBeInViewport();
  expect(await pageGrew(page)).toEqual({ h: 0, w: 0 });
});

test("手机宽度：整个页面滚动，标签条吸顶，滚得到最后；没有横向滚动", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, "demo-8");
  await expect(page.locator("[data-answer] [data-prose-table]").first()).toBeVisible();
  await page.mouse.move(200, 400);
  await page.mouse.wheel(0, 900);
  await page.waitForTimeout(150);
  expect(await page.evaluate(() => scrollY)).toBe(900);
  expect((await page.locator(".tk-tabs").boundingBox())!.y).toBeLessThanOrEqual(1);
  await page.mouse.wheel(0, 100_000);
  await page.waitForTimeout(150);
  await expect(page.locator(".tk-rail > :last-child")).toBeInViewport();
  expect((await pageGrew(page)).w).toBeLessThanOrEqual(0);
});

test("宽表：横向滚动时首列与表头不动；键盘能聚焦并滚动；整页不出现横向滚动", async ({ page }) => {
  await open(page, "demo-8");
  const region = page.locator('[data-prose-table][data-wide="true"] [role="region"]');
  await region.scrollIntoViewIfNeeded();
  const over = await region.evaluate((e) => e.scrollWidth - e.clientWidth);
  expect(over).toBeGreaterThan(0);
  const first = region.locator("tbody th").first();
  const x0 = (await first.boundingBox())!.x;
  await region.focus();
  await expect(region).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await page.waitForTimeout(200);
  expect(await region.evaluate((e) => e.scrollLeft)).toBeGreaterThan(0);
  await region.evaluate((e) => { e.scrollLeft = e.scrollWidth; });
  expect(Math.abs((await first.boundingBox())!.x - x0)).toBeLessThanOrEqual(1);
  await expect(region.locator("tbody tr").first().locator("td").last()).toBeInViewport();
  expect(await pageGrew(page)).toEqual({ h: 0, w: 0 });
});

test("结果一栏：概要点过去跳到那一节；“要你补的”把焦点送到输入框；摘要值点开看全、复制的是完整的值", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await open(page, "demo-8");
  await page.locator('[data-jump="unverified"]').click();
  await expect(page.locator("[data-unverified]")).toBeFocused();
  await expect(page.locator("[data-unverified] h2")).toBeInViewport({ ratio: 1 });
  // 跳过去的小节标题没有被吸顶的标签条盖住
  const tabs = (await page.locator(".tk-tabs").boundingBox())!;
  expect((await page.locator("[data-unverified] h2").boundingBox())!.y).toBeGreaterThanOrEqual(tabs.y + tabs.height);
  await page.locator('[data-jump="needs"]').click();
  await expect(page.locator("[data-needs]")).toBeFocused();
  await page.locator('[data-action="reply-needs"]').click();
  await expect(page.locator('[data-field="follow-up"]')).toBeFocused();
  const chip = page.locator("[data-answer] [data-hash]").first();
  await chip.scrollIntoViewIfNeeded();
  await expect(chip.locator(".pr-hash-t")).toHaveText("3fa2c1d0…9e4b");
  await chip.locator(".pr-hash-v").click();
  await expect(chip.locator(".pr-hash-t")).toHaveText("3fa2c1d09b7e4a6f8d2c5e1b0a9f7c3d4e6b8a1c2d5f7e9b0c3a6d8f1e4b9e4b");
  await chip.locator('[data-action="copy"]').click();
  await expect(chip.locator('[data-action="copy"]')).toHaveAttribute("data-copied", "ok");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("3fa2c1d09b7e4a6f8d2c5e1b0a9f7c3d4e6b8a1c2d5f7e9b0c3a6d8f1e4b9e4b");
  expect(await pageGrew(page)).toEqual({ h: 0, w: 0 });                    // 摘要值展开后也不撑出横向滚动
});
