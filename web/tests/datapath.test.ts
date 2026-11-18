// P2-1 前端数据路径：一条事件至多一个读请求（合并读端点 + 流里的 view 帧），冷启动不读全量事件。
import { describe, expect, it } from "vitest";
import { createApi } from "../src/api/client";
import { ProblemSession } from "../src/app/session";
import { hashOf } from "../src/model/hash";
import { liveSession, noWait, playToEnd, rig, until } from "./helpers";

const reads = (r: ReturnType<typeof rig>, from: number) =>
  r.fetch.calls.slice(from).filter((c) => c.method === "GET" && !c.url.endsWith("/stream"));

describe("数据路径", () => {
  it("冷启动：一个 /ticks 加一个 /snapshot，不分页读 /events", async () => {
    const r = rig();
    await playToEnd(r);
    const before = r.fetch.calls.length;
    const s = await liveSession(r, r.mock.demoPid);
    await s.settled();
    const urls = reads(r, before).map((c) => new URL(c.url, "http://x").pathname.split("/").at(-1));
    expect(urls).toEqual(["ticks", "snapshot"]);              // 连上之后的 view 帧与手上的一致：不再发请求
    expect(s.log.ticks.map((t) => t.seq)).toEqual(r.mock.eventsOf(r.mock.demoPid).map((e) => e.seq));
    s.close();
  });

  it("实时：每条事件至多一个读请求，没变的投影沿用", async () => {
    const r = rig();
    const pid = r.mock.demoPid;
    const s = await liveSession(r, pid);
    await s.settled();
    const before = r.fetch.calls.length;
    let events = 0;
    const startHead = r.mock.head(pid);
    await playToEnd(r);
    await until(() => s.getState().vm?.seq === r.mock.head(pid), "跟到链头");
    await s.settled();
    events = r.mock.eventsOf(pid).filter((e) => e.seq > startHead).length;
    const got = reads(r, before).filter((c) => c.url.includes(`/problems/${pid}/`));
    // playToEnd 自己读了一张审批卡；其余都是会话的合并读
    const snaps = got.filter((c) => c.url.includes("/snapshot"));
    expect(got.filter((c) => /\/(status|view|budget|work)\?/.test(c.url))).toEqual([]);   // 不再分别读四份
    expect(snaps.length).toBeGreaterThan(0);
    expect(snaps.length).toBeLessThanOrEqual(events);
    expect(snaps.some((c) => new URL(c.url, "http://x").searchParams.has("parts"))).toBe(true);   // 至少有一次只取变了的几份
    s.close();
  });

  it("HT-10 沿用旧投影拼出的视图模型，与冷启动到同一序号的哈希相同", async () => {
    const r = rig();
    const pid = r.mock.demoPid;
    const live = await liveSession(r, pid);
    await playToEnd(r);
    await until(() => live.getState().vm?.seq === r.mock.head(pid), "跟到链头");
    await live.settled();
    const api = createApi(r.cfg);
    for (const [seq, h] of live.recorded) {
      const cold = new ProblemSession(api, r.cfg, pid, { asOf: seq, wait: noWait });
      await cold.start();
      await until(() => cold.getState().vm !== null, "冷启动");
      expect(cold.getState().vmHash, `seq=${seq}`).toBe(h);
      expect(await hashOf(cold.getState().vm)).toBe(h);
      cold.close();
    }
  });
});
