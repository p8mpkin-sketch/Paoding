// 本题的事件序列（只追加），只留时间轴要的那几个字段。前端不解释事件（不内嵌 reducer，H3）：
// 这份序列只用来画时间轴刻度、知道链头在哪。无缺靠哈希链核对（只需记住链尾的哈希），无重靠 seq。
import type { Event, TicksResponse, WireTick } from "../api/types";
import { toWireTick } from "./ticks";

export type PushResult = "ok" | "dup" | "gap";

export class EventLog {
  private list: WireTick[] = [];
  private tailHash: string | null = null;

  get ticks(): readonly WireTick[] {
    return this.list;
  }
  get head(): number {
    return this.list.at(-1)?.seq ?? 0;
  }

  /** 冷启动：用 /ticks 的应答整体替换（也用于落后太多、图服务改发快照之后）。 */
  reset(r: TicksResponse): void {
    this.list = [...r.ticks].sort((a, b) => a.seq - b.seq);
    this.tailHash = r.head_hash;
  }

  push(ev: Event): PushResult {
    const last = this.list.at(-1);
    if (last && ev.seq <= last.seq) return "dup";
    // seq 全局单调、按题不连续，所以缺口只能靠 prev_hash 看出来
    if (last && ev.prev_hash !== this.tailHash) return "gap";
    this.list.push(toWireTick(ev));
    this.tailHash = ev.hash;
    return "ok";
  }

  /** 用 /events?after= 取回的一段补洞；返回是否接上了。 */
  fill(events: Event[]): boolean {
    for (const ev of [...events].sort((a, b) => a.seq - b.seq)) if (this.push(ev) === "gap") return false;
    return true;
  }
}
