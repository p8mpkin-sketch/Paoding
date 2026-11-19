// 审批卡（守门官的载体；HMI 设计 §3.5）。字段由图服务投影，前端只排版。
// - 批准绑定 card_hash（H2）：卡片在打开期间有变化，标出差异并要求重新确认；服务端以 stale_view 兜底。
// - 能不能批准只听服务端的 display.approve_enabled（裁决 004-8、005-3，与 pd 一致）；r2 缺回退声明时卡面醒目标出“未声明回退”，不自己加一道禁用。
// - 估值不作为批准理由：expected_gain 只在折叠区（I8）。审批问的是"可不可以做"，不是"值不值得做"。
import { btnClass } from "../kit";
import { useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { ops } from "../api/ops";
import type { ApprovalDisplay, ApprovalFields, CardResponse, ScopeRule } from "../api/types";
import { useServices } from "../app/context";
import { diffPaths } from "../model/diff";
import { shortHash, usd } from "../model/text";
import { CriterionCard, LevelBadge } from "./criterion";
import { Plain, Text } from "./registers";
import { rejectText, useProposal } from "./useProposal";

type ACard = CardResponse<ApprovalFields, ApprovalDisplay>;
const ruleText = (r: ScopeRule) => `${r.resource}  ${r.pattern}  ${r.actions.join(",")}  ${r.risk}`;
const isCard = (v: unknown): v is ACard => typeof v === "object" && v !== null && "card_hash" in v && "card" in v && "display" in v;

export function ApprovalCard({ pid, intentId, head, canWrite, onInspect }: { pid: string; intentId: string; head: number; canWrite: boolean; onInspect?: (id: string) => void }) {
  const { api } = useServices();
  /** 人确认看过的那张卡；批准带的是它的哈希与它的序号。 */
  const [seen, setSeen] = useState<ACard | null>(null);
  const [latest, setLatest] = useState<ACard | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const { busy, error, done, run } = useProposal(pid);
  const seenRef = useRef(seen);
  seenRef.current = seen;

  // 决策只能针对链头：卡片取自不带 as_of 的端点。链头一动就重取，与已确认的那张比哈希。
  useEffect(() => {
    let live = true;
    api.card<ApprovalFields, ApprovalDisplay>(pid, "approval", intentId).then(
      (c) => {
        if (!live) return;
        setLatest(c);
        if (!seenRef.current) setSeen(c);
      },
      (e: Error) => live && setLoadErr(e.message),
    );
    return () => { live = false; };
  }, [api, pid, intentId, head]);

  // 服务端说 stale_view：它附上的最新卡片就是 latest
  useEffect(() => {
    if (error instanceof ApiError && error.code === "stale_view" && isCard(error.extra)) setLatest(error.extra);
  }, [error]);

  if (loadErr) return <p className="error">取不到审批卡：<Plain text={loadErr} /></p>;
  if (!seen || !latest) return <p className="muted">读取审批卡…</p>;

  const f = seen.card.fields;
  const d = seen.display;
  const changed = latest.card_hash !== seen.card_hash;
  const changes = changed ? diffPaths(seen.card.fields, latest.card.fields) : [];
  const noRollback = f.risk === "r2" && !d.rollback_declared;
  const decided = d.decision !== null || done !== null;
  const blocked = !canWrite || changed || busy || decided;
  const seenArg = { seq: seen.as_of, card_hash: seen.card_hash };
  const flags = new Map(f.premises.map((p) => [p.id, p]));

  return (
    <article className="card approval" data-card="approval" data-card-hash={seen.card_hash}>
      <header>
        <h3>审批：{seen.card.target}</h3>
        <span className="muted">card_hash <code>{shortHash(seen.card_hash)}</code> · 所见 seq {seen.as_of}</span>
        {noRollback && <span className="badge badge-warn" data-flag="no-rollback">r2 · 未声明回退</span>}
      </header>

      {changed && (
        <div className="stale" data-stale>
          <strong>卡片在你查看之后变了。</strong>下列字段与你看到的不同，请看完再重新确认：
          <ul>{changes.map((p) => <li key={p}><code>{p}</code></li>)}</ul>
          <button type="button" data-action="reconfirm" onClick={() => setSeen(latest)}>显示最新卡片并重新确认</button>
        </div>
      )}

      <section data-zone="action">
        <h4>动作</h4>
        <Text t={d.title} />
        <Text t={d.summary} />
        <dl className="kv">
          <dt>risk</dt><dd>{f.risk}</dd>
          <dt>预留预算</dt><dd>{usd(d.reserve.usd_milli)} · {d.reserve.wall_s}s</dd>
        </dl>
        <p className="muted"><Plain text={d.lease_note} />：会话结束后再次执行需要新的批准。</p>
      </section>

      <section data-zone="rollback">
        <h4>回退</h4>
        {d.rollback_declared && d.rollback
          ? <Text t={d.rollback} />
          : <p data-no-rollback className={noRollback ? "warn" : undefined}>未声明回退{noRollback ? "。这是 r2 动作：批准前请确认出了问题怎么收回。" : "。"}</p>}
      </section>

      <section data-zone="prediction">
        <h4>结果预测</h4>
        {d.predicate ? <CriterionCard p={d.predicate} seq={seen.as_of} /> : <p className="muted">这次尝试不带 done 判据。</p>}
        <p>所检验的论断：{f.tests.length ? f.tests.join("、") : "无"}</p>
      </section>

      <section data-zone="premises">
        <h4>前提</h4>
        {d.premises.length === 0 ? <p className="muted">无</p> : (
          <table className="mini">
            <thead><tr><th>前提</th><th>等级</th><th>标题</th><th>标记</th></tr></thead>
            <tbody>
              {d.premises.map((p) => {
                const g = flags.get(p.id);
                return (
                  <tr key={p.id} data-premise={p.id}>
                    <td>{onInspect ? <button type="button" className="chip" onClick={() => onInspect(p.id)}>{p.id}</button> : p.id}</td>
                    <td><LevelBadge level={p.level} word={p.level_word ?? "无等级"} /></td>
                    <td><Text t={p.title} block={false} /></td>
                    <td>{g ? [g.controlled && "带对照", g.disputed && "争议", g.unstable && "unstable", g.stale && "stale", g.waived && "已有豁免"].filter(Boolean).join(" · ") || "—" : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      <section data-zone="disputes">
        <h4>争议</h4>
        {d.disputes.length === 0 ? <p>无</p> : <ul>{d.disputes.map((c, i) => <li key={i}><code><Plain text={JSON.stringify(c)} /></code></li>)}</ul>}
      </section>

      <section data-zone="scope">
        <h4>范围</h4>
        {d.needs_scope.length === 0 ? <p className="muted">不申请扩大授权范围。</p> : (
          <pre className="scope-diff">{[...d.scope.map((r) => `  ${ruleText(r)}`), ...d.needs_scope.map((r) => `+ ${ruleText(r)}`)].join("\n")}</pre>
        )}
      </section>

      {d.expected_gain && (
        <details data-zone="estimate">
          <summary className="muted">估值（不是批准理由）</summary>
          <Text t={d.expected_gain} meta={{ what: "期望增益" }} />
        </details>
      )}

      <section data-zone="decision" className="decision">
        <h4>决定</h4>
        {d.decision ? (
          <>
            <p>已有决定：{d.decision.decision === "approve" ? "批准" : "拒绝"} · seq {d.decision.seq}</p>
            {d.decision.reason.value !== "" && <Text t={d.decision.reason} meta={{ author: d.decision.by }} />}
          </>
        ) : done ? (
          <p data-done>已提交，事件 seq {done.map((x) => x.seq).join("、")}。</p>
        ) : (
          <>
            <button
              type="button" className={btnClass("zhu")} data-action="approve" disabled={blocked || !d.approve_enabled}
              onClick={() => run([ops.approve(seen.card.target, seenArg)])}
            >批准（只管一次会话）</button>
            <div className="deny">
              <label>拒绝的理由（必填）<textarea value={reason} maxLength={2000} onChange={(e) => setReason(e.target.value)} disabled={blocked} /></label>
              <button type="button" className={btnClass("line", "sm")} data-action="deny" disabled={blocked || reason.trim() === ""} onClick={() => run([ops.deny(seen.card.target, reason.trim(), seenArg)])}>拒绝</button>
            </div>
            {!d.approve_enabled && <p className="muted" data-approve-disabled>图服务标明这张卡现在不能批准。</p>}
            {!canWrite && <p className="muted">现在不能决定：人的决定只能针对链头，且连接必须是实时的。</p>}
            {rejectText(error) && <p className="error" data-reject>{rejectText(error)}</p>}
          </>
        )}
      </section>
    </article>
  );
}
