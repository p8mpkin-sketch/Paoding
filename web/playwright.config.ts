// 浏览器测试（P2-2）：驾驶舱、审批卡、时间轴回放、窄屏。npm run e2e。
import { defineConfig, devices } from "@playwright/test";

const port = 4317;
export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  workers: 1,                                   // 共用一个假后端；每个用例开头 reset
  retries: 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: `http://127.0.0.1:${port}`, trace: "off", viewport: { width: 1360, height: 900 } },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1360, height: 900 } } }],
  webServer: { command: `npx tsx e2e/server.ts`, url: `http://127.0.0.1:${port}/`, env: { PORT: String(port) }, reuseExistingServer: !process.env.CI, timeout: 30_000 },
});
