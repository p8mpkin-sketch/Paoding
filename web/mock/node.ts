// 把假服务挂到 node 的 HTTP 服务上（Vite 开发中间件与独立进程共用）。
import type { IncomingMessage, ServerResponse } from "node:http";
import type { Mock } from "./backend";

export function nodeMiddleware(mock: Mock) {
  return (req: IncomingMessage, res: ServerResponse, next?: () => void) => {
    const url = req.url ?? "/";
    if (!url.startsWith("/v1/")) return next ? next() : void res.writeHead(404).end();
    const stream = url.match(/^\/v1\/problems\/([^/]+)\/stream/);
    if (stream && req.method === "GET") {
      const last = Number(req.headers["last-event-id"] ?? new URL(url, "http://x").searchParams.get("after") ?? 0);
      res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-store", connection: "keep-alive" });
      res.write(": ok\n\n");
      const pid = decodeURIComponent(stream[1]);
      // 与图服务相同：每条事件之后跟一帧 view（该序号上四份投影的 view_hash），刚连上时也先发一帧
      const view = (seq: number) => {
        const h = seq > 0 ? mock.partsHash(pid, seq) : null;
        if (h) res.write(`id: ${seq}\nevent: view\ndata: ${JSON.stringify({ as_of: seq, parts_hash: h })}\n\n`);
      };
      const off = mock.subscribe(pid, last, (e) => { res.write(`id: ${e.seq}\ndata: ${JSON.stringify(e)}\n\n`); view(e.seq); });
      view(last);
      const beat = setInterval(() => res.write(": beat\n\n"), 15000);
      req.on("close", () => { off(); clearInterval(beat); });
      return;
    }
    const chunks: Buffer[] = [];
    req.on("data", (c: Buffer) => chunks.push(c));
    req.on("end", () => {
      const r = mock.handle({ method: req.method ?? "GET", url, headers: req.headers as Record<string, string>, body: new Uint8Array(Buffer.concat(chunks)) });
      res.writeHead(r.status, r.headers).end(Buffer.from(r.body));
    });
  };
}
