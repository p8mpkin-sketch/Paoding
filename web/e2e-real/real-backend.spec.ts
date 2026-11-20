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

  // 今日看板里列着这道题（数据来自真图服务的 /v1/problems）
  await page.goto("/today");
  await expect(page.locator(`[data-problem="${PID}"]`).first()).toBeVisible();

  await page.goto(`/p/${PID}`);
  await expect(page.locator(".cockpit")).toBeVisible();
  await expect(page.locator("[data-conn-label]")).toHaveText("实时");
  await page.locator('[data-task-tab="struct"]').click();             // 前沿与图在“结构”一栏
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

// ---- 人工验收（宪章 D3、02 §3.3；地图 Q23）：真图服务 + 真判官运行器（结构检查）+ 网页的验收卡 ----

const HPID = "real-human-1";

async function putInput(request: APIRequestContext, text: string) {
  const bytes = Buffer.from(text, "utf-8");
  const put = await request.put("/v1/blobs", { headers: { ...auth(), "Content-Type": "application/octet-stream" }, data: bytes });
  expect(put.ok()).toBe(true);
  const { hash } = await put.json();
  return { op: "register_artifact", body: { hash, size: bytes.length, media_type: "text/plain; charset=utf-8", class: "input" } };
}

async function proposeTo(request: APIRequestContext, pid: string, ops: unknown[]) {
  const r = await request.post(`/v1/problems/${pid}/proposals`, { headers: auth(), data: { idem_key: `real-${++n}-${Date.now()}`, ops } });
  const out = await r.json();
  expect(out.ok, JSON.stringify(out)).toBe(true);
  return out.results as { id?: string }[];
}

test("真实全栈：人工验收的任务交付后由结构检查给读数，人在验收卡上逐条判，图服务以 accepted 关闭", async ({ page, request }) => {
  const r = await request.post("/v1/problems", {
    headers: auth(),
    data: {
      id: HPID,
      idem_key: `open-${HPID}`,
      ops: [
        await putInput(request, "帮我调研一下主流的智能体框架，写一份对比。"),
        {
          op: "open_problem",
          body: {
            title: "框架对比（人工验收）",
            origin: { statement_ref: "$0", materials: [] },
            goal: {
              statement: "写一份主流智能体框架的对比", check: { judge_id: "structure_check", expect: { format: "text", min_bytes: 20 } }, max_attempts: 3, accept: "human",
              acceptance: [
                { text: "帮我调研一下主流的智能体框架，写一份对比。", src: "span" },
                { text: "对比覆盖至少三个框架，并附上对比表", src: "human", needs: "artifact" },
              ],
            },
            scope: [{ resource: "workspace", pattern: "*", actions: ["read", "write"], risk: "r0" }],
            budget: { usd_milli: 5000, wall_s: 3600, verify_share: 0.2, bootstrap_share: 0.3 },
            env: { base: "basic", baseline_ref: "basic@1" },
            judges: ["structure_check"],
          },
        },
      ],
    },
  });
  const opened = await r.json();
  expect(opened.ok, JSON.stringify(opened)).toBe(true);
  await page.addInitScript((t) => {
    sessionStorage.setItem("paoding.human_token", JSON.stringify({ token: t, expires_at: Date.now() + 3600_000 }));
  }, token());
  await page.goto(`/p/${HPID}`);
  await expect(page.locator("[data-conn-label]")).toHaveText("实时");

  // 交付：候选与对比表（人给的 input 类），请判官做结构检查；判官运行器在后台领租约、出裁决
  const [{ id: cand }, { id: table }] = await proposeTo(request, HPID, [
    await putInput(request, "# 框架对比\n\nA、B、C 三个框架在编排、工具调用、记忆三方面的对比……\n"),
    await putInput(request, "| 框架 | 编排 | 工具调用 |\n| A | 图 | 有 |\n| B | 链 | 有 |\n| C | 角色 | 有 |\n"),
  ]);
  await proposeTo(request, HPID, [{ op: "request_judge", body: { target: "goal", judge_id: "structure_check", candidate: cand } }]);

  // 结构检查只给读数：Goal 不到 E3、不关题，待办里出现“人工验收”
  const todo = page.locator(`[data-todo-item="acceptance:${HPID}"] button`);
  await expect(todo).toBeVisible({ timeout: 20_000 });
  await todo.click();
  const card = page.locator('[data-card="acceptance"]');
  await expect(card.locator("[data-deliverable]")).toContainText("只是读数");
  await expect(card.locator("[data-accept-item]")).toHaveCount(2);

  await card.locator('[data-accept-item="a1"] [data-verdict="pass"]').check();
  await card.locator('[data-accept-item="a2"] [data-verdict="pass"]').check();
  await expect(card.locator('[data-action="accept-submit"]')).toBeDisabled();       // a2 要附交付物
  await card.locator('[data-ref="a2"]').fill(table!);
  // 关题三步不可跳（Q21、AC9.2）：四顾没逐条确认时“验收通过”不可用，并指出是哪一项
  await expect(card.locator('[data-action="accept-submit"]')).toBeDisabled();
  await expect(card.locator("[data-missing]")).toContainText("四顾还没确认：closeout_review");
  await card.locator('[data-four="closeout_review"]').check();
  await card.locator('[data-action="accept-submit"]').click();

  // 图服务的后续：以 accepted 关题（待办随之清空）；结果页首行写人工验收，不写“已证明”
  await expect(page.locator("[data-result-head]")).toContainText("终态 accepted", { timeout: 15_000 });
  await expect(page.locator("[data-result-head]")).toContainText("根结论等级上限 E0");
  await expect(todo).toHaveCount(0);
  await expect(page.locator("[data-result-authority]")).toContainText("判定来源：人工验收");
  await expect(page.locator("[data-result]")).not.toContainText("已证明");
  const st = await (await request.get(`/v1/problems/${HPID}/status`, { headers: auth() })).json();
  expect(st.problem.terminal).toBe("accepted");
  const ev = (await (await request.get(`/v1/problems/${HPID}/events`, { headers: auth() })).json()).events.find((e: { kind: string }) => e.kind === "accept");
  expect(ev.body.closeout).toEqual(["closeout_review"]);
  expect(st.goal.accept_log[0]).toMatchObject({ decision: "accept", checks: [{ id: "a1", verdict: "pass" }, { id: "a2", verdict: "pass", ref: table }] });

  // 读数页：accepted 只进人工验收一行，不并进 solved
  await page.goto("/readings");
  const human = page.locator('[data-by-authority] [data-authority="human"]');
  await expect(human).toContainText("人工验收");
  const tot = (await (await request.get("/v1/problems", { headers: auth() })).json()).totals;
  expect(tot.by_authority.human.accepted).toBe(1);
  expect(tot.solved).toBe(tot.by_authority.local.solved);
});
