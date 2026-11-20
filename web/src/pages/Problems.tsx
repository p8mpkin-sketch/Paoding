// 任务列表（前端重新设计 v5 第三期）：一张表，按状态分组；搜索、排列、行菜单、选择模式与批量、归档与回收站。
// 列表是 GET /v1/problems 的排版：分组、排序、搜索都只在本机做，不改任何派生量。
// 整理（归档、删除、恢复、改名、置顶）走 curate 操作（软删：账与花费不动）；正在跑的任务删除前先在同一批里关题。
import * as Dialog from "@radix-ui/react-dialog";
import * as Popover from "@radix-ui/react-popover";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MoreHorizontal, RefreshCw, Search } from "lucide-react";
import type { Op, ProblemItem, ProblemsView } from "../api/types";
import { ops } from "../api/ops";
import { newIdemKey } from "../api/client";
import { useServices } from "../app/context";
import { hrefOf, navigate, NO_FILTER, type BankFilter, type Route } from "../app/router";
import { Button, Empty, Mast, btnClass } from "../kit";
import { usd } from "../model/text";
import { StationCell } from "../ui/StationStrip";
import { stationsOf } from "../model/stations";
import { pending, recorded, rejected } from "../ui/feedback";
import { Plain, Text } from "../ui/registers";

export function Link({ to, children, className, onClick, ...data }: { to: Route; children: React.ReactNode; className?: string; onClick?: () => void } & { [k: `data-${string}`]: string }) {
  return <a {...data} className={className} href={hrefOf(to)} onClick={(e) => { onClick?.(); if (e.metaKey || e.ctrlKey || e.shiftKey) return; e.preventDefault(); navigate(to); }}>{children}</a>;
}

/** 读一次题目列表；every 给出时按毫秒轮询（页面不可见时跳过）。reload 立刻重读。 */
export function useProblems(every?: number): { view: ProblemsView | null; error: string | null; reload: () => Promise<void> } {
  const { api } = useServices();
  const [view, setView] = useState<ProblemsView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const live = useRef(true);
  const reload = useCallback(
    () => api.problems().then((v) => { if (live.current) { setView(v); setError(null); } }, (e: Error) => { if (live.current) setError(e.message); }),
    [api],
  );
  useEffect(() => {
    live.current = true;
    void reload();
    if (!every) return () => { live.current = false; };
    const t = setInterval(() => { if (globalThis.document?.visibilityState !== "hidden") void reload(); }, every);
    return () => { live.current = false; clearInterval(t); };
  }, [reload, every]);
  return { view, error, reload };
}

/** 视图：全部 | 进行中 | 已结束 | 归档 | 回收站；旧链接里的终态（solved 等）照样认。 */
export type ListView = "" | "running" | "ended" | "archived" | "trash";
const VIEWS: { v: ListView; word: string }[] = [
  { v: "", word: "全部" }, { v: "running", word: "进行中" }, { v: "ended", word: "已结束" },
];
const SHELVES: { v: ListView; word: string }[] = [{ v: "archived", word: "归档" }, { v: "trash", word: "回收站" }];

const shelfOf = (p: ProblemItem) => p.shelf ?? "active";

/** 任务列表筛选：标题或编号含搜索词（不分大小写）、视图、判定器。纯排版。 */
export function filterBank(items: ProblemItem[], f: BankFilter): ProblemItem[] {
  const q = f.q.trim().toLowerCase();
  const v = f.terminal;
  return items.filter((p) => {
    const sh = shelfOf(p);
    const inView =
      v === "archived" ? sh === "archived" :
      v === "trash" ? sh === "trash" :
      sh !== "active" ? false :
      v === "" ? true :
      v === "running" ? !p.closed :
      v === "ended" ? p.closed :
      p.terminal === v;
    return inView && (!q || p.id.toLowerCase().includes(q) || p.title.value.toLowerCase().includes(q)) && (!f.judge || p.terminal_badge.judge_id === f.judge);
  });
}

export type Group = "need" | "live" | "end";
export const groupOf = (p: ProblemItem): Group => (p.closed ? "end" : p.human_todo > 0 ? "need" : "live");
const GROUPS: { g: Group; word: string; hint?: string }[] = [
  { g: "need", word: "要你处理", hint: "处理完它才能接着做" },
  { g: "live", word: "正在做" },
  { g: "end", word: "已结束" },
];
export type Sort = "group" | "recent" | "cost";
const SORTS: { s: Sort; word: string }[] = [{ s: "group", word: "按状态分组" }, { s: "recent", word: "最近更新" }, { s: "cost", word: "花费从高到低" }];
const lastSeq = (p: ProblemItem) => p.closed_seq ?? p.opened_seq;

/** 排序：置顶的永远在前（分组时在组内最前），其余按所选方式。 */
export function sortRows(items: ProblemItem[], sort: Sort): ProblemItem[] {
  const by = sort === "cost" ? (a: ProblemItem, b: ProblemItem) => b.spent_usd_milli - a.spent_usd_milli : (a: ProblemItem, b: ProblemItem) => lastSeq(b) - lastSeq(a);
  return [...items].sort((a, b) => Number(!!b.pinned) - Number(!!a.pinned) || by(a, b));
}

const END_WORD: Record<string, string> = { solved: "判定通过", accepted: "已验收", delivered: "已交付", unsolved: "没做成" };
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
const dayOf = (ts: number) => { const d = new Date(ts); return `${d.getMonth() + 1}月${d.getDate()}日`; };

function StatusCell({ p }: { p: ProblemItem }) {
  const g = groupOf(p);
  if (shelfOf(p) === "trash") return <span className="tl-st"><i aria-hidden="true" />已删除</span>;
  if (g === "need") return <span className="tl-st need"><i aria-hidden="true" />等你处理</span>;
  if (g === "live") return <span className="tl-st live"><i aria-hidden="true" />执行中</span>;
  const good = p.terminal === "solved" || p.terminal === "accepted";
  return <span className={`tl-st${p.terminal === "delivered" ? " ok" : good ? " ok dim" : ""}`}><i aria-hidden="true" />{END_WORD[p.terminal ?? ""] ?? "已结束"}</span>;
}

type Ask = { ids: string[] } | null;

export function Problems({ filter = NO_FILTER }: { filter?: BankFilter }) {
  const { api, cfg } = useServices();
  const writable = !!cfg.token;
  const { view, error, reload } = useProblems(5000);
  const [q, setQ] = useState(filter.q);
  const [sort, setSort] = useState<Sort>("group");
  const [selMode, setSelMode] = useState(false);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [ask, setAsk] = useState<Ask>(null);
  const [renaming, setRenaming] = useState<ProblemItem | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [busy, setBusy] = useState(false);
  const search = useRef<HTMLInputElement>(null);
  useEffect(() => setQ(filter.q), [filter.q]);
  useEffect(() => { setSel(new Set()); setShowAll(false); }, [filter.terminal]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (e.key !== "/" || e.metaKey || e.ctrlKey || (t && (t.closest("input, textarea, select, [contenteditable]")))) return;
      e.preventDefault(); search.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const set = (patch: Partial<BankFilter>) => navigate({ page: "problems", ...filter, ...patch }, true);
  const items = useMemo(() => view?.items.filter((p) => shelfOf(p) !== "purged") ?? [], [view]);
  const list = useMemo(() => filterBank(items, { ...filter, q }), [items, filter, q]);
  const byId = useMemo(() => new Map(items.map((p) => [p.id, p])), [items]);

  /** 对一组任务逐个提交；每个任务一批（批内依次校验，所以“先关题再进回收站”可以在同一批里）。 */
  async function act(ids: string[], opsOf: (p: ProblemItem) => Op[], what: string) {
    setBusy(true);
    const id = pending(what);
    let ok = 0;
    const fails: string[] = [];
    for (const pid of ids) {
      const p = byId.get(pid);
      if (!p) continue;
      try { await api.propose(pid, opsOf(p), newIdemKey()); ok += 1; }
      catch (e) { fails.push(`${p.title.value}：${(e as Error).message}`); }
    }
    if (fails.length) rejected(id, what, `${ok} 个成功，${fails.length} 个没成：${fails.join("；")}`);
    else recorded(id, what, null);
    setBusy(false);
    setSel(new Set());
    await reload();
  }
  const trash = (ids: string[]) => act(ids, (p) => (p.closed ? [ops.shelve("trash")] : [ops.closeProblem("删除前停下"), ops.shelve("trash")]), ids.length === 1 ? "删除任务" : `删除 ${ids.length} 个任务`);
  const shelve = (ids: string[], to: "active" | "archived", word: string) => act(ids, () => [ops.shelve(to)], ids.length === 1 ? `${word}任务` : `${word} ${ids.length} 个任务`);

  if (error && !view) return <p className="error">读不到任务列表：<Plain text={error} /></p>;
  if (!view) return <p className="muted">读取中…</p>;
  const v = (filter.terminal ?? "") as ListView;
  const count = (x: ListView) => filterBank(items, { q: "", terminal: x, judge: "" }).length;
  const shelfView = v === "archived" || v === "trash";
  const sorted = sortRows(list, sort);
  const toggle = (pid: string) => setSel((s) => { const n = new Set(s); if (n.has(pid)) n.delete(pid); else n.add(pid); return n; });

  const row = (p: ProblemItem) => <Row key={p.id} p={p} selMode={selMode} picked={sel.has(p.id)} onPick={() => toggle(p.id)} writable={writable && !busy}
    onAct={(a) => {
      if (a === "delete") setAsk({ ids: [p.id] });
      else if (a === "rename") setRenaming(p);
      else if (a === "pin") void act([p.id], () => [ops.pin(!p.pinned)], p.pinned ? "取消置顶" : "置顶");
      else if (a === "archive") void shelve([p.id], "archived", "归档");
      else if (a === "restore") void shelve([p.id], "active", shelfOf(p) === "trash" ? "恢复" : "移出归档");
    }} />;

  let body: React.ReactNode;
  if (list.length === 0) {
    body = q.trim()
      ? <Empty title={`没有找到带“${q.trim()}”的任务`} action={<Button tone="line" size="sm" onClick={() => { setQ(""); set({ q: "" }); }} data-action="clear-q">清空搜索</Button>}>只搜标题和编号。</Empty>
      : v === "trash" ? <Empty title="回收站是空的">删除的任务在这里放 30 天，期间可以恢复。</Empty>
      : v === "archived" ? <Empty title="没有归档的任务">归档只是收起来，随时可以移回。</Empty>
      : <Empty title={items.length ? "这一类里还没有任务" : "还没有任务"} action={items.length ? undefined : <Link to={{ page: "new" }} className={btnClass("ink", "sm")}>新建任务</Link>}>{items.length ? "换一个分类看看。" : "说一句要做的事，回车就开始。"}</Empty>;
  } else if (sort !== "group" || shelfView) {
    body = sorted.map(row);
  } else {
    body = GROUPS.map(({ g, word, hint }) => {
      let rows = sorted.filter((p) => groupOf(p) === g);
      if (!rows.length) return null;
      const n = rows.length;
      const cut = g === "end" && !showAll && !q.trim() && v === "" && n > 5;
      if (cut) rows = rows.slice(0, 5);
      return (
        <div key={g} role="rowgroup" data-group={g}>
          <div className="tl-grp" role="row"><span role="columnheader" aria-colspan={7}>{word}<span className="num">{n}</span>{hint && <em>{hint}</em>}</span></div>
          {rows.map(row)}
          {cut && <div className="tl-more" role="row"><span role="cell"><button type="button" className="linkbtn" onClick={() => setShowAll(true)} data-action="show-all">再显示 {n - 5} 个</button></span></div>}
        </div>
      );
    });
  }
  const pickedIds = [...sel].filter((x) => list.some((p) => p.id === x));
  const allPicked = pickedIds.length === list.length && list.length > 0;

  return (
    <div className="problems" data-page="bank">
      <Mast title="任务" dek={shelfView ? (v === "trash" ? "删除的任务在这里放 30 天，可以恢复；到期后工作区文件清掉。已经花掉的钱一直计入读数。" : "归档的任务只是收起来，账和结果都在。") : undefined} />
      <div className="tl-tool">
        <form className="tl-search" role="search" onSubmit={(e) => { e.preventDefault(); set({ q }); }}>
          <Search aria-hidden="true" />
          <input ref={search} type="search" value={q} placeholder="搜标题或编号" aria-label="搜索任务" data-field="q" onChange={(e) => setQ(e.target.value)} onBlur={() => set({ q })} />
          <kbd className="k-kbd" aria-hidden="true">/</kbd>
        </form>
        <select value={sort} aria-label="排列方式" data-field="sort" onChange={(e) => setSort(e.target.value as Sort)} disabled={shelfView}>
          {SORTS.map((s) => <option key={s.s} value={s.s}>{s.word}</option>)}
        </select>
        {writable && <Button tone="line" aria-pressed={selMode} onClick={() => { setSelMode(!selMode); setSel(new Set()); }} data-action="select-mode">{selMode ? "完成" : "选择"}</Button>}
        <span className="tl-live" role="status">
          <span className="tl-dot" aria-hidden="true" />每 5 秒更新
          <button type="button" className="k-btn k-btn-bare k-btn-sm" aria-label="刷新" onClick={() => void reload()} data-action="refresh"><RefreshCw aria-hidden="true" /></button>
        </span>
      </div>
      <div className="tl-tabs" role="tablist" aria-label="分类">
        {VIEWS.map(({ v: x, word }) => (
          <button key={word} type="button" role="tab" aria-selected={v === x} data-tab={x || "all"} onClick={() => set({ terminal: x })}>{word}<span className="num">{count(x)}</span></button>
        ))}
        <span className="grow" />
        {SHELVES.map(({ v: x, word }) => (
          <button key={word} type="button" role="tab" aria-selected={v === x} data-tab={x} onClick={() => set({ terminal: x })}>{word}<span className="num">{count(x)}</span></button>
        ))}
      </div>
      <div className={`tl${selMode ? " selm" : ""}`} role="table" aria-label="任务" data-list>
        <div className="tl-row tl-head" role="row">
          {selMode && <span role="columnheader"><span className="sr-only">选择</span></span>}
          <span role="columnheader">状态</span><span role="columnheader">任务</span><span role="columnheader">站位</span>
          <span role="columnheader" className="r">花费</span><span role="columnheader" className="r">{v === "trash" ? "可恢复至" : "时间"}</span>
          <span role="columnheader"><span className="sr-only">操作</span></span>
        </div>
        {body}
      </div>

      {selMode && (
        <div className="tl-bulk" role="toolbar" aria-label="批量操作" data-bulk>
          <b>{pickedIds.length ? `选了 ${pickedIds.length} 个` : "点左边的方框选任务"}</b>
          <button type="button" onClick={() => setSel(allPicked ? new Set() : new Set(list.map((p) => p.id)))} data-action="select-all">{allPicked ? "全不选" : "全选"}</button>
          <span className="sep" />
          {v === "trash" || v === "archived"
            ? <button type="button" disabled={!pickedIds.length || busy} onClick={() => void shelve(pickedIds, "active", v === "trash" ? "恢复" : "移出归档")} data-action="bulk-restore">{v === "trash" ? "恢复" : "移出归档"}</button>
            : <button type="button" disabled={!pickedIds.length || busy} onClick={() => void shelve(pickedIds, "archived", "归档")} data-action="bulk-archive">归档</button>}
          {v !== "trash" && <button type="button" className="danger" disabled={!pickedIds.length || busy} onClick={() => setAsk({ ids: pickedIds })} data-action="bulk-delete">删除</button>}
          <span className="sep" />
          <button type="button" onClick={() => { setSelMode(false); setSel(new Set()); }}>完成</button>
        </div>
      )}

      <ConfirmDelete ask={ask} byId={byId} onClose={() => setAsk(null)} onYes={async (ids) => { setAsk(null); await trash(ids); setSelMode(false); }} />
      <RenameDialog p={renaming} onClose={() => setRenaming(null)} onSave={async (p, t) => { setRenaming(null); await act([p.id], () => [ops.rename(t)], "改名"); }} />
    </div>
  );
}

type RowAct = "delete" | "rename" | "pin" | "archive" | "restore";

function Row({ p, selMode, picked, onPick, writable, onAct }: { p: ProblemItem; selMode: boolean; picked: boolean; onPick: () => void; writable: boolean; onAct: (a: RowAct) => void }) {
  const g = groupOf(p);
  const sh = shelfOf(p);
  const to: Route = { page: "problem", pid: p.id, asOf: null, node: null };
  const sub =
    sh === "trash" ? (p.trash_until !== null ? `删于${dayOf(p.trash_until - 30 * 86_400_000)}` : "") :
    g === "need" ? `有 ${p.human_todo} 件事等你处理` :
    g === "live" ? `已跑 ${mmss(p.wall.elapsed_s)}${p.active.length ? ` · ${p.active.length} 个会话在做` : ""}` :
    p.authority === "self" ? "结果未经判定" : p.terminal_badge.judge_id ? `由 ${p.terminal_badge.judge_id} 判定` : "";
  const time = sh === "trash" ? (p.trash_until === null ? "—" : `到${dayOf(p.trash_until)}`) : g === "end" ? (p.closed_ts ? dayOf(p.closed_ts) : "—") : mmss(p.wall.elapsed_s);
  const pct = p.cap_usd_milli ? Math.min(100, Math.round((p.spent_usd_milli / p.cap_usd_milli) * 100)) : null;
  return (
    <div className={`tl-row ${g}${picked ? " on" : ""}${sh !== "active" ? " shelved" : ""}`} role="row" data-problem={p.id} data-group-of={g} data-shelf={sh}>
      {selMode && <span role="cell"><input type="checkbox" className="tl-ck" checked={picked} onChange={onPick} aria-label={`选择：${p.title.value}`} data-pick={p.id} /></span>}
      <span role="cell" data-terminal={p.terminal ?? "running"}><StatusCell p={p} /></span>
      <span role="cell" className="tl-main">
        <Link to={to} className="tl-title">{p.pinned && <span className="tl-pin">置顶</span>}<Text t={p.title} block={false} /></Link>
        {sub && <span className="tl-sub">{sub}</span>}
      </span>
      <span role="cell" className="tl-stn"><StationCell st={stationsOf({ closed: p.closed, active: p.active.map((a) => a.kind), todo: p.human_todo })} /></span>
      <span role="cell" className="tl-cost r">
        <span className="k-mono">{usd(p.spent_usd_milli)}{g !== "end" && p.cap_usd_milli !== null && <span className="ink3"> / {usd(p.cap_usd_milli)}</span>}</span>
        {g !== "end" && pct !== null && <span className="tl-meter" aria-hidden="true"><b style={{ width: `${pct}%` }} /></span>}
      </span>
      <span role="cell" className="tl-time r">{time}</span>
      <span role="cell" className="tl-acts">
        {g === "need" && sh === "active" && <Link to={{ page: "inbox" }} className={btnClass("ink", "sm")} data-action="go-handle">去处理</Link>}
        <RowMenu p={p} writable={writable} onAct={onAct} />
      </span>
    </div>
  );
}

function RowMenu({ p, writable, onAct }: { p: ProblemItem; writable: boolean; onAct: (a: RowAct) => void }) {
  const [open, setOpen] = useState(false);
  const sh = shelfOf(p);
  const item = (a: RowAct | "clone", word: string, danger = false) => (
    <button key={a} type="button" role="menuitem" className={danger ? "danger" : undefined} disabled={a !== "clone" && !writable} data-menu={a}
      onClick={() => { setOpen(false); if (a === "clone") navigate({ page: "new", advanced: true, from: p.id }); else onAct(a); }}>{word}</button>
  );
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button type="button" className="k-btn k-btn-bare k-btn-sm tl-moreb" aria-label={`更多操作：${p.title.value}`} data-action="row-menu"><MoreHorizontal aria-hidden="true" /></button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content className="tl-menu" role="menu" align="end" sideOffset={4} data-row-menu={p.id}>
          {sh === "trash" ? item("restore", "恢复") : (
            <>
              {item("rename", "改名")}
              {item("pin", p.pinned ? "取消置顶" : "置顶")}
              {item("clone", "再跑一次")}
              {sh === "archived" ? item("restore", "移出归档") : item("archive", "归档")}
              <hr />
              {item("delete", "删除", true)}
            </>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

function ConfirmDelete({ ask, byId, onClose, onYes }: { ask: Ask; byId: Map<string, ProblemItem>; onClose: () => void; onYes: (ids: string[]) => Promise<void> }) {
  if (!ask) return null;
  const ps = ask.ids.map((x) => byId.get(x)).filter((x): x is ProblemItem => !!x);
  const running = ps.some((p) => !p.closed);
  return (
    <Dialog.Root open onOpenChange={(o) => { if (!o) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="k-overlay" />
        <Dialog.Content className="tl-modal" role="alertdialog" data-confirm-delete aria-describedby="tl-del-note">
          <Dialog.Title>{ps.length === 1 ? "删除这个任务？" : `删除这 ${ps.length} 个任务？`}</Dialog.Title>
          <p className="t2">{ps.map((p) => p.title.value).join("、")}</p>
          <p className="tl-note" id="tl-del-note">任务会进回收站，30 天内可以恢复。到期后工作区文件一起清掉；已经花掉的钱仍然计入读数。{running && "其中有正在跑的任务，会先停下来。"}</p>
          <div className="tl-modal-f">
            <Dialog.Close asChild><Button tone="line">取消</Button></Dialog.Close>
            <Button tone="ink" className="danger" onClick={() => void onYes(ps.map((p) => p.id))} data-action="confirm-delete">删除</Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function RenameDialog({ p, onClose, onSave }: { p: ProblemItem | null; onClose: () => void; onSave: (p: ProblemItem, title: string) => Promise<void> }) {
  const [t, setT] = useState("");
  useEffect(() => setT(p?.title.value ?? ""), [p]);
  if (!p) return null;
  const ok = t.trim() && t.trim() !== p.title.value && t.trim().length <= 200;
  return (
    <Dialog.Root open onOpenChange={(o) => { if (!o) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="k-overlay" />
        <Dialog.Content className="tl-modal" data-rename aria-describedby={undefined}>
          <Dialog.Title>改名</Dialog.Title>
          <form onSubmit={(e) => { e.preventDefault(); if (ok) void onSave(p, t.trim()); }}>
            <label className="tl-f"><span className="sr-only">新名字</span>
              <input value={t} onChange={(e) => setT(e.target.value)} maxLength={200} autoFocus data-field="rename" />
            </label>
            <p className="tl-note">原来的名字会留在记录里。</p>
            <div className="tl-modal-f">
              <Dialog.Close asChild><Button tone="line">取消</Button></Dialog.Close>
              <Button tone="ink" type="submit" disabled={!ok} data-action="save-rename">保存</Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
