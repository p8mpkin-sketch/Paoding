import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { createMock, MOCK_TOKEN, type Mock } from "../mock/backend";
import { mockFetch, type MockFetch } from "../mock/fetch";
import { createApi, newIdemKey, type Api, type ApiConfig } from "../src/api/client";
import { ops } from "../src/api/ops";
import { ServicesContext } from "../src/app/context";
import { ProblemSession } from "../src/app/session";

export type Rig = { mock: Mock; fetch: MockFetch; cfg: ApiConfig; api: Api };

export function rig(token: string | null = MOCK_TOKEN): Rig {
  const mock = createMock();
  const fetch = mockFetch(mock);
  const cfg: ApiConfig = { base: "", token, fetch };
  return { mock, fetch, cfg, api: createApi(cfg) };
}

export const noWait = () => Promise.resolve();

export async function until(cond: () => boolean, what = "条件", ms = 3000): Promise<void> {
  const t0 = performance.now();
  while (!cond()) {
    if (performance.now() - t0 > ms) throw new Error(`等不到：${what}`);
    await new Promise((r) => setTimeout(r, 5));
  }
}

export function renderWith(r: Rig, ui: ReactElement) {
  return render(<ServicesContext.Provider value={{ api: r.api, cfg: r.cfg }}>{ui}</ServicesContext.Provider>);
}

/** 一个跟到链头的会话。 */
export async function liveSession(r: Rig, pid: string, asOf: number | null = null): Promise<ProblemSession> {
  const s = new ProblemSession(r.api, r.cfg, pid, { asOf, wait: noWait });
  await s.start();
  await until(() => s.getState().vm !== null && (asOf !== null || s.getState().conn === "live"), "会话就绪");
  return s;
}

/** 演示题里等人审批的那条 Intent。 */
export async function pendingIntent(r: Rig, pid: string): Promise<string> {
  const w = await r.api.work(pid);
  const item = w.items.find((x) => x.kind === "human" && x.why === "needs_human");
  if (!item || item.kind !== "human") throw new Error("没有待审批项");
  return item.target;
}

/** 批准演示题并把剧本播到头。 */
export async function playToEnd(r: Rig): Promise<void> {
  const pid = r.mock.demoPid;
  const intent = await pendingIntent(r, pid);
  const card = await r.api.card(pid, "approval", intent);
  await r.api.propose(pid, [ops.approve(intent, { seq: card.as_of, card_hash: card.card_hash })], newIdemKey());
  while (r.mock.step()) { /* 播到头 */ }
}

/** 确定性的伪随机数（性质测试用；不用 Math.random，失败可复现）。 */
export function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
