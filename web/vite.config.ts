/// <reference types="vitest" />
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// 开发时的两种后端：
//   默认            进程内假后端（mock/，线格式与图服务的 HTTP 绑定相同）
//   PAODING_API=…   反向代理到真实图服务（例如 http://127.0.0.1:8787）
const api = process.env.PAODING_API;

function mockPlugin(): Plugin {
  return {
    name: "paoding-mock",
    apply: "serve",
    async configureServer(server) {
      const { createMock } = await import("./mock/backend");
      const { nodeMiddleware } = await import("./mock/node");
      const mock = createMock({ autoplayMs: 1500 });
      server.middlewares.use(nodeMiddleware(mock));
    },
  };
}

// 构建产物带内容安全策略：只连同源，没有外部脚本、框架与表单提交（HMI 设计 §13.1）。
// 开发服务器要注入热更新脚本，所以只在构建时加。
const CSP = "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'";
function cspPlugin(): Plugin {
  return {
    name: "paoding-csp",
    apply: "build",
    transformIndexHtml: (html) => html.replace("<head>", `<head>\n    <meta http-equiv="Content-Security-Policy" content="${CSP}" />`),
  };
}

// 自托管字体只留 woff2：@fontsource 的样式表同时列了 woff 兜底，现在的浏览器都不会用它，留着只占部署体积。
function woff2Only(): Plugin {
  return {
    name: "paoding-woff2-only",
    apply: "build",
    generateBundle(_, bundle) {
      for (const [name, out] of Object.entries(bundle)) {
        if (name.endsWith(".woff")) delete bundle[name];
        else if (out.type === "asset" && name.endsWith(".css") && typeof out.source === "string") {
          out.source = out.source.replace(/,\s*url\([^)]*\.woff\)\s*format\(["']woff["']\)/g, "");
        }
      }
    },
  };
}

export default defineConfig(({ command }) => ({
  plugins: [woff2Only(), react(), tailwindcss(), cspPlugin(), ...(api ? [] : [mockPlugin()])],
  // 只有"开发服务器 + 内置假后端"才预置令牌；构建产物与连真图服务时都要人自己填
  define: { "import.meta.env.VITE_DEV_TOKEN": JSON.stringify(command === "serve" && !api && !process.env.VITEST ? "mock-human-token" : "") },
  server: {
    host: "127.0.0.1",
    proxy: api ? { "/v1": { target: api, changeOrigin: false } } : undefined,
  },
  build: { outDir: "dist", sourcemap: false },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
    restoreMocks: true,
  },
}));
