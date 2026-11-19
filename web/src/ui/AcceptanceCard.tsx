// 人工验收卡（宪章 D3、02 §3.3；地图 Q23）：按开题时登记的验收清单逐条判，绑定所见的收尾卡（seen）。
// 没有默认选项：每一条都要人点“过”或“不过”。全部过才能验收通过（终态 accepted，由图服务关闭任务）；
// 有一条不过只能拒收，拒收须写理由，任务回到人介入。结构检查的结果只是读数，不替人判。
import { useEffect, useState } from "react";
import { ops } from "../api/ops";
import type { AcceptCheck, AcceptanceItem, AcceptRecord, CardResponse } from "../api/types";
import { useServices } from "../app/context";
import { btnClass } from "../kit";
import { shortHash } from "../model/text";
import { Plain } from "./registers";
import { rejectText, useProposal } from "./useProposal";

/** 收尾卡里人工验收那一部分的字段（cards.py 的 closeout，accept=human 时才有）。 */
export type CloseoutAcceptance = {
  /** 四顾清单（地图 Q21）：验收通过之前逐条确认。项名由图服务给出。 */
  items: CloseoutItem[];
  acceptance?: AcceptanceItem[];
  deliverable?: { verdict_seq: number; candidate: string | null } | null;
};

export type CloseoutItem = { item: string; reason?: string; rules?: { resource: string; pattern: string; risk: string }[]; leases?: string[] };

/** 四顾一项的说法，与 pd 的 closeout_word 同一组措辞。 */
export function closeoutWord(c: CloseoutItem): string {
  if (c.item === "scope_granted") return `执行中扩过的权限仍然有效：${(c.rules ?? []).map((r) => `${r.resource} ${r.pattern} ${r.risk}`).join("、")}；确认保留或已另行撤销`;
  if (c.item === "leases_active") return `还有在途会话 ${(c.leases ?? []).join("、")}；确认它们的产出不影响验收`;
  return `交付物以外没有留下影响（容器、文件、外部状态；可逆性 ${c.reason ?? "?"}）`;
}

type Row = { verdict: "pass" | "fail" | null; ref: string; note: string };
const NEED: Record<string, string> = { artifact: "要附交付物（exec 或 input 类产物编号）", note: "要附说明" };

/** 由人在卡上填的内容组装 checks；缺项时返回出错的原因（不替人补）。 */
export function buildChecks(items: AcceptanceItem[], rows: Record<string, Row>): AcceptCheck[] | string {
  const out: AcceptCheck[] = [];
  for (const a of items) {
    const r = rows[a.id];
    if (!r?.verdict) return `${a.id} 还没判`;
    const ref = r.ref.trim(), note = r.note.trim();
    if (r.verdict === "pass" && a.needs === "artifact" && !ref) return `${a.id} 要附交付物`;
    if (r.verdict === "pass" && a.needs === "note" && !note) return `${a.id} 要附说明`;
    out.push({ id: a.id, verdict: r.verdict, ...(ref ? { ref } : {}), ...(note ? { note } : {}) });
  }
  return out;
}

export function AcceptanceCard({ pid, head, canWrite, log = [] }: { pid: string; head: number; canWrite: boolean; log?: AcceptRecord[] }) {
  const { api } = useServices();
  const [card, setCard] = useState<CardResponse<CloseoutAcceptance> | null>(null);
  const [err, setErr] = useState<Error | null>(null);
  const [rows, setRows] = useState<Record<string, Row>>({});
  const [reason, setReason] = useState("");
  const [four, setFour] = useState<string[]>([]);
  const { busy, error, done, run } = useProposal(pid);

  useEffect(() => {
    let live = true;
    api.card<CloseoutAcceptance>(pid, "closeout", pid).then((c) => live && setCard(c), (e: Error) => live && setErr(e));
    return () => { live = false; };
  }, [api, pid, head]);

  if (err) return <p className="error">取不到收尾卡：<Plain text={err.message} /></p>;
  if (!card) return <p className="muted">读取收尾卡…</p>;
  const items = card.card.fields.acceptance ?? [];
  if (items.length === 0) return <p className="muted">这个任务由判定器判定，没有人工验收。</p>;
  const deliv = card.card.fields.deliverable ?? null;
  const seen = { seq: card.as_of, card_hash: card.card_hash };
  const blank: Row = { verdict: null, ref: "", note: "" };
  const set = (id: string, patch: Partial<Row>) => setRows((x) => ({ ...x, [id]: { ...(x[id] ?? blank), ...patch } }));
  const checks = buildChecks(items, rows);
  // 一点“不过”就切到拒收：理由框立刻出现，不等其余条目判完
  const failed = items.filter((a) => rows[a.id]?.verdict === "fail").map((a) => a.id);
  const closeout = card.card.fields.items ?? [];
  const unconfirmed = closeout.filter((c) => !four.includes(c.item)).map((c) => c.item);
  // 关题三步不可跳（AC9.2）：四顾有未确认项时“验收通过”不可用，并指出是哪一项；拒收不需要四顾
  const ready = typeof checks !== "string" && (failed.length === 0 ? unconfirmed.length === 0 : reason.trim() !== "");

  return (
    <article className="card acceptance" data-card="acceptance" data-card-hash={card.card_hash}>
      <header><h3>人工验收</h3><span className="muted">card_hash <code>{shortHash(card.card_hash)}</code></span></header>
      <p>按创建任务时登记的清单逐条判。终态最多为“已验收”（accepted），不提升等级，也不计入判定通过的数。</p>
      {deliv ? (
        <p data-deliverable>待验收的交付物：<code>{deliv.candidate ?? "无"}</code>，结构检查在 seq {deliv.verdict_seq} 给出通过的读数（只是读数，不替你判）。</p>
      ) : <p className="muted" data-deliverable>还没有待验收的交付物：要等结构检查通过（拒收之后要等新的交付物）。</p>}
      <ol className="accept-items">
        {items.map((a) => {
          const r = rows[a.id];
          return (
            <li key={a.id} data-accept-item={a.id}>
              <div><span className="k-mono">{a.id}</span> <Plain text={a.text} /> <span className="t2">（{a.src === "span" ? "原文" : "人写"}{a.needs ? `；${NEED[a.needs]}` : ""}）</span></div>
              <fieldset disabled={!canWrite || busy || !!done || !deliv} className="accept-row">
                <label><input type="radio" name={`acc-${a.id}`} data-verdict="pass" checked={r?.verdict === "pass"} onChange={() => set(a.id, { verdict: "pass" })} /> 过</label>
                <label><input type="radio" name={`acc-${a.id}`} data-verdict="fail" checked={r?.verdict === "fail"} onChange={() => set(a.id, { verdict: "fail" })} /> 不过</label>
                {a.needs === "artifact" && <input placeholder="产物编号，如 a_12" data-ref={a.id} value={r?.ref ?? ""} onChange={(e) => set(a.id, { ref: e.target.value })} />}
                <input placeholder={a.needs === "note" ? "说明（必填）" : "说明（可空）"} maxLength={2000} data-note={a.id} value={r?.note ?? ""} onChange={(e) => set(a.id, { note: e.target.value })} />
              </fieldset>
            </li>
          );
        })}
      </ol>
      {log.length > 0 && (
        <section data-accept-log>
          <h4>历次验收</h4>
          <ul>{log.map((e) => (
            <li key={e.seq}>seq {e.seq} {e.decision === "accept" ? "验收通过" : "拒收"}：{e.checks.map((c) => `${c.id} ${c.verdict === "pass" ? "过" : "不过"}`).join("、")}
              {e.reason && <> · <Plain text={e.reason} /></>}</li>
          ))}</ul>
        </section>
      )}
      {closeout.length > 0 && (
        <section data-closeout>
          <h4>四顾<span className="t2">（验收通过之前逐条确认）</span></h4>
          <ul className="accept-four">
            {closeout.map((c) => (
              <li key={c.item}><label><input type="checkbox" data-four={c.item} checked={four.includes(c.item)} disabled={!canWrite || busy || !!done}
                onChange={(e) => setFour((x) => (e.target.checked ? [...x, c.item] : x.filter((y) => y !== c.item)))} /> <span className="k-mono">{c.item}</span> {closeoutWord(c)}</label></li>
            ))}
          </ul>
        </section>
      )}
      <section className="decision">
        {done ? <p>已提交，事件 seq {done.map((d) => d.seq).join("、")}。</p> : (
          <fieldset disabled={!canWrite || busy || !deliv}>
            {failed.length > 0 && <input placeholder="拒收的理由（必填）" maxLength={2000} data-field="reject-reason" value={reason} onChange={(e) => setReason(e.target.value)} />}
            {failed.length === 0 ? (
              <button type="button" className={btnClass("zhu")} data-action="accept-submit" disabled={!ready} onClick={() => typeof checks !== "string" && run([ops.accept(checks, seen, four.filter((x) => closeout.some((c) => c.item === x)))], "验收")}>验收通过</button>
            ) : (
              <button type="button" className={btnClass("line")} data-action="reject-submit" disabled={!ready} onClick={() => typeof checks !== "string" && run([ops.rejectDelivery(checks, reason.trim(), seen)], "拒收")}>拒收（{failed.join("、")} 不过）</button>
            )}
            {typeof checks === "string" && <span className="t2" data-missing> {checks}</span>}
            {typeof checks !== "string" && failed.length === 0 && unconfirmed.length > 0 && <span className="t2" data-missing> 四顾还没确认：{unconfirmed.join("、")}</span>}
            {!canWrite && <p className="muted">现在不能决定：人的决定只能针对链头，且连接必须是实时的。</p>}
            {rejectText(error) && <p className="error" data-reject>{rejectText(error)}</p>}
          </fieldset>
        )}
      </section>
    </article>
  );
}
