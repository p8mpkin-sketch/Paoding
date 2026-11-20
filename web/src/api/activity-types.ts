// 会话活动的应答形状：scripts/stack.py 挂在图服务 HTTP 上的 GET /v1/leases/{id}/activity（adapter/activity.py）。
// 这个端点挂在组装根上，不在图服务的线格式 schema 里，所以不放进生成物 types.ts。
// 条目来自 CLI 的 stream-json：模型调用（turn）、思考（think）、工具调用（call）、它的结果（result）、自述（say）、一轮结束（end）。只排版，不推断。
// t 是会话内的本机毫秒（相对会话开始），只在实时流与会话目录里：不进链哈希、不入账，回放的条目没有 t。

// 可回放的实时性（焚决首炼，炼档 001）：每条带链哈希 h；exec 的结果带执行层登记的 ArtifactId。
type Base = { n: number; round: number; t?: number; h?: string };
export type ActCall = Base & { kind: "call"; tool: string; gist: string; id: string };
/** size：结果全文的字数（gist 只是开头一段）；全文在执行留档里。 */
export type ActResult = Base & { kind: "result"; id: string; ok: boolean; gist: string; artifact?: string; size?: number };
export type ActSay = Base & { kind: "say"; text: string };
export type ActEnd = Base & { kind: "end"; ok: boolean; turns?: number | null; gist: string; ms?: number };
/** 一次模型调用：CLI 流里 assistant 消息自带的 usage 与停止原因，原样搬运（花费以端点代理的 cost 事件为准）。 */
export type ActTurn = Base & { kind: "turn"; model: string; in: number; out: number; cache_read: number; cache_write: number; stop: string };
/** 扩展思考；redacted 表示上游遮蔽了这段，不显示内容。 */
export type ActThink = Base & { kind: "think"; text: string; redacted?: boolean };
export type ActItem = ActCall | ActResult | ActSay | ActEnd | ActTurn | ActThink;
export type Tokens = { in: number; out: number; cache_read: number; cache_write: number };

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
  /** 模型调用次数与 token 合计（活动端点从 turn 条目加总）；旧端点没有这几个字段。 */
  turns?: number;
  tokens?: Tokens;
  models?: string[];
  now: ActCall | null;
  last_say: ActSay | null;
  /** 已入账（分段登记进事件账）的最后一个序号；null 表示这个会话不入账（严格道缺省、首炼之前的会话）。 */
  anchored_through?: number | null;
  /** 回放：只含那个 seq 及之前入账的条目。 */
  as_of?: number;
};
