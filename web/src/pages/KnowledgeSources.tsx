// 知识页的资料一栏（v5 第四期，资料库第一期）：正在导入、已有资料、“试一下”、导入抽屉。
// 后端是书库（scripts/knowledge_hub.py）：导入一次推进一步，关掉页面也继续；页面在有作业时每 2 秒读一次。
// 只收网页交来的字节（文件或粘贴的文字）；文件夹、网址与 pdf / docx 在第三期，这里如实标出。
import * as Dialog from "@radix-ui/react-dialog";
import { RefreshCw, X } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import type { KnJob, KnScope, KnSearch, KnSource, KnSourceVerb, KnStage } from "../api/knowledge-types";
import { useServices } from "../app/context";
import { Button, Empty, SectionHead } from "../kit";
import { pending, recorded, rejected } from "../ui/feedback";
import { Plain } from "../ui/registers";

const STEPS: { key: "upload" | KnStage; word: string }[] = [
  { key: "upload", word: "上传" },
  { key: "parse", word: "解析" },
  { key: "chunk", word: "切分" },
  { key: "index", word: "建索引" },
  { key: "ready", word: "可用" },
];
const ORIGIN_WORD: Record<string, string> = { file: "文件", folder: "文件夹", url: "网址", text: "粘贴的文字" };
const SCOPE_WORD: Record<KnScope, string> = { all: "所有任务", pick: "只在我指定时" };
const VERB_WORD: Record<KnSourceVerb, string> = { disable: "停用", enable: "启用", delete: "删除", restore: "恢复" };
const TEXT_ACCEPT = ".md,.markdown,.txt,.rst,.log,.csv,.tsv,.json,.yaml,.yml,.toml,.ini,.xml,.html,.htm,.py,.js,.ts,.tsx,.jsx,.go,.rs,.java,.kt,.c,.h,.cc,.cpp,.hpp,.cs,.rb,.php,.sh,.sql,.swift,.scala,.lua,.css,.scss";
const MAX_FILE = 200 * 1024 * 1024;
const POLL_MS = 2000;

const errText = (e: unknown) => (e instanceof ApiError ? e.message : String(e));

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / 1024 / 1024).toFixed(n < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}

/** 更新时间：只按记录的时刻排版（视图不读本机时钟，HMI §2）。 */
export function when(ts: number): string {
  const d = new Date(ts);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** 五段刀路：走过的灰、当前的蓝（失败是琥珀）、没到的浅。 */
function Steps({ job }: { job: KnJob }) {
  const at = STEPS.findIndex((s) => s.key === job.stage);
  return (
    <ol className="kn-steps" aria-label={`导入进度：${STEPS[at]?.word ?? job.stage}${job.failed ? "失败" : "中"}`}>
      {STEPS.map((s, i) => (
        <li key={s.key} data-step={s.key} data-at={i < at ? "done" : i === at ? (job.failed ? "failed" : "now") : "todo"}>
          <i aria-hidden="true" />{s.word}
        </li>
      ))}
    </ol>
  );
}

function Jobs({ jobs, writable, onAct }: { jobs: KnJob[]; writable: boolean; onAct: (j: KnJob, verb: "retry" | "cancel") => void }) {
  return (
    <div className="kn-jobs">
      {jobs.map((j) => (
        <div key={`${j.source}-${j.revision}`} className="kn-job" data-job={j.source} data-stage={j.stage} data-failed={!!j.failed}>
          <div className="kn-job-name">
            <b><Plain text={j.name} /></b>
            <span className="t2">{j.revision > 1 ? `第 ${j.revision} 版 · ` : ""}{j.file.name && j.file.name !== j.name ? <><Plain text={j.file.name} /> · </> : ""}{bytes(j.file.size)}</span>
          </div>
          <div className="kn-job-prog">
            <Steps job={j} />
            {j.failed ? <p className="kn-job-why" role="status"><Plain text={j.failed.reason} /></p>
              : <p className="t2 kn-job-note">{j.stage === "index" && j.chunks ? `${j.chunks} 段，正在建索引` : j.stage === "chunk" ? "正在切分" : "正在解析"}</p>}
            {j.warnings.length > 0 && <p className="t2 kn-job-note">{j.warnings.join("；")}</p>}
          </div>
          <div className="kn-job-acts">
            {j.failed && <Button tone="line" size="sm" disabled={!writable} onClick={() => onAct(j, "retry")} data-action="kn-retry">重试</Button>}
            <Button tone="bare" size="sm" disabled={!writable} onClick={() => onAct(j, "cancel")} data-action="kn-cancel">取消</Button>
          </div>
        </div>
      ))}
    </div>
  );
}

function stateOf(s: KnSource): { word: string; tone: "ok" | "need" | "live" | "" } {
  if (s.deleted_at !== null) return { word: "在回收站", tone: "" };
  if (s.disabled) return { word: "已停用", tone: "" };
  if (s.live_revision !== null) return { word: s.importing ? "可用，新版本在导入" : "可用", tone: "ok" };
  if (s.failed) return { word: "导入失败", tone: "need" };
  if (s.importing) return { word: "导入中", tone: "live" };
  return { word: "没有可用的版本", tone: "" };
}

function SourceRows({ rows, writable, onAct }: { rows: KnSource[]; writable: boolean; onAct: (s: KnSource, verb: KnSourceVerb) => void }) {
  return (
    <div className="md-tbl kn-src" role="table" aria-label="已有资料">
      <div className="md-row kn-srow md-head" role="row">
        <span role="columnheader">名称</span><span role="columnheader">来源</span><span role="columnheader" className="num">段数</span>
        <span role="columnheader" className="num">大小</span><span role="columnheader">更新</span><span role="columnheader">状态</span>
        <span role="columnheader"><span className="sr-only">操作</span></span>
      </div>
      {rows.map((s) => {
        const st = stateOf(s);
        const gone = s.deleted_at !== null;
        return (
          <div key={s.id} className="md-row kn-srow" role="row" data-source={s.id} data-live={s.live_revision ?? ""} data-disabled={s.disabled} data-deleted={gone}>
            <span role="cell" className="kn-title"><Plain text={s.name} /></span>
            <span role="cell" className="t2">{ORIGIN_WORD[s.origin] ?? s.origin}{s.scope === "pick" ? " · 只在指定时" : ""}</span>
            <span role="cell" className="num k-mono">{s.chunks.toLocaleString("en-US")}</span>
            <span role="cell" className="num k-mono">{bytes(s.size)}</span>
            <span role="cell" className="t2 k-mono kn-when">{when(gone ? s.deleted_at! : s.updated)}</span>
            <span role="cell"><span className={`md-st ${st.tone}`}><i aria-hidden="true" />{st.word}</span></span>
            <span role="cell" className="md-acts">
              {gone ? <Button tone="bare" size="sm" disabled={!writable} onClick={() => onAct(s, "restore")} data-action="kn-restore">恢复</Button> : (
                <>
                  <Button tone="bare" size="sm" disabled={!writable} onClick={() => onAct(s, s.disabled ? "enable" : "disable")} data-action={s.disabled ? "kn-enable" : "kn-disable"}>{s.disabled ? "启用" : "停用"}</Button>
                  <Button tone="bare" size="sm" disabled={!writable} onClick={() => onAct(s, "delete")} data-action="kn-delete">删除</Button>
                </>
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function TryIt() {
  const { api } = useServices();
  const [q, setQ] = useState("");
  const [res, setRes] = useState<KnSearch | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async () => {
    if (!q.trim()) return;
    setBusy(true);
    try { setRes(await api.knSearch(q.trim())); setError(null); } catch (e) { setError(errText(e)); } finally { setBusy(false); }
  };
  return (
    <section className="kn-try" data-try>
      <SectionHead title="试一下" note="输入一句话，看它会查到哪些段落" />
      <form className="kn-try-box" onSubmit={(e) => { e.preventDefault(); void run(); }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="比如：回滚要注意什么" aria-label="试着查一句" data-field="kn-query" />
        <Button tone="line" size="sm" type="submit" disabled={busy || !q.trim()} data-action="kn-search">查</Button>
      </form>
      {error && <p className="kn-note" role="status">查不了：<Plain text={error} /></p>}
      {res && (
        <div className="kn-hits" data-hits={res.hits.length}>
          {res.hits.length === 0 ? <p className="t2">没有查到。可检索的只有“所有任务”可见、没停用的资料。</p> : res.hits.map((h) => (
            <article key={`${h.id}-${h.revision}`} className="kn-hit" data-hit={h.id}>
              <header><b><Plain text={h.source_name} /></b>{h.heading && h.heading !== h.source_name && <span className="t2"> · <Plain text={h.heading.startsWith(`${h.source_name} / `) ? h.heading.slice(h.source_name.length + 3) : h.heading} /></span>}<span className="k-mono t2 kn-score">{h.score.toFixed(2)}</span></header>
              <p><Plain text={h.text.length > 240 ? `${h.text.slice(0, 240)}…` : h.text} /></p>
            </article>
          ))}
          <p className="t2 kn-via">{res.via === "lexical" ? "只用了词法检索" : "词法与向量混合检索"} · 向量模型 <span className="k-mono">{res.embedder}</span>{res.note ? ` · ${res.note}` : ""}</p>
        </div>
      )}
    </section>
  );
}

type Mode = "file" | "folder" | "url" | "text";
const MODES: { key: Mode; word: string; later?: boolean }[] = [
  { key: "file", word: "文件" },
  { key: "folder", word: "文件夹", later: true },
  { key: "url", word: "网址", later: true },
  { key: "text", word: "粘贴文本" },
];

export function ImportSheet({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const { api } = useServices();
  const [mode, setMode] = useState<Mode>("file");
  const [files, setFiles] = useState<File[]>([]);
  const [name, setName] = useState("");
  const [text, setText] = useState("");
  const [scope, setScope] = useState<KnScope>("all");
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const pick = useRef<HTMLInputElement>(null);
  useEffect(() => { if (open) { setMode("file"); setFiles([]); setName(""); setText(""); setScope("all"); } }, [open]);
  if (!open) return null;
  const big = files.filter((f) => f.size > MAX_FILE);
  const ready = mode === "file" ? files.length > 0 && big.length === 0 : mode === "text" ? !!name.trim() && !!text.trim() : false;
  const total = files.reduce((n, f) => n + f.size, 0);
  // 先拷出来：选择框随后会清空 value，FileList 跟着变空
  const add = (list: FileList | null) => { const got = Array.from(list ?? []); if (got.length) setFiles((xs) => [...xs, ...got.filter((f) => !xs.some((x) => x.name === f.name && x.size === f.size))]); };
  const submit = async () => {
    setBusy(true);
    const t = pending("导入资料");
    try {
      if (mode === "text") await api.knPut({ name: name.trim(), scope, text });
      else for (const f of files) {
        const blob = await api.putBlob(new Uint8Array(await f.arrayBuffer()));
        await api.knPut({ name: f.name, scope, origin: "file", file: { hash: blob.hash, size: blob.size, media_type: f.type, name: f.name } });
      }
      recorded(t, "导入资料", null);
      onDone();
    } catch (e) { rejected(t, "导入资料", errText(e)); } finally { setBusy(false); }
  };
  const later: ReactNode = <Empty title={mode === "folder" ? "文件夹导入在下一期" : "网址导入在下一期"}>{mode === "folder" ? "现在可以在“文件”里一次选多个文件，每个文件成为一份资料。" : "网址要由服务端抓取并受联网白名单约束，下一期接上。现在可以把网页另存为 html 后当文件导入。"}</Empty>;
  return (
    <Dialog.Root open onOpenChange={(o) => { if (!o) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="k-overlay" />
        <Dialog.Content className="md-sheet" data-kn-import aria-describedby={undefined}>
          <header className="md-sheet-h">
            <Dialog.Title>导入资料</Dialog.Title>
            <Dialog.Close className="k-btn k-btn-bare k-btn-sm" aria-label="关闭"><X aria-hidden="true" /></Dialog.Close>
          </header>
          <div className="md-sheet-b">
            <div className="md-seg" role="radiogroup" aria-label="从哪导入" data-field="kn-mode">
              {MODES.map((m) => (
                <button key={m.key} type="button" role="radio" aria-checked={mode === m.key} data-mode={m.key} onClick={() => setMode(m.key)}>{m.word}{m.later && <span className="sr-only">（下一期）</span>}</button>
              ))}
            </div>
            {mode === "file" && (
              <>
                <div className={`kn-drop${over ? " over" : ""}`} data-drop
                  onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
                  onDrop={(e) => { e.preventDefault(); setOver(false); add(e.dataTransfer.files); }}>
                  <p>把文件拖到这里，或者<button type="button" className="kn-link" onClick={() => pick.current?.click()}>选择文件</button></p>
                  <p className="t2">md、txt、html、csv、json、yaml、源码都行，单个不超过 200 MB。pdf 与 docx 下一期支持。</p>
                  <input ref={pick} type="file" multiple accept={TEXT_ACCEPT} hidden data-field="kn-files" onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
                </div>
                {files.length > 0 && (
                  <div className="kn-picked">
                    <p><b>已选 {files.length} 个</b> <span className="t2">{bytes(total)}</span></p>
                    <ul>
                      {files.map((f) => (
                        <li key={`${f.name}-${f.size}`} data-picked={f.name}>
                          <span><Plain text={f.name} /></span>
                          <span className={`k-mono ${f.size > MAX_FILE ? "kn-bad" : "t2"}`}>{bytes(f.size)}</span>
                          <Button tone="bare" size="sm" aria-label={`移除 ${f.name}`} onClick={() => setFiles((xs) => xs.filter((x) => x !== f))}><X aria-hidden="true" /></Button>
                        </li>
                      ))}
                    </ul>
                    {big.length > 0 && <p className="kn-note" role="status">有 {big.length} 个文件超过 200 MB，先移除。</p>}
                  </div>
                )}
              </>
            )}
            {(mode === "folder" || mode === "url") && later}
            {mode === "text" && (
              <>
                <label className="md-f"><span className="md-l">名称</span><input value={name} onChange={(e) => setName(e.target.value)} placeholder="比如：值班约定" data-field="kn-name" /></label>
                <label className="md-f"><span className="md-l">内容</span><textarea rows={10} value={text} onChange={(e) => setText(e.target.value)} data-field="kn-text" /></label>
              </>
            )}
            <div className="md-f">
              <span className="md-l" id="kn-scope">哪些任务能用</span>
              <div className="md-seg" role="radiogroup" aria-labelledby="kn-scope" data-field="kn-scope">
                {(["all", "pick"] as const).map((s) => (
                  <button key={s} type="button" role="radio" aria-checked={scope === s} data-scope={s} onClick={() => setScope(s)}>{SCOPE_WORD[s]}</button>
                ))}
              </div>
            </div>
            <p className="t2">索引在本机建，不花模型的钱，资料也不会发出去。任务用到的段落会进模型的上下文。</p>
          </div>
          <footer className="md-sheet-f">
            <span className="grow" />
            <Button tone="ink" disabled={!ready || busy} onClick={() => void submit()} data-action="kn-start">开始导入</Button>
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** 资料一栏。导入抽屉由页面头上的按钮开（importOpen 由页面持有），这里只管列表与作业。 */
export function Sources({ importOpen, setImportOpen, onCount }: { importOpen: boolean; setImportOpen: (o: boolean) => void; onCount: (n: number | null) => void }) {
  const { api, cfg } = useServices();
  const [sources, setSources] = useState<KnSource[] | null>(null);
  const [jobs, setJobs] = useState<KnJob[]>([]);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const writable = !!cfg.token;
  const load = useCallback(async () => {
    try {
      const [s, j] = await Promise.all([api.knSources(), api.knJobs()]);
      setSources(s.sources); setJobs(j.jobs); setNote(s.note); setError(null);
    } catch (e) { setError(errText(e)); }
  }, [api]);
  useEffect(() => { void load(); }, [load]);
  const busy = jobs.some((j) => !j.failed);
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(() => { if (globalThis.document?.visibilityState !== "hidden") void load(); }, POLL_MS);
    return () => clearInterval(t);
  }, [busy, load]);
  const live = sources?.filter((s) => s.deleted_at === null) ?? null;
  useEffect(() => { onCount(live ? live.length : null); }, [live?.length, onCount]); // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (label: string, fn: () => Promise<unknown>) => {
    const t = pending(label);
    try { await fn(); recorded(t, label, null); } catch (e) { rejected(t, label, errText(e)); }
    await load();
  };
  if (!sources || !live) return <p className="t2">{error ? <>读不到资料：<Plain text={error} /></> : "读取资料…"}</p>;
  const trash = sources.filter((s) => s.deleted_at !== null);
  return (
    <section className="kn-pane" data-sources>
      {!writable && <p className="md-tip">只读：填了人的令牌才能导入、停用或删除。</p>}
      {note && <p className="md-tip" data-kn-note>{note}</p>}
      {jobs.length > 0 && (
        <section data-jobs>
          <SectionHead title="正在导入" note="关掉页面也会继续"
            right={<span className="kn-poll t2">{busy && <><i aria-hidden="true" />每 2 秒更新</>}<Button tone="bare" size="sm" aria-label="刷新" onClick={() => void load()}><RefreshCw aria-hidden="true" /></Button></span>} />
          <Jobs jobs={jobs} writable={writable} onAct={(j, verb) => void act(verb === "retry" ? "重试导入" : "取消导入", () => api.knJob(j.source, j.revision, verb))} />
        </section>
      )}
      <section>
        <SectionHead title="已有资料" />
        {live.length === 0 ? (
          <Empty title="还没有资料" action={<Button tone="ink" disabled={!writable} onClick={() => setImportOpen(true)}>导入资料</Button>}>
            导入文件或一段文字，经过解析、切分、建索引后可用。任务执行时按需检索，资料不发给模型服务商。
          </Empty>
        ) : <SourceRows rows={live} writable={writable} onAct={(s, verb) => void act(`${VERB_WORD[verb]}资料`, () => api.knSource(s.id, verb))} />}
        {trash.length > 0 && (
          <details className="kn-gone" data-trash>
            <summary>回收站 {trash.length} 份 · 30 天后清掉索引</summary>
            <SourceRows rows={trash} writable={writable} onAct={(s, verb) => void act(`${VERB_WORD[verb]}资料`, () => api.knSource(s.id, verb))} />
          </details>
        )}
      </section>
      <TryIt />
      <ImportSheet open={importOpen} onClose={() => setImportOpen(false)} onDone={() => { setImportOpen(false); void load(); }} />
    </section>
  );
}
