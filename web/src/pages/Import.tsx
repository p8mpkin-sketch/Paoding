// 导入题集（工作台设计 §1 模块二、线框 f3）：JSON 或 CSV 在本机解析成草稿，逐题走与向导相同的提交路径，
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
      <h2>导入题集</h2>
      <p className="muted">在本机解析，逐题先存材料、再开题，与向导走同一条路；每题的结果单独显示，失败的可重试。</p>
      <div className="import-controls">
        <label>文件（.json 或 .csv）<input type="file" accept=".json,.csv,application/json,text/csv" data-field="import-file" onChange={(e) => { const f = e.target.files?.[0]; if (f) void load(f); }} /></label>
        <label>缺省值取自模板
          <select value={tpl} data-field="import-template" onChange={(e) => setTpl(e.target.value)}>
            <option value="">不用模板</option>
            {templates?.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
          </select>
        </label>
        <label>缺省目标陈述（题目没写时用）<input value={goal} data-field="import-goal" onChange={(e) => setGoal(e.target.value)} /></label>
      </div>
      <details className="sample"><summary>JSON 格式示例</summary><pre className="output">{SAMPLE}</pre>
        <p className="muted">没写的字段（判官、scope、预算、env）取自所选模板。答案类的判定条件应进 vault，只填引用。</p></details>
      {err && <p className="error" data-import-error><Plain text={err} /></p>}

      {csv && map && (
        <section data-csv-mapping>
          <h3>CSV 列映射</h3>
          <table className="mini">
            <thead><tr><th>Problem 字段</th><th>取自 CSV 列</th></tr></thead>
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
          <p className="muted">其余字段（判官、scope、预算、env）取自所选模板。CSV 里的答案列不要映射，答案应进 vault。</p>
        </section>
      )}

      {rows.length > 0 && (
        <section data-import-queue>
          <h3>待导入（{rows.length}）</h3>
          <div className="table-scroll">
            <table className="mini wide">
              <thead><tr><th>题目 id</th><th>题名</th><th>状态</th><th>说明</th></tr></thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i} data-import-row={r.draft.id || i} data-state={r.state}>
                    <td>{r.state === "done" ? <Link to={{ page: "problem", pid: r.draft.id, asOf: null, node: null }}><Plain text={r.draft.id} /></Link> : <Plain text={r.draft.id || "—"} />}</td>
                    <td><Plain text={r.draft.title || "—"} /></td>
                    <td>{{ ready: "待提交", invalid: "✕ 缺项", busy: "…", done: "✓ 已开题", failed: "✕ 被拒" }[r.state]}</td>
                    <td><Plain text={r.note} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button type="button" data-action="import-all" disabled={running || ready === 0 || cfg.token === null} onClick={runAll}>{running ? "导入中…" : `导入 ${ready} 题`}</button>
          {cfg.token === null && <span className="muted"> 开题是写操作：先在页面右上角配置人的令牌。</span>}
        </section>
      )}
    </div>
  );
}
