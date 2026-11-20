// 任务页的执行流程条（v5 第三期）：这件任务走到哪一步。只读已有投影（status 的道、交付、追问、在途会话、
// /work 的人工项、终态），不推断进度、不读本机时钟。和站位条（stations.ts）同一套输入，只是按人看得懂的步骤说。
import type { Terminal } from "../api/types";

export type FlowState = "done" | "cur" | "todo" | "off";
export type FlowStep = { key: string; word: string; state: FlowState; note?: string };

export type FlowInput = {
  accept: "judge" | "human" | "open";
  closed: boolean;
  terminal: Terminal | null;
  /** 在途会话的种类。 */
  active: readonly string[];
  /** 有过会话（任何种类）。 */
  started: boolean;
  /** 等人的事的 why。 */
  todo: readonly string[];
  /** 开放道：交付次数、最后一次交付的序号与是否带自检；最后一次追问的序号。 */
  deliveries: number;
  lastDeliverySeq: number;
  lastHadSelfCheck: boolean;
  lastFollowUpSeq: number;
  /** 判定道：有过判定裁决。 */
  judged: boolean;
};

const step = (key: string, word: string, state: FlowState, note?: string): FlowStep => ({ key, word, state, ...(note ? { note } : {}) });

/** 当前步之前的都算做完，之后的都还没到。 */
function line(keys: [string, string][], cur: number, done: boolean, extra: Record<string, FlowState> = {}): FlowStep[] {
  return keys.map(([k, w], i) => step(k, w, extra[k] ?? (done || i < cur ? "done" : i === cur ? "cur" : "todo")));
}

export function flowOf(x: FlowInput): FlowStep[] {
  if (x.accept === "open") {
    const keys: [string, string][] = [["understand", "理解任务"], ["work", "动手做"], ["self", "自己查一遍"], ["deliver", "交付"], ["review", "另一个模型复核"], ["you", "你来看"]];
    // 复核会话（地图 Q34）还没有：一直标“未开启”，不算进度
    const extra: Record<string, FlowState> = { review: "off" };
    const asked = x.lastFollowUpSeq > x.lastDeliverySeq; // 追问之后回到动手做
    if (x.closed) return line(keys, keys.length, true, { ...extra, ...(x.lastHadSelfCheck ? {} : { self: "todo" }) });
    if (x.deliveries > 0 && !asked) return line(keys, 5, false, { ...extra, ...(x.lastHadSelfCheck ? {} : { self: "todo" }) });
    if (!x.started) return line(keys, 0, false, extra);
    return line(keys, 1, false, extra);
  }
  const last: [string, string] = x.accept === "human" ? ["you", "你来验收"] : ["end", "结束"];
  const keys: [string, string][] = [["understand", "理解任务"], ["work", "动手做"], ["judge", x.accept === "human" ? "结构检查" : "判定器判定"], last];
  if (x.closed) return line(keys, keys.length, true);
  if (x.todo.includes("acceptance") || x.todo.includes("closeout")) return line(keys, 3, false);
  if (x.active.includes("judge") || x.active.includes("verify")) return line(keys, 2, false);
  if (!x.started) return line(keys, 0, false);
  return line(keys, x.judged && x.active.length === 0 ? 2 : 1, false);
}

/** 流程条当前那一步是不是“正在跑”（有在途会话）。 */
export const flowLive = (x: FlowInput) => !x.closed && x.active.length > 0;
