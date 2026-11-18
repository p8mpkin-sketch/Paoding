import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { loadConfig } from "./app/config";
import { applyTheme, loadTheme } from "./app/theme";
import "./styles.css";

applyTheme(loadTheme()); // 先于首帧，免得闪一下

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App cfg={loadConfig()} />
  </StrictMode>,
);
