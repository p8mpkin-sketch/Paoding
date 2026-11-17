// 独立运行的假图服务：npm run mock（默认 127.0.0.1:8787）。
import { createServer } from "node:http";
import { createMock } from "./backend";
import { nodeMiddleware } from "./node";

const port = Number(process.env.PORT ?? 8787);
createServer(nodeMiddleware(createMock({ autoplayMs: 1500 }))).listen(port, "127.0.0.1", () => {
  console.log(`假图服务在 http://127.0.0.1:${port}`);
});
