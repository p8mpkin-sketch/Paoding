// 任务库的预览面板（docs/design/pages-v6 §3）：点一行，不离开列表就能看状态、花费、会话、待办与最近几步过程。
// 数据：列表行本身（ProblemItem）+ /status 的会话 + /work 的待办 + 与任务页“过程”同一份轨迹（事件 + 各会话活动）。
import { useEffect, useMemo, useState } from "react";
import type { HumanWorkItem, LeaseRow, ProblemItem } from "../api/types";
import { useServices } from "../app/context";
import { btnClass } from "../kit";
import { buildTrace, type Entry } from "../model/trace";
import { usd } from "../model/text";
import { Link } from "../pages/Problems";
import { Plain, Text } from "./registers";
import { LEASE_WORD } from "./Sessions";
import { WHY } from "./Todo";
import { useEvents } from "./TaskLog";
import { labelOf, useActivities } from "./TaskTrace";

const SHOW = 6;
const AUTH_WORD: Record<string, string> = { local: "判定器", external: "外部判定", human: "人工验收", self: "开放道（不经判定）" };
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
const NO_LEASES: LeaseRow[] = [];

export function TaskPreview({ p, onClose }: { p: ProblemItem; onClose: () => void }) {
  const { api } = useServices();
  const [leases, setLeases] = useState<LeaseRow[] | null>(null);
  const [todo, setTodo] = useState<HumanWorkItem[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const last = p.closed_seq ?? p.opened_seq;
  const tick = `${p.id}|${p.spent_usd_milli}|${p.human_todo}|${p.closed}|${p.active.length}`;
  useEffect(() => {
    let live = true;
    setErr(null);
    api.status(p.id).then((s) => live && setLeases(s.leases), (e: Error) => live && setErr(e.message));
    if (p.human_todo > 0) api.work(p.id).then((w) => live && setTodo(w.items.filter((x): x is HumanWorkItem => x.kind === "human")), () => undefined);
    else setTodo([]);
    return () => { live = false; };
  }, [api, tick]); // eslint-disable-line react-hooks/exhaustive-deps
  const { events, error } = useEvents(p.id, Number.MAX_SAFE_INTEGER, true);
  const { feeds } = useActivities(leases ?? NO_LEASES, null);
  const sig = `${events?.length ?? 0}|${Object.values(feeds).map((f) => f.items.length).join(",")}|${last}`;
  const trace = useMemo(() => (events ? buildTrace(events, feeds) : null), [sig]); // eslint-disable-line react-hooks/exhaustive-deps
  const recent: Entry[] = trace ? trace.entries.filter((x) => x.kind !== "think" && x.kind !== "end").slice(-SHOW) : [];
  const t0 = events?.[0]?.ts ?? 0;
  const active = (leases ?? []).filter((l) => l.active);
  const pct = p.cap_usd_milli ? Math.min(100, Math.round((p.spent_usd_milli * 100) / p.cap_usd_milli)) : null;
  const to = { page: "problem" as const, pid: p.id, asOf: null, node: null };
  return (
    <aside className="tp" aria-label="任务预览" data-preview={p.id}>
      <header className="tp-h">
        <h2><Text t={p.title} block={false} /></h2>
        <button type="button" className={btnClass("bare", "sm")} onClick={onClose} data-action="preview-close">收起</button>
      </header>
      <p className="t2 k-mono">{p.id} · {AUTH_WORD[p.authority] ?? p.authority}</p>
      <dl className="tp-kv">
        <dt>花费</dt>
        <dd><span className="k-mono">{usd(p.spent_usd_milli)}{p.cap_usd_milli !== null && <span className="ink3"> / {usd(p.cap_usd_milli)}</span>}</span>
          {pct !== null && <span className="tl-meter" aria-hidden="true"><b style={{ width: `${pct}%` }} /></span>}</dd>
        <dt>用时</dt><dd className="k-mono">{mmss(p.wall.elapsed_s)}<span className="ink3"> / {mmss(p.wall.cap_s)}</span></dd>
        {trace && trace.totals.turns > 0 && <><dt>模型调用</dt><dd className="k-mono" data-preview-turns>{trace.totals.turns} 次 · 工具 {trace.totals.calls}{trace.totals.failed ? `（失败 ${trace.totals.failed}）` : ""}</dd></>}
        <dt>会话</dt>
        <dd>{leases === null ? <span className="t2">{err ? "读不到会话" : "读取中…"}</span>
          : active.length ? active.map((l) => <span key={l.id} className="tp-sess"><span className="live-dot" aria-hidden="true" />{LEASE_WORD[l.kind] ?? l.kind} <span className="k-mono ink3">{l.id}</span></span>)
            : <span className="t2">没有在途会话（共 {leases.length} 个）</span>}</dd>
      </dl>
      {todo.length > 0 && (
        <section className="tp-sec" data-preview-todo>
          <h3>等你处理</h3>
          <ul>{todo.map((x) => <li key={`${x.why}:${x.target}`}>{WHY[x.why] ?? x.why} <span className="k-mono t2">{x.target}</span></li>)}</ul>
        </section>
      )}
      <section className="tp-sec" data-preview-steps>
        <h3>最近几步</h3>
        {!trace ? <p className="t2">{error ? <>读不到过程：<Plain text={error} /></> : "读取中…"}</p>
          : recent.length === 0 ? <p className="t2">还没有过程。</p> : (
            <ol className="tp-steps">
              {recent.map((x) => { const l = labelOf(x); return (
                <li key={x.key} className={x.state === "bad" ? "bad" : x.state === "now" ? "now" : undefined}>
                  <span className="k-mono t2">{mmss(Math.max(0, Math.floor((x.at - t0) / 1000)))}</span>
                  <b>{l.label}</b>
                  <span className="t2 ell"><Plain text={l.sub} /></span>
                </li>
              ); })}
            </ol>
          )}
      </section>
      <div className="tp-f">
        <Link to={to} className={btnClass("ink", "sm")} data-action="preview-open">打开任务</Link>
      </div>
    </aside>
  );
}
