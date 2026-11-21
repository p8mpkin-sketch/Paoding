// 能力配置 › 候选方案（docs/design/engine-ui §5；09 §12 的异火榜）：所有分析过的外部做法，排除过的也留着理由。
// 数据：GET /v1/fenjue/bang（仓库里的 yihuobang.json，还没写入正式榜时是引擎样例的首批条目）。一期只读：排除写操作在三期。
import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { BangEntry } from "../api/analysis-types";
import { useServices } from "../app/context";
import { navigate } from "../app/router";
import { Mast } from "../kit";
import { BANG_WORD, SLOT_WORD, plain } from "../model/analysis";
import { Plain } from "../ui/registers";
import { CapTabs, St, useAnalyses, waitingOf } from "./Analyses";

type Filter = "all" | "open" | "running" | "done" | "off";
const FILTER_WORD: Record<Filter, string> = { all: "全部", open: "可以分析", running: "进行中", done: "已集成", off: "已排除与不采纳" };
const IN: Record<Filter, (s: string) => boolean> = {
  all: () => true,
  open: (s) => s === "identified" || s === "dry_run",
  running: (s) => s === "selected" || s === "handed_off",
  done: (s) => s === "absorbed",
  off: (s) => s === "rejected" || s === "excluded" || s === "superseded" || s === "reverted",
};
const P = ({ text }: { text: string }) => <Plain text={plain(text)} />;

function useBang() {
  const { api } = useServices();
  const [data, setData] = useState<{ entries: BangEntry[]; source: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    api.bang().then((d) => { if (alive) { setData(d); setError(null); } }, (e: unknown) => { if (alive) setError(e instanceof Error ? e.message : String(e)); });
    return () => { alive = false; };
  }, [api]);
  return { data, error };
}

const word = (s: string) => BANG_WORD[s] ?? { word: s, tone: "" as const };
const last = (e: BangEntry) => e.history.at(-1);
const reuseWord = (e: BangEntry) => (e.license?.reuse === "idea_only" ? "只借思路" : e.license?.reuse ? "可参考原码" : "—");

function Detail({ e, onClose }: { e: BangEntry; onClose: () => void }) {
  const st = word(e.status);
  return (
    <Dialog.Root open onOpenChange={(o) => { if (!o) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="k-overlay" />
        <Dialog.Content className="an-drawer" aria-describedby={undefined} data-bang-detail={e.id}>
          <div className="an-drawer-h">
            <Dialog.Title><span className="k-mono t2">{e.id}</span> <P text={e.title} /></Dialog.Title>
            <Dialog.Close className="k-btn k-btn-bare k-btn-sm" aria-label="关闭"><X aria-hidden="true" /></Dialog.Close>
          </div>
          <div className="an-chips"><St tone={st.tone}>{e.status === "absorbed" && e.jie ? `已集成（v${e.jie}）` : st.word}</St><span className="an-chip">{SLOT_WORD[e.slot] ?? e.slot}{e.also_slots?.length ? ` · 兼及 ${e.also_slots.map((s) => SLOT_WORD[s] ?? s).join("、")}` : ""}</span><span className={`an-chip${e.license?.reuse === "idea_only" ? " need" : ""}`}>{reuseWord(e)}</span></div>
          {e.essence && <section><h4>核心机制</h4><p><P text={e.essence} /></p></section>}
          {e.fusion && <section><h4>融合假设</h4><p><P text={e.fusion} /></p></section>}
          <dl className="an-kv">
            <dt>来源类型</dt><dd><P text={e.source_kind ?? "—"} /></dd>
            <dt>预计内核改动</dt><dd className="k-mono">{e.kernel_lines_expected ?? "—"} 行</dd>
            <dt>能力维</dt><dd className="k-mono">{e.dims?.join("、") ?? "—"}</dd>
            {e.dossier && <><dt>集成记录</dt><dd className="k-mono">{e.dossier}</dd></>}
          </dl>
          <section>
            <h4>分析记录</h4>
            {e.analyses?.length ? (
              <ul className="an-list">{e.analyses.map((a) => <li key={a.run}><span className="k-mono">{a.run}</span>{a.date ? ` · ${a.date}` : ""}{a.outcome ? ` · ${plain(a.outcome)}` : ""}</li>)}</ul>
            ) : <p className="t2">还没有经方案分析看过（首批条目从设计文档迁入）。失败的分析也会留在这里。</p>}
          </section>
          <section>
            <h4>状态史 <span className="t3">只追加</span></h4>
            <ol className="an-hist">{e.history.map((h, i) => <li key={i}><span className="k-mono t3">{h.date}</span> <St tone={word(h.status).tone}>{word(h.status).word}</St>{h.by ? <span className="t2"> · {h.by}</span> : null}{h.note ? <span className="t2"> · <P text={h.note} /></span> : null}</li>)}</ol>
          </section>
          <p className="an-note">“以它为起点分析”“排除…”在三期（经导入命令写入、随 PR 审）。</p>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function Candidates({ id }: { id?: string }) {
  const { data, error } = useBang();
  const an = useAnalyses();
  const [f, setF] = useState<Filter>("all");
  const rows = useMemo(() => (data?.entries ?? []).filter((e) => IN[f](e.status)), [data, f]);
  if (error && !data) return <p className="error">读不到候选方案：<Plain text={error} /></p>;
  if (!data) return <p className="muted">读取中…</p>;
  const sel = id ? data.entries.find((e) => e.id === id) : undefined;
  const count = (k: Filter) => data.entries.filter((e) => IN[k](e.status)).length;
  return (
    <div className="candidates" data-page="candidates">
      <Mast title="能力配置" dek="所有分析过的外部做法都留在这里；排除过的也留着理由，避免同一件事被反复提起。" />
      <CapTabs cur="candidates" waiting={an.data ? waitingOf(an.data.items).length : undefined} candidates={data.entries.length} />
      <div className="tk-tabs an-filter" role="tablist" aria-label="按状态筛选">
        {(Object.keys(FILTER_WORD) as Filter[]).map((k) => (
          <button key={k} type="button" role="tab" aria-selected={f === k} data-bang-filter={k} onClick={() => setF(k)}>{FILTER_WORD[k]}<span className="ct">{count(k)}</span></button>
        ))}
      </div>
      <div className="md-tbl an-bang" role="table" aria-label="候选方案">
        <div className="md-row an-bang-row md-head" role="row">
          <span role="columnheader">编号</span><span role="columnheader">做法</span><span role="columnheader">模块槽</span>
          <span role="columnheader">状态</span><span role="columnheader">许可</span><span role="columnheader" className="r">最近</span>
        </div>
        {rows.length === 0 ? <div className="md-row an-bang-row" role="row"><span role="cell" className="t2">这一类还没有条目。</span></div> : rows.map((e) => {
          const st = word(e.status);
          return (
            <div key={e.id} className="md-row an-bang-row" role="row" data-bang={e.id}>
              <span role="cell" className="k-mono t2">{e.id}</span>
              <span role="cell" className="an-name">
                <button type="button" className="an-link an-strong" data-action="bang-open" onClick={() => navigate({ page: "candidates", id: e.id }, true)}><P text={e.title} /></button>
                {e.essence && <span className="t2"><P text={e.essence} /></span>}
              </span>
              <span role="cell">{SLOT_WORD[e.slot] ?? e.slot}</span>
              <span role="cell"><St tone={st.tone}>{e.status === "absorbed" && e.jie ? `已集成（v${e.jie}）` : st.word}</St></span>
              <span role="cell" className="t2">{reuseWord(e)}</span>
              <span role="cell" className="r k-mono t3">{last(e)?.date ?? "—"}</span>
            </div>
          );
        })}
      </div>
      <p className="an-note">“找点什么分析”从“可以分析”里按优先级取前 3 个，复算后直接进第 1 次确认；排除过的不再自动提起，除非来源或能力配置变了（09 §8.3–8.4）。数据来自 <span className="k-mono">{data.source ?? "—"}</span>。</p>
      {sel && <Detail e={sel} onClose={() => navigate({ page: "candidates" }, true)} />}
    </div>
  );
}
