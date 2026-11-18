// 本机配置：图服务基址与人的令牌。只存在本机（令牌只在本标签页），不影响任何派生量（HMI 设计 §2 禁令 2）。
import type { ApiConfig } from "../api/client";

const read = (key: string): string | null => {
  try {
    return globalThis.localStorage?.getItem(key) ?? null;
  } catch {
    return null;
  }
};

/** 人的令牌只放在本标签页的 sessionStorage，带到期时间（裁决 005-6）：关掉标签页或到期即失效，要重新填。 */
const TOKEN_KEY = "paoding.human_token";
/** 缺省有效期：8 小时。 */
export const TOKEN_TTL_MS = 8 * 3600 * 1000;
export type StoredToken = { token: string; expires_at: number };

const session = (): Storage | undefined => {
  try {
    return globalThis.sessionStorage;
  } catch {
    return undefined;
  }
};

/** 读本标签页里没过期的令牌；过期的顺手删掉。旧版本放在 localStorage 的令牌一并清除，不再沿用。 */
export function loadToken(now = Date.now()): StoredToken | null {
  try {
    globalThis.localStorage?.removeItem(TOKEN_KEY);
  } catch {
    /* 读不到就算了 */
  }
  try {
    const raw = session()?.getItem(TOKEN_KEY);
    if (!raw) return null;
    const t = JSON.parse(raw) as Partial<StoredToken>;
    if (typeof t.token === "string" && t.token && typeof t.expires_at === "number" && t.expires_at > now) return { token: t.token, expires_at: t.expires_at };
    session()?.removeItem(TOKEN_KEY);
  } catch {
    /* 坏了就当没有 */
  }
  return null;
}

export function loadConfig(): ApiConfig {
  return {
    base: read("paoding.api_base") ?? "",
    // 开发时连内置的假后端，vite 把它的固定令牌放进 VITE_DEV_TOKEN，省得每次手填
    token: loadToken()?.token ?? (import.meta.env?.VITE_DEV_TOKEN || null),
    fetch: (input, init) => globalThis.fetch(input, init),
  };
}

/** 存令牌并返回它的到期时间；token 为 null 时清除。 */
export function saveToken(token: string | null, now = Date.now(), ttlMs = TOKEN_TTL_MS): StoredToken | null {
  try {
    if (!token) {
      session()?.removeItem(TOKEN_KEY);
      return null;
    }
    const t = { token, expires_at: now + ttlMs };
    session()?.setItem(TOKEN_KEY, JSON.stringify(t));
    return t;
  } catch {
    /* 存不了就只在本页有效 */
    return token ? { token, expires_at: now + ttlMs } : null;
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
