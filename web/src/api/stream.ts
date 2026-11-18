// 事件流（HMI 设计 §11.1、§13.2）：SSE，id 就是事件 seq，断连后带 Last-Event-ID 续上。
// 用 fetch 读流而不用 EventSource：要自己带 Last-Event-ID（冷启动时从已读到的序号续上，
// 不带游标的话图服务从链头之后开始），断连的时刻也要自己看得见。读端点不带令牌。
import type { ApiConfig } from "./client";
import { SseParser } from "./sse";
import type { Event, ViewFrame } from "./types";

export type StreamHandle = { close(): void };
export type StreamOptions = {
  /** 已有的最后一个 seq；流从它的下一条开始。 */
  after: number;
  onEvent(ev: Event): void;
  /** 落后超过补发窗口时图服务先发一帧快照再续流：中间的事件没有逐条送来，调用方要自己补。 */
  onSnapshot?(asOf: number): void;
  /** 一批事件之后（以及刚连上时）图服务发一帧 view：该序号上四份投影各自的 view_hash。 */
  onView?(frame: ViewFrame): void;
  /** live：连接已建立；disconnected：断开，正在重试。 */
  onState(state: "live" | "disconnected"): void;
  /** 重连前的等待；测试里注入。 */
  wait?: (attempt: number) => Promise<void>;
};

const defaultWait = (attempt: number) => new Promise<void>((r) => setTimeout(r, Math.min(500 * 2 ** attempt, 8000)));

export function openStream(cfg: ApiConfig, pid: string, opts: StreamOptions): StreamHandle {
  const ctrl = new AbortController();
  let last = opts.after;
  const wait = opts.wait ?? defaultWait;

  async function once(): Promise<void> {
    const res = await cfg.fetch(`${cfg.base}/v1/problems/${encodeURIComponent(pid)}/stream`, {
      headers: { accept: "text/event-stream", "last-event-id": String(last) },
      signal: ctrl.signal,
      credentials: "omit",
    });
    if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
    opts.onState("live");
    const parser = new SseParser();
    const dec = new TextDecoder();
    const reader = res.body.getReader();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;
      for (const msg of parser.feed(dec.decode(value, { stream: true }))) {
        if (msg.event === "snapshot") {
          const asOf = (JSON.parse(msg.data) as { as_of: number }).as_of;
          opts.onSnapshot?.(asOf);
          continue;
        }
        if (msg.event === "view") {
          opts.onView?.(JSON.parse(msg.data) as ViewFrame);
          continue;
        }
        if (msg.event !== null) continue; // 不认识的具名帧
        const ev = JSON.parse(msg.data) as Event;
        if (ev.seq <= last) continue; // 无重
        last = ev.seq;
        opts.onEvent(ev);
      }
    }
  }

  (async () => {
    for (let attempt = 0; !ctrl.signal.aborted; attempt++) {
      try {
        await once();
        attempt = 0;
      } catch {
        /* 断连与中止都落到下面 */
      }
      if (ctrl.signal.aborted) return;
      opts.onState("disconnected");
      await wait(attempt);
    }
  })();

  return { close: () => ctrl.abort() };
}
