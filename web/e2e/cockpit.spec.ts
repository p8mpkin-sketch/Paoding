// 浏览器里的驾驶舱、审批卡、时间轴回放与窄屏（P2-2）。后端是假后端（e2e/server.ts），剧本由测试推进。
import { expect, test, type Page } from "@playwright/test";
import { KAITI } from "../mock/kaiti";

const TOKEN = "mock-human-token";

test.beforeEach(async ({ page, request }) => {
  await request.post("/__e2e/reset");
  // 令牌只在本标签页的 sessionStorage，带到期时间（与界面里填写的效果相同）
  await page.addInitScript((t) => {
    sessionStorage.setItem("paoding.human_token", JSON.stringify({ token: t, expires_at: Date.now() + 3600_000 }));
  }, TOKEN);
});

async function openCockpit(page: Page, pid: string) {
  await page.goto("/today");
  await page.locator(`[data-problem="${pid}"] a`).first().click();
  await expect(page.locator(".cockpit")).toBeVisible();
  await expect(page.locator("[data-conn-label]")).toHaveText("实时");
}

test("驾驶舱：顶栏分主次，事件到来时视图跟着走，一条事件至多一次 snapshot 请求", async ({ page, request }) => {
  const snaps: string[] = [];
  page.on("request", (r) => { if (r.url().includes("/snapshot")) snaps.push(r.url()); });
  await openCockpit(page, "demo-1");
  await expect(page.locator(".tk-head [data-terminal]")).toBeVisible();
  await expect(page.locator(".tk-rail .cost")).toBeVisible();          // 花费在右栏
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

test("工作区：会话流列出 status 里的会话，按 H 打开“给出指导”并聚焦输入框，Esc 收起", async ({ page }) => {
  await openCockpit(page, "demo-2");
  await expect(page.locator("[data-sessions]")).toBeVisible();
  const done = page.locator(".sess-done");
  if (await done.count()) { await done.locator("summary").click(); await expect(done.locator("[data-lease]").first()).toBeVisible(); }
  await page.locator("body").click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("h");
  await expect(page.locator('[data-card="hint-inject"] textarea')).toBeFocused();
  await page.keyboard.type("hh");                                       // 输入框里按 H 不再触发快捷键
  await expect(page.locator('[data-card="hint-inject"] textarea')).toHaveValue("hh");
  await page.locator('[data-card="hint-inject"] textarea').blur();
  await page.keyboard.press("Escape");
  await expect(page.locator('[data-card="hint-inject"]')).toHaveCount(0);
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
  await expect(page.locator(".seq-input")).toBeHidden();               // 不常用的定位手段默认收起
  await page.locator("[data-timeline-more] summary").click();
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

test("窄屏（手机宽度）：右栏落到正文下面，结构一栏里选中节点后检视在下方；没有横向滚动", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openCockpit(page, "demo-1");
  const col = (await page.locator(".tk-col").boundingBox())!;
  const rail = (await page.locator(".tk-rail").boundingBox())!;
  expect(rail.y).toBeGreaterThanOrEqual(col.y + col.height - 1);
  await page.locator('[data-task-tab="struct"]').click();
  await page.locator('[data-action="select-node"]').first().click();
  await expect(page.locator(".cockpit")).toHaveAttribute("data-inspect", "node");
  const main = (await page.locator(".tk-struct .main").boundingBox())!;
  const right = (await page.locator(".tk-struct .right").boundingBox())!;
  expect(right.y).toBeGreaterThanOrEqual(main.y + main.height - 1);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("宽屏：正文与右栏并排；结构一栏没选节点时检视收窄，选中后展开", async ({ page }) => {
  await openCockpit(page, "demo-1");
  const col = (await page.locator(".tk-col").boundingBox())!;
  const rail = (await page.locator(".tk-rail").boundingBox())!;
  expect(rail.x).toBeGreaterThanOrEqual(col.x + col.width - 1);
  await page.locator('[data-task-tab="struct"]').click();
  for (const c of [".tk-struct .main", ".tk-struct .right"]) await expect(page.locator(c)).toBeVisible();
  const narrow = (await page.locator(".tk-struct .right").boundingBox())!.width;
  expect(narrow).toBeLessThanOrEqual(240);
  await page.locator('[data-action="select-node"]').first().click();
  await expect(page.locator(".cockpit")).toHaveAttribute("data-inspect", "node");
  expect((await page.locator(".tk-struct .right").boundingBox())!.width).toBeGreaterThan(narrow + 60);
});

test("开放道任务页：结果一栏、依据抽屉、采纳要逐条确认四顾", async ({ page }) => {
  await openCockpit(page, "demo-6");
  await expect(page.locator("[data-status]")).toHaveAttribute("data-status", "look");
  await expect(page.locator("[data-answer]")).toContainText("LangGraph");
  await page.locator("[data-claim] [data-ref]").first().click();
  await expect(page.locator("[data-evidence]")).toContainText("python repro/crash_test.py");
  await page.keyboard.press("Escape");
  await expect(page.locator("[data-evidence]")).toHaveCount(0);
  // 引用的资料（资料库第二期）：与执行记录分开标示，抽屉里是资料名、位置与当时的原文
  await expect(page.locator("[data-claims-count]")).toContainText("6 条里 4 条有执行记录；1 条引用了资料");
  await page.locator('[data-claim][data-cited="true"] [data-ref-class="knowledge"]').click();
  await expect(page.locator("[data-evidence] [data-knowledge]")).toContainText("回滚用上一个标签重新发布");
  await expect(page.locator("[data-evidence] [data-kn-note]")).toHaveText("这是你给的资料里的话，没有在这次任务里验证。");
  await page.keyboard.press("Escape");
  await page.locator('[data-action="adopt-delivery"]').click();
  const ok = page.locator('[data-action="confirm-feedback"]');
  await expect(ok).toBeDisabled();
  for (const b of await page.locator("[data-four]").all()) await b.check();
  await ok.click();
  await expect(page.locator("[data-feedback]")).toHaveAttribute("data-feedback", "adopted");
  await expect(page.locator('[data-field="follow-up"]')).toHaveCount(0);   // 关闭后不再能追问
});

test("图：键盘聚焦节点、Enter 检视，+ − 缩放", async ({ page }) => {
  await openCockpit(page, "demo-1");
  await page.locator('[data-task-tab="struct"]').click();
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

test("总览：进行中卡片、等你处理、主题切换；手机宽度只留待审批与进行中", async ({ page }) => {
  await page.goto("/today");
  await expect(page.locator(".run-card").first()).toBeVisible();
  await expect(page.locator("[data-waiting]")).toBeVisible();
  await expect(page.locator(".dash-stats")).toBeVisible();
  await page.locator('[data-field="theme"]').selectOption("dark");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark"); // 本机偏好
  await page.setViewportSize({ width: 390, height: 800 });
  await expect(page.locator(".dash-stats")).toBeHidden();
  await expect(page.locator(".run-card").first()).toBeVisible();
});

test("待办：侧栏数量与页面一致，去处理进工作区并定位节点", async ({ page }) => {
  await page.goto("/");
  await page.locator('[data-nav="inbox"]').click();
  await expect(page).toHaveURL(/\/inbox$/);
  const items = page.locator("[data-inbox-item]");
  await expect(items.first()).toBeVisible();
  await expect(page.locator("[data-inbox-analysis]").first()).toBeVisible(); // 方案分析的确认点也算进待办
  const n = (await items.count()) + (await page.locator("[data-inbox-analysis]").count());
  await expect(page.locator('[data-nav="inbox"] .ct')).toHaveText(new RegExp(`^${n}\\D`));
  await items.first().locator("a").click();
  await expect(page).toHaveURL(/\/p\/.+node=/);
  await expect(page.locator(".cockpit")).toBeVisible();
});

test("任务库：筛选写进 URL，刷新后仍在", async ({ page }) => {
  await page.goto("/problems");
  await expect(page.locator("[data-list] [data-problem]").first()).toBeVisible();
  await page.locator('[data-tab="running"]').click();
  await expect(page).toHaveURL(/terminal=running/);
  await page.reload();
  await expect(page.locator('[data-tab="running"]')).toHaveAttribute("aria-selected", "true");
  for (const t of await page.locator("[data-list] [data-terminal]").all()) await expect(t).toHaveAttribute("data-terminal", "running");
});

test("一句话新建：回车起草，确认卡核对出处，创建后进工作区", async ({ page }) => {
  await page.goto("/new");
  await page.locator('[data-field="kaiti-text"]').fill(KAITI.drafts.practice.text);
  await expect(page.locator('[data-kaiti-extract] [data-kind="addr"]')).toContainText("q1:8080");
  await page.locator('[data-field="kaiti-text"]').press("Enter");
  await expect(page.locator("[data-kaiti-card] [data-eligible]")).toContainText("零确认尚未放行");
  await expect(page.locator("[data-kaiti-card]")).not.toContainText("PD-7Q2M9XKD");
  await page.locator('[data-action="open-problem"]').click();
  await expect(page).toHaveURL(new RegExp(`/p/${KAITI.drafts.practice.out.pid}`));
  await expect(page.locator(".cockpit")).toBeVisible();
});

test("向导：四步走完，文字材料与初始指导，创建后进工作区；草稿刷新不丢", async ({ page }) => {
  await page.goto("/new/advanced");
  await page.locator('[data-field="id"]').fill("e2e-wiz");
  await page.locator('[data-field="title"]').fill("浏览器里开的题");
  await page.locator('[data-field="statement"]').fill("提交答案串");
  await page.reload();
  await expect(page.locator("[data-restored]")).toBeVisible();
  await expect(page.locator('[data-field="title"]')).toHaveValue("浏览器里开的题");
  await page.locator('[data-material="0"] [data-kind="text"]').click();
  await page.locator('[data-text-slot="0"]').fill("题面：登录后页面上有一串答案");
  await expect(page.locator(".sheet-title")).toHaveText("浏览器里开的题"); // 右侧任务单随填随变
  await page.locator('[data-action="next"]').click();
  await page.locator('[data-action="next"]').click();
  await page.locator('[data-rule="0"] input').nth(1).fill("target:8080");
  await page.locator('[data-step-tab="3"]').click();
  await page.locator('[data-field="hint"]').fill("先看登录页源码");
  await expect(page.locator("[data-profile-preview] [data-axis]")).toHaveCount(3);
  await page.locator('[data-action="open-problem"]').click();
  await expect(page).toHaveURL(/\/p\/e2e-wiz/);
  await expect(page.locator(".cockpit")).toBeVisible();
});

test("任务库：克隆一个任务进向导，id 留空、判据与 scope 已预填", async ({ page }) => {
  await page.goto("/problems");
  await page.locator('[data-list] [data-problem] [data-action="row-menu"]').first().click();
  await page.locator('[data-menu="clone"]').click();
  await expect(page).toHaveURL(/\/new\/advanced\?from=/);
  await expect(page.locator("[data-cloned-from]")).toBeVisible();
  await expect(page.locator('[data-field="id"]')).toHaveValue("");
  await page.locator('[data-step-tab="2"]').click();
  await expect(page.locator('[data-rule="0"] input').nth(1)).not.toHaveValue("");
});

test("运行时扩权：横幅点开扩权卡，批准后横幅的数字减一，时间轴多一个扩权节点", async ({ page }) => {
  await openCockpit(page, "demo-4");
  const banner = page.locator('[data-banner="scope"]');
  await expect(banner).toContainText("等你批准访问 2 个地址");
  await banner.click();
  const card = page.locator('[data-card="scope"]');
  await expect(card.locator("[data-risk-source]").first()).toBeVisible();
  const before = await page.locator('.tick[data-tick="S"]').count();
  await card.locator('[data-action="approve"]').click();
  await expect(banner).toContainText("等你批准访问 1 个地址");
  await expect(page.locator('.tick[data-tick="S"]')).toHaveCount(before + 1);
});

test("任务列表：删除进回收站，30 天内可恢复；账不动", async ({ page }) => {
  await page.goto("/tasks");
  const row = page.locator('[data-list] [data-group-of="end"]').first();
  const pid = await row.getAttribute("data-problem");
  await row.locator('[data-action="row-menu"]').click();
  await page.locator('[data-menu="delete"]').click();
  await expect(page.locator("[data-confirm-delete]")).toContainText("30 天内可以恢复");
  await page.locator('[data-action="confirm-delete"]').click();
  await expect(page.locator(`[data-list] [data-problem="${pid}"]`)).toHaveCount(0);
  await page.locator('[data-tab="trash"]').click();
  await expect(page.locator(`[data-list] [data-problem="${pid}"]`)).toBeVisible();
  await page.locator(`[data-problem="${pid}"] [data-action="row-menu"]`).click();
  await page.locator('[data-menu="restore"]').click();
  await expect(page.locator(`[data-list] [data-problem="${pid}"]`)).toHaveCount(0);
  await page.locator('[data-tab="all"]').click();
  await expect(page.locator(`[data-list] [data-problem="${pid}"]`)).toBeVisible();
});

test("知识页资料：粘贴一段文字导入，几轮后可用并能查到", async ({ page }) => {
  await page.goto("/knowledge");
  await expect(page.locator('[data-job="s_runbk01"]')).toBeVisible();
  await page.locator('[data-action="kn-import"]').click();
  await page.locator('[data-mode="text"]').click();
  await page.locator('[data-field="kn-name"]').fill("值班约定");
  await page.locator('[data-field="kn-text"]').fill("交接时写清楚未关的告警和正在做的变更。");
  await page.locator('[data-action="kn-start"]').click();
  await expect(page.locator("[data-kn-import]")).toHaveCount(0);
  const row = page.locator("[data-source]", { hasText: "值班约定" });
  await expect(row).toBeVisible();
  await expect(row).toHaveAttribute("data-live", "1", { timeout: 15_000 }); // 每 2 秒一轮，一轮推进一步
  await page.locator('[data-field="kn-query"]').fill("未关的告警");
  await page.locator('[data-action="kn-search"]').click();
  await expect(page.locator("[data-hit]", { hasText: "值班约定" }).first()).toBeVisible();
});

test("知识页资料：选文件后列在抽屉里，导入后出现作业", async ({ page }) => {
  await page.goto("/knowledge");
  await page.locator('[data-action="kn-import"]').click();
  await page.locator('[data-field="kn-files"]').setInputFiles([{ name: "告警规则.yaml", mimeType: "text/yaml", buffer: Buffer.from("延迟超过 300ms 报警\n") }]);
  await expect(page.locator('[data-picked="告警规则.yaml"]')).toBeVisible();
  await page.locator('[data-action="kn-start"]').click();
  await expect(page.locator("[data-kn-import]")).toHaveCount(0);
  await expect(page.locator("[data-source]", { hasText: "告警规则.yaml" })).toBeVisible();
});
