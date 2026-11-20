// 开放道的人的点位（v5 第三期；地图 Q20、Q31、Q32，接口按地图 v0.9 §3.2 ③ 草案）：
// 采纳 / 不采纳（close_problem.feedback，带四顾）、叫停（halt）、追问（follow_up，剩余不够时附追加预算）。
// 每个都是一次提议（与 pd 同一条通道）；页面不推断能不能做，被拒就原样说出图服务的理由。
import * as Dialog from "@radix-ui/react-dialog";
import { Check, Square } from "lucide-react";
import { useEffect, useState } from "react";
import { ApiError } from "../api/client";
import { ops } from "../api/ops";
import type { CardResponse } from "../api/types";
import { useServices } from "../app/context";
import { btnClass } from "../kit";
import { closeoutWord, type CloseoutAcceptance } from "./AcceptanceCard";
import { Plain } from "./registers";
import { rejectText, useProposal } from "./useProposal";

/** 采纳与不采纳：先读收尾卡，四顾有项就逐条确认（与验收同法），再关题并记反馈。 */
export function FeedbackButtons({ pid, head, disabled }: { pid: string; head: number; disabled: boolean }) {
  const { api } = useServices();
  const [ask, setAsk] = useState<"adopted" | "rejected" | null>(null);
  const [card, setCard] = useState<CardResponse<CloseoutAcceptance> | null>(null);
  const [four, setFour] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const { busy, error, run } = useProposal(pid);
  useEffect(() => {
    if (!ask) return;
    let live = true;
    setCard(null); setFour([]);
    api.card<CloseoutAcceptance>(pid, "closeout", pid).then((c) => live && setCard(c), () => live && setCard(null));
    return () => { live = false; };
  }, [api, pid, head, ask]);
  const items = card?.card.fields.items ?? [];
  const left = items.filter((c) => !four.includes(c.item));
  const submit = async () => {
    if (!ask) return;
    const why = reason.trim() || (ask === "adopted" ? "采纳交付" : "不采纳交付");
    const closeout = items.length && card ? { items: four, seen: { seq: card.as_of, card_hash: card.card_hash } } : undefined;
    if (await run([ops.closeWithFeedback(ask, why, closeout)], ask === "adopted" ? "采纳" : "不采纳")) setAsk(null);
  };
  return (
    <>
      <button type="button" className={btnClass("bare", "sm")} data-action="reject-delivery" disabled={disabled} onClick={() => setAsk("rejected")}>不采纳</button>
      <button type="button" className={btnClass("ink", "sm")} data-action="adopt-delivery" disabled={disabled} onClick={() => setAsk("adopted")}><Check aria-hidden="true" />采纳</button>
      <Dialog.Root open={ask !== null} onOpenChange={(o) => { if (!o) setAsk(null); }}>
        <Dialog.Portal>
          <Dialog.Overlay className="k-overlay" />
          <Dialog.Content className="tl-modal" role="alertdialog" data-confirm-feedback={ask ?? ""} aria-describedby="tk-fb-note">
            <Dialog.Title>{ask === "adopted" ? "采纳这次交付并结束任务？" : "不采纳，结束任务？"}</Dialog.Title>
            <p className="tl-note" id="tk-fb-note">{ask === "adopted" ? "记为采纳。" : "记为不采纳。"}任务会关闭，结局仍是“已交付，未经判定”，不计入判定通过的数。想让它接着做，用下面的“接着问”。</p>
            {items.length > 0 && (
              <fieldset className="tk-four" data-closeout>
                <legend>结束前确认</legend>
                {items.map((c) => (
                  <label key={c.item}><input type="checkbox" data-four={c.item} checked={four.includes(c.item)} onChange={(e) => setFour((x) => (e.target.checked ? [...x, c.item] : x.filter((y) => y !== c.item)))} /> {closeoutWord(c)}</label>
                ))}
              </fieldset>
            )}
            <label className="tl-f">说一句为什么（可空）<input value={reason} maxLength={2000} data-field="feedback-reason" onChange={(e) => setReason(e.target.value)} /></label>
            {rejectText(error) && <p className="error" data-reject>{rejectText(error)}</p>}
            <div className="tl-modal-f">
              <Dialog.Close className={btnClass("line", "sm")}>取消</Dialog.Close>
              <button type="button" className={btnClass(ask === "adopted" ? "ink" : "line", "sm")} data-action="confirm-feedback" disabled={busy || !card && items.length > 0 || left.length > 0} onClick={() => void submit()}>
                {ask === "adopted" ? "采纳并结束" : "不采纳并结束"}
              </button>
              {left.length > 0 && <span className="t2"> 还有 {left.length} 项没确认</span>}
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}

/** 叫停：不再派新会话，在途的收到收尾轮，约一分钟内把已有结果交出来；之后还可以接着问。 */
export function HaltButton({ pid, disabled }: { pid: string; disabled: boolean }) {
  const [open, setOpen] = useState(false);
  const { busy, error, run } = useProposal(pid);
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger className={btnClass("line", "sm")} data-action="halt" disabled={disabled}><Square aria-hidden="true" />停下并交付</Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="k-overlay" />
        <Dialog.Content className="tl-modal" role="alertdialog" data-confirm-halt aria-describedby="tk-halt-note">
          <Dialog.Title>停下并交付？</Dialog.Title>
          <p className="tl-note" id="tk-halt-note">它会先把手头的结果整理好交出来，大约 1 分钟；不交的话会直接停掉。交付后你还可以接着问，让它继续。</p>
          {rejectText(error) && <p className="error" data-reject>{rejectText(error)}</p>}
          <div className="tl-modal-f">
            <Dialog.Close className={btnClass("line", "sm")}>继续跑</Dialog.Close>
            <button type="button" className={btnClass("ink", "sm")} data-action="confirm-halt" disabled={busy} onClick={async () => { if (await run([ops.halt("人叫停")], "叫停")) setOpen(false); }}>停下并交付</button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** 底部的输入条：交付之后是“接着问”（follow_up），还在做时是“补充一句”（hint）。 */
export function TaskDock({ pid, head, mode, disabled }: { pid: string; head: number; mode: "follow" | "hint"; disabled: boolean }) {
  const [text, setText] = useState("");
  const [add, setAdd] = useState("");
  const [needAdd, setNeedAdd] = useState(false);
  const { busy, error, run } = useProposal(pid);
  const send = async () => {
    const t = text.trim();
    if (!t) return;
    const milli = Math.round(Number(add) * 1000);
    const op = mode === "hint" ? ops.hintAdd(t) : ops.followUp(t, { seq: head }, needAdd && milli > 0 ? milli : undefined);
    const ok = await run([op], mode === "hint" ? "补充指导" : "追问");
    if (ok) { setText(""); setAdd(""); setNeedAdd(false); }
  };
  useEffect(() => {
    if (error instanceof ApiError && error.code === "over_budget") setNeedAdd(true);
  }, [error]);
  return (
    <div className="tk-dock" data-dock={mode}>
      <form className="tk-follow" onSubmit={(e) => { e.preventDefault(); void send(); }}>
        <label className="sr-only" htmlFor="tk-dock-in">{mode === "hint" ? "补充一句" : "接着问"}</label>
        <input id="tk-dock-in" value={text} maxLength={2000} disabled={disabled || busy} data-field={mode === "hint" ? "dock-hint" : "follow-up"}
          placeholder={mode === "hint" ? "补充一句，比如“只看开源版本”；下一步生效" : "接着问，比如“把 Postgres 后端也测一下”；它会接着之前的工作区做"}
          onChange={(e) => setText(e.target.value)} />
        {needAdd && (
          <label className="tk-add">追加 $<input inputMode="decimal" value={add} data-field="follow-up-add" aria-label="追加预算（美元）" onChange={(e) => setAdd(e.target.value)} /></label>
        )}
        <button type="submit" className={btnClass("ink", "sm")} data-action={mode === "hint" ? "send-hint" : "send-follow-up"} disabled={disabled || busy || !text.trim() || (needAdd && !(Number(add) > 0))}>发送</button>
      </form>
      {rejectText(error) && <p className="error" data-reject><Plain text={rejectText(error)!} />{needAdd && " 填一个追加金额再发。"}</p>}
    </div>
  );
}
