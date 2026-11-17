// 一道题的会话：事件流 + 某个序号的视图模型。不依赖 React，测试直接驱动它。
//
// 实时就是"as_of 跟着链头走"：每到一条事件，按这条事件的 seq 取四份投影。
// 所以实时运行到 s 与冷启动回放到 s 走的是同一条路，视图模型哈希相同（HT-10）。
import type { Api, ApiConfig } from "../api/client";
import { openStream, type StreamHandle } from "../api/stream";
import type { Event } from "../api/types";
import { EventLog } from "../model/eventlog";
import { hashOf } from "../model/hash";
import { buildViewModel, sameSeq, type ViewModel } from "../model/viewmodel";

export type Conn = "connecting" | "live" | "disconnected";
export type SessionState = {
  conn: Conn;
  /** 本机已知的链头。 */
  head: number;
  /** null 即跟随链头；数字即回放于该序号。 */
  asOf: number | null;
  vm: ViewModel | null;
  vmHash: string | null;
  error: string | null;
};

export class ProblemSession {
  readonly log = new EventLog();
  private state: SessionState = { conn: "connecting", head: 0, asOf: null, vm: null, vmHash: null, error: null };
  private listeners = new Set<() => void>();
  private stream: StreamHandle | null = null;
  private ticket = 0;
  private closed = false;
  /** 每个序号上记录过的视图模型哈希（实时与回放共用一张表）。 */
  readonly recorded = new Map<number, string>();
  /** 图服务对同一序号给出的 view_hash 与 state_hash，留作对照。 */
  readonly serverHashes = new Map<number, { status: string; state: string | null }>();

  constructor(
    private api: Api,
    private cfg: ApiConfig,
    readonly pid: string,
    private opts: { asOf?: number | null; wait?: (attempt: number) => Promise<void> } = {},
  ) {
    this.state.asOf = opts.asOf ?? null;
  }

  getState = (): SessionState => this.state;
  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };
  private set(patch: Partial<SessionState>) {
    this.state = { ...this.state, ...patch };
    for (const fn of this.listeners) fn();
  }

  async start(): Promise<void> {
    try {
      await this.catchUp();
      this.set({ head: this.log.head });
      await this.refresh();
    } catch (e) {
      this.set({ error: String((e as Error).message ?? e) });
    }
    if (this.closed) return;
    this.stream = openStream(this.cfg, this.pid, {
      after: this.log.head,
      wait: this.opts.wait,
      onState: (s) => {
        this.set({ conn: s });
        // 重连后补一次：断连期间可能错过事件，流会从 Last-Event-ID 续上，这里只刷新视图
        if (s === "live") void this.refresh();
      },
      onEvent: (ev) => void this.onEvent(ev),
      onSnapshot: () => void this.onSnapshot(),
    });
  }

  private pending: Promise<void> = Promise.resolve();
  private onEvent(ev: Event): Promise<void> {
    // 串行处理，保证补洞与追加的先后
    this.pending = this.pending.then(async () => {
      if (this.log.push(ev) === "gap") {
        try {
          await this.catchUp();
        } catch {
          return;
        }
      }
      this.set({ head: this.log.head });
      if (this.state.asOf === null) await this.refresh();
    });
    return this.pending;
  }

  private onSnapshot(): Promise<void> {
    this.pending = this.pending.then(async () => {
      try {
        await this.catchUp();
      } catch {
        return;
      }
      this.set({ head: this.log.head });
      if (this.state.asOf === null) await this.refresh();
    });
    return this.pending;
  }

  /** 用审计日志端点把本机序列补到链头（分页读，直到读不出新的）。冷启动、缺口、快照帧之后都走它。 */
  private async catchUp(): Promise<void> {
    for (;;) {
      const page = await this.api.events(this.pid, this.log.head);
      if (page.events.length === 0) return;
      if (!this.log.fill(page.events)) throw new Error("事件序列接不上（哈希链断了）");
    }
  }

  /** 等事件处理队列排空（测试用）。 */
  settled(): Promise<void> {
    return this.pending;
  }

  setAsOf(asOf: number | null): Promise<void> {
    this.set({ asOf });
    return this.refresh();
  }

  /** 取当前目标序号（as_of 或链头）的四份投影并拼成视图模型。 */
  async refresh(): Promise<void> {
    const seq = this.state.asOf ?? this.log.head;
    if (seq <= 0) return;
    const ticket = ++this.ticket;
    try {
      const { api, pid } = this;
      const [status, view, budget, work] = await Promise.all([api.status(pid, seq), api.view(pid, seq), api.budget(pid, seq), api.work(pid, seq)]);
      const p = { status, view, budget, work };
      if (!sameSeq(p)) throw new Error("四份投影不在同一序号");
      const vm = buildViewModel(pid, p, this.log.events);
      const vmHash = await hashOf(vm);
      this.recorded.set(vm.seq, vmHash);
      this.serverHashes.set(vm.seq, { status: status.view_hash, state: status.state_hash ?? null });
      if (ticket !== this.ticket || this.closed) return; // 只保留最后一次请求的结果
      this.set({ vm, vmHash, error: null });
    } catch (e) {
      if (ticket === this.ticket) this.set({ error: String((e as Error).message ?? e) });
    }
  }

  close(): void {
    this.closed = true;
    this.stream?.close();
    this.listeners.clear();
  }
}

/** 写操作只能针对链头，且连接必须是实时的（HMI 设计 §10.4、§13.2）。 */
export function canWrite(s: SessionState): boolean {
  return s.conn === "live" && s.asOf === null && s.vm !== null && !s.vm.closed && s.vm.seq === s.head;
}
