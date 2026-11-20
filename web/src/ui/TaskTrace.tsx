// 任务页“过程”：全链路追踪（任务详情 v6 §2.2）。把事件账（编排、授权、预算、交付、判定、人的操作）与每个会话的活动
// （思考、模型调用、自述、工具调用与输出）按时间合成一条轨迹，按会话与轮次分组；可筛、可搜、可只看一个会话、可跟到最新。
// 只排版两路数据里已有的字段（合并在 model/trace.ts，纯函数）；访问申请还没批时，就在请求发生的那一行给出处理入口。
import { useEffect, useMemo, useRef, useState } from "react";
import type { ActFeed, Entry, Filter, SessionGroup, Trace } from "../model/trace";
import { buildTrace, dur, FILTER_WORD, FILTERS, matches, STOP_WORD, tok } from "../model/trace";
import type { ActCall, ActEnd, ActThink, ActTurn } from "../api/activity-types";
import type { LeaseRow } from "../api/types";
import { useServices } from "../app/context";
import { btnClass, Kbd } from "../kit";
import { usd } from "../model/text";
import type { ViewModel } from "../model/viewmodel";
import { ACTIVITY_POLL_MS } from "./SessionActivity";
import { Plain } from "./registers";
import { LEASE_WORD } from "./Sessions";
import { stepOf, useEvents } from "./TaskLog";
import { EvidenceDrawer } from "./TaskResult";

const NO_LEASES: LeaseRow[] = [];
const SKIP_KINDS = new Set(["judge", "rejudge"]); // 判定会话在判定箱里跑，没有 CLI 活动
const MAX_LEASES = 60;
const PREVIEW = 400;

type FeedState = ActFeed & { cursor: number; error: string | null; loaded: boolean };

/** 按游标轮询多个会话的活动：只轮询在途的会话，结束的取到底一次。回放（asOf）每个会话取一次，不轮询。 */
export function useActivities(leases: LeaseRow[], asOf: number | null): { feeds: Record<string, ActFeed>; errors: Record<string, string> } {
  const { api } = useServices();
  const store = useRef<{ asOf: number | null; m: Map<string, FeedState> }>({ asOf, m: new Map() });
  const [, bump] = useState(0);
  const want = leases.filter((l) => !SKIP_KINDS.has(l.kind)).slice(-MAX_LEASES);
  const key = `${asOf ?? "live"}|${want.map((l) => `${l.id}:${l.active ? 1 : 0}`).join(",")}`;
  useEffect(() => {
    if (store.current.asOf !== asOf) store.current = { asOf, m: new Map() };
    const m = store.current.m;
    let alive = true;
    const timers: ReturnType<typeof setTimeout>[] = [];
    const pull = async (l: LeaseRow) => {
      const cur = m.get(l.id) ?? { items: [], anchored: null, live: false, now: null, cursor: 0, error: null, loaded: false };
      try {
        const d = await api.activity(l.id, cur.cursor, asOf);
        if (!alive) return;
        const next: FeedState = { items: [...cur.items, ...d.items], anchored: d.anchored_through ?? null, live: asOf === null && (d.live || d.active), now: d.now?.id ?? null, cursor: d.next_after, error: null, loaded: true };
        m.set(l.id, next);
        bump((x) => x + 1);
        if (asOf === null && (d.live || d.active || l.active)) timers.push(setTimeout(() => void pull(l), ACTIVITY_POLL_MS));
      } catch (e) {
        if (!alive) return;
        m.set(l.id, { ...cur, error: (e as Error).message, loaded: true });
        bump((x) => x + 1);
        if (asOf === null && l.active) timers.push(setTimeout(() => void pull(l), ACTIVITY_POLL_MS * 2));
      }
    };
    for (const l of want) {
      const cur = m.get(l.id);
      if (!cur || !cur.loaded || l.active || cur.live) void pull(l);
    }
    return () => { alive = false; timers.forEach(clearTimeout); };
  }, [api, key]); // eslint-disable-line react-hooks/exhaustive-deps
  const feeds: Record<string, ActFeed> = {};
  const errors: Record<string, string> = {};
  for (const [id, f] of store.current.m) {
    if (f.items.length) feeds[id] = f;
    if (f.error) errors[id] = f.error;
  }
  return { feeds, errors };
}

export type TraceData = { trace: Trace | null; error: string | null; actErrors: Record<string, string>; t0: number };

/** 任务页的轨迹：事件（到当前时刻）+ 各会话活动。 */
export function useTrace(pid: string, vm: ViewModel | null, asOf: number | null): TraceData {
  const { events, error } = useEvents(pid, vm?.seq ?? 0, vm !== null);
  const { feeds, errors } = useActivities(vm?.leases ?? NO_LEASES, asOf);
  const sig = Object.entries(feeds).map(([k, f]) => `${k}:${f.items.length}:${f.anchored}:${f.live}`).join(",");
  const trace = useMemo(() => (events ? buildTrace(events, feeds) : null), [events, sig]); // eslint-disable-line react-hooks/exhaustive-deps
  return { trace, error, actErrors: errors, t0: events?.[0]?.ts ?? 0 };
}

const mmss = (ms: number) => { const s = Math.max(0, Math.floor(ms / 1000)); return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`; };
export const kindWord = (k: string) => LEASE_WORD[k] ?? (k === "verify" ? "复核" : k === "recall" ? "回忆" : k);

/** 概要条（§2.1）：会话、模型调用、工具调用（失败）、token、花费；点数字跳到“过程”并套上筛选。 */
export function TraceSummary({ trace, spent, onPick }: { trace: Trace | null; spent: number; onPick: (f: Filter) => void }) {
  if (!trace) return null;
  const t = trace.totals;
  const item = (f: Filter, label: string, value: React.ReactNode, extra?: React.ReactNode) => (
    <button type="button" className="tr-sum-i" data-summary={f} onClick={() => onPick(f)}>
      <span className="t2">{label}</span><b className="k-mono">{value}</b>{extra}
    </button>
  );
  return (
    <div className="tr-sum" data-trace-summary aria-label="概要">
      {item("orch", "会话", t.sessions, t.live > 0 ? <span className="tr-live t2"><i aria-hidden="true" />{t.live} 个在途</span> : null)}
      {item("turn", "模型调用", t.turns)}
      {item("tool", "工具调用", t.calls, t.failed > 0 ? <span className="tr-bad t2">失败 {t.failed}</span> : null)}
      {item("turn", "token 入/出", `${tok(t.tokensIn)} / ${tok(t.tokensOut)}`)}
      <span className="tr-sum-i static"><span className="t2">花费</span><b className="k-mono" data-summary-spent>{usd(spent)}</b></span>
      {t.models.length > 0 && <span className="tr-sum-i static"><span className="t2">模型</span><b className="k-mono">{t.models.join("、")}</b></span>}
    </div>
  );
}

/** 一条的标题与短说明：执行图的节点与检视都用这一份。 */
export function labelOf(x: Entry): { label: string; sub: string } {
  switch (x.kind) {
    case "turn": { const t = x.item as ActTurn | undefined; return t ? { label: "模型调用", sub: `${tok(t.in)}→${tok(t.out)} · ${STOP_WORD[t.stop] ?? t.stop}` } : { label: "模型调用", sub: "" }; }
    case "cost": return { label: "模型调用", sub: `${tok(x.cost!.tokens_in)}→${tok(x.cost!.tokens_out)} · ${usd(x.cost!.usd_milli)}` };
    case "think": return { label: "思考", sub: (x.item as ActThink).redacted ? "已遮蔽" : (x.item as ActThink).text.slice(0, 18) };
    case "say": return { label: "自述", sub: x.text.slice(0, 18) };
    case "call": {
      if (x.item) { const c = x.item as ActCall; return { label: c.tool, sub: c.gist.slice(0, 22) }; }
      const exec = (x.ev?.body as { exec?: { command?: string } } | undefined)?.exec;
      return { label: x.tool ?? "工具", sub: (exec?.command ?? x.text).slice(0, 22) };
    }
    case "file": return { label: "文件", sub: x.artifact ?? "" };
    case "session": return { label: x.ev?.kind === "lease" ? "会话开始" : "会话结束", sub: x.lease ?? "" };
    case "end": return { label: "一轮结束", sub: (x.item as ActEnd).ok ? "" : "异常" };
    default: {
      const s = x.ev ? stepOf(x.ev) : null;
      return { label: s?.k ?? x.kind, sub: x.text.replace(/^\S+\s/, "").slice(0, 20) };
    }
  }
}

const KIND_LABEL: Record<string, string> = { think: "思考", turn: "模型", cost: "模型", say: "自述", call: "工具", end: "轮末", file: "文件" };

type Handlers = { onEvidence: (id: string) => void; onScope?: (requestId: string) => void; pendingScope: Set<string>; expandAll: boolean };

/** 一条的正文；open 为真时把输出、思考全文展开（检视面板用）。 */
export function EntryBody({ x, h, open = false }: { x: Entry; h: Handlers; open?: boolean }) {
  switch (x.kind) {
    case "think": {
      const t = x.item as ActThink;
      if (t.redacted) return <span className="t2">上游遮蔽了这段思考，看不到内容。</span>;
      return (
        <details className="tr-think" open={open || h.expandAll}>
          <summary><Plain text={t.text.length > 90 ? `${t.text.slice(0, 90)}…` : t.text} /></summary>
          {t.text.length > 90 && <p className="tr-think-full"><Plain text={t.text} /></p>}
        </details>
      );
    }
    case "turn": {
      const t = x.item as ActTurn;
      const cut = t.stop === "max_tokens";
      return (
        <span className="tr-turn">
          <b className="k-mono">{t.model || "模型"}</b>
          <span className="k-mono t2">输入 {tok(t.in)} · 输出 {tok(t.out)}{t.cache_read ? ` · 缓存读 ${tok(t.cache_read)}` : ""}{t.cache_write ? ` · 缓存写 ${tok(t.cache_write)}` : ""}</span>
          <span className={`tk-tag${cut ? " need" : ""}`} data-stop={t.stop}>{STOP_WORD[t.stop] ?? (t.stop || "—")}</span>
          {x.cost ? <span className="k-mono" data-turn-cost>{usd(x.cost.usd_milli)}</span> : null}
        </span>
      );
    }
    case "cost": {
      const c = x.cost!;
      return <span className="tr-turn"><b className="k-mono">{c.model || "模型"}</b><span className="k-mono t2">输入 {tok(c.tokens_in)} · 输出 {tok(c.tokens_out)}{c.tokens_cached ? ` · 缓存 ${tok(c.tokens_cached)}` : ""}</span><span className="k-mono">{usd(c.usd_milli)}</span><span className="t2">端点代理的计量</span></span>;
    }
    case "say": return <span className="reg reg-narrative tr-say" data-register="narrative"><Plain text={x.text} /></span>;
    case "end": { const e = x.item as ActEnd; return <span className="t2">第 {e.round} 轮结束{e.ok ? "" : "（异常）"}{e.turns ? ` · CLI 记 ${e.turns} 轮` : ""}{e.ms ? ` · ${dur(e.ms)}` : ""}</span>; }
    case "call":
      if (x.item) {
        const c = x.item as ActCall;
        const r = x.result;
        const out = r?.gist ?? "";
        return (
          <span className="tr-call">
            <span className="tr-call-h">
              <b className="k-mono">{c.tool}</b>
              <code className="tr-gist"><Plain text={c.gist} /></code>
              <span className={`tr-st ${x.state}`} data-call-state={x.state}>{x.state === "now" ? "进行中" : x.state === "ok" ? "成功" : x.state === "bad" ? "出错" : "没等到结果"}</span>
              <span className="k-mono t2">{dur(x.dur)}</span>
              {r?.size !== undefined && <span className="k-mono t2">{r.size} 字</span>}
              {x.artifact && <button type="button" className="chip" data-action="trace-evidence" data-artifact-ref={x.artifact} onClick={() => h.onEvidence(x.artifact!)}>看执行记录<span className="k-mono ink3">{x.artifact}</span></button>}
              {x.anchored === false && <span className="tk-tag t2">未入账</span>}
            </span>
            {out && (
              <details className="tr-out" open={open || h.expandAll}>
                <summary className="t2">{r?.ok ? "输出" : "出错输出"}</summary>
                <pre className="k-mono"><Plain text={out.length > PREVIEW ? `${out.slice(0, PREVIEW)}…` : out} /></pre>
                {(r?.size ?? 0) > out.length && <p className="t2">只显示开头{x.artifact ? "，完整输出在执行记录里" : ""}。</p>}
              </details>
            )}
          </span>
        );
      }
      break;
    default: break;
  }
  if (!x.ev) return null;
  const s = stepOf(x.ev);
  const req = x.ev.kind === "request_scope" ? `r_${x.ev.seq}` : null;
  return (
    <span className="tr-ev">
      {s?.body}
      {s?.art && <button type="button" className="tk-ref" data-ref={s.art} onClick={() => h.onEvidence(s.art!)}>{s.art}</button>}
      {req && h.pendingScope.has(req) && h.onScope && (
        <span className="tr-scope" data-trace-scope={req}>
          <span className="tk-tag need">等你批</span>
          <button type="button" className={btnClass("ink", "sm")} data-action="trace-scope" onClick={() => h.onScope!(req)}>处理这条申请</button>
        </span>
      )}
    </span>
  );
}

function toneOf(x: Entry): string {
  if (x.state === "bad" || x.kind === "alert") return "bad";
  if (x.state === "now") return "live";
  if (x.kind === "think") return "think";
  if (x.kind === "turn" || x.kind === "cost") return "turn";
  if (x.ev) { const s = stepOf(x.ev); return s?.tone ?? ""; }
  return "";
}

function Row({ x, t0, h, sel, onSel }: { x: Entry; t0: number; h: Handlers; sel: boolean; onSel: () => void }) {
  const s = x.ev ? stepOf(x.ev) : null;
  return (
    <li className={`tk-step tr-row ${toneOf(x)}${sel ? " sel" : ""}${x.during ? " during" : ""}`} data-step={x.key} data-kind={x.kind} data-tool={x.tool} onClick={onSel} data-selected={sel}>
      <span className="tm k-mono">{mmss(x.at - t0)}</span>
      <span className="k">{x.during ? "你" : s?.k ?? KIND_LABEL[x.kind] ?? x.kind}</span>
      <span className="b"><EntryBody x={x} h={h} /></span>
    </li>
  );
}

function SessionHead({ g, t0 }: { g: SessionGroup; t0: number }) {
  return (
    <span className="tr-sess-h">
      <span className={`pulse${g.active ? "" : " off"}`} aria-hidden="true" />
      <b>{kindWord(g.kind)}会话</b>
      <span className="k-mono ink3">{g.lease}</span>
      {g.model && <span className="k-mono t2">{g.model}</span>}
      <span className="t2 k-mono">{mmss(g.start - t0)}{g.end !== null ? `–${mmss(g.end - t0)}` : " 起"}</span>
      <span className="t2">{g.active ? "在做" : g.outcome ? `结束（${g.outcome}）` : "已结束"}</span>
      {g.after && <span className="t2">接力自 <span className="k-mono">{g.after}</span></span>}
      <span className="grow" />
      <span className="t2 k-mono">模型 {g.turns} · 工具 {g.calls}{g.failed ? ` · 失败 ${g.failed}` : ""}{g.tokens.in ? ` · ${tok(g.tokens.in)}/${tok(g.tokens.out)}` : ""}{g.usd_milli ? ` · ${usd(g.usd_milli)}` : ""}</span>
    </span>
  );
}

export function TaskTrace({ data, vm, seq, live, filter, onFilter, focus, onScope }: {
  data: TraceData; vm: ViewModel; seq: number; live: boolean;
  filter: Filter; onFilter: (f: Filter) => void;
  /** 从执行图“在过程里定位”过来的条目。 */
  focus?: string | null;
  onScope?: (requestId: string) => void;
}) {
  const { trace, error, actErrors, t0 } = data;
  const [q, setQ] = useState("");
  const [lease, setLease] = useState<string | null>(null);
  const [detail, setDetail] = useState(true);
  const [expandAll, setExpandAll] = useState(false);
  const [follow, setFollow] = useState(true);
  const [sel, setSel] = useState<string | null>(focus ?? null);
  const [ev, setEv] = useState<string | null>(null);
  const listRef = useRef<HTMLOListElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const pendingScope = useMemo(() => new Set(vm.todo.filter((t) => t.why === "scope_request").map((t) => t.target)), [vm.todo]);
  const h: Handlers = { onEvidence: setEv, onScope, pendingScope, expandAll };

  const brief = (x: Entry) => detail || !(x.kind === "think" || x.kind === "turn" || x.kind === "cost" || x.kind === "end");
  const shown = (x: Entry) => brief(x) && matches(x, filter, q.trim(), lease);
  const flat = trace ? trace.entries.filter(shown) : [];
  const flatKeys = flat.map((x) => x.key).join(",");

  useEffect(() => { if (focus) { setSel(focus); setFollow(false); setFilterAll(); } }, [focus]); // eslint-disable-line react-hooks/exhaustive-deps
  const setFilterAll = () => { onFilter("all"); setQ(""); setLease(null); };
  // 选中的条目滚到可见处；跟随最新时滚到最后一条
  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    const target = sel && !follow ? el.querySelector<HTMLElement>(`[data-step="${CSS.escape(sel)}"]`) : live && follow ? [...el.querySelectorAll<HTMLElement>("[data-step]")].at(-1) : null;
    target?.scrollIntoView?.({ block: "nearest" });
  }, [sel, follow, live, flatKeys]);

  // 键盘：j/k 上下一条，Enter 展开，/ 搜索，f 切跟随
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (e.metaKey || e.ctrlKey || e.altKey || (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)))) return;
      const i = flat.findIndex((x) => x.key === sel);
      if (e.key === "j" || e.key === "k") {
        e.preventDefault();
        const n = e.key === "j" ? Math.min(flat.length - 1, i + 1) : Math.max(0, i < 0 ? flat.length - 1 : i - 1);
        if (flat[n]) { setSel(flat[n].key); setFollow(false); }
      } else if (e.key === "Enter" && sel) {
        const d = listRef.current?.querySelector<HTMLDetailsElement>(`[data-step="${CSS.escape(sel)}"] details`);
        if (d) { e.preventDefault(); d.open = !d.open; }
      } else if (e.key === "/") { e.preventDefault(); searchRef.current?.focus(); }
      else if (e.key === "f") { setFollow((v) => !v); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (!trace) return <p className="t2">{error ? <>读不到过程：<Plain text={error} /></> : "读取过程…"}</p>;
  const errs = Object.entries(actErrors);
  const row = (x: Entry) => <Row key={x.key} x={x} t0={t0} h={h} sel={sel === x.key} onSel={() => { setSel(x.key); setFollow(false); }} />;

  return (
    <div className="tr" data-trace data-filter={filter}>
      <div className="tr-bar" role="toolbar" aria-label="筛选过程">
        <div className="tr-filters" role="group" aria-label="类型">
          {FILTERS.filter((f) => f === "all" || trace.counts[f] > 0).map((f) => (
            <button key={f} type="button" className="tr-chip" aria-pressed={filter === f} data-filter={f} onClick={() => onFilter(f)}>
              {FILTER_WORD[f]}<span className="k-mono">{trace.counts[f]}</span>
            </button>
          ))}
        </div>
        <div className="tr-tools">
          <label className="tr-search">
            <span className="sr-only">搜索命令、输出、自述、思考</span>
            <input ref={searchRef} type="search" placeholder="搜索命令、输出、自述、思考" value={q} data-trace-search onChange={(e) => setQ(e.target.value)} />
            <Kbd>/</Kbd>
          </label>
          {trace.sessions.length > 1 && (
            <select aria-label="只看一个会话" value={lease ?? ""} data-trace-lease onChange={(e) => setLease(e.target.value || null)}>
              <option value="">全部会话</option>
              {trace.sessions.map((g) => <option key={g.lease} value={g.lease}>{kindWord(g.kind)} {g.lease}{g.active ? "（在做）" : ""}</option>)}
            </select>
          )}
          <div className="tr-seg" role="group" aria-label="详略">
            <button type="button" aria-pressed={!detail} data-action="trace-brief" onClick={() => setDetail(false)}>概要</button>
            <button type="button" aria-pressed={detail} data-action="trace-detail" onClick={() => setDetail(true)}>详细</button>
          </div>
          <button type="button" className={btnClass("bare", "sm")} aria-pressed={expandAll} data-action="trace-expand" onClick={() => setExpandAll((v) => !v)}>{expandAll ? "全部折起" : "全部展开"}</button>
          {live && (
            <button type="button" className={`tr-follow${follow ? " on" : ""}`} aria-pressed={follow} data-action="trace-follow" onClick={() => setFollow((v) => !v)}>
              <span className="tl-dot" aria-hidden="true" />跟随最新<Kbd>F</Kbd>
            </button>
          )}
        </div>
      </div>
      {errs.length > 0 && <p className="t2 tr-err" data-trace-act-error>有 {errs.length} 个会话的活动读不到（{errs.map(([k, v]) => `${k}：${v}`).join("；")}），下面只排了事件账里的那部分。</p>}
      {flat.length === 0 && <p className="t2" data-trace-empty>{trace.entries.length === 0 ? (live ? "正在起会话…" : "这一刻还没有活动。") : "没有符合筛选的条目。"}<button type="button" className="k-link" onClick={setFilterAll}>清除筛选</button></p>}
      <ol ref={listRef} className="tk-steps tr-list" data-steps data-live={live}>
        {trace.blocks.map((b) => {
          if (b.type === "entry") return shown(b.entry) ? row(b.entry) : null;
          const g = b.group;
          const ents = g.entries.filter(shown);
          if (ents.length === 0 && (filter !== "all" || q || (lease && lease !== g.lease))) return null;
          const many = g.rounds.length > 1;
          return (
            <li key={g.lease} className={`tr-sess${g.active ? " on" : ""}`} data-trace-session={g.lease} data-active={g.active}>
              <details open={g.active || trace.sessions.length <= 3 || !!q || filter !== "all" || g.entries.some((x) => x.key === sel)}>
                <summary><SessionHead g={g} t0={t0} /></summary>
                <ol className="tr-rounds">
                  {g.rounds.map((r) => {
                    const rs = r.entries.filter(shown);
                    if (rs.length === 0) return null;
                    return many ? (
                      <li key={r.n} className="tr-round" data-trace-round={r.n}>
                        <div className="tr-round-h t2">{r.n === 0 ? "会话开始" : `第 ${r.n} 轮 · 模型调用 ${r.turns} · 工具调用 ${r.calls} · ${dur(r.to - r.from)}`}</div>
                        <ol className="tr-list-in">{rs.map(row)}</ol>
                      </li>
                    ) : <li key={r.n} className="tr-round solo"><ol className="tr-list-in">{rs.map(row)}</ol></li>;
                  })}
                </ol>
              </details>
            </li>
          );
        })}
      </ol>
      {trace.entries.length > 2000 && <p className="t2">条目超过 2000 条：完整的日志用命令行 <code>pd log</code> 看。</p>}
      <EvidenceDrawer id={ev} seq={seq} onClose={() => setEv(null)} />
    </div>
  );
}
