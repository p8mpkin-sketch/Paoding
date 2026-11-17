// 测试用：把假服务包成一个 fetch，不经过套接字。事件流可以人为掐断。
import type { Mock } from "./backend";

export type MockFetch = typeof fetch & {
  /** 掐断当前所有事件流连接（模拟断网）。 */
  dropStreams(): void;
  /** 之后的请求全部失败，直到 online(true)。 */
  online(v: boolean): void;
  calls: { method: string; url: string; headers: Record<string, string>; body?: string }[];
};

export function mockFetch(mock: Mock): MockFetch {
  const open = new Set<() => void>();
  let up = true;
  const calls: MockFetch["calls"] = [];
  const f = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const headers = Object.fromEntries(new Headers(init?.headers).entries());
    const raw = init?.body;
    const body = raw === undefined || raw === null ? undefined : typeof raw === "string" ? new TextEncoder().encode(raw) : new Uint8Array(raw as ArrayBuffer);
    calls.push({ method, url, headers, body: typeof raw === "string" ? raw : undefined });
    if (!up) throw new TypeError("network down");
    const stream = new URL(url, "http://mock").pathname.match(/^\/v1\/problems\/([^/]+)\/stream$/);
    if (stream && method === "GET") {
      const enc = new TextEncoder();
      let off = () => {};
      let close = () => {};
      const rs = new ReadableStream<Uint8Array>({
        start(ctrl) {
          off = mock.subscribe(decodeURIComponent(stream[1]), Number(headers["last-event-id"] ?? 0), (e) => ctrl.enqueue(enc.encode(`id: ${e.seq}\ndata: ${JSON.stringify(e)}\n\n`)));
          close = () => { off(); open.delete(close); try { ctrl.error(new TypeError("dropped")); } catch { /* 已关 */ } };
          open.add(close);
          init?.signal?.addEventListener("abort", () => { off(); open.delete(close); try { ctrl.close(); } catch { /* 已关 */ } });
        },
        cancel() { off(); open.delete(close); },
      });
      return new Response(rs, { status: 200, headers: { "content-type": "text/event-stream" } });
    }
    const r = mock.handle({ method, url, headers, body });
    return new Response(r.body as BodyInit, { status: r.status, headers: r.headers });
  };
  return Object.assign(f as typeof fetch, {
    dropStreams: () => [...open].forEach((c) => c()),
    online: (v: boolean) => { up = v; },
    calls,
  });
}
