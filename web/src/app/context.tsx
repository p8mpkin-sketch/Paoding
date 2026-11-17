import { createContext, useContext } from "react";
import type { Api, ApiConfig } from "../api/client";

export type Services = { api: Api; cfg: ApiConfig };
export const ServicesContext = createContext<Services | null>(null);

export function useServices(): Services {
  const s = useContext(ServicesContext);
  if (!s) throw new Error("缺少 ServicesContext");
  return s;
}

/** 时间显示取事件的 ts，按 UTC 排版；视图里不读本机时钟。 */
export const fmtTs = (ts: number): string => new Date(ts).toISOString().replace("T", " ").replace(".000Z", "Z");
