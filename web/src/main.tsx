import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { loadConfig } from "./app/config";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App cfg={loadConfig()} />
  </StrictMode>,
);
