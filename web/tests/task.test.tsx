// 任务页（v5 第三期）：流程条、开放道的结果一栏、采纳与不采纳、追问、叫停、过程与文件、右栏的按会话花费。
import { cleanup, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { newIdemKey } from "../src/api/client";
import { ops } from "../src/api/ops";
import { flowOf, type FlowInput } from "../src/model/flow";
import { Cockpit } from "../src/pages/Cockpit";
import { renderWith, rig } from "./helpers";

afterEach(cleanup);

const PID = "demo-6"; // 开放道，已交付，等人看
const $ = (c: HTMLElement, sel: string) => c.querySelector<HTMLElement>(sel);
const base: FlowInput = { accept: "open", closed: false, terminal: null, active: [], started: false, todo: [], deliveries: 0, lastDeliverySeq: 0, lastHadSelfCheck: false, lastFollowUpSeq: 0, judged: false };
const states = (x: Partial<FlowInput>) => Object.fromEntries(flowOf({ ...base, ...x }).map((s) => [s.key, s.state]));

describe("执行流程条（纯函数）", () => {
  it("开放道：还没会话在“理解任务”；在做在“动手做”；交付后在“你来看”；追问之后回到“动手做”；复核一直未开启", () => {
    expect(states({})).toMatchObject({ understand: "cur", work: "todo", review: "off" });
    expect(states({ started: true, active: ["solve"] })).toMatchObject({ understand: "done", work: "cur" });
    expect(states({ started: true, deliveries: 1, lastDeliverySeq: 9, lastHadSelfCheck: true, todo: ["delivered"] })).toMatchObject({ work: "done", self: "done", deliver: "done", review: "off", you: "cur" });
    expect(states({ started: true, deliveries: 1, lastDeliverySeq: 9, lastHadSelfCheck: false })).toMatchObject({ self: "todo", you: "cur" });
    expect(states({ started: true, active: ["solve"], deliveries: 1, lastDeliverySeq: 9, lastFollowUpSeq: 12 })).toMatchObject({ work: "cur", you: "todo" });
    expect(states({ closed: true, terminal: "delivered", deliveries: 1, lastDeliverySeq: 9, lastHadSelfCheck: true })).toMatchObject({ you: "done", review: "off" });
  });
  it("判定道与人工验收道：判定器判定 / 结构检查，最后一步各不相同", () => {
    expect(flowOf({ ...base, accept: "judge", started: true, active: ["judge"] }).map((s) => s.word)).toEqual(["理解任务", "动手做", "判定器判定", "结束"]);
    expect(states({ accept: "judge", started: true, active: ["judge"] })).toMatchObject({ judge: "cur" });
    expect(states({ accept: "human", started: true, todo: ["acceptance"] })).toMatchObject({ you: "cur" });
  });
});

describe("开放道任务页（假后端 demo-6）", () => {
  it("默认打开“结果”：答案、没经判定的说明、依据（无记录的标出来）、自检、没验证的；点依据打开执行记录", async () => {
    const r = rig();
    const { container } = renderWith(r, <Cockpit pid={PID} asOf={null} node={null} />);
    await waitFor(() => expect($(container, "[data-open-result]")).not.toBeNull());
    expect($(container, '[data-status]')!.getAttribute("data-status")).toBe("look");
    expect($(container, '[data-flow-step="you"]')!.getAttribute("data-state")).toBe("cur");
    await waitFor(() => expect($(container, "[data-answer]")!.textContent).toContain("LangGraph"));
    expect($(container, '[data-verdict="self"]')!.textContent).toContain("没有经过独立判定");
    expect(container.querySelectorAll("[data-claim]")).toHaveLength(5);
    expect(container.querySelectorAll('[data-claim][data-supported="false"]')).toHaveLength(1);
    expect($(container, "[data-claims] h2")!.textContent).toContain("5 条里 4 条有执行记录");
    expect(container.querySelectorAll('[data-self-check] [data-check="fail"]')).toHaveLength(1);
    expect(container.querySelectorAll("[data-unverified] li")).toHaveLength(2);
    fireEvent.click($(container, "[data-claim] [data-ref]")!);
    await waitFor(() => expect(document.querySelector('[data-evidence] [data-class="exec"]')).not.toBeNull());
    expect(document.querySelector("[data-evidence]")!.textContent).toContain("python repro/crash_test.py --fw langgraph");
    expect(container.querySelectorAll("[data-split]").length).toBeGreaterThan(0); // 右栏按会话的花费
  });

  it("采纳：确认框里逐条确认四顾，关闭任务并记反馈 adopted，终态 delivered", async () => {
    const r = rig();
    const { container } = renderWith(r, <Cockpit pid={PID} asOf={null} node={null} />);
    const adopt = await waitFor(() => { const b = $(container, '[data-action="adopt-delivery"]') as HTMLButtonElement; expect(b?.disabled).toBe(false); return b; });
    fireEvent.click(adopt);
    const ok = await waitFor(() => { const b = document.querySelector<HTMLButtonElement>('[data-action="confirm-feedback"]'); expect(b).not.toBeNull(); return b!; });
    await waitFor(() => expect(document.querySelectorAll("[data-four]").length).toBeGreaterThan(0));
    expect(ok.disabled).toBe(true);
    document.querySelectorAll<HTMLInputElement>("[data-four]").forEach((x) => fireEvent.click(x));
    await waitFor(() => expect(ok.disabled).toBe(false));
    fireEvent.click(ok);
    await waitFor(async () => {
      const st = await r.api.status(PID);
      expect(st.problem.closed).toBe(true);
      expect(st.problem.terminal).toBe("delivered");
      expect(st.goal.feedback).toBe("adopted");
    });
    const body = JSON.parse(String(r.fetch.calls.filter((c) => c.url === `/v1/problems/${PID}/proposals`).at(-1)!.body));
    expect(body.ops[0]).toMatchObject({ op: "close_problem", body: { feedback: "adopted" } });
    expect(body.ops[0].body).not.toHaveProperty("terminal");
  });

  it("接着问：发出 follow_up（带所见链头），任务回到动手做，结果里写明追问了什么", async () => {
    const r = rig();
    const { container } = renderWith(r, <Cockpit pid={PID} asOf={null} node={null} />);
    const box = await waitFor(() => { const i = $(container, '[data-field="follow-up"]') as HTMLInputElement; expect(i?.disabled).toBe(false); return i; });
    fireEvent.change(box, { target: { value: "把 Postgres 后端也测一下" } });
    fireEvent.click($(container, '[data-action="send-follow-up"]')!);
    await waitFor(async () => expect((await r.api.status(PID)).goal.follow_ups?.map((u) => u.text.value)).toEqual(["把 Postgres 后端也测一下"]));
    const body = JSON.parse(String(r.fetch.calls.filter((c) => c.url === `/v1/problems/${PID}/proposals`).at(-1)!.body));
    expect(body.ops[0].op).toBe("follow_up");
    expect(body.ops[0].body.seen.seq).toBeGreaterThan(0);
    await waitFor(() => expect($(container, "[data-asked]")).not.toBeNull());
    expect($(container, '[data-flow-step="work"]')!.getAttribute("data-state")).toBe("cur");
    expect((await r.api.work(PID)).items.some((w) => w.kind === "solve")).toBe(true); // 追问之后再派求解
  });

  it("追问的预算：追加后超过单题硬顶，或剩余不够再跑一轮而没附追加，都回 over_budget", async () => {
    const r = rig();
    const head = (await r.api.status(PID)).as_of;
    await expect(r.api.propose(PID, [ops.followUp("再来", { seq: head }, 50_000)], newIdemKey())).rejects.toMatchObject({ code: "over_budget" });
    const ok = await r.api.propose(PID, [ops.followUp("再来", { seq: head }, 500)], newIdemKey());
    expect(ok).toHaveLength(1);
    expect((await r.api.budget(PID)).cap.usd_milli).toBe(2500);
  });

  it("叫停只用于开放道；叫停过一次再叫被拒", async () => {
    const r = rig();
    await expect(r.api.propose("demo-1", [ops.halt()], newIdemKey())).rejects.toMatchObject({ code: "conflict" });
    await r.api.propose(PID, [ops.halt("人叫停")], newIdemKey());
    expect((await r.api.status(PID)).goal.halted).toBeTruthy();
    await expect(r.api.propose(PID, [ops.halt()], newIdemKey())).rejects.toMatchObject({ code: "conflict" });
  });

  it("过程与文件：执行的命令按时间排，产物列成表；打开一个看登记记录", async () => {
    const r = rig();
    const { container } = renderWith(r, <Cockpit pid={PID} asOf={null} node={null} />);
    await waitFor(() => expect($(container, '[data-task-tab="steps"]')).not.toBeNull());
    fireEvent.click($(container, '[data-task-tab="steps"]')!);
    await waitFor(() => expect(container.querySelectorAll("[data-step]").length).toBeGreaterThan(5));
    expect($(container, "[data-steps]")!.textContent).toContain("python repro/crash_test.py --fw crewai");
    expect($(container, "[data-steps]")!.textContent).toContain("交出结果（完整回答），附 5 条主张");
    fireEvent.click($(container, '[data-task-tab="files"]')!);
    await waitFor(() => expect(container.querySelectorAll("[data-file]").length).toBeGreaterThan(5));
    fireEvent.click($(container, '[data-file] [data-action="open-file"]')!);
    await waitFor(() => expect(document.querySelector("[data-evidence] [data-artifact]")).not.toBeNull());
  });
});
