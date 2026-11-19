// 主题（v5）：亮色、暗色、高对比，缺省跟随系统。id 沿用旧名，存过的偏好照样生效。只存本机，不影响任何派生量。
// 等级与终态仍靠形状记号加文字区分，颜色只是第三重编码，所以任何主题下都不丢信息。
export type Theme = "system" | "light" | "dark" | "contrast";
export const THEMES: { id: Theme; word: string }[] = [
  { id: "system", word: "跟随系统" },
  { id: "light", word: "亮色" },
  { id: "dark", word: "暗色" },
  { id: "contrast", word: "高对比" },
];
const KEY = "paoding.theme";

export function loadTheme(): Theme {
  try {
    const v = globalThis.localStorage?.getItem(KEY);
    return THEMES.some((t) => t.id === v) ? (v as Theme) : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(t: Theme): void {
  const root = globalThis.document?.documentElement;
  if (!root) return;
  if (t === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", t);
  try {
    if (t === "system") globalThis.localStorage?.removeItem(KEY);
    else globalThis.localStorage?.setItem(KEY, t);
  } catch {
    /* 存不了就只在本页有效 */
  }
}
