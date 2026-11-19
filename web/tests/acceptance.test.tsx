// 人工验收（宪章 D3、02 §3.3；地图 Q23）：逐条判、绑定收尾卡；全部过才 accepted，有不过只能拒收。
// 读数按判定来源分列：accepted 只在人工验收一行，不并进 solved。
import { cleanup, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { KAITI } from "../mock/kaiti";
import { submitVetted } from "../src/app/submit";
import { stationsOf } from "../src/model/stations";
import { AcceptanceCard, buildChecks } from "../src/ui/AcceptanceCard";
import { ResultReport } from "../src/ui/ResultReport";
import { liveSession, renderWith, rig, type Rig } from "./helpers";

afterEach(cleanup);

/** 用录下的“人工验收”确认卡创建任务，再让结构检查给一次通过的读数；返回一份 exec 类产物供验收项引用。 */
async function delivered(r: Rig): Promise<{ pid: string; run: string }> {
  const { pid } = await submitVetted(r.api, KAITI.acceptance[0].out, "");
  const cand = r.mock.append(pid, { kind: "executor", id: "ex" }, "register_artifact", { hash: "c".repeat(64), size: 3, media_type: "text/plain", class: "exec" });
  const req = r.mock.append(pid, { kind: "human", id: "local" }, "request_judge", { target: "goal", judge_id: "structure_check", candidate: `a_${cand.seq}` });
  r.mock.append(pid, { kind: "judge", id: "jr" }, "judge_verdict", { request: `j_${req.seq}`, result: "pass", version: "1", evidence: [] });
  const run = r.mock.append(pid, { kind: "executor", id: "ex" }, "register_artifact", { hash: "d".repeat(64), size: 3, media_type: "text/plain", class: "exec" });
  return { pid, run: `a_${run.seq}` };
}

async function card(r: Rig, pid: string) {
  const out = renderWith(r, <AcceptanceCard pid={pid} head={r.mock.head(pid)} canWrite />);
  await waitFor(() => expect(out.container.querySelector('[data-card="acceptance"]')).not.toBeNull());
  return out.container;
}

const pick = (c: HTMLElement, id: string, v: "pass" | "fail") => fireEvent.click(c.querySelector(`[data-accept-item="${id}"] [data-verdict="${v}"]`)!);

describe("人工验收卡", () => {
  it("逐条组装：没判的、缺依据的都不替人补", () => {
    const items = [{ id: "a1", text: "x", src: "span" as const }, { id: "a2", text: "y", src: "human" as const, needs: "artifact" as const }];
    expect(buildChecks(items, {})).toBe("a1 还没判");
    expect(buildChecks(items, { a1: { verdict: "pass", ref: "", note: "" }, a2: { verdict: "pass", ref: " ", note: "" } })).toBe("a2 要附交付物");
    expect(buildChecks(items, { a1: { verdict: "pass", ref: "", note: "" }, a2: { verdict: "fail", ref: "", note: "" } })).toEqual([{ id: "a1", verdict: "pass" }, { id: "a2", verdict: "fail" }]);
  });

  it("全部过：图服务以 accepted 关闭；读数里只进人工验收一行", async () => {
    const r = rig();
    const { pid, run } = await delivered(r);
    const w = await r.api.work(pid);
    expect(w.items).toContainEqual({ kind: "human", target: pid, why: "acceptance" });
    expect(stationsOf({ closed: false, active: [], todo: ["acceptance"] }).current).toBe("S10");
    const c = await card(r, pid);
    expect(c.querySelector("[data-deliverable]")?.textContent).toContain("只是读数");
    pick(c, "a1", "pass");
    pick(c, "a2", "pass");
    const go = c.querySelector('[data-action="accept-submit"]') as HTMLButtonElement;
    expect(go.disabled).toBe(true);
    expect(c.querySelector("[data-missing]")?.textContent).toContain("a2 要附交付物");
    fireEvent.change(c.querySelector('[data-ref="a2"]')!, { target: { value: run } });
    expect(go.disabled).toBe(false);
    fireEvent.click(go);
    await waitFor(() => expect(c.textContent).toContain("已提交"));
    const st = await r.api.status(pid);
    expect(st.problem.closed && st.problem.terminal).toBe("accepted");
    expect(st.goal.accept_log?.[0]).toMatchObject({ decision: "accept", checks: [{ id: "a1", verdict: "pass" }, { id: "a2", verdict: "pass", ref: run }] });
    const t = (await r.api.problems()).totals;
    expect(t.by_authority.human).toMatchObject({ accepted: 1, solved: 0 });
    expect(t.solved).toBe(t.by_authority.local.solved);
    // 结果页（Q22）：首行终态与等级上限，判定来源写人工验收，不出现“证明”以外的说法
    const s = await liveSession(r, pid);
    const rep = renderWith(r, <ResultReport vm={s.getState().vm!} />).container;
    expect(rep.querySelector("[data-result-head]")?.textContent).toMatch(/^终态 accepted · 人验收；根结论等级上限 E0/);
    expect(rep.querySelector("[data-result-authority]")?.textContent).toContain("判定来源：人工验收");
    expect(rep.querySelector("[data-result-accept]")?.textContent).toContain("验收通过：a1 过、a2 过");
    s.close();
  });

  it("有一条不过：只能拒收，理由必填；任务回到人介入，等新的交付物", async () => {
    const r = rig();
    const { pid } = await delivered(r);
    const c = await card(r, pid);
    pick(c, "a1", "fail");
    pick(c, "a2", "fail");
    expect(c.querySelector('[data-action="accept-submit"]')).toBeNull();
    const no = c.querySelector('[data-action="reject-submit"]') as HTMLButtonElement;
    expect(no.textContent).toContain("a1、a2 不过");
    expect(no.disabled).toBe(true);
    fireEvent.change(c.querySelector('[data-field="reject-reason"]')!, { target: { value: "对比只写了一个框架" } });
    fireEvent.click(no);
    await waitFor(() => expect(c.textContent).toContain("已提交"));
    const st = await r.api.status(pid);
    expect(st.problem.closed).toBe(false);
    expect(st.goal.accept_log?.[0]).toMatchObject({ decision: "reject", reason: "对比只写了一个框架" });
    expect(st.goal.acceptance_ready).toBeNull();
    expect((await r.api.work(pid)).items.some((x) => x.kind === "human" && x.why === "acceptance")).toBe(false);
  });
});
