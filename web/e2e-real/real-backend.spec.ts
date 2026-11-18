// 浏览器连真实图服务（不是 mock）：开题、渲染、SSE 推送。后端由 playwright.real.config.ts 起 scripts/run.py。
// 人的写操作经 HTTP 提交（与 scripts/e2e/drive.py 相同的线格式）；页面不刷新，只靠 /stream 推送跟上。
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { REAL_HOME } from "../playwright.real.config";

const PID = "real-1";
const STATEMENT = "在执行环境里算出 6 乘 7 的结果，把结果原样提交。";
const token = () => readFileSync(join(REAL_HOME, "human.token"), "utf-8").trim();
const auth = () => ({ Authorization: `Bearer ${token()}` });
let n = 0;

async function propose(request: APIRequestContext, ops: unknown[]) {
  const r = await request.post(`/v1/problems/${PID}/proposals`, { headers: auth(), data: { idem_key: `real-${++n}-${Date.now()}`, ops } });
  const out = await r.json();
  expect(out.ok, JSON.stringify(out)).toBe(true);
  return out.results as { id?: string }[];
}

async function openProblem(request: APIRequestContext) {
  const bytes = Buffer.from(STATEMENT, "utf-8");
  const put = await request.put("/v1/blobs", { headers: { ...auth(), "Content-Type": "application/octet-stream" }, data: bytes });
  expect(put.ok()).toBe(true);
  const { hash } = await put.json();
  const answer = createHash("sha256").update("42").digest("hex");
  const r = await request.post("/v1/problems", {
    headers: auth(),
    data: {
      id: PID,
      idem_key: `open-${PID}`,
      ops: [
        { op: "register_artifact", body: { hash, size: bytes.length, media_type: "text/plain; charset=utf-8", class: "input" } },
        {
          op: "open_problem",
          body: {
            title: "算出 6×7（真实图服务）",
            origin: { statement_ref: "$0", materials: [] },
            goal: { statement: "提交 6 乘 7 的结果", check: { judge_id: "exact_match", expect: { sha256: answer } }, max_attempts: 3, accept: "judge" },
            scope: [{ resource: "workspace", pattern: "*", actions: ["read", "write"], risk: "r0" }],
            budget: { usd_milli: 5000, wall_s: 3600, verify_share: 0.2, bootstrap_share: 0.3 },
            env: { base: "basic", baseline_ref: "basic@1" },
            judges: ["exact_match", "replay"],
          },
        },
      ],
    },
  });
  const out = await r.json();
  expect(out.ok, JSON.stringify(out)).toBe(true);
}

const row = (page: Page, id: string | undefined) => page.locator(`[data-frontier="all"] [data-node-row="${id}"]`);

async function seq(page: Page) {
  return Number(await page.locator(".cockpit").getAttribute("data-seq"));
}

test("真实图服务：开题后驾驶舱渲染，人写入的 Intent 经 SSE 推到页面，不刷新", async ({ page, request }) => {
  await openProblem(request);
  await page.addInitScript((t) => {
    sessionStorage.setItem("paoding.human_token", JSON.stringify({ token: t, expires_at: Date.now() + 3600_000 }));
  }, token());

  const streams: string[] = [];
  let navigations = 0;
  page.on("request", (r) => { if (r.url().includes("/stream")) streams.push(r.url()); });
  page.on("framenavigated", (f) => { if (f === page.mainFrame()) navigations++; });

  // 总览里列着这道题（数据来自真图服务的 /v1/problems）
  await page.goto("/");
  await expect(page.locator(`[data-problem="${PID}"]`).first()).toBeVisible();

  await page.goto(`/p/${PID}`);
  await expect(page.locator(".cockpit")).toBeVisible();
  await expect(page.locator("[data-conn-label]")).toHaveText("实时");
  expect(streams.length).toBeGreaterThan(0);                      // 页面订了 SSE
  const seq0 = await seq(page);
  expect(seq0).toBeGreaterThan(0);
  const nav0 = navigations;

  // 人写入两条 Intent：页面不刷新，靠推送跟上，序号前进、节点出现
  const [{ id: i1 }] = await propose(request, [
    { op: "add_intent", body: { title: "先在工作区里把乘法算一遍", summary: "", premises: [], risk: "r0", budget: { usd_milli: 100 } } },
  ]);
  await expect(row(page, i1)).toBeVisible();
  await expect(row(page, i1)).toContainText("先在工作区里把乘法算一遍");
  const seq1 = await seq(page);
  expect(seq1).toBeGreaterThan(seq0);

  const [{ id: i2 }] = await propose(request, [
    { op: "add_intent", body: { title: "再核对一次结果", summary: "", premises: [], risk: "r0", budget: { usd_milli: 100 } } },
  ]);
  await expect(row(page, i2)).toBeVisible();
  expect(await seq(page)).toBeGreaterThan(seq1);

  // Hint 也经推送到达
  const [{ id: h }] = await propose(request, [{ op: "hint", body: { text: "答案是一个两位数" } }]);
  await expect(page.locator(`[data-hint-row="${h}"]`).first()).toContainText("答案是一个两位数");

  // 图视图画出这两个节点
  await page.locator('[data-action="graph-always"]').check();
  await page.locator('[data-action="tab-graph"]').click();
  await expect(page.locator(`[data-graph-node="${i1}"]`)).toBeVisible();
  await expect(page.locator(`[data-graph-node="${i2}"]`)).toBeVisible();

  expect(navigations).toBe(nav0);                                 // 全程没有重新加载页面
  await expect(page.locator("[data-conn-label]")).toHaveText("实时");
});
