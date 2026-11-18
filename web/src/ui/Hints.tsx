// Hint 注入与效果追溯（HMI 设计 §3.6、§10.3）。Hint 是人的判断，不是证据：
// about 选择器只列论断与 Intent；Hint 本身不出现在任何前提选择器里。
import { useEffect, useState } from "react";
import { ops } from "../api/ops";
import type { HintTrace } from "../api/types";
import { useServices } from "../app/context";
import type { NodeRow } from "../model/viewmodel";
import { visible } from "../model/text";
import { Plain, Text } from "./registers";
import { rejectText, useProposal } from "./useProposal";

const MAX = 2000;

/** about 的候选：按类型过滤，只有论断与 Intent。 */
export function aboutCandidates(rows: NodeRow[]): NodeRow[] {
  return rows.filter((r) => r.kind === "fact" || r.kind === "intent");
}

export function HintInject({ pid, rows, canWrite, onDone }: { pid: string; rows: NodeRow[]; canWrite: boolean; onDone?: () => void }) {
  const [text, setText] = useState("");
  const [about, setAbout] = useState("");
  const { busy, error, done, run } = useProposal(pid);
  const ok = canWrite && !busy && text.trim().length > 0 && text.length <= MAX;
  return (
    <form
      className="card hint-inject" data-card="hint-inject"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!ok) return;
        if (await run([ops.hintAdd(text.trim(), about || undefined)])) { setText(""); setAbout(""); onDone?.(); }
      }}
    >
      <h3>注入 Hint</h3>
      <label>文本（纯文本，上限 {MAX} 字）
        <textarea value={text} maxLength={MAX} onChange={(e) => setText(e.target.value)} disabled={!canWrite} />
      </label>
      <span className="muted">{text.length} / {MAX}</span>
      <label>about（可选，只列论断与 Intent）
        <select value={about} onChange={(e) => setAbout(e.target.value)} disabled={!canWrite} data-about>
          <option value="">不指向节点</option>
          {aboutCandidates(rows).map((r) => <option key={r.id} value={r.id}>{r.id} · {r.kind === "fact" ? "论断" : "Intent"} · {visible(r.title.value).slice(0, 30)}</option>)}
        </select>
      </label>
      <p className="muted">提示：下一个任务包生效，在途会话不受影响。</p>
      <button type="submit" data-action="hint-submit" disabled={!ok}>注入</button>
      {done && <span> 已注入，事件 seq {done[0]?.seq}。</span>}
      {!canWrite && <p className="muted">现在不能注入：写操作只能针对链头，且连接必须是实时的。</p>}
      {rejectText(error) && <p className="error" data-reject>{rejectText(error)}</p>}
    </form>
  );
}

/** 一组 Intent：+ 新增，− 放弃。标题从同一序号的视图模型里取，按它自己的语域显示。 */
function Changes({ added, abandoned, rows }: { added: string[]; abandoned: string[]; rows: ReadonlyMap<string, NodeRow> }) {
  if (added.length + abandoned.length === 0) return <p className="muted">无</p>;
  const line = (sign: string, id: string) => {
    const row = rows.get(id);
    return <li key={sign + id}>{sign} {id} {row && <Text t={row.title} block={false} />}</li>;
  };
  return <ul>{added.map((id) => line("+", id))}{abandoned.map((id) => line("−", id))}</ul>;
}

export function HintTraceCard({ pid, hintId, seq, ts, rows, canWrite }: { pid: string; hintId: string; seq: number; ts: number | null; rows: NodeRow[]; canWrite: boolean }) {
  const { api } = useServices();
  const [t, setT] = useState<HintTrace | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const { busy, error, run } = useProposal(pid);
  useEffect(() => {
    let live = true;
    setT(null);
    api.hintTrace(hintId, seq).then((r) => live && setT(r), (e: Error) => live && setErr(e.message));
    return () => { live = false; };
  }, [api, hintId, seq]);
  if (err) return <p className="error">取不到 Hint 追溯：<Plain text={err} /></p>;
  if (!t) return <p className="muted">读取 Hint 追溯…</p>;
  const byId = new Map(rows.map((r) => [r.id, r]));
  return (
    <article className={`card hint-trace${t.hint.closed ? " closed" : ""}`} data-card="hint-trace">
      <header>
        <h3>Hint {t.hint.id}{t.hint.closed ? `（已关闭${t.closed_seq !== null ? `于 seq ${t.closed_seq}` : ""}）` : ""}</h3>
        {!t.hint.closed && <button type="button" className="btn-small" data-action="hint-close" disabled={!canWrite || busy} onClick={() => run([ops.hintClose(t.hint.id)])}>关闭 Hint</button>}
      </header>
      <Text t={t.hint.text} meta={{ author: t.hint.author, ts, note: t.hint.about ? `about ${t.hint.about}` : undefined }} />
      <div className="trace-cols">
        <section data-trace="temporal">
          <h4>时序关联（之后新增/放弃）</h4>
          <Changes added={t.temporal.added} abandoned={t.temporal.abandoned} rows={byId} />
        </section>
        <section data-trace="exposure">
          <h4>暴露关联（读过它的 Reason）</h4>
          {t.exposure === null ? <p>暂不可用</p> : t.exposure.sessions.length === 0 ? <p className="muted">还没有读过它的 Reason 会话</p> : (
            <>
              <p className="muted">会话 <Plain text={t.exposure.sessions.join("、")} /></p>
              <Changes added={t.exposure.added} abandoned={t.exposure.abandoned} rows={byId} />
            </>
          )}
        </section>
      </div>
      <p className="muted">说明：<Plain text={t.note} />。两列都是关联，不是因果。</p>
      {rejectText(error) && <p className="error" data-reject>{rejectText(error)}</p>}
    </article>
  );
}
