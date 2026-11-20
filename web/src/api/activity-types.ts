// 会话活动的应答形状：scripts/stack.py 挂在图服务 HTTP 上的 GET /v1/leases/{id}/activity（adapter/activity.py）。
// 这个端点挂在组装根上，不在图服务的线格式 schema 里，所以不放进生成物 types.ts。
// 条目来自 CLI 的 stream-json：工具调用（call）、它的结果（result）、自述（say）、一轮结束（end）。只排版，不推断。

export type ActCall = { n: number; round: number; kind: "call"; tool: string; gist: string; id: string };
export type ActResult = { n: number; round: number; kind: "result"; id: string; ok: boolean; gist: string };
export type ActSay = { n: number; round: number; kind: "say"; text: string };
export type ActEnd = { n: number; round: number; kind: "end"; ok: boolean; turns?: number | null; gist: string };
export type ActItem = ActCall | ActResult | ActSay | ActEnd;

export type SessionActivity = {
  lease: string;
  problem_id: string;
  kind: string;
  /** 租约还在图里活着（来自图服务状态）。 */
  active: boolean;
  /** 会话运行器手里正有这个会话（在途读内存；否则读会话目录）。 */
  live: boolean;
  /** 运行器的会话状态（running、collecting、released、failed(...)…）；none 表示还没留下活动。 */
  status: string;
  rounds: number;
  model: string;
  elapsed_s: number;
  /** 端点代理给这个会话记的账（与 cost 事件同一个计量）。 */
  spent_usd_milli: number;
  /** 越过软线，正在收尾轮。 */
  closing: boolean;
  items: ActItem[];
  next_after: number;
  total: number;
  calls: number;
  now: ActCall | null;
  last_say: ActSay | null;
};
