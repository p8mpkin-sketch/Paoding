// 界面使用读数（HMI 设计 H5）：每模块打开次数与下钻次数，写进独立的本机存储。
// 不进题目日志，不进任何任务包，不发往服务端；可整体关闭（prefs.usage）。量具：只显示，不驱动任何默认值。
import { prefs } from "./config";

const KEY = "paoding.usage_readings";
export type UsageReadings = Record<string, number>;

export function readUsage(): UsageReadings {
  try {
    return JSON.parse(globalThis.localStorage?.getItem(KEY) ?? "{}") as UsageReadings;
  } catch {
    return {};
  }
}

export function countUsage(module: string): void {
  if (!prefs.usage()) return;
  try {
    const r = readUsage();
    r[module] = (r[module] ?? 0) + 1;
    globalThis.localStorage?.setItem(KEY, JSON.stringify(r));
  } catch {
    /* 读数丢了不影响任何功能 */
  }
}
