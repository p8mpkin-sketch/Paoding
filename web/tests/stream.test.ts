// HT-16：断连重连后事件序列无缺无重；断开期间界面状态是"已断开"而不是静默陈旧。
import { describe, expect, it } from "vitest";
import { SseParser } from "../src/api/sse";
import { canWrite } from "../src/app/session";
import { EventLog } from "../src/model/eventlog";
import { liveSession, noWait, playToEnd, rig, until } from "./helpers";
import { ProblemSession } from "../src/app/session";

describe("事件流", () => {
  it("SSE 解析：帧可以被任意切开；id、具名帧、注释行", () => {
    const text = ": ok\n\nid: 7\ndata: {\"a\":1}\n\nevent: snapshot\ndata: {\"as_of\":9}\n\nid: 10\ndata: x\ndata: y\n\n";
    for (const cut of [1, 3, 11, 20, text.length]) {
      const p = new SseParser();
      const out = [];
      for (let i = 0; i < text.length; i += cut) out.push(...p.feed(text.slice(i, i + cut)));
      expect(out).toEqual([
        { id: "7", event: null, data: '{"a":1}' },
        { id: "7", event: "snapshot", data: '{"as_of":9}' },
        { id: "10", event: null, data: "x\ny" },
      ]);
    }
  });

  it("本机序列：重复的丢掉，接不上的报缺口", () => {
    const r = rig();
    const evs = r.mock.eventsOf(r.mock.demoPid);
    const log = new EventLog();
    expect(log.push(evs[0])).toBe("ok");
    expect(log.push(evs[0])).toBe("dup");
    expect(log.push(evs[2])).toBe("gap");
    expect(log.fill(evs.slice(1, 4))).toBe(true);
    expect(log.head).toBe(evs[3].seq);
  });

  it("HT-16 断连期间显示已断开且不可写；重连后无缺无重", async () => {
    const r = rig();
    const pid = r.mock.demoPid;
    let release: () => void = () => {};
    const gate = () => new Promise<void>((res) => { release = res; });
    const s = new ProblemSession(r.api, r.cfg, pid, { wait: gate });
    await s.start();
    await until(() => s.getState().conn === "live" && s.getState().vm !== null, "连上");
    expect(canWrite(s.getState())).toBe(true);
    const before = s.getState().vm!.seq;

    r.fetch.dropStreams();
    await until(() => s.getState().conn === "disconnected", "看到断开");
    expect(canWrite(s.getState())).toBe(false);
    await playToEnd(r); // 断开期间链头往前走了一大段
    await new Promise((res) => setTimeout(res, 20));
    expect(s.getState().vm!.seq).toBe(before); // 停在原处，不是静默更新

    release();
    await until(() => s.getState().conn === "live" && s.log.head === r.mock.head(pid), "补齐");
    await s.settled();
    expect(s.log.events.map((e) => e.seq)).toEqual(r.mock.eventsOf(pid).map((e) => e.seq));
    await until(() => s.getState().vm?.seq === r.mock.head(pid), "视图到链头");
    expect(s.getState().vm!.closed).toBe(true);
    s.close();
  });

  it("HT-16 流里中途丢了一条：靠哈希链发现并用 /events 补齐", async () => {
    const r = rig();
    const pid = r.mock.demoPid;
    // 一条会漏事件的流：每逢第 3 条不送
    let n = 0;
    const lossy: typeof fetch = async (input, init) => {
      if (!String(input).endsWith("/stream")) return r.fetch(input, init);
      const enc = new TextEncoder();
      const last = Number(new Headers(init?.headers).get("last-event-id") ?? 0);
      const body = new ReadableStream<Uint8Array>({
        start(ctrl) {
          const off = r.mock.subscribe(pid, last, (e) => { if (++n % 3 !== 0) ctrl.enqueue(enc.encode(`id: ${e.seq}\ndata: ${JSON.stringify(e)}\n\n`)); });
          init?.signal?.addEventListener("abort", () => { off(); try { ctrl.close(); } catch { /* 已关 */ } });
        },
      });
      return new Response(body, { status: 200 });
    };
    const s = new ProblemSession(r.api, { ...r.cfg, fetch: lossy }, pid, { wait: noWait });
    await s.start();
    await until(() => s.getState().conn === "live", "连上");
    await playToEnd(r);
    await until(() => s.log.head === r.mock.head(pid), "追到链头");
    await s.settled();
    expect(n).toBeGreaterThan(9);
    expect(s.log.events.map((e) => e.seq)).toEqual(r.mock.eventsOf(pid).map((e) => e.seq));
    s.close();
  });

  it("读请求不带令牌，写请求带", async () => {
    const r = rig();
    const pid = r.mock.demoPid;
    const s = await liveSession(r, pid);
    await playToEnd(r);
    s.close();
    for (const c of r.fetch.calls) {
      if (c.method === "GET") expect(c.headers.authorization, c.url).toBeUndefined();
      else expect(c.headers.authorization, c.url).toMatch(/^Bearer /);
    }
    expect(r.fetch.calls.some((c) => c.method === "POST")).toBe(true);
  });
});
