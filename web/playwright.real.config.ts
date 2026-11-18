// 浏览器连真实图服务（阶段二第 3 项）：起 scripts/run.py（图服务 + 判官 + 司南 + 哮天犬，单进程），
// 托管 web/dist，浏览器只走 /v1/ 与 SSE。执行层 none、没有会话脚本：组件不自己开会话，事件由测试以人的身份写入，
// 所以每一步都确定。需要 uv（仓库根目录的 Python 工作区）与构建过的 dist/。npm run e2e:real。
import { defineConfig, devices } from "@playwright/test";
import { tmpdir } from "node:os";
import { join } from "node:path";

export const REAL_PORT = 4318;
export const REAL_HOME = process.env.PD_REAL_HOME ?? join(tmpdir(), "paoding-web-real");

const boot = [
  `rm -rf '${REAL_HOME}'`,
  `mkdir -p '${REAL_HOME}'`,
  `printf 'executor: none\\npoll_s: 0.3\\ndog_interval_s: 1.0\\nlog:\\n  format: text\\n' > '${REAL_HOME}/config.yaml'`,
  `cd ..`,
  `exec uv run --quiet python scripts/run.py --home '${REAL_HOME}' --port ${REAL_PORT} --static web/dist`,
].join(" && ");

export default defineConfig({
  testDir: "e2e-real",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never", outputFolder: "playwright-report-real" }]] : "list",
  use: { baseURL: `http://127.0.0.1:${REAL_PORT}`, trace: "off", viewport: { width: 1360, height: 900 } },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1360, height: 900 } } }],
  webServer: {
    command: `sh -c "${boot.replace(/"/g, '\\"')}"`,
    url: `http://127.0.0.1:${REAL_PORT}/v1/health`,
    reuseExistingServer: false,
    timeout: 120_000,
    stdout: "ignore",
    stderr: "pipe",
  },
});
