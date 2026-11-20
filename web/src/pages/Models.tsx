// 模型页（前端重新设计 v5 第二期）：设置层的模型档案与默认分配单独成页。
// 一张表看全部档案：接口、模型 ID、密钥槽有没有密钥、上次测试的结果；添加与编辑在右侧抽屉里，测通才能存。
// 档案与路由仍是设置存储里的同一份（PUT /v1/settings，带 base_digest 做乐观并发）；密钥走 /v1/keys，页面不留它。
// 接口格式两种：Anthropic 兼容原样转发；OpenAI 兼容由端点代理改写（adapter/openai_compat.py）。
import * as Dialog from "@radix-ui/react-dialog";
import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw, X } from "lucide-react";
import { ApiError } from "../api/client";
import type { ApiFormat, KeysView, ModelProbe, ModelProfile, Settings, SettingsDoc } from "../api/settings-types";
import { useServices } from "../app/context";
import { Button, Empty, Mast, SectionHead } from "../kit";
import { ROLES, SLOT_RE, TIERS, settingsIssues } from "../model/settings";
import { pending, recorded, rejected } from "../ui/feedback";
import { Plain } from "../ui/registers";

const errText = (e: unknown) => (e instanceof ApiError ? e.message : String(e));
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
/** 测试结果只对这三项有效：改了任何一项就要重测。 */
export const probeSig = (p: Pick<ModelProfile, "endpoint" | "model" | "key_slot" | "format">) => JSON.stringify([p.endpoint.trim(), p.model.trim(), p.key_slot.trim(), p.format ?? "anthropic"]);
export const FORMAT_WORD: Record<ApiFormat, string> = { anthropic: "Anthropic 兼容", openai: "OpenAI 兼容" };
const FORMAT_HINT: Record<ApiFormat, string> = {
  anthropic: "原样转发 /v1/messages。地址写到域名为止，不带 /v1。",
  openai: "端点代理把请求改写成 /chat/completions 再改回来；文字、图片、工具调用都转，思考过程与缓存控制转不过去。地址写到 /v1 为止。",
};
/** 存进设置时 anthropic 不写 format：旧快照与新存的同一个档案摘要相同。 */
const withFormat = (p: ModelProfile): ModelProfile => { const { format, ...rest } = p; return format === "openai" ? { ...rest, format } : rest; };
const hostOf = (endpoint: string) => {
  if (!endpoint.trim()) return "缺省上游";
  try { return new URL(endpoint).host; } catch { return endpoint; }
};
const ROLE_NOTE: Record<string, string> = {
  draft: "一句话起草任务单", bootstrap: "开局摸清情况", reason: "想清楚下一步", explore: "动手做", verify: "自己查一遍",
};

type Probe = ModelProbe & { sig: string };
type Sheet = { index: number | null; form: ModelProfile; key: string; probe: Probe | null; busy: boolean };

function ProbeCell({ p, slotSet }: { p: Probe | undefined; slotSet: boolean }) {
  if (!slotSet) return <span className="md-st need"><i aria-hidden="true" />密钥未填</span>;
  if (!p) return <span className="md-st"><i aria-hidden="true" />未测</span>;
  if (p.ok) return <span className="md-st ok"><i aria-hidden="true" />正常<span className="num md-ms">{p.latency_ms} ms</span></span>;
  return <span className="md-st need" title={p.message}><i aria-hidden="true" />{p.code === "bad_key" ? "密钥无效" : p.code === "not_found" ? "地址或 ID 不对" : p.code === "unreachable" ? "连不上" : p.code === "no_model" ? "没写模型 ID" : "没通过"}</span>;
}

export function ModelsPage() {
  const { api, cfg } = useServices();
  const writable = !!cfg.token;
  const [doc, setDoc] = useState<SettingsDoc | null>(null);
  const [keys, setKeys] = useState<KeysView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [probes, setProbes] = useState<Record<string, Probe>>({});
  const [testing, setTesting] = useState<Set<string>>(new Set());
  const [sheet, setSheet] = useState<Sheet | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const d = await api.settings();
      setDoc(d); setError(null);
      if (writable) setKeys(await api.keys());
    } catch (e) { setError(errText(e)); }
  }, [api, writable]);
  useEffect(() => { void load(); }, [load]);

  const slotSet = useCallback((slot: string) => !!keys?.slots.find((s) => s.slot === slot)?.set, [keys]);

  async function test(p: ModelProfile) {
    setTesting((t) => new Set(t).add(p.name));
    try {
      const r = await api.testModel({ endpoint: p.endpoint, model: p.model, key_slot: p.key_slot, format: p.format ?? "anthropic" });
      setProbes((m) => ({ ...m, [p.name]: { ...r, sig: probeSig(p) } }));
    } catch (e) {
      setProbes((m) => ({ ...m, [p.name]: { ok: false, code: "error", message: errText(e), sig: probeSig(p) } }));
    } finally {
      setTesting((t) => { const n = new Set(t); n.delete(p.name); return n; });
    }
  }

  /** 存一份新设置：成功后整页换成服务端回来的那份；别处先改了就 409，提示重读。 */
  async function put(next: Settings, what: string): Promise<boolean> {
    if (!doc) return false;
    const issues = settingsIssues(next);
    if (issues.length) { rejected(pending(what), what, issues.join("；")); return false; }
    setSaving(true);
    const id = pending(what);
    try {
      const d = await api.putSettings(doc.digest, next);
      setDoc(d);
      recorded(id, what, null, `设置 v${d.version}`);
      return true;
    } catch (e) {
      rejected(id, what, e instanceof ApiError && e.status === 409 ? "设置在你打开这页之后被别处改过：已重读，请再改一次" : errText(e));
      if (e instanceof ApiError && e.status === 409) void load();
      return false;
    } finally { setSaving(false); }
  }

  if (error && !doc) return <p className="error">读不到模型设置：<Plain text={error} /></p>;
  if (!doc) return <p className="muted">读取中…</p>;
  const { profiles, routes } = doc.settings.models;
  const routed = (name: string) => ROLES.filter((r) => routes[r.role] === name).map((r) => r.word);

  function openAdd() {
    setSheet({ index: null, form: { name: "", endpoint: "", model: "", family: "", tier: "mid", key_slot: "default" }, key: "", probe: null, busy: false });
  }
  function openEdit(i: number) {
    const p = profiles[i];
    const last = probes[p.name];
    setSheet({ index: i, form: { ...p }, key: "", probe: last && last.sig === probeSig(p) ? last : null, busy: false });
  }

  return (
    <div className="models" data-page="models">
      <Mast cap="模型" title={`${profiles.length} 个模型档案`}
        dek="这里连得通的模型，新建任务时才选得到。端点和密钥只在这里改，任务里只能从这些档案里选。"
        actions={
          <>
            <Button tone="line" disabled={!writable || testing.size > 0} onClick={() => profiles.forEach((p) => void test(p))} data-action="test-all">
              <RefreshCw aria-hidden="true" className={testing.size ? "spin" : undefined} />全部重测
            </Button>
            <Button tone="ink" disabled={!writable} onClick={openAdd} data-action="add-model">添加模型</Button>
          </>
        } />
      {!writable && <p className="md-tip">只读：填了人的令牌才能测试、添加和修改。</p>}

      <div className="md-tbl" role="table" aria-label="模型档案" data-profiles>
        <div className="md-row md-head" role="row">
          <span role="columnheader">模型</span><span role="columnheader">接口</span><span role="columnheader">密钥</span>
          <span role="columnheader">连接</span><span role="columnheader">档位</span><span role="columnheader">用在</span><span role="columnheader"><span className="sr-only">操作</span></span>
        </div>
        {profiles.map((p, i) => {
          const pr = probes[p.name];
          const fresh = pr && pr.sig === probeSig(p) ? pr : undefined;
          const set = slotSet(p.key_slot);
          return (
            <div key={p.name} className="md-row" role="row" data-profile={p.name}>
              <span role="cell" className="md-name"><b>{p.name}</b><span className="k-mono">{p.model || "（命令行缺省模型）"}</span></span>
              <span role="cell" className="md-api" data-format={p.format ?? "anthropic"}><span>{FORMAT_WORD[p.format ?? "anthropic"]}</span><span className="k-mono">{hostOf(p.endpoint)}</span></span>
              <span role="cell" className="md-key"><span className="k-mono">{p.key_slot}</span><span className={set ? "ok" : "need"}>{keys ? (set ? "已设" : "未填") : "—"}</span></span>
              <span role="cell" data-probe={fresh ? (fresh.ok ? "ok" : fresh.code) : "none"}>{testing.has(p.name) ? <span className="md-st live"><i aria-hidden="true" />测试中…</span> : <ProbeCell p={fresh} slotSet={!keys || set} />}</span>
              <span role="cell">{TIERS.find((t) => t.tier === p.tier)?.word}</span>
              <span role="cell" className="md-used">{routed(p.name).join("、") || <span className="muted">—</span>}</span>
              <span role="cell" className="md-acts">
                <Button tone="bare" size="sm" disabled={!writable || testing.has(p.name)} onClick={() => void test(p)} data-action="test-model">测试</Button>
                <Button tone="line" size="sm" disabled={!writable} onClick={() => openEdit(i)} data-action="edit-model">编辑</Button>
              </span>
            </div>
          );
        })}
      </div>
      {profiles.length === 0 && <Empty title="还没有模型">添加一个并测通，新建任务时才有得选。</Empty>}

      <section className="md-sec" aria-labelledby="md-routes">
        <SectionHead id="md-routes" title="默认分配" note="新建任务时模型选“自动”，就按这里；新会话起生效，跑到一半的会话不换模型" />
        <div className="md-routes" data-routes>
          {ROLES.map(({ role, word }) => (
            <label key={role} className="md-route">
              <span className="md-route-w"><b>{word}</b><span className="t2">{ROLE_NOTE[role]}</span></span>
              <select value={routes[role]} disabled={!writable || saving} data-field={`route.${role}`}
                onChange={(e) => { const n = clone(doc.settings); n.models.routes[role] = e.target.value; void put(n, `默认分配：${word}`); }}>
                {profiles.map((p) => <option key={p.name} value={p.name}>{p.name}{p.model ? ` · ${p.model}` : ""}</option>)}
              </select>
            </label>
          ))}
        </div>
      </section>

      <ModelSheet sheet={sheet} setSheet={setSheet} profiles={profiles} routedOf={routed} saving={saving}
        onTest={async (form, key) => {
          if (!sheet) return;
          setSheet({ ...sheet, form, busy: true });
          try {
            if (key.trim()) { await api.putKey(form.key_slot, key.trim()); setKeys(await api.keys()); }
            const r = await api.testModel({ endpoint: form.endpoint, model: form.model, key_slot: form.key_slot, format: form.format ?? "anthropic" });
            const pr = { ...r, sig: probeSig(form) };
            setSheet((s) => s && { ...s, key: "", probe: pr, busy: false });
            if (form.name) setProbes((m) => ({ ...m, [form.name]: pr }));
          } catch (e) {
            setSheet((s) => s && { ...s, key: "", probe: { ok: false, code: "error", message: errText(e), sig: probeSig(form) }, busy: false });
          }
        }}
        onSave={async (form) => {
          const n = clone(doc.settings);
          const idx = sheet?.index ?? null;
          if (idx === null) n.models.profiles.push(withFormat(form));
          else {
            const old = n.models.profiles[idx].name;
            n.models.profiles[idx] = withFormat(form);
            for (const { role } of ROLES) if (n.models.routes[role] === old) n.models.routes[role] = form.name; // 改名时路由跟着走
          }
          if (await put(n, idx === null ? `添加模型 ${form.name}` : `保存模型 ${form.name}`)) setSheet(null);
        }}
        onDelete={async () => {
          if (!sheet || sheet.index === null) return;
          const n = clone(doc.settings);
          const [gone] = n.models.profiles.splice(sheet.index, 1);
          if (await put(n, `删除模型 ${gone.name}`)) setSheet(null);
        }} />
    </div>
  );
}

function ModelSheet({ sheet, setSheet, profiles, routedOf, saving, onTest, onSave, onDelete }: {
  sheet: Sheet | null;
  setSheet: (s: Sheet | null) => void;
  profiles: ModelProfile[];
  routedOf: (name: string) => string[];
  saving: boolean;
  onTest: (form: ModelProfile, key: string) => Promise<void>;
  onSave: (form: ModelProfile) => Promise<void>;
  onDelete: () => Promise<void>;
}) {
  const form = sheet?.form;
  const issues = useMemo(() => {
    if (!form || !sheet) return [];
    const out: string[] = [];
    const name = form.name.trim();
    if (!name) out.push("要起个名字");
    else if (profiles.some((p, i) => p.name === name && i !== sheet.index)) out.push("已经有同名的档案");
    if (!SLOT_RE.test(form.key_slot)) out.push("密钥槽名只取小写字母、数字、- 与 _");
    if (form.endpoint.trim() && !/^https?:\/\/./.test(form.endpoint.trim())) out.push("接口地址要以 http 或 https 协议开头");
    if (form.format === "openai" && !form.endpoint.trim()) out.push("OpenAI 格式要写接口地址：缺省上游是 Anthropic 格式");
    return out;
  }, [form, sheet, profiles]);
  if (!sheet || !form) return null;
  const tested = !!sheet.probe && sheet.probe.sig === probeSig(form);
  const passed = tested && !!sheet.probe?.ok;
  const editing = sheet.index !== null;
  const routes = editing ? routedOf(profiles[sheet.index!].name) : [];
  const setForm = (patch: Partial<ModelProfile>) => setSheet({ ...sheet, form: { ...form, ...patch } });

  return (
    <Dialog.Root open onOpenChange={(o) => { if (!o) setSheet(null); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="k-overlay" />
        <Dialog.Content className="md-sheet" data-model-sheet aria-describedby={undefined}>
          <header className="md-sheet-h">
            <Dialog.Title>{editing ? "编辑模型" : "添加模型"}</Dialog.Title>
            <Dialog.Close className="k-btn k-btn-bare k-btn-sm" aria-label="关闭"><X aria-hidden="true" /></Dialog.Close>
          </header>
          <div className="md-sheet-b">
            <div className="md-f">
              <span className="md-l" id="md-format">接口格式</span>
              <div className="md-seg" role="radiogroup" aria-labelledby="md-format" data-field="model.format">
                {(["anthropic", "openai"] as const).map((f) => (
                  <button key={f} type="button" role="radio" aria-checked={(form.format ?? "anthropic") === f} data-format={f} onClick={() => setForm({ format: f })}>{FORMAT_WORD[f]}</button>
                ))}
              </div>
              <span className="md-hint">{FORMAT_HINT[form.format ?? "anthropic"]}</span>
            </div>
            <label className="md-f">
              <span className="md-l">接口地址</span>
              <input className="k-mono" value={form.endpoint} placeholder="不填即用缺省上游" data-field="model.endpoint" onChange={(e) => setForm({ endpoint: e.target.value })} />
            </label>
            <label className="md-f">
              <span className="md-l">模型 ID</span>
              <input className="k-mono" value={form.model} placeholder="上游认得的模型名" data-field="model.model" onChange={(e) => setForm({ model: e.target.value })} />
            </label>
            <div className="md-2">
              <label className="md-f">
                <span className="md-l">显示名称</span>
                <input value={form.name} placeholder="比如：主力" data-field="model.name" onChange={(e) => setForm({ name: e.target.value })} />
              </label>
              <div className="md-f">
                <span className="md-l" id="md-tier">档位</span>
                <div className="md-seg" role="radiogroup" aria-labelledby="md-tier">
                  {TIERS.map((t) => (
                    <button key={t.tier} type="button" role="radio" aria-checked={form.tier === t.tier} onClick={() => setForm({ tier: t.tier })}>{t.word}</button>
                  ))}
                </div>
              </div>
            </div>
            <label className="md-f">
              <span className="md-l">密钥槽</span>
              <input className="k-mono" value={form.key_slot} data-field="model.key_slot" onChange={(e) => setForm({ key_slot: e.target.value })} />
            </label>
            <label className="md-f">
              <span className="md-l">密钥</span>
              <input type="password" autoComplete="off" value={sheet.key} placeholder="可空：不填就用这个槽里已有的" data-field="model.key"
                onChange={(e) => setSheet({ ...sheet, key: e.target.value })} />
              <span className="md-hint">测试时先存进槽 {form.key_slot || "…"}，只在服务进程的内存里，重启后要重填；想长期生效用环境变量。</span>
            </label>
            {sheet.probe && (
              <div className={`md-result${sheet.probe.ok ? " ok" : " bad"}`} role="status" data-probe-result={sheet.probe.ok ? "ok" : sheet.probe.code}>
                {sheet.probe.ok
                  ? <><b>连通了</b><span className="num">{sheet.probe.latency_ms} ms</span>{!tested && <span>（之后改过地址、ID 或密钥槽，要再测一次）</span>}</>
                  : <><b>没通过</b><span><Plain text={sheet.probe.message ?? "未知原因"} /></span></>}
              </div>
            )}
            {issues.length > 0 && <ul className="md-issues">{issues.map((x) => <li key={x}>{x}</li>)}</ul>}
          </div>
          <footer className="md-sheet-f">
            {editing && (
              <Button tone="bare" disabled={saving || routes.length > 0 || profiles.length <= 1} onClick={() => void onDelete()} data-action="delete-model"
                title={routes.length ? `默认分配里还在用它（${routes.join("、")}），先改分配` : undefined}>删除</Button>
            )}
            <span className="grow">{routes.length > 0 && <span className="t2">在用：{routes.join("、")}</span>}</span>
            <Button tone="line" disabled={sheet.busy || issues.length > 0} onClick={() => void onTest(form, sheet.key)} data-action="probe-model">
              {sheet.busy ? "测试中…" : "测试连接"}
            </Button>
            <Button tone="ink" disabled={!passed || saving || issues.length > 0} onClick={() => void onSave({ ...form, name: form.name.trim(), endpoint: form.endpoint.trim(), model: form.model.trim() })}
              data-action="save-model" title={passed ? undefined : "测通了才能存"}>保存</Button>
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
