// 任务页“过程”与“文件”两栏（v5 第三期）：本题的审计日志按人看得懂的说法排成步骤，登记过的产物排成文件表。
// 只排版事件体里已有的字段（标题、命令、种类、大小），不推导状态（不内嵌 reducer，H3）；时间取事件的 ts。
import { useEffect, useState } from "react";
import type { Event } from "../api/types";
import { useServices } from "../app/context";
import { btnClass } from "../kit";
import { usd } from "../model/text";
import { Plain, Text } from "./registers";
import { LEASE_WORD } from "./Sessions";
import { EvidenceDrawer } from "./TaskResult";

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

type Step = { seq: number; ts: number; k: string; body: React.ReactNode; tone?: "you" | "need" | "ok" | "bad"; art?: string };
type B = Record<string, unknown>;
const str = (x: unknown) => (typeof x === "string" ? x : "");

/** 一条事件怎么说；不值得单列的（花费、刻度、整理）返回 null。 */
function stepOf(e: Event): Omit<Step, "seq" | "ts"> | null {
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

const CLASS_WORD: Record<string, string> = { exec: "执行输出", authored: "会话写的", input: "你给的材料", judge: "判定输出" };

export function TaskFiles({ pid, seq }: { pid: string; seq: number }) {
  const { events, error } = useEvents(pid, seq, true);
  const [ref, setRef] = useState<string | null>(null);
  if (!events) return <p className="t2">{error ? <>读不到文件：<Plain text={error} /></> : "读取文件…"}</p>;
  const t0 = events[0]?.ts ?? 0;
  const arts = events.filter((e) => e.kind === "register_artifact");
  if (arts.length === 0) return <p className="t2">还没有登记任何文件。</p>;
  return (
    <>
      <div className="tk-files" role="table" aria-label="登记的文件" data-files>
        <div className="tk-frow tk-fhead" role="row"><span role="columnheader">文件</span><span role="columnheader">类别</span><span role="columnheader" className="r">大小</span><span role="columnheader">什么时候</span><span role="columnheader"><span className="sr-only">操作</span></span></div>
        {arts.map((e) => {
          const b = e.body as B;
          const exec = b.exec as { command?: string } | undefined;
          const id = `a_${e.seq}`;
          return (
            <div key={id} className="tk-frow" role="row" data-file={id}>
              <span role="cell" className="tk-fname"><span className="k-mono">{id}</span>{exec?.command ? <span className="t2 k-mono tk-fsub"><Plain text={exec.command} /></span> : <span className="t2 tk-fsub"><Plain text={str(b.media_type)} /></span>}</span>
              <span role="cell">{CLASS_WORD[str(b.class)] ?? str(b.class)}</span>
              <span role="cell" className="r k-mono">{Number(b.size ?? 0)} B</span>
              <span role="cell" className="t2">{mmss(e.ts - t0)}</span>
              <span role="cell"><button type="button" className={btnClass("bare", "sm")} data-action="open-file" onClick={() => setRef(id)}>打开</button></span>
            </div>
          );
        })}
      </div>
      <EvidenceDrawer id={ref} seq={seq} onClose={() => setRef(null)} />
    </>
  );
}
