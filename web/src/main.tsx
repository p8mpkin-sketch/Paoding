import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { loadConfig } from "./app/config";
import { applyTheme, loadTheme } from "./app/theme";
import "./index.css";
import "./kit/kit.css";
import "./shell/shell.css";
import "./styles.css";
import "./pages/pages.css";
import "./pages/workspace.css";
import "./pages/kaiti.css";
import "./pages/models.css";
import "./pages/tasks.css";
import "./pages/task.css";
import "./pages/trace.css";
import "./pages/pages-v6.css";
import "./pages/knowledge.css";

applyTheme(loadTheme()); // 先于首帧，免得闪一下

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App cfg={loadConfig()} />
  </StrictMode>,
);
