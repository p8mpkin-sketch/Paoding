// 知识页（前端重新设计 v5 第四期）：资料与记忆两栏。
// 记忆是通鉴从关闭的任务里派生出来的条目（环境事实、走不通的路、花费画像），人只能钉住或遗忘，不能手写；
// 状态（在用 / 闲置 / 核对没过 / 已退役）是服务端算的派生量，页面只排版。钉住与遗忘都要写理由，并交回所看的那张卡的 seen。
// 资料一栏在 KnowledgeSources.tsx（书库：五阶段导入、检索）。
import * as Dialog from "@radix-ui/react-dialog";
import { Plus, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../api/client";
import type { MemCard, MemRow, MemState } from "../api/memory-types";
import { useServices } from "../app/context";
import { navigate } from "../app/router";
import { Button, Empty, Mast } from "../kit";
import { pending, recorded, rejected } from "../ui/feedback";
import { Plain } from "../ui/registers";
import { Sources } from "./KnowledgeSources";
import { Link } from "./Problems";

const KIND_WORD: Record<string, string> = { env_fact: "环境", excluded: "走不通", spend_profile: "花费" };
const STATE_WORD: Record<MemState, { word: string; tone: "ok" | "need" | "" }> = {
  active: { word: "在用", tone: "ok" },
  dormant: { word: "闲置", tone: "" },
  stale: { word: "核对没过", tone: "need" },
  retired: { word: "已退役", tone: "" },
};
const VERDICT_WORD: Record<string, string> = { pass: "核对通过", fail: "核对没过", flaky: "时好时坏" };

const errText = (e: unknown) => (e instanceof ApiError ? e.message : String(e));

/** 状态下面那一行小字：钉住了没有、核对过几次、最近一次的结果。 */
function stateNote(m: MemRow): string {
  const parts: string[] = [];
  if (m.pinned) parts.push("钉住了");
  if (m.kind === "spend_profile") parts.push("不用核对");
  else if (m.recalls.length === 0) parts.push("还没带进过新任务");
  else {
    const last = m.recalls.at(-1)!;
    parts.push(`核对 ${m.recalls.length} 次，最近一次${VERDICT_WORD[last.verdict] ?? last.verdict}`);
  }
  return parts.join(" · ");
}

function Tabs({ tab, memCount, srcCount }: { tab: "sources" | "memory"; memCount: number | null; srcCount: number | null }) {
  return (
    <div className="tk-tabs kn-tabs" role="tablist" aria-label="知识">
      <button type="button" role="tab" aria-selected={tab === "sources"} data-kn-tab="sources" onClick={() => navigate({ page: "knowledge", tab: "sources" })}>
        资料{srcCount !== null && <span className="ct">{srcCount}</span>}
      </button>
      <button type="button" role="tab" aria-selected={tab === "memory"} data-kn-tab="memory" onClick={() => navigate({ page: "knowledge", tab: "memory" })}>
        记忆{memCount !== null && <span className="ct">{memCount}</span>}
      </button>
    </div>
  );
}

function MemRows({ rows, onDecide, writable }: { rows: MemRow[]; onDecide: (m: MemRow, verb: "pin" | "forget") => void; writable: boolean }) {
  return (
    <div className="md-tbl kn-tbl" role="table" aria-label="记忆条目">
      <div className="md-row kn-row md-head" role="row">
        <span role="columnheader">类型</span><span role="columnheader">记下的事</span><span role="columnheader">来自</span>
        <span role="columnheader">状态</span><span role="columnheader"><span className="sr-only">操作</span></span>
      </div>
      {rows.map((m) => {
        const st = STATE_WORD[m.state] ?? { word: m.state, tone: "" };
        const pid = m.source.problem;
        const canPin = writable && !m.pinned && (m.state === "active" || m.state === "dormant");
        return (
          <div key={m.id} className="md-row kn-row" role="row" data-mem={m.id} data-state={m.state} data-pinned={m.pinned}>
            <span role="cell" className="t2">{KIND_WORD[m.kind] ?? m.kind}</span>
            <span role="cell" className="kn-title"><Plain text={m.title} /></span>
            <span role="cell" className="t2 kn-from">{pid ? <Link to={{ page: "problem", pid, asOf: null, node: m.source.node ?? null }}>{pid}</Link> : "—"}</span>
            <span role="cell" className="kn-st"><span className={`md-st ${st.tone}`}><i aria-hidden="true" />{st.word}</span><span className="md-ms">{stateNote(m)}</span></span>
            <span role="cell" className="md-acts">
              {m.state !== "retired" && (
                <>
                  <Button tone="bare" size="sm" disabled={!canPin} onClick={() => onDecide(m, "pin")} data-action="mem-pin"
                    title={m.pinned ? "已经钉住了" : m.state === "stale" ? "核对没过的钉不住" : undefined}>钉住</Button>
                  <Button tone="bare" size="sm" disabled={!writable} onClick={() => onDecide(m, "forget")} data-action="mem-forget">忘掉</Button>
                </>
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
}

const VERB_WORD = { pin: "钉住", forget: "忘掉" } as const;
const VERB_NOTE = {
  pin: "钉住的条目不会因为久不用而闲置；核对没过照样会失效。",
  forget: "忘掉后不再带进新任务，已经开始的任务不受影响。这一步撤不回来。",
} as const;

function DecideDialog({ target, onClose, onDone }: { target: { m: MemRow; verb: "pin" | "forget" } | null; onClose: () => void; onDone: () => void }) {
  const { api } = useServices();
  const [card, setCard] = useState<MemCard | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async (id: string) => {
    setCard(null);
    try { setCard(await api.memoryCard(id)); } catch (e) { setNote(`取不到这条记忆：${errText(e)}`); }
  }, [api]);
  useEffect(() => { setReason(""); setNote(null); if (target) void load(target.m.id); }, [target, load]);
  if (!target) return null;
  const { verb } = target;
  const submit = async () => {
    if (!card) return;
    setBusy(true);
    const t = pending(VERB_WORD[verb]);
    try {
      const r = await api.memoryDecide(card.item.id, verb, reason.trim(), card.seen);
      recorded(t, VERB_WORD[verb], r.results.at(-1)?.seq ?? null);
      onDone();
    } catch (e) {
      if (e instanceof ApiError && e.code === "stale_view") {
        rejected(t, VERB_WORD[verb], "这条记忆刚变了，看一眼最新的再确认");
        setNote("这条记忆刚变了：下面是最新的样子，看过再确认。");
        await load(card.item.id);
      } else rejected(t, VERB_WORD[verb], errText(e));
    } finally { setBusy(false); }
  };
  return (
    <Dialog.Root open onOpenChange={(o) => { if (!o) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="k-overlay" />
        <Dialog.Content className="tl-modal kn-modal" data-mem-decide={verb} aria-describedby={undefined}>
          <header className="kn-modal-h">
            <Dialog.Title>{VERB_WORD[verb]}这条记忆</Dialog.Title>
            <Dialog.Close className="k-btn k-btn-bare k-btn-sm" aria-label="关闭"><X aria-hidden="true" /></Dialog.Close>
          </header>
          {card ? (
            <div className="kn-card" data-mem-card={card.item.id}>
              <p className="kn-card-t"><Plain text={card.item.title} /></p>
              <p className="t2">{KIND_WORD[card.item.kind] ?? card.item.kind} · {STATE_WORD[card.state]?.word ?? card.state}{card.pinned ? " · 钉住了" : ""}{card.item.source.problem ? ` · 来自 ${card.item.source.problem}` : ""}</p>
              {card.recalls.length > 0 && (
                <ul className="kn-recalls">
                  {card.recalls.slice(-5).map((h) => (
                    <li key={`${h.seq}-${h.problem}`}><span className="k-mono t2">{h.problem}</span>{VERDICT_WORD[h.verdict] ?? h.verdict}{h.on_chain ? "，用在了解题链上" : ""}{h.derived ? "（那次任务自己确认的）" : ""}</li>
                  ))}
                </ul>
              )}
            </div>
          ) : <p className="t2">{note ?? "读取中…"}</p>}
          {card && note && <p className="kn-note" role="status">{note}</p>}
          <p className="t2">{VERB_NOTE[verb]}</p>
          <label className="kn-reason">
            <span>理由（必填，会记进记录）</span>
            <textarea rows={2} value={reason} data-field="mem-reason" onChange={(e) => setReason(e.target.value)} />
          </label>
          <footer className="kn-modal-f">
            <Button tone="line" onClick={onClose}>取消</Button>
            <Button tone="ink" disabled={!card || busy || !reason.trim()} onClick={() => void submit()} data-action="confirm-mem">{VERB_WORD[verb]}</Button>
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function Memory({ rows, error, reload }: { rows: MemRow[] | null; error: string | null; reload: () => void }) {
  const { cfg } = useServices();
  const [target, setTarget] = useState<{ m: MemRow; verb: "pin" | "forget" } | null>(null);
  if (!rows) return <p className="t2">{error ? <>读不到记忆：<Plain text={error} /></> : "读取记忆…"}</p>;
  const live = rows.filter((m) => m.state !== "retired");
  const gone = rows.filter((m) => m.state === "retired");
  const writable = !!cfg.token;
  return (
    <section className="kn-pane" data-memory>
      <p className="t2 kn-lede">记忆不用手动导入，任务关闭后自动记下。带进新任务之前会先核对一遍，核不过的不用。</p>
      {!writable && <p className="md-tip">只读：填了人的令牌才能钉住或忘掉。</p>}
      {live.length === 0 ? <Empty title="还没有记忆">有任务关闭后，它从那次的过程里记下环境、走不通的路和花费。</Empty>
        : <MemRows rows={live} writable={writable} onDecide={(m, verb) => setTarget({ m, verb })} />}
      {gone.length > 0 && (
        <details className="kn-gone" data-retired>
          <summary>已退役 {gone.length} 条</summary>
          <MemRows rows={gone} writable={false} onDecide={() => undefined} />
        </details>
      )}
      <DecideDialog target={target} onClose={() => setTarget(null)} onDone={() => { setTarget(null); reload(); }} />
    </section>
  );
}

export function Knowledge({ tab }: { tab: "sources" | "memory" }) {
  const { api, cfg } = useServices();
  const [rows, setRows] = useState<MemRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    api.memory().then((r) => { if (live) { setRows(r.items); setError(null); } }, (e: Error) => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [api, tick]);
  const count = rows ? rows.filter((m) => m.state !== "retired").length : null;
  const [srcCount, setSrcCount] = useState<number | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  return (
    <div className="knowledge" data-page="knowledge" data-tab={tab}>
      <Mast title="知识" dek="庖丁不训练模型。这里放的是它干活时能查的资料，和它从做过的任务里记下的事。"
        actions={tab === "sources" ? <Button tone="ink" disabled={!cfg.token} onClick={() => setImportOpen(true)} data-action="kn-import"><Plus aria-hidden="true" />导入资料</Button> : undefined} />
      <Tabs tab={tab} memCount={count} srcCount={srcCount} />
      {tab === "sources" ? <Sources importOpen={importOpen} setImportOpen={setImportOpen} onCount={setSrcCount} /> : <Memory rows={rows} error={error} reload={() => setTick((n) => n + 1)} />}
    </div>
  );
}
