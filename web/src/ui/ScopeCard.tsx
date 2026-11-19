// 扩权卡（runtime-grants §7；宪章 04 的 Q19 提前到 L1）。字段由图服务投影，前端只排版。
// - 差异视图：新增规则与现有范围并排，不让人读整份 scope；风险的来源照写（风险表第几条，或未命中按缺省 r2）。
// - 批准绑定 card_hash，与审批卡同法：卡片在打开期间变了，标出差异并要求重新确认；服务端以 stale_view 兜底。
// - 风险只可上调：可选的档位由服务端给（display.risk_choices），前端不自己算下限。
// - 原文对照只是字面查找，帮人读，不替人判；理由是申请方（模型）写的，不作证据。
import { useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { ops } from "../api/ops";
import type { Risk, ScopeCardFields, ScopeDisplay, ScopeRule, CardResponse } from "../api/types";
import { useServices } from "../app/context";
import { btnClass } from "../kit";
import { diffPaths } from "../model/diff";
import { mentionsOf, paraMark, profileChanges, riskSource } from "../model/scope";
import { shortHash } from "../model/text";
import { Plain, Text } from "./registers";
import { rejectText, useProposal } from "./useProposal";

type SCard = CardResponse<ScopeCardFields, ScopeDisplay>;
const isCard = (v: unknown): v is SCard => typeof v === "object" && v !== null && "card_hash" in v && "card" in v && "display" in v;
const ruleText = (r: ScopeRule) => `${r.resource}  ${r.pattern || "—"}  ${r.actions.join(",")}`;
const ROLE: Record<string, string> = { bootstrap: "摸底会话", reason: "推理会话", explore: "探索会话" };
const AXIS: Record<string, string> = { info: "信息", judge: "判定", reversibility: "可逆性" };

/** 题面正文：取一次，只在本卡里用来做原文对照。 */
function useStatement(ref: string | null): string | null {
  const { api } = useServices();
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    if (!ref) return;
    let live = true;
    api.artifact(ref).then((a) => api.blob(a.hash)).then(
      (b) => live && setText(new TextDecoder().decode(b)),
      () => live && setText(null),
    );
    return () => { live = false; };
  }, [api, ref]);
  return text;
}

export function ScopeCard({ pid, requestId, head, canWrite, statementRef }: { pid: string; requestId: string; head: number; canWrite: boolean; statementRef?: string }) {
  const { api } = useServices();
  const [seen, setSeen] = useState<SCard | null>(null);
  const [latest, setLatest] = useState<SCard | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [risks, setRisks] = useState<Risk[] | null>(null);
  const { busy, error, done, run } = useProposal(pid);
  const seenRef = useRef(seen);
  seenRef.current = seen;
  const statement = useStatement(statementRef ?? null);

  useEffect(() => {
    let live = true;
    api.card<ScopeCardFields, ScopeDisplay>(pid, "scope", requestId).then(
      (c) => {
        if (!live) return;
        setLatest(c);
        if (!seenRef.current) setSeen(c);
      },
      (e: Error) => live && setLoadErr(e.message),
    );
    return () => { live = false; };
  }, [api, pid, requestId, head]);

  useEffect(() => {
    if (error instanceof ApiError && error.code === "stale_view" && isCard(error.extra)) setLatest(error.extra);
  }, [error]);

  if (loadErr) return <p className="error">取不到扩权卡：<Plain text={loadErr} /></p>;
  if (!seen || !latest) return <p className="muted">读取扩权卡…</p>;

  const f = seen.card.fields;
  const d = seen.display;
  const changed = latest.card_hash !== seen.card_hash;
  const changes = changed ? diffPaths(seen.card.fields, latest.card.fields) : [];
  const decided = d.decision !== null || done !== null;
  const blocked = !canWrite || changed || busy || decided;
  const seenArg = { seq: seen.as_of, card_hash: seen.card_hash };
  const chosen = risks ?? f.rules.map((r) => r.risk);
  const raised = chosen.some((x, k) => x !== f.rules[k].risk);
  const who = d.role ? `${ROLE[d.role] ?? d.role}${d.session ? ` ${d.session}` : ""}` : d.session ? `会话 ${d.session}` : d.by;

  return (
    <article className="card scope-card" data-card="scope" data-card-hash={seen.card_hash}>
      <header>
        <h3>申请访问：{seen.card.target}</h3>
        <span className="muted">申请方 <Plain text={who} /> · card_hash <code>{shortHash(seen.card_hash)}</code> · 所见 seq {seen.as_of}</span>
      </header>

      {changed && (
        <div className="stale" data-stale>
          <strong>卡片在你查看之后变了。</strong>下列字段与你看到的不同，请看完再重新确认：
          <ul>{changes.map((p) => <li key={p}><code>{p}</code></li>)}</ul>
          <button type="button" data-action="reconfirm" onClick={() => { setSeen(latest); setRisks(null); }}>显示最新卡片并重新确认</button>
        </div>
      )}

      <section data-zone="diff">
        <h4>范围</h4>
        <table className="mini scope-table">
          <tbody>
            {f.rules.map((r, k) => (
              <tr key={`n${k}`} data-rule="new">
                <td className="k-mono">新增</td>
                <td className="k-mono"><Plain text={ruleText(r)} /></td>
                <td>风险 {r.risk}<span className="t2" data-risk-source>（{riskSource(d.risk_rows, k)}）</span></td>
              </tr>
            ))}
            {f.scope.map((r, k) => (
              <tr key={`o${k}`} data-rule="held" className="t2">
                <td className="k-mono">现有</td>
                <td className="k-mono"><Plain text={ruleText(r)} /></td>
                <td>{r.risk}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section data-zone="why">
        <h4>理由</h4>
        <Text t={d.why} meta={{ author: who }} />
        {statement !== null && f.rules.map((r) => mentionsOf(statement, r.pattern).map((m) => (
          <p key={`${r.pattern}:${m.para}`} data-mention={m.para}>
            原文提到〔人〕 {paraMark(m.para)} “<Plain text={m.text.length > 120 ? `${m.text.slice(0, 120)}…` : m.text} />”
            {!m.exact && <span className="t2">（只对上主机名）</span>}
          </p>
        )))}
      </section>

      {d.profile && (
        <section data-zone="profile">
          <h4>批准后</h4>
          {(() => {
            const ch = profileChanges(d.profile.before, d.profile.after);
            return ch.length === 0 ? <p className="t2" data-profile-same>画像不变。</p> : (
              <p data-profile-change>{ch.map(([k, a, b]) => `${AXIS[k] ?? k} ${a} → ${b}`).join("；")}</p>
            );
          })()}
          {d.profile.overridden.length > 0 && <p className="t2">人工覆盖过的轴（{d.profile.overridden.join("、")}）照旧盖在上面。</p>}
        </section>
      )}

      {!d.auto && d.blockers.length > 0 && d.decision === null && (
        <section data-zone="blockers">
          <h4>没有自动批准</h4>
          <ul>{d.blockers.map((b) => <li key={b}><Plain text={b} /></li>)}</ul>
        </section>
      )}

      <section data-zone="decision" className="decision">
        <h4>决定</h4>
        {d.decision ? (
          <>
            <p data-decided={d.decision.decision}>
              {d.decision.via === "auto" ? `按练习道信封 v${d.decision.policy_version ?? "?"} 自动批准`
                : d.decision.via === "approval" ? `随尝试 ${d.intent ?? ""} 的审批${d.decision.decision === "approve" ? "批准" : "拒绝"}`
                : `${d.decision.by ?? "人"} ${d.decision.decision === "approve" ? "批准" : "拒绝"}`} · seq {d.decision.seq ?? "—"}
            </p>
            {d.decision.reason.value !== "" && <Text t={d.decision.reason} meta={{ author: d.decision.by ?? "" }} />}
          </>
        ) : done ? (
          <p data-done>已提交，事件 seq {done.map((x) => x.seq).join("、")}。</p>
        ) : d.intent ? (
          <p className="muted" data-via-approval>这条申请随尝试 {d.intent} 而来，在它的审批卡上一起决定。</p>
        ) : (
          <>
            <div className="scope-risk">
              {f.rules.map((r, k) => (
                <label key={k}>{r.pattern} 风险
                  <select data-action="risk" value={chosen[k]} disabled={blocked} onChange={(e) => { const next = [...chosen]; next[k] = e.target.value as Risk; setRisks(next); }}>
                    {d.risk_choices.filter((x) => Number(x[1]) >= Number(r.risk[1])).map((x) => <option key={x} value={x}>{x}{x === r.risk ? "" : "（上调）"}</option>)}
                  </select>
                </label>
              ))}
              <span className="t2">只可上调</span>
            </div>
            <button
              type="button" className={btnClass("zhu")} data-action="approve" disabled={blocked || !d.approve_enabled}
              onClick={() => run([ops.grantScope(seen.card.target, seenArg, raised ? chosen : undefined)], "批准访问")}
            >批准</button>
            <div className="deny">
              <label>拒绝的理由（必填；拒绝后本任务里不能再申请这个地址）<textarea value={reason} maxLength={2000} onChange={(e) => setReason(e.target.value)} disabled={blocked} /></label>
              <button type="button" className={btnClass("line", "sm")} data-action="deny" disabled={blocked || reason.trim() === ""} onClick={() => run([ops.denyScope(seen.card.target, reason.trim(), seenArg)], "拒绝访问")}>拒绝</button>
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
