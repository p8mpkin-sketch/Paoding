// Playwright 用的服务：构建产物（dist/）加进程内假后端，剧本不自动播放，测试自己推进。
// 只有测试用的 /__e2e/step 推进一步；页面本身只走 /v1/，与连真图服务时相同。
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { createMock } from "../mock/backend";
import { nodeMiddleware } from "../mock/node";

const port = Number(process.env.PORT ?? 4317);
const dist = join(import.meta.dirname, "..", "dist");
const TYPES: Record<string, string> = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml" };

let mock = createMock();
let api = nodeMiddleware(mock);

createServer((req, res) => {
  const url = new URL(req.url ?? "/", "http://x");
  if (url.pathname === "/__e2e/step" && req.method === "POST") return void res.writeHead(200).end(JSON.stringify({ moved: mock.step() }));
  if (url.pathname === "/__e2e/reset" && req.method === "POST") {
    mock = createMock();
    api = nodeMiddleware(mock);
    return void res.writeHead(200).end("{}");
  }
  if (url.pathname.startsWith("/v1/")) return api(req, res);
  const file = normalize(join(dist, url.pathname));
  const send = (path: string): Promise<unknown> =>
    readFile(path).then(
      (b) => res.writeHead(200, { "content-type": TYPES[extname(path)] ?? "application/octet-stream" }).end(b),
      (): Promise<unknown> => send(join(dist, "index.html")),              // 前端路由：其余路径都回 index.html
    );
  void send(file.startsWith(dist) && extname(file) ? file : join(dist, "index.html"));
}).listen(port, "127.0.0.1", () => console.log(`e2e 服务在 http://127.0.0.1:${port}`));
