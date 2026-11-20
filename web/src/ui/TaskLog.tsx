// 任务页“过程”与“文件”两栏（v5 第三期）：本题的审计日志按人看得懂的说法排成步骤，登记过的产物排成文件表。
// 只排版事件体里已有的字段（标题、命令、种类、大小），不推导状态（不内嵌 reducer，H3）；时间取事件的 ts。
import { useEffect, useState } from "react";
import type { Event } from "../api/types";
import { useServices } from "../app/context";
import { btnClass } from "../kit";
import { usd } from "../model/text";
import { Plain, Text } from "./registers";
import { LEASE_WORD } from "./Sessions";
import { ArtifactPreview, EvidenceDrawer } from "./TaskResult";

const PAGE_LIMIT = 10; // 至多读 10 页（每页 1000 条）；更长的日志用时间轴与 pd log

/** 读本题到 seq 为止的全部事件；seq 变了就接着读后面的。 */
export function useEvents(pid: string, seq: number, enabled: boolean): { events: Event[] | null; error: string | null } {
  const { api } = useServices();
  const [events, setEvents] = useState<Event[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    (async () => {
      const out: Event[] = [];
      let after = 0;
      for (let i = 0; i < PAGE_LIMIT; i++) {
        const r = await api.events(pid, after);
        out.push(...r.events);
        if (r.events.length === 0 || r.next_after <= after || r.next_after >= r.head) break;
        after = r.next_after;
      }
      if (live) { setEvents(out.filter((e) => e.seq <= seq)); setError(null); }
    })().catch((e: Error) => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [api, pid, seq, enabled]);
  return { events, error };
}

const mmss = (ms: number) => { const s = Math.max(0, Math.floor(ms / 1000)); return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`; };
const tagged = (src: string, value: string) => ({ src, register: "叙述" as const, value });
const human = (value: string) => ({ src: "hint", register: "人" as const, value });

export type Step = { seq: number; ts: number; k: string; body: React.ReactNode; tone?: "you" | "need" | "ok" | "bad"; art?: string };
type B = Record<string, unknown>;
const str = (x: unknown) => (typeof x === "string" ? x : "");

/** 一条事件怎么说；不值得单列的（花费、刻度、整理）返回 null。 */
export function stepOf(e: Event): Omit<Step, "seq" | "ts"> | null {
  const b = e.body as B;
  const exec = b.exec as { command?: string; exit_code?: number | null } | undefined;
  switch (e.kind) {
    case "open_problem": return { k: "新建", body: <>你新建了这个任务：<Plain text={str(b.title)} /></>, tone: "you" };
    case "lease": return { k: "会话", body: <>开始一个{LEASE_WORD[str(b.kind)] ?? (str(b.kind) === "solve" ? "求解" : str(b.kind))}会话 <span className="k-mono t2">l_{e.seq}</span></> };
    case "release": case "expire_lease": return { k: "会话", body: <>会话 <span className="k-mono t2">{str(b.lease)}</span> 结束{b.outcome ? `（${str(b.outcome)}）` : e.kind === "expire_lease" ? "（超时）" : ""}</> };
    case "register_artifact": {
      const id = `a_${e.seq}`;
      if (b.class === "exec" && exec) return { k: "执行", body: <><code className="tk-cmd">$ <Plain text={exec.command ?? ""} /></code>{exec.exit_code ? <span className="tk-tag need">退出码 {exec.exit_code}</span> : null}</>, art: id };
      if (b.class === "judge") return { k: "判定", body: <>判定器跑完，留了输出</>, art: id };
      if (b.class === "input") return { k: "材料", body: <>登记了一份材料（{Number(b.size ?? 0)} 字节）</>, art: id, tone: "you" };
      if (b.class === "knowledge") return { k: "查资料", body: <>读了一段你给的资料：<Plain text={str((b.knowledge as B | undefined)?.locator)} /></>, art: id };
      return { k: "写", body: <>写了一份 <Plain text={str(b.media_type)} />（{Number(b.size ?? 0)} 字节）</>, art: id };
    }
    case "add_fact": return { k: "得出", body: <Text t={tagged("title", str(b.title))} block={false} /> };
    case "add_intent": return { k: "计划", body: <Text t={tagged("title", str(b.title))} block={false} /> };
    case "hint": return "close" in b ? { k: "指导", body: <>你收回了一条指导</>, tone: "you" } : { k: "指导", body: <Text t={human(str(b.text))} block={false} />, tone: "you" };
    case "approve": return { k: "审批", body: <>你{b.decision === "approve" ? "批准" : "拒绝"}了 <span className="k-mono">{str(b.intent)}</span></>, tone: "you" };
    case "request_scope": return { k: "想访问", body: <>{((b.rules as { pattern: string }[] | undefined) ?? []).map((r) => r.pattern).join("、")}{b.why ? <span className="t2"> · <Plain text={str(b.why)} /></span> : null}</>, tone: "need" };
    case "grant_scope": return { k: "授权", body: <>{b.via === "auto" ? "按白名单自动" : "你"}{b.decision === "approve" ? "允许" : "拒绝"}了访问申请 <span className="k-mono">{str(b.request)}</span></>, tone: b.via === "auto" ? undefined : "you" };
    case "revoke_scope": return { k: "授权", body: <>你撤销了一条授权</>, tone: "you" };
    case "judge_verdict": return { k: "判定", body: <>判定结果：{b.result === "pass" ? "通过" : b.result === "fail" ? "不通过" : "无结论"}</>, tone: b.result === "pass" ? "ok" : b.result === "fail" ? "bad" : undefined };
    case "kb_query": return { k: "查资料", body: <>查了“<Plain text={str(b.query)} />”，命中 {((b.hits as unknown[]) ?? []).length} 段</> };
    case "deliver": return { k: "交付", body: <>交出结果（{b.outcome === "answered" ? "完整回答" : b.outcome === "partial" ? "部分完成" : "受阻"}），附 {((b.claims as unknown[]) ?? []).length} 条主张</>, tone: "ok" };
    case "follow_up": return { k: "追问", body: <><Text t={human(str(b.text))} block={false} />{b.budget_add_usd_milli ? <span className="t2"> · 追加 {usd(Number(b.budget_add_usd_milli))}</span> : null}</>, tone: "you" };
    case "halt": return { k: "叫停", body: <>你叫停了，它会把已有结果交出来</>, tone: "you" };
    case "budget_mark": return { k: "花费", body: <>花到预算的 {Number(b.mark)}%</>, tone: "need" };
    case "budget_add": return { k: "花费", body: <>你追加了 {usd(Number(b.usd_milli))}</>, tone: "you" };
    case "accept": return { k: "验收", body: <>你{b.decision === "accept" ? "验收通过" : "拒收"}</>, tone: "you" };
    case "close_problem": return { k: "结束", body: <>任务关闭{b.feedback === "adopted" ? "，你采纳了结果" : b.feedback === "rejected" ? "，你没有采纳" : ""}</>, tone: "ok" };
    case "alert": case "scope_violation": return { k: "告警", body: <Plain text={str(b.detail ?? b.reason ?? e.kind)} />, tone: "bad" };
    default: return null;
  }
}

export function TaskSteps({ pid, seq, live }: { pid: string; seq: number; live: boolean }) {
  const { events, error } = useEvents(pid, seq, true);
  const [ref, setRef] = useState<string | null>(null);
  if (!events) return <p className="t2">{error ? <>读不到过程：<Plain text={error} /></> : "读取过程…"}</p>;
  const t0 = events[0]?.ts ?? 0;
  const steps: Step[] = events.flatMap((e) => { const s = stepOf(e); return s ? [{ ...s, seq: e.seq, ts: e.ts }] : []; });
  return (
    <>
      <ol className="tk-steps" data-steps data-live={live}>
        {steps.map((s, i) => (
          <li key={s.seq} className={`tk-step${s.tone ? ` ${s.tone}` : ""}${live && i === steps.length - 1 ? " live" : ""}`} data-step={s.seq}>
            <span className="tm k-mono">{mmss(s.ts - t0)}</span>
            <span className="k">{s.k}</span>
            <span className="b">{s.body}{s.art && <button type="button" className="tk-ref" data-ref={s.art} onClick={() => setRef(s.art!)}>{s.art}</button>}</span>
          </li>
        ))}
      </ol>
      <EvidenceDrawer id={ref} seq={seq} onClose={() => setRef(null)} />
    </>
  );
}

const CLASS_WORD: Record<string, string> = { exec: "执行输出", authored: "会话写的", input: "你给的材料", judge: "判定输出", knowledge: "引用的资料" };
const CLASS_ORDER = ["exec", "authored", "input", "judge", "knowledge"];
const size = (n: number) => (n < 1024 ? `${n} B` : n < 1024 * 1024 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`);

/** 文件（任务详情 v6 §2.5）：左边按来源分组的列表，写明产出它的会话与命令；右边是预览。可搜、可只看一个会话、可按时间或大小排。 */
export function TaskFiles({ pid, seq }: { pid: string; seq: number }) {
  const { events, error } = useEvents(pid, seq, true);
  const [ref, setRef] = useState<string | null>(null);
  const [pick, setPick] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [lease, setLease] = useState("");
  const [sort, setSort] = useState<"time" | "size">("time");
  if (!events) return <p className="t2">{error ? <>读不到文件：<Plain text={error} /></> : "读取文件…"}</p>;
  const t0 = events[0]?.ts ?? 0;
  const arts = events.filter((e) => e.kind === "register_artifact").map((e) => {
    const b = e.body as B;
    const exec = b.exec as { command?: string; exit_code?: number | null } | undefined;
    const producer = b.producer as { actor?: string; session?: string } | undefined;
    const sub = exec?.command ?? (b.class === "knowledge" ? str((b.knowledge as B | undefined)?.locator) : str(b.media_type));
    return { id: `a_${e.seq}`, e, cls: str(b.class), size: Number(b.size ?? 0), sub, exit: exec?.exit_code ?? null, session: producer?.session ?? "", actor: producer?.actor ?? e.actor.kind, hash: str(b.hash) };
  });
  if (arts.length === 0) return <p className="t2">还没有登记任何文件。</p>;
  const sessions = [...new Set(arts.map((a) => a.session).filter(Boolean))];
  const needle = q.trim().toLowerCase();
  const shown = arts.filter((a) => (!lease || a.session === lease) && (!needle || `${a.id} ${a.sub} ${a.cls}`.toLowerCase().includes(needle)));
  const sorted = [...shown].sort((a, b) => (sort === "size" ? b.size - a.size : a.e.seq - b.e.seq));
  const groups = CLASS_ORDER.concat([...new Set(arts.map((a) => a.cls))].filter((c) => !CLASS_ORDER.includes(c))).map((c) => ({ c, xs: sorted.filter((a) => a.cls === c) })).filter((g) => g.xs.length > 0);
  const cur = pick && arts.some((a) => a.id === pick) ? pick : groups[0]?.xs[0]?.id ?? null;
  const curA = arts.find((a) => a.id === cur);
  return (
    <div className="tk-fx" data-files-two>
      <div className="tk-fx-l">
        <div className="tk-fx-bar">
          <input type="search" placeholder="搜文件名、命令" value={q} onChange={(e) => setQ(e.target.value)} aria-label="搜文件名、命令" data-file-search />
          {sessions.length > 1 && (
            <select value={lease} onChange={(e) => setLease(e.target.value)} aria-label="只看一个会话" data-file-lease>
              <option value="">全部会话</option>
              {sessions.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          )}
          <select value={sort} onChange={(e) => setSort(e.target.value as "time" | "size")} aria-label="排序" data-file-sort>
            <option value="time">按时间</option><option value="size">按大小</option>
          </select>
        </div>
        <p className="t2 tk-fx-count">{shown.length} / {arts.length} 个文件 · 合计 {size(shown.reduce((a, x) => a + x.size, 0))}</p>
        <div className="tk-files" role="table" aria-label="登记的文件" data-files>
          {groups.map((g) => (
            <div key={g.c} role="rowgroup" className="tk-fgroup" data-file-group={g.c}>
              <div className="tk-fgh" role="row"><span role="columnheader">{CLASS_WORD[g.c] ?? g.c}</span><span className="t2 k-mono">{g.xs.length}</span></div>
              {g.xs.map((a) => (
                <div key={a.id} className={`tk-frow${cur === a.id ? " on" : ""}`} role="row" data-file={a.id} data-selected={cur === a.id} onClick={() => setPick(a.id)}>
                  <span role="cell" className="tk-fname">
                    <span className="k-mono">{a.id}{a.exit ? <span className="tk-tag need"> 退出码 {a.exit}</span> : null}</span>
                    <span className={`t2 tk-fsub${a.cls === "exec" ? " k-mono" : ""}`}><Plain text={a.sub} /></span>
                    <span className="t2 tk-fprov">{a.session ? <>会话 <span className="k-mono">{a.session}</span> · </> : null}{a.actor === "executor" ? "执行层登记" : a.actor === "adapter" ? "会话写入" : a.actor === "judgebox" ? "判定箱登记" : a.actor === "shuku" ? "书库登记" : a.actor === "local" ? "你上传的" : a.actor}</span>
                  </span>
                  <span role="cell" className="r k-mono">{size(a.size)}</span>
                  <span role="cell" className="t2 k-mono">{mmss(a.e.ts - t0)}</span>
                  <span role="cell"><button type="button" className={btnClass("bare", "sm")} data-action="open-file" onClick={(ev) => { ev.stopPropagation(); setRef(a.id); }}>打开</button></span>
                </div>
              ))}
            </div>
          ))}
          {shown.length === 0 && <p className="t2">没有符合的文件。</p>}
        </div>
      </div>
      <section className="tk-fx-r" aria-label="预览" data-file-preview={cur ?? ""}>
        {curA ? (
          <>
            <header className="tk-fx-rh">
              <b className="k-mono">{curA.id}</b>
              <span className="t2">{CLASS_WORD[curA.cls] ?? curA.cls} · {size(curA.size)} · seq {curA.e.seq}</span>
              {curA.hash && <span className="t2 k-mono">sha256 {curA.hash.slice(0, 12)}…</span>}
            </header>
            <ArtifactPreview key={curA.id} id={curA.id} seq={seq} />
          </>
        ) : <p className="t2">选一个文件看内容。</p>}
      </section>
      <EvidenceDrawer id={ref} seq={seq} onClose={() => setRef(null)} />
    </div>
  );
}
