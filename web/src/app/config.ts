// 本机配置：图服务基址与人的令牌。只存在本机，不影响任何派生量（HMI 设计 §2 禁令 2）。
import type { ApiConfig } from "../api/client";

const read = (key: string): string | null => {
  try {
    return globalThis.localStorage?.getItem(key) ?? null;
  } catch {
    return null;
  }
};

export function loadConfig(): ApiConfig {
  return {
    base: read("paoding.api_base") ?? "",
    // 开发时连内置的假后端，vite 把它的固定令牌放进 VITE_DEV_TOKEN，省得每次手填
    token: read("paoding.human_token") ?? (import.meta.env?.VITE_DEV_TOKEN || null),
    fetch: (input, init) => globalThis.fetch(input, init),
  };
}

export function saveToken(token: string | null): void {
  try {
    if (token) globalThis.localStorage?.setItem("paoding.human_token", token);
    else globalThis.localStorage?.removeItem("paoding.human_token");
  } catch {
    /* 存不了就只在本次会话有效 */
  }
}

/** 本机界面偏好（T-1 开关）。 */
export const prefs = {
  /** 图可视化的启用条件是节点数超过 50（HMI 设计 §3.8）；always 是手动开关。 */
  graphView: (): "auto" | "always" => (read("paoding.graph_view") === "always" ? "always" : "auto"),
  setGraphView(v: "auto" | "always") {
    try {
      globalThis.localStorage?.setItem("paoding.graph_view", v);
    } catch {
      /* 存不了就只在本次会话有效 */
    }
  },
  /** H5 的界面使用读数是否记录；可整体关闭。 */
  usage: (): boolean => read("paoding.usage") !== "off",
};
export const GRAPH_MIN_NODES = 50;
