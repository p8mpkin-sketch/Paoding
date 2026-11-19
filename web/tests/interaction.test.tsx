// HT-2（提交体没有画像）、HT-6（三次点击到证据根）、HT-7（卡片过期时不能批准；r2 缺回退时卡面标出，能否批准听服务端）、HT-8（Hint 进不了前提与 about）。
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ApiError, newIdemKey } from "../src/api/client";
import { ops } from "../src/api/ops";
import type { ApprovalDisplay, ApprovalFields, CardResponse } from "../src/api/types";
import { buildOpen, draftFromTemplate, problemsOf } from "../src/model/wizard";
import { Wizard } from "../src/pages/Wizard";
import { ApprovalCard } from "../src/ui/ApprovalCard";
import { ExtensionDialog } from "../src/ui/ExtensionDialog";
import { aboutCandidates, HintInject, HintTraceCard } from "../src/ui/Hints";
import { Inspector } from "../src/ui/Inspector";
import { liveSession, pendingIntent, playToEnd, renderWith, rig, until, type Rig } from "./helpers";

afterEach(cleanup);

async function vmOf(r: Rig, pid = r.mock.demoPid) {
  const s = await liveSession(r, pid);
  const vm = s.getState().vm!;
  s.close();
  return vm;
}
const byTitle = (vm: Awaited<ReturnType<typeof vmOf>>, part: string) => vm.rows.find((x) => x.title.value.includes(part))!;

describe("HT-6 下钻", () => {
  it("观察类论断：选中之后再点两次就到 Artifact 卡，命令行与退出码在首行，哈希可本地校验", async () => {
    const r = rig();
    const vm = await vmOf(r);
    const fact = byTitle(vm, "首页是一个登录表单");
    let clicks = 1; // 第 1 次：在前沿里点这一行
    const { container } = renderWith(r, <Inspector vm={vm} nodeId={fact.id} />);
    await waitFor(() => expect(container.querySelector(".inspector")).not.toBeNull());
    // 路一：grounds 直接列在检视里，点一次就到采集记录
    const chips = [...container.querySelectorAll<HTMLElement>('.inspector [data-action="open-artifact"]')];
    const ground = chips.find((c) => !c.closest("details"))!;
    fireEvent.click(ground); clicks++;
    await waitFor(() => expect(container.querySelector('[data-class="exec"]')).not.toBeNull());
    expect(clicks).toBeLessThanOrEqual(3);
    // 路二：支持记录 → 判官输出，一共三次点击
    const verdict = container.querySelector('[data-action="open-support"]')!;
    fireEvent.click(verdict.querySelector("summary")!);
    fireEvent.click(verdict.querySelector('[data-action="open-artifact"]')!);
    await waitFor(() => expect(verdict.querySelector('[data-class="judge"] .evidence-first')).not.toBeNull());
    const box = container.querySelector('[data-class="exec"]')!;
    expect(box.querySelector(".evidence-first")!.textContent).toContain("http_get http://target:8080/");
    expect(box.querySelector(".evidence-first")!.textContent).toContain("退出码 0");
    fireEvent.click(box.querySelector('[data-action="local-verify"]')!);
    await waitFor(() => expect(box.querySelector('[data-verify="match"]')).not.toBeNull());
  });

  it("本地校验：服务端给的字节与登记的哈希不符时显示不一致", async () => {
    const r = rig();
    const vm = await vmOf(r);
    const fact = byTitle(vm, "首页是一个登录表单");
    const tampered: typeof fetch = async (input, init) => (String(input).includes("/v1/blobs/") ? new Response("被改过的字节") : r.fetch(input, init));
    const r2 = { ...r, cfg: { ...r.cfg, fetch: tampered } };
    const { createApi } = await import("../src/api/client");
    const { container } = renderWith({ ...r2, api: createApi(r2.cfg) }, <Inspector vm={vm} nodeId={fact.id} />);
    await waitFor(() => expect(container.querySelector('[data-action="open-artifact"]')).not.toBeNull());
    fireEvent.click(container.querySelector('[data-action="open-artifact"]')!);
    await waitFor(() => expect(container.querySelector('[data-action="local-verify"]')).not.toBeNull());
    fireEvent.click(container.querySelector('[data-action="local-verify"]')!);
    await waitFor(() => expect(container.querySelector('[data-verify="mismatch"]')).not.toBeNull());
  });

  it("推断类论断：沿前提链两次点击内到上游的 Artifact", async () => {
    const r = rig();
    const vm = await vmOf(r);
    const guess = byTitle(vm, "账号放在 8081");
    expect(guess.claim_type).toBe("inference");
    const { container } = renderWith(r, <Inspector vm={vm} nodeId={guess.id} />);
    await waitFor(() => expect(container.querySelector('[data-action="open-premise"]')).not.toBeNull());
    expect(container.querySelector('[data-evidence-root="none"]')).toBeNull();
    const premise = container.querySelector('[data-action="open-premise"]')!;
    fireEvent.click(premise.querySelector("summary")!);
    fireEvent.click(premise.querySelector('[data-action="open-artifact"]')!);
    await waitFor(() => expect(container.querySelector('[data-register="evidence"] .evidence-first')).not.toBeNull());
  });

  it("链上没有任何登记过的 Artifact：显式标无证据根", async () => {
    const r = rig();
    // 一条凭空的推断：没有前提，也没有 grounds
    r.mock.append(r.mock.demoPid, { kind: "adapter", id: "ad1", session: "l_x", role: "reason" }, "add_fact", { title: "答案串大概是八位", summary: "没有依据的猜测。", claim_type: "inference", premises: [], grounds: [] });
    const vm = await vmOf(r);
    const none = byTitle(vm, "答案串大概是八位");
    // 链级判定在服务端（裁决 005-4）：经过一条未达成的 Intent 也算链，它的上游有采集记录，所以不是无证据根
    const root = async (title: string) => (await r.api.node(byTitle(vm, title).id)) as { no_evidence_root?: boolean };
    expect((await root("拿到账号后登录即可见答案串")).no_evidence_root).toBe(false);
    expect((await root("答案串大概是八位")).no_evidence_root).toBe(true);
    expect((await root("账号放在 8081")).no_evidence_root).toBe(false);
    const { container } = renderWith(r, <Inspector vm={vm} nodeId={none.id} />);
    await waitFor(() => expect(container.querySelector('[data-evidence-root="none"]')).not.toBeNull());
    expect(container.querySelector('[data-register="evidence"]')).toBeNull();
  });

  it("目标的判据卡：裁决序列里失败的那次也在，候选按叙述显示", async () => {
    const r = rig();
    await playToEnd(r);
    const vm = await vmOf(r);
    const { container } = renderWith(r, <Inspector vm={vm} nodeId="goal" />);
    const verdicts = [...container.querySelectorAll("[data-verdict]")].map((e) => e.getAttribute("data-verdict"));
    expect(verdicts).toEqual(["fail", "pass"]);
    const last = container.querySelectorAll("[data-verdict]")[1];
    fireEvent.click(last.querySelector("summary")!);
    const chips = last.querySelectorAll<HTMLElement>('[data-action="open-artifact"]');
    fireEvent.click(chips[chips.length - 1]); // 候选
    await waitFor(() => expect(last.querySelector('[data-class="authored"]')).not.toBeNull());
    expect(last.querySelector('[data-class="authored"]')!.getAttribute("data-register")).toBe("narrative");
  });
});

describe("HT-7 审批卡", () => {
  it("批准带上所见的 seq 与 card_hash；估值只在折叠区", async () => {
    const r = rig();
    const pid = r.mock.demoPid;
    const intent = await pendingIntent(r, pid);
    const { container } = renderWith(r, <ApprovalCard pid={pid} intentId={intent} head={r.mock.head(pid)} canWrite />);
    await waitFor(() => expect(container.querySelector('[data-card="approval"]')).not.toBeNull());
    const est = container.querySelector('[data-register="estimate"]')!;
    expect(est.closest("details")).not.toBeNull();
    expect(est.closest("details")!.hasAttribute("open")).toBe(false);
    expect(container.querySelector(".scope-diff")!.textContent).toContain("+ net  target:8081");
    const hash = container.querySelector("[data-card-hash]")!.getAttribute("data-card-hash");
    const seenSeq = r.mock.globalHead();
    fireEvent.click(container.querySelector('[data-action="approve"]')!);
    await waitFor(() => expect(container.querySelector("[data-done]")).not.toBeNull());
    const post = r.fetch.calls.find((c) => c.method === "POST")!;
    const body = JSON.parse(post.body!) as { idem_key: string; ops: { op: string; body: { intent: string; decision: string; seen: { seq: number; card_hash: string } } }[] };
    expect(body.ops).toHaveLength(1);
    expect(body.ops[0].op).toBe("approve");
    expect(body.ops[0].body).toEqual({ intent, decision: "approve", seen: { seq: seenSeq, card_hash: hash } });
    expect(body.idem_key).toMatch(/.{8,}/);
  });

  it("卡片在查看期间变了：批准与拒绝都禁用，列出变了的字段，重新确认后才可批准", async () => {
    const r = rig();
    const pid = r.mock.demoPid;
    const intent = await pendingIntent(r, pid);
    let changed = false;
    const shifting: typeof fetch = async (input, init) => {
      const res = await r.fetch(input, init);
      if (!changed || !String(input).includes("/cards/approval/")) return res;
      const c = (await res.json()) as CardResponse<ApprovalFields, ApprovalDisplay>;
      c.card.fields.risk = "r2";
      c.card.fields.premises[0].disputed = true;
      c.card_hash = "f".repeat(64);
      c.display.rollback_declared = true;
      c.display.rollback = { src: "summary", register: "叙述", value: "恢复快照" };
      return new Response(JSON.stringify(c), { status: 200 });
    };
    const { createApi } = await import("../src/api/client");
    const cfg = { ...r.cfg, fetch: shifting };
    const rr = { ...r, cfg, api: createApi(cfg) };
    const view = renderWith(rr, <ApprovalCard pid={pid} intentId={intent} head={10} canWrite />);
    const q = (sel: string) => view.container.querySelector<HTMLButtonElement>(sel);
    await waitFor(() => expect(q('[data-action="approve"]')).not.toBeNull());
    expect(q('[data-action="approve"]')!.disabled).toBe(false);
    const first = q("[data-card-hash]")!.getAttribute("data-card-hash");

    changed = true;
    const { ServicesContext } = await import("../src/app/context");
    view.rerender(<ServicesContext.Provider value={{ api: rr.api, cfg }}><ApprovalCard pid={pid} intentId={intent} head={11} canWrite /></ServicesContext.Provider>);
    await waitFor(() => expect(q("[data-stale]")).not.toBeNull());
    expect(q('[data-action="approve"]')!.disabled).toBe(true);
    expect(q('[data-action="deny"]')!.disabled).toBe(true);
    expect(q("[data-card-hash]")!.getAttribute("data-card-hash")).toBe(first); // 还显示着人看过的那张
    const paths = [...view.container.querySelectorAll("[data-stale] li")].map((e) => e.textContent);
    expect(paths).toContain("risk");
    expect(paths.some((p) => p!.startsWith("premises"))).toBe(true);

    fireEvent.click(q('[data-action="reconfirm"]')!);
    await waitFor(() => expect(q("[data-stale]")).toBeNull());
    expect(q("[data-card-hash]")!.getAttribute("data-card-hash")).toBe("f".repeat(64));
    expect(q('[data-action="approve"]')!.disabled).toBe(false);
  });

  it("服务端兜底：seen.card_hash 不等即 stale_view，并附上最新的卡", async () => {
    const r = rig();
    const pid = r.mock.demoPid;
    const intent = await pendingIntent(r, pid);
    const err = await r.api.propose(pid, [ops.approve(intent, { seq: 1, card_hash: "0".repeat(64) })], newIdemKey()).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe("stale_view");
    expect((err as ApiError).extra).toMatchObject({ card: { kind: "approval", target: intent } });
    expect((await r.api.work(pid)).items.some((x) => x.kind === "human")).toBe(true); // 没有被批准
  });

  it("r2 而没有回退声明：卡面标出未声明回退，能否批准只听 approve_enabled（裁决 004-8、005-3）", async () => {
    const r = rig();
    const intent = await pendingIntent(r, "demo-2");
    const { container } = renderWith(r, <ApprovalCard pid="demo-2" intentId={intent} head={r.mock.head("demo-2")} canWrite />);
    await waitFor(() => expect(container.querySelector('[data-action="approve"]')).not.toBeNull());
    expect(container.querySelector("[data-no-rollback]")!.textContent).toContain("r2");
    expect(container.querySelector('[data-flag="no-rollback"]')!.textContent).toContain("未声明回退");
    expect(container.querySelector<HTMLButtonElement>('[data-action="approve"]')!.disabled).toBe(false);
    // 拒绝要写理由
    const deny = container.querySelector<HTMLButtonElement>('[data-action="deny"]')!;
    expect(deny.disabled).toBe(true);
    fireEvent.change(container.querySelector(".deny textarea")!, { target: { value: "没有回退方案" } });
    expect(deny.disabled).toBe(false);
  });

  it("图服务说 approve_enabled=false：批准禁用并说明", async () => {
    const r = rig();
    const intent = await pendingIntent(r, "demo-2");
    const closed: typeof fetch = async (input, init) => {
      const res = await r.fetch(input, init);
      if (!String(input).includes("/cards/approval/")) return res;
      const c = (await res.json()) as CardResponse<ApprovalFields, ApprovalDisplay>;
      c.display.approve_enabled = false;
      return new Response(JSON.stringify(c), { status: 200 });
    };
    const { createApi } = await import("../src/api/client");
    const cfg = { ...r.cfg, fetch: closed };
    const { container } = renderWith({ ...r, cfg, api: createApi(cfg) }, <ApprovalCard pid="demo-2" intentId={intent} head={r.mock.head("demo-2")} canWrite />);
    await waitFor(() => expect(container.querySelector('[data-action="approve"]')).not.toBeNull());
    expect(container.querySelector<HTMLButtonElement>('[data-action="approve"]')!.disabled).toBe(true);
    expect(container.querySelector("[data-approve-disabled]")).not.toBeNull();
  });

  it("不在链头或不是实时：两个按钮都禁用", async () => {
    const r = rig();
    const pid = r.mock.demoPid;
    const intent = await pendingIntent(r, pid);
    const { container } = renderWith(r, <ApprovalCard pid={pid} intentId={intent} head={r.mock.head(pid)} canWrite={false} />);
    await waitFor(() => expect(container.querySelector('[data-action="approve"]')).not.toBeNull());
    expect(container.querySelector<HTMLButtonElement>('[data-action="approve"]')!.disabled).toBe(true);
    fireEvent.change(container.querySelector(".deny textarea")!, { target: { value: "x" } });
    expect(container.querySelector<HTMLButtonElement>('[data-action="deny"]')!.disabled).toBe(true);
  });

  it("续期门：没有默认选项；图服务没启用这张卡时如实显示", async () => {
    const r = rig();
    const { container } = renderWith(r, <ExtensionDialog pid="demo-2" head={r.mock.head("demo-2")} canWrite />);
    await waitFor(() => expect(container.querySelector('[data-card="extension"]')).not.toBeNull());
    expect([...container.querySelectorAll<HTMLInputElement>('input[type="radio"]')].filter((x) => x.checked)).toHaveLength(0);
    expect(container.querySelector<HTMLButtonElement>('[data-action="extension-submit"]')!.disabled).toBe(true);
    cleanup();
    const off: typeof fetch = async () => new Response(JSON.stringify({ ok: false, code: "not_enabled", detail: "extension 卡随 M1 落地" }), { status: 404 });
    const { createApi } = await import("../src/api/client");
    const cfg = { ...r.cfg, fetch: off };
    const v = renderWith({ ...r, cfg, api: createApi(cfg) }, <ExtensionDialog pid="demo-2" head={1} canWrite />);
    await waitFor(() => expect(v.container.querySelector("[data-not-enabled]")).not.toBeNull());
  });
});

describe("HT-8 Hint", () => {
  it("about 的候选只有论断与 Intent，没有 Hint", async () => {
    const r = rig();
    const vm = await vmOf(r);
    expect(vm.hints.length).toBeGreaterThan(0);
    const ids = aboutCandidates(vm.rows).map((x) => x.id);
    for (const h of vm.hints) expect(ids).not.toContain(h.id);
    const { container } = renderWith(r, <HintInject pid={vm.pid} rows={vm.rows} canWrite />);
    const options = [...container.querySelectorAll("[data-about] option")].map((o) => o.getAttribute("value"));
    expect(options.filter(Boolean).sort()).toEqual([...ids].sort());
    expect(options.some((v) => v?.startsWith("h_"))).toBe(false);
    // 视图模型里 Hint 不在节点行里，也没有任何节点以 Hint 为前提
    for (const row of vm.rows) for (const p of row.premises) expect(vm.hints.some((h) => h.id === p)).toBe(false);
    expect(vm.layout.edges.filter((e) => e.kind === "premise").some((e) => e.from.startsWith("h_") || e.to.startsWith("h_"))).toBe(false);
  });

  it("注入走提议通道，按人的语域显示，追溯两列都写明是关联", async () => {
    const r = rig();
    const pid = r.mock.demoPid;
    const vm = await vmOf(r);
    const { container } = renderWith(r, <HintInject pid={pid} rows={vm.rows} canWrite />);
    fireEvent.change(container.querySelector("textarea")!, { target: { value: "  先核对归档接口  " } });
    fireEvent.change(container.querySelector("[data-about]")!, { target: { value: vm.rows[0].id } });
    fireEvent.click(container.querySelector('[data-action="hint-submit"]')!);
    await waitFor(() => expect(container.textContent).toContain("已注入"));
    const post = r.fetch.calls.find((c) => c.method === "POST")!;
    expect(post.url).toBe(`/v1/problems/${pid}/proposals`);
    expect((JSON.parse(post.body!) as { ops: unknown[] }).ops).toEqual([{ op: "hint", body: { text: "先核对归档接口", about: vm.rows[0].id } }]);
    cleanup();

    const vm2 = await vmOf(r);
    const old = vm2.hints[0];
    const t = renderWith(r, <HintTraceCard pid={pid} hintId={old.id} seq={vm2.seq} ts={old.ts} rows={vm2.rows} canWrite />);
    await waitFor(() => expect(t.container.querySelector('[data-card="hint-trace"]')).not.toBeNull());
    expect(t.container.querySelector('[data-register="human"]')!.textContent).toContain("别在 8080 上枚举了");
    expect(t.container.querySelector('[data-trace="temporal"]')!.textContent).toContain("+");
    expect(t.container.querySelector('[data-trace="exposure"]')).not.toBeNull();
    expect(t.container.textContent).toContain("不是因果");
  });
});

describe("HT-2 开题向导", () => {
  it("提交体没有画像字段；未标风险的规则按 r2 提交", () => {
    const d = { ...draftFromTemplate(null), id: "t1", title: "题", statement: "目标", judge: "exact_match", usd: "2", wall_s: "600" };
    d.materials[0] = { ...d.materials[0], name: "s.txt", hash: "ab".repeat(32), size: 9, media_type: "text/plain" };
    d.scope = [{ resource: "net", pattern: "h:1", actions: "connect", risk: "" }];
    expect(problemsOf(d).flat()).toEqual([]);
    const open = buildOpen(d);
    const text = JSON.stringify(open);
    expect(text).not.toMatch(/profile|reversibility/);
    expect(open.problem.scope[0].risk).toBe("r2");
    expect(open.problem.origin).toEqual({ statement_ref: "$0", materials: [] });
    expect(open.materials).toEqual([{ op: "register_artifact", body: { class: "input", hash: "ab".repeat(32), size: 9, media_type: "text/plain" } }]);
    expect(Object.keys(open.problem).sort()).toEqual(["budget", "env", "goal", "judges", "origin", "scope", "title"]);
  });

  it("表单里没有可填的画像；画像预览来自服务端；走完四步能开出题", async () => {
    const r = rig();
    const { container } = renderWith(r, <Wizard />);
    await waitFor(() => expect(container.querySelector("[data-wizard]")).not.toBeNull());
    const q = <T extends Element = HTMLInputElement>(sel: string) => container.querySelector<T>(sel)!;
    const fields = () => [...container.querySelectorAll("input, select, textarea")].map((e) => `${e.getAttribute("data-field") ?? ""}${e.getAttribute("name") ?? ""}`);
    const step = (i: number) => fireEvent.click(container.querySelectorAll(".steps button")[i]);
    const seen = new Set<string>();

    fireEvent.change(q('[data-field="id"]'), { target: { value: "web-1" } });
    fireEvent.change(q('[data-field="title"]'), { target: { value: "网页开的题" } });
    fireEvent.change(q('[data-field="statement"]'), { target: { value: "提交答案串" } });
    const file = new File(["题面正文"], "s.txt", { type: "text/plain" });
    fireEvent.change(q('[data-slot="题面"]'), { target: { files: [file] } });
    await waitFor(() => expect(container.querySelector(".hash-badge")).not.toBeNull());
    fields().forEach((f) => seen.add(f));
    step(1);
    fields().forEach((f) => seen.add(f));
    step(2);
    const rule = container.querySelectorAll<HTMLInputElement>('[data-rule="0"] input');
    fireEvent.change(rule[1], { target: { value: "target:8080" } });
    fields().forEach((f) => seen.add(f));
    step(3);
    fields().forEach((f) => seen.add(f));
    for (const f of seen) expect(f).not.toMatch(/profile|reversibility|info/);

    await waitFor(() => expect(container.querySelector('[data-axis="reversibility"]')).not.toBeNull());
    expect(r.fetch.calls.some((c) => c.method === "POST" && c.url === "/v1/profile/preview")).toBe(true);
    expect(q<HTMLPreElement>("[data-problem-json]").textContent).not.toMatch(/profile/);

    await waitFor(() => expect(q<HTMLButtonElement>('[data-action="open-problem"]').disabled).toBe(false));
    fireEvent.click(q('[data-action="open-problem"]'));
    await until(() => r.mock.pids().includes("web-1"), "题目开出来");
    const open = r.fetch.calls.find((c) => c.method === "POST" && c.url === "/v1/problems")!;
    const body = JSON.parse(open.body!) as { id: string; ops: { op: string }[] };
    expect(body.id).toBe("web-1");
    expect(body.ops.map((o) => o.op)).toEqual(["register_artifact", "open_problem"]);
    const st = await r.api.status("web-1");
    expect(st.problem.profile.reversibility).toBe("r0"); // 画像是服务端按 scope 推出来的
    expect(screen.queryByText(/提交失败|被拒/)).toBeNull();
  });

  it("没有令牌：写操作在发出请求之前就被拦下", async () => {
    const r = rig(null);
    const before = r.fetch.calls.length;
    const err = await r.api.propose(r.mock.demoPid, [ops.hintAdd("x")], newIdemKey()).catch((e: unknown) => e);
    expect((err as ApiError).code).toBe("forbidden_op");
    expect(r.fetch.calls.length).toBe(before);
    expect((await r.api.problems()).items.length).toBeGreaterThan(0); // 读不需要令牌
  });
});
