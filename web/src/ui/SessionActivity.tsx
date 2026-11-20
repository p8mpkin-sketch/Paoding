// 会话活动（开放道进度可见性；open-lane §3.1“创建后能看到智能体在做什么”）。
// 开放道的图台按设计是空的，进度在会话里：这里排版 GET /v1/leases/{id}/activity 的条目——
// 正在做的工具调用、最近一段自述、工具调用序列、耗时与花费。在途时每几秒按游标取增量。
// 只排版服务端给的字段：耗时取服务端的 elapsed_s，花费优先取 /budget 的按会话一行（与右栏同一口径）。
import { useEffect, useRef, useState } from "react";
import type { ActCall, ActItem, ActResult, SessionActivity as Doc } from "../api/activity-types";
import { useServices } from "../app/context";
import { btnClass } from "../kit";
import { usd } from "../model/text";
import { Plain } from "./registers";
import { LEASE_WORD } from "./Sessions";

export const ACTIVITY_POLL_MS = 3000;
const SHOWN = 12; // 默认只排最近这么多条；其余点开

const mmss = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

type State = { lease: string; doc: Doc | null; items: ActItem[]; error: string | null };

/** 按游标轮询一个会话的活动。会话不在途（服务端 live=false 且租约已结束）时停在最后一次。 */
export function useActivity(lease: string | null, poll: boolean): State {
  const { api } = useServices();
  const [st, setSt] = useState<State>({ lease: lease ?? "", doc: null, items: [], error: null });
  const cursor = useRef(0);
  useEffect(() => {
    cursor.current = 0;
    setSt({ lease: lease ?? "", doc: null, items: [], error: null });
    if (!lease) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        const d = await api.activity(lease, cursor.current);
        if (!alive) return;
        cursor.current = d.next_after;
        setSt((s) => ({ lease, doc: d, items: [...(s.lease === lease ? s.items : []), ...d.items], error: null }));
        if (poll && (d.live || d.active)) timer = setTimeout(tick, ACTIVITY_POLL_MS);
      } catch (e) {
        if (!alive) return;
        setSt((s) => ({ ...s, error: (e as Error).message }));
        if (poll) timer = setTimeout(tick, ACTIVITY_POLL_MS * 2);
      }
    };
    void tick();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [api, lease, poll]);
  return st;
}

function statusWord(d: Doc): string {
  if (d.status === "none") return d.active ? "正在起会话" : "没有留下活动";
  if (d.live) return d.closing ? "收尾中" : d.status === "collecting" ? "在收尾登记" : "在做";
  return d.status === "released" ? "已结束" : `已结束（${d.status}）`;
}

function CallRow({ c, r, now }: { c: ActCall; r: ActResult | undefined; now: boolean }) {
  const state = r ? (r.ok ? "ok" : "bad") : now ? "now" : "gone";
  return (
    <li className={`act-call ${state}`} data-act="call" data-tool={c.tool} data-state={state}>
      <span className="act-mark" aria-hidden="true">{state === "ok" ? "✓" : state === "bad" ? "✗" : state === "now" ? "…" : "·"}</span>
      <b className="k-mono act-tool">{c.tool}</b>
      <code className="act-gist"><Plain text={c.gist} /></code>
      {state === "bad" && r && <span className="sr-only">出错</span>}
      {r && r.gist && (
        <details className="act-out">
          <summary className="t2">{r.ok ? "结果" : "出错"}</summary>
          <pre className="k-mono"><Plain text={r.gist} /></pre>
        </details>
      )}
    </li>
  );
}

/** 条目序列：工具调用与它的结果合成一行；自述单列一行；一轮结束是一条分隔。 */
function Items({ items, now }: { items: ActItem[]; now: ActCall | null }) {
  const [all, setAll] = useState(false);
  const results = new Map(items.filter((x): x is ActResult => x.kind === "result").map((x) => [x.id, x]));
  const rows = items.filter((x) => x.kind !== "result");
  const shown = all ? rows : rows.slice(-SHOWN);
  return (
    <>
      {rows.length > shown.length && (
        <button type="button" className={btnClass("bare", "sm")} data-action="activity-all" onClick={() => setAll(true)}>前面还有 {rows.length - shown.length} 条，展开全部</button>
      )}
      <ol className="act-list" data-act-list>
        {shown.map((x) =>
          x.kind === "call" ? <CallRow key={x.n} c={x} r={results.get(x.id)} now={now?.id === x.id} />
            : x.kind === "say" ? <li key={x.n} className="act-say" data-act="say"><Plain text={x.text} /></li>
              : x.kind === "end" ? <li key={x.n} className="act-end t2" data-act="end">第 {x.round} 轮结束{x.ok ? "" : "（异常）"}</li>
                : null,
        )}
      </ol>
    </>
  );
}

/** 一块面板。spent 由调用方给（/budget 的按会话花费）；没有就用活动端点里端点代理的账。 */
export function SessionActivity({ lease, kind, spent, onClose }: { lease: string; kind: string; spent?: number; onClose?: () => void }) {
  const { doc, items, error } = useActivity(lease, true);
  const live = !!doc && (doc.live || doc.active);
  return (
    <section className="tk-act" aria-label="会话活动" data-activity data-lease={lease} data-live={live}>
      <header className="act-head">
        <h2 className="ws-h">会话活动</h2>
        <span className={`pulse${live ? "" : " off"}`} aria-hidden="true" />
        <b>{LEASE_WORD[kind] ?? kind}</b>
        <span className="k-mono ink3">{lease}</span>
        {doc && <span className="t2" data-act-status>{statusWord(doc)}</span>}
        <span className="grow" />
        {doc && (
          <span className="act-nums k-mono t2">
            <span data-act-elapsed>{mmss(doc.elapsed_s)}</span>
            <span data-act-spent>{usd(spent ?? doc.spent_usd_milli)}</span>
            <span>工具调用 {doc.calls} 次</span>
            {doc.rounds > 1 && <span>第 {doc.rounds} 轮</span>}
          </span>
        )}
        {onClose && <button type="button" className={btnClass("bare", "sm")} data-action="activity-close" onClick={onClose}>收起</button>}
      </header>
      {error && <p className="error t2">读不到会话活动：<Plain text={error} /></p>}
      {!doc && !error && <p className="t2">读取中…</p>}
      {doc && (
        <>
          <div className="act-now" data-act-now>
            <span className="t2">正在做</span>
            {doc.now ? <span><b className="k-mono">{doc.now.tool}</b> <code><Plain text={doc.now.gist} /></code></span>
              : <span className="t2">{live ? (doc.status === "none" ? "会话正在起来" : "在想下一步") : "没有在做的事"}</span>}
          </div>
          {doc.last_say && (
            <blockquote className="reg reg-narrative act-said" data-register="narrative" data-act-said>
              <span className="reg-label">最近自述</span>
              <Plain text={doc.last_say.text} />
            </blockquote>
          )}
          {items.length > 0 ? <Items items={items} now={doc.now} /> : <p className="t2">还没有工具调用。</p>}
        </>
      )}
    </section>
  );
}
