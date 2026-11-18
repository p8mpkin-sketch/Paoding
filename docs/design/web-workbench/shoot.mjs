// 生成线框截图：在 web/ 下 node ../docs/design/web-workbench/shoot.mjs（借用 web 的 @playwright/test）
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";
const { chromium } = createRequire(path.join(process.cwd(), "package.json"))("@playwright/test");
const dir = path.dirname(fileURLToPath(import.meta.url));
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1340, height: 1000 }, deviceScaleFactor: 1 });
await p.goto("file://" + path.join(dir, "wireframes.html"));
for (const id of await p.$$eval("section.frame", (xs) => xs.map((x) => x.id))) {
  await p.locator("#" + id).screenshot({ path: path.join(dir, id + ".png") });
}
await b.close();
