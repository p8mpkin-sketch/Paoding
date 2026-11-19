// 续期门对话（HMI 设计 §3.10）。四个选项，不设默认选项；关闭是合法输出。
// 续期门随 M1 落地：M0 的图服务对这张卡返回 not_enabled，这里如实显示，不拼一张假的。
import { btnClass } from "../kit";
import { useEffect, useState } from "react";
import { ApiError } from "../api/client";
import { ops } from "../api/ops";
import type { CardResponse, ExtensionFields, Op } from "../api/types";
import { useServices } from "../app/context";
import { shortHash, usd } from "../model/text";
import { Plain } from "./registers";
import { rejectText, useProposal } from "./useProposal";

type Choice = "extend" | "budget_add" | "hint_extend" | "close";

export function ExtensionDialog({ pid, head, canWrite }: { pid: string; head: number; canWrite: boolean }) {
  const { api } = useServices();
  const [card, setCard] = useState<CardResponse<ExtensionFields> | null>(null);
  const [err, setErr] = useState<Error | null>(null);
  const [choice, setChoice] = useState<Choice | null>(null);
  const [amount, setAmount] = useState("");
  const [hint, setHint] = useState("");
  const [reason, setReason] = useState("");
  const { busy, error, done, run } = useProposal(pid);

  useEffect(() => {
    let live = true;
    api.card<ExtensionFields>(pid, "extension", pid).then((c) => live && setCard(c), (e: Error) => live && setErr(e));
    return () => { live = false; };
  }, [api, pid, head]);

  if (err) {
    return err instanceof ApiError && err.code === "not_enabled"
      ? <p className="muted" data-not-enabled>续期门暂不可用：图服务还没有启用这张卡（随 M1 落地）。</p>
      : <p className="error">取不到续期卡：<Plain text={err.message} /></p>;
  }
  if (!card) return <p className="muted">读取续期卡…</p>;
  const f = card.card.fields;
  const seen = { seq: card.as_of, card_hash: card.card_hash };
  const milli = Math.round(Number(amount) * 1000);
  const built: Op[] | null =
    choice === "extend" ? [ops.extend(seen)]
    : choice === "budget_add" ? (Number.isInteger(milli) && milli > 0 ? [ops.budgetAdd(milli)] : null)
    : choice === "hint_extend" ? (hint.trim() ? [ops.hintAdd(hint.trim()), ops.extend(seen)] : null)
    : choice === "close" ? (reason.trim() ? [ops.closeProblem(reason.trim())] : null)
    : null;

  return (
    <article className="card extension" data-card="extension" data-card-hash={card.card_hash}>
      <header><h3>续期门</h3><span className="muted">card_hash <code>{shortHash(card.card_hash)}</code></span></header>
      <p>任务已越过 80% 预算标记，而自 50% 标记以来没有进展。</p>
      <p className="muted">进展的定义：自 50% 标记以来，有带判据的对象新到 E3（观察被重放确认，或带判据的尝试达成）。</p>
      <section>
        <h4>50% 以来新到 E3 的带判据对象</h4>
        {f.progress_since_50.length === 0 ? <p>无</p> : <ul>{f.progress_since_50.map((id) => <li key={id}>{id}</li>)}</ul>}
      </section>
      <section>
        <h4>花费</h4>
        <p>已花 {usd(f.spent_usd_milli)} / 上限 {usd(f.cap_usd_milli)}</p>
        <p className="muted">折损账（割与折）暂不可用。</p>
      </section>
      <section className="decision">
        <h4>决定（没有默认选项）</h4>
        {done ? <p>已提交，事件 seq {done.map((d) => d.seq).join("、")}。</p> : (
          <fieldset disabled={!canWrite || busy}>
            <label><input type="radio" name="ext" checked={choice === "extend"} onChange={() => setChoice("extend")} /> 放行（pd extend）</label>
            <label><input type="radio" name="ext" checked={choice === "budget_add"} onChange={() => setChoice("budget_add")} /> 追加预算（pd budget add）
              {choice === "budget_add" && <input inputMode="decimal" placeholder="美元" value={amount} onChange={(e) => setAmount(e.target.value)} />}
            </label>
            <label><input type="radio" name="ext" checked={choice === "hint_extend"} onChange={() => setChoice("hint_extend")} /> 给出指导后放行
              {choice === "hint_extend" && <textarea maxLength={2000} value={hint} onChange={(e) => setHint(e.target.value)} />}
            </label>
            <label><input type="radio" name="ext" checked={choice === "close"} onChange={() => setChoice("close")} /> 关闭任务并保留余额（终态由图服务按三值给出）
              {choice === "close" && <input placeholder="关闭的理由（必填）" maxLength={2000} value={reason} onChange={(e) => setReason(e.target.value)} />}
            </label>
            <button type="button" className={btnClass("zhu")} data-action="extension-submit" disabled={!built} onClick={() => built && run(built)}>提交这个决定</button>
            {!canWrite && <p className="muted">现在不能决定：人的决定只能针对链头，且连接必须是实时的。</p>}
            {rejectText(error) && <p className="error" data-reject>{rejectText(error)}</p>}
          </fieldset>
        )}
      </section>
    </article>
  );
}
