// 导入任务集（视觉重做第二期；工作台设计 §1 模块二、线框 f3）：JSON 或 CSV 在本机解析成草稿，逐题走与向导相同的提交路径，
// 逐题回显结果（seq 或拒绝码）。YAML 要解析库，本轮不做（异议 web-workbench 第 1 条）。
import { useEffect, useState } from "react";
import { newIdemKey } from "../api/client";
import type { CatalogItem } from "../api/types";
import { useServices } from "../app/context";
import { submitDraft } from "../app/submit";
import { CSV_TARGETS, draftsFromCsv, guessMapping, parseCsv, parseJsonBatch, type CsvMapping } from "../model/importer";
import { draftFromTemplate, problemsOf, STEPS, type Draft } from "../model/wizard";
import { Plain } from "../ui/registers";
import { rejectText } from "../ui/useProposal";
import { toast } from "sonner";
import { FileUp } from "lucide-react";
import { Mark, Mast, SectionHead, btnClass, type MarkTone } from "../kit";
import { Link } from "./Problems";

type Row = { draft: Draft; state: "ready" | "invalid" | "busy" | "done" | "failed"; note: string };

const SAMPLE = `[
  {
    "id": "batch-1",
    "title": "示例：取得登录后显示的答案串",
    "statement": "提交页面上的答案串",
    "materials": [{ "slot": "题面", "text": "登录页在 target:8080 …" }],
    "judge": "exact_match",
    "scope": [{ "resource": "net", "pattern": "target:8080", "actions": ["connect"], "risk": "r0" }],
    "budget": { "usd_milli": 2000, "wall_s": 1800 },
    "hint": "先看登录页源码"
  }
]`;

const check = (d: Draft): Row => {
  const bad = problemsOf(d).flatMap((xs, i) => xs.map((x) => `${STEPS[i]}：${x}`));
  return { draft: d, state: bad.length ? "invalid" : "ready", note: bad.join("；") };
};

export function Import() {
  const { api, cfg } = useServices();
  const [templates, setTemplates] = useState<CatalogItem[] | null>(null);
  const [tpl, setTpl] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [csv, setCsv] = useState<string[][] | null>(null);
  const [map, setMap] = useState<CsvMapping | null>(null);
  const [running, setRunning] = useState(false);
  const [goal, setGoal] = useState("");

  useEffect(() => { api.templates().then((t) => { setTemplates(t.items); setTpl(t.items[0]?.name ?? ""); }, (e: Error) => setErr(e.message)); }, [api]);
  const base = () => {
    const d = draftFromTemplate(templates?.find((t) => t.name === tpl) ?? null);
    return goal.trim() ? { ...d, statement: goal } : d;
  };

  async function load(file: File) {
    setErr(null); setRows([]); setCsv(null); setMap(null);
    const text = await file.text();
    if (/\.csv$/i.test(file.name) || file.type === "text/csv") {
      const table = parseCsv(text);
      if (table.length < 2) { setErr("CSV 至少要一行表头加一行数据"); return; }
      setCsv(table); setMap(guessMapping(table[0]));
      return;
    }
    if (/\.ya?ml$/i.test(file.name)) { setErr("YAML 暂不支持（要加解析依赖，见异议 web-workbench 第 1 条）；请转成 JSON"); return; }
    const out = parseJsonBatch(text, base());
    if (out instanceof Error) { setErr(out.message); return; }
    setRows(out.map(check));
  }

  useEffect(() => {
    if (csv && map) setRows(draftsFromCsv(csv, map, base()).map(check));
    // base 随模板变
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [csv, map, tpl, goal]);

  async function runAll() {
    setRunning(true);
    let ok = 0, bad = 0;
    for (let i = 0; i < rows.length; i++) {
      if (rows[i].state !== "ready" && rows[i].state !== "failed") continue;
      setRows((rs) => rs.map((r, k) => (k === i ? { ...r, state: "busy", note: "提交中…" } : r)));
      try {
        const res = await submitDraft(api, rows[i].draft, newIdemKey());
        const note = `已开题 seq ${res.seq}${res.hintSeq !== null ? `，初始提示 seq ${res.hintSeq}` : ""}${res.hintError ? `；初始提示失败：${res.hintError}` : ""}`;
        ok++;
        setRows((rs) => rs.map((r, k) => (k === i ? { ...r, state: "done", note } : r)));
      } catch (e) {
        bad++;
        setRows((rs) => rs.map((r, k) => (k === i ? { ...r, state: "failed", note: rejectText(e as Error) ?? (e as Error).message } : r)));
      }
    }
    setRunning(false);
    if (ok + bad > 0) (bad ? toast.warning : toast.success)(`导入任务集：开成 ${ok} 个${bad ? `，${bad} 个没成功，可重试` : ""}`);
  }

  const ready = rows.filter((r) => r.state === "ready" || r.state === "failed").length;
  return (
    <div className="importer" data-page="import">
      <Mast vol={["卷三", "导入"]} cap="导入任务集" title="把一批任务一次开好" dek="文件在本机解析，逐个先存材料、再开题，与向导走同一条路；每个任务的结果单独显示，失败的可以重试。" />
      <section className="today-sec">
        <SectionHead title="选文件与缺省值" note="JSON 或 CSV" />
        <div className="import-grid">
          <label className="drop" data-has-file={rows.length > 0 || !!csv}>
            <FileUp aria-hidden="true" />
            <span className="drop-main">选择文件</span>
            <span className="t2">.json 或 .csv，只在本机读取</span>
            <input type="file" accept=".json,.csv,application/json,text/csv" data-field="import-file" onChange={(e) => { const f = e.target.files?.[0]; if (f) void load(f); }} />
          </label>
          <div className="import-defaults">
            <label>缺省值取自模板
              <select value={tpl} data-field="import-template" onChange={(e) => setTpl(e.target.value)}>
                <option value="">不用模板</option>
                {templates?.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
              </select>
            </label>
            <label>缺省目标陈述<span className="t2">任务里没写时用</span><input value={goal} data-field="import-goal" onChange={(e) => setGoal(e.target.value)} /></label>
            <details className="sample"><summary>JSON 格式示例</summary><pre className="output">{SAMPLE}</pre>
              <p className="t2">没写的字段（判定器、范围、预算、环境）取自所选模板。答案类的判定条件应进 vault，只填引用。</p></details>
          </div>
        </div>
        {err && <p className="error" data-import-error><Plain text={err} /></p>}
      </section>

      {csv && map && (
        <section className="today-sec" data-csv-mapping>
          <SectionHead title="CSV 列映射" note="其余字段取自模板；答案列不要映射" />
          <table className="bank map">
            <thead><tr><th>任务字段</th><th>取自 CSV 列</th></tr></thead>
            <tbody>
              {CSV_TARGETS.map((t) => (
                <tr key={t.key}>
                  <td>{t.word}</td>
                  <td>
                    <select value={map[t.key]} data-map={t.key} onChange={(e) => setMap({ ...map, [t.key]: Number(e.target.value) })}>
                      <option value={-1}>（不映射）</option>
                      {csv[0].map((h, i) => <option key={i} value={i}>{h || `第 ${i + 1} 列`}</option>)}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {rows.length > 0 && (
        <section className="today-sec" data-import-queue>
          <SectionHead title="待导入" note={`${rows.length} 个`} right={
            <span className="row">
              {cfg.token === null && <span className="t2">开题是写操作，先在左下角配置令牌</span>}
              <button type="button" className={btnClass("zhu", "sm")} data-action="import-all" disabled={running || ready === 0 || cfg.token === null} onClick={runAll}>{running ? "导入中…" : `导入 ${ready} 个`}</button>
            </span>
          } />
          <div className="table-scroll">
            <table className="bank">
              <thead><tr><th></th><th>编号</th><th>任务</th><th>说明</th></tr></thead>
              <tbody>
                {rows.map((r, i) => {
                  const m = STATE_MARK[r.state];
                  return (
                    <tr key={i} data-import-row={r.draft.id || i} data-state={r.state}>
                      <td><Mark ch={m.ch} tone={m.tone} label={m.word} /></td>
                      <td className="k-mono">{r.state === "done" ? <Link to={{ page: "problem", pid: r.draft.id, asOf: null, node: null }}><Plain text={r.draft.id} /></Link> : <Plain text={r.draft.id || "—"} />}</td>
                      <td className="title"><Plain text={r.draft.title || "—"} /></td>
                      <td className="note"><span className="sr-only">{m.word}：</span><Plain text={r.note} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}

const STATE_MARK: Record<Row["state"], { ch: string; tone: MarkTone; word: string }> = {
  ready: { ch: "待", tone: "wei", word: "待提交" },
  invalid: { ch: "缺", tone: "dai", word: "缺项" },
  busy: { ch: "行", tone: "xing", word: "提交中" },
  done: { ch: "开", tone: "jie", word: "已开题" },
  failed: { ch: "拒", tone: "dai", word: "被拒" },
};
