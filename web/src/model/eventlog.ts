// 本题的事件序列（只追加）。前端不解释事件（不内嵌 reducer，H3）：
// 这份序列只用来画时间轴刻度、知道链头在哪。无缺靠哈希链核对，无重靠 seq。
import type { Event } from "../api/types";

export type PushResult = "ok" | "dup" | "gap";

export class EventLog {
  private list: Event[] = [];

  get events(): readonly Event[] {
    return this.list;
  }
  get head(): number {
    return this.list.at(-1)?.seq ?? 0;
  }

  push(ev: Event): PushResult {
    const last = this.list.at(-1);
    if (last && ev.seq <= last.seq) return "dup";
    // seq 全局单调、按题不连续，所以缺口只能靠 prev_hash 看出来
    if (last && ev.prev_hash !== last.hash) return "gap";
    this.list.push(ev);
    return "ok";
  }

  /** 用 /events?after= 取回的一段补洞；返回是否接上了。 */
  fill(events: Event[]): boolean {
    for (const ev of [...events].sort((a, b) => a.seq - b.seq)) if (this.push(ev) === "gap") return false;
    return true;
  }
}
