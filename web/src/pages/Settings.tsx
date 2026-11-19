// 设置页“系统”一组（宪章 03 §2、§4、§5、§7；交互稿 set-models、set-budget）。
// 存在服务端的设置存储里，只有人的令牌能写；读端点不含密钥。“个人”一组（主题等）仍在侧栏，只存本机。
//
// 密钥一节：每个槽只显示已设 / 未设、指纹、设置时间与来源；输入框提交后立即清空，浏览器不在任何存储里留它。
// 其余四节（硬顶、模型档案与角色路由、风险表）是同一份设置，一次保存，带 base_digest 做乐观并发：
// 别人先改了就 409，重读再改。
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError } from "../api/client";
import type { KeySlot, KeysView, ModelProfile, RiskRule, Settings, SettingsDoc, SettingsLogEntry, SettingsSources } from "../api/settings-types";
import type { PlatformEntry } from "../api/kaiti";
import { fmtTs, useServices } from "../app/context";
import { Button, Mark, Mast, SectionHead } from "../kit";
import {
  KEY_NOTE, ROLES, TIERS, capIssues, changedKeys, emptyRule, fromMinInput, fromUsdInput, parseActions, rulerFraction, settingsIssues, toMinInput, toUsdInput,
} from "../model/settings";
import { shortHash, usd } from "../model/text";
import { pending, recorded, rejected } from "../ui/feedback";
import { Plain } from "../ui/registers";

const SOURCE_WORD: Record<string, string> = { page: "设置页", env: "环境变量", config: "配置文件", fake: "假上游（无需密钥）" };
const errText = (e: unknown) => (e instanceof ApiError ? e.message : String(e));
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

export function SettingsPage() {
  const { api, cfg } = useServices();
  const writable = !!cfg.token;
  const [doc, setDoc] = useState<SettingsDoc | null>(null);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [log, setLog] = useState<SettingsLogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [d, l] = await Promise.all([api.settings(), api.settingsLog()]);
      setDoc(d); setDraft(clone(d.settings)); setLog(l.items); setError(null); setStale(false);
    } catch (e) { setError(errText(e)); }
  }, [api]);
  useEffect(() => { void load(); }, [load]);

  const changed = useMemo(() => (doc && draft ? changedKeys(doc.settings, draft) : []), [doc, draft]);
  const issues = useMemo(() => (draft ? settingsIssues(draft) : []), [draft]);

  async function save() {
    if (!doc || !draft) return;
    setBusy(true);
    const id = pending("保存设置");
    try {
      const d = await api.putSettings(doc.digest, draft);
      setDoc(d); setDraft(clone(d.settings)); setLog((await api.settingsLog()).items);
      recorded(id, "保存设置", null, `设置 v${d.version}，摘要 ${shortHash(d.digest)}`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setStale(true);
      rejected(id, "保存设置", errText(e));
    } finally { setBusy(false); }
  }

  if (error && !doc) return <p className="error">读不到设置：<Plain text={error} /></p>;
  if (!doc || !draft) return <p className="muted">读取中…</p>;
  const set = (patch: (s: Settings) => void) => setDraft((d) => { const n = clone(d!); patch(n); return n; });

  return (
    <div className="settings" data-settings-version={doc.version}>
      <Mast
        vol={["卷五", "设置"]}
        cap="系统 · 存在服务端，改动只追加进变更记录"
        title="设置只许下一层收窄上一层"
        dek="任务里能改的只有预算、风险（只许往上调）、模型档案（只能选这里登记过的）；端点、密钥、硬顶、风险表都只在这里改。"
        actions={<span className="settings-ver num" data-settings-digest={doc.digest}>v{doc.version} · {shortHash(doc.digest)}</span>}
      />

      <Keys />

      <Platforms />

      <section className="settings-sec" aria-labelledby="sec-caps">
        <SectionHead id="sec-caps" title="预算与硬顶" note="练习 ≤ 单任务 ≤ 全局；保存时由服务端校验次序" />
        <Caps draft={draft} set={set} writable={writable} />
      </section>

      <Sources version={doc.version} />

      <section className="settings-sec" aria-labelledby="sec-models">
        <SectionHead id="sec-models" title="模型档案与角色路由" note="新会话起生效，会话中途不换模型" />
        <Models draft={draft} set={set} writable={writable} />
      </section>

      <section className="settings-sec" aria-labelledby="sec-risk">
        <SectionHead id="sec-risk" title="风险表" note="自上而下顺序匹配；没命中的一律 r2，新建的任务起生效" />
        <Risk draft={draft} set={set} writable={writable} />
      </section>

      <div className="settings-foot" data-settings-foot>
        {stale && (
          <p className="issues" role="alert">设置在你读过之后被别处改过，没有保存。<Button tone="line" size="sm" onClick={() => void load()} data-action="reload-settings">重读（丢掉这里的改动）</Button></p>
        )}
        {issues.length > 0 && <ul className="issues" data-settings-issues>{issues.map((x) => <li key={x}>{x}</li>)}</ul>}
        <Button tone="ink" disabled={!writable || busy || changed.length === 0 || issues.length > 0} onClick={() => void save()} data-action="save-settings">
          保存设置{changed.length > 0 && <span className="t2 inv">改了 {changed.length} 项</span>}
        </Button>
        <Button tone="line" disabled={changed.length === 0} onClick={() => setDraft(clone(doc.settings))} data-action="revert-settings">放弃改动</Button>
        {!writable && <span className="muted">只读：填了人的令牌才能改设置。</span>}
      </div>

      <section className="settings-sec" aria-labelledby="sec-log">
        <SectionHead id="sec-log" title="变更记录" note="只追加；每行一次保存" />
        <table className="mini wide" data-settings-log>
          <thead><tr><th>版本</th><th>时间（UTC）</th><th>改了什么</th><th>谁</th><th>新摘要</th></tr></thead>
          <tbody>
            {[...log].reverse().map((e) => (
              <tr key={e.version}>
                <td className="num">v{e.version}</td>
                <td className="num nowrap">{fmtTs(e.ts)}</td>
                <td>{e.keys.join("、")}</td>
                <td>{e.by === "init" ? "首次启动" : e.by === "human" ? "人" : e.by}</td>
                <td className="num">{shortHash(e.to)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

// ---------- 已登记的外部平台（external-verdict §10 第 7 条：只读呈现） ----------

function Platforms() {
  const { api, cfg } = useServices();
  const [items, setItems] = useState<PlatformEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!cfg.token) return;
    api.platforms().then((x) => { setItems(x.items); setError(null); }, (e) => setError(errText(e)));
  }, [api, cfg.token]);
  return (
    <section className="settings-sec" aria-labelledby="sec-platforms" data-settings-platforms>
      <SectionHead id="sec-platforms" title="外部平台" note="连接器档案在 judgebox/connectors.d，启动时加载、摘要进新建任务时的快照；这里只读，凭据在上面的密钥槽位" />
      {!cfg.token ? <p className="muted">填了人的令牌才能看。</p>
        : error ? <p className="error">读不到平台：<Plain text={error} /></p>
        : !items ? <p className="muted">读取中…</p>
        : items.length === 0 ? <p className="muted" data-no-platform>没有登记任何平台。判定权在外部平台的任务，先把平台档案放进 judgebox/connectors.d，重启后在这里看到它，再设好它的密钥槽位。</p>
        : (
          <table className="bank"><tbody>
            {items.map((p) => (
              <tr key={p.id} data-platform={p.id}>
                <td className="k-mono"><Plain text={`${p.id}@${p.version}`} /></td>
                <td className="k-mono t2" title={p.digest}>{shortHash(p.digest)}</td>
                <td>判定器 <Plain text={p.judges.join("、") || "—"} /> · 交付 {p.deliver === "judge" ? "判定器代交" : "智能体自交"}</td>
                <td>槽位 <span className="k-mono"><Plain text={p.slot} /></span> {p.slot_set ? "已设" : "未设"}</td>
                <td className="t2"><Plain text={p.hosts.join("、")} /></td>
              </tr>
            ))}
          </tbody></table>
        )}
    </section>
  );
}

// ---------- 01 密钥 ----------

function Keys() {
  const { api, cfg } = useServices();
  const [view, setView] = useState<KeysView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => {
    if (!cfg.token) return;
    api.keys().then((v) => { setView(v); setError(null); }, (e) => setError(errText(e)));
  }, [api, cfg.token]);
  useEffect(reload, [reload]);

  return (
    <section className="settings-sec" aria-labelledby="sec-keys">
      <SectionHead
        id="sec-keys"
        title="密钥"
        note="只在端点代理进程的内存里：不入库、不进日志、不出导出物，也读不回来"
        right={view && view.slots.some((s) => s.set) ? (
          <Button tone="line" size="sm" data-action="clear-all-keys" onClick={() => void api.clearKeys().then(setView, (e) => setError(errText(e)))}>全部锁定</Button>
        ) : undefined}
      />
      <p className="settings-note" data-key-note><Mark ch="注" tone="xing" />{KEY_NOTE}</p>
      {!cfg.token ? <p className="muted">填了人的令牌（侧栏下方）才能看和改密钥。</p>
        : error ? <p className="error">读不到密钥槽：<Plain text={error} /></p>
        : !view ? <p className="muted">读取中…</p>
        : (
          <ul className="key-slots">
            {view.slots.map((s) => <KeyRow key={s.slot} s={s} onChange={reload} />)}
          </ul>
        )}
    </section>
  );
}

function KeyRow({ s, onChange }: { s: KeySlot; onChange: () => void }) {
  const { api } = useServices();
  const [draft, setDraft] = useState("");
  const [err, setErr] = useState<string | null>(null);
  async function submit() {
    const key = draft;
    setDraft(""); // 发出即清空：密钥不留在页面状态里
    try { await api.putKey(s.slot, key); setErr(null); onChange(); } catch (e) { setErr(errText(e)); }
  }
  return (
    <li className={`key-slot${s.source === "config" ? " legacy" : ""}`} data-key-slot={s.slot} data-key-set={s.set}>
      <Mark ch={s.set ? "设" : "未"} tone={s.set ? "jie" : "wei"} label={s.set ? "已设" : "未设"} />
      <b className="num">{s.slot}</b>
      {s.set ? (
        <>
          <span className="num" data-fingerprint>{s.fingerprint}</span>
          <span className="muted">{SOURCE_WORD[s.source ?? ""] ?? s.source}{s.set_at !== null && ` · ${fmtTs(s.set_at)}`}</span>
          <span className="grow" />
          <Button tone="line" size="sm" data-action="clear-key" onClick={() => void api.clearKey(s.slot).then(onChange, (e) => setErr(errText(e)))}>清除</Button>
        </>
      ) : (
        <form className="row grow" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
          <input type="password" autoComplete="off" spellCheck={false} value={draft} aria-label={`${s.slot} 的密钥`} data-field="key" placeholder="粘贴密钥" onChange={(e) => setDraft(e.target.value)} />
          <Button type="submit" tone="ink" size="sm" disabled={!draft.trim()} data-action="set-key">设置</Button>
        </form>
      )}
      <span className="key-env muted">{s.env ? `持久注入：环境变量 ${s.env}` : "无对应的环境变量"}</span>
      {s.source === "config" && <p className="issues">这把密钥来自配置文件（backend.api_key），下一版不再支持：请清除后在这里输入，或改用环境变量。</p>}
      {err && <p className="error"><Plain text={err} /></p>}
    </li>
  );
}

// ---------- 02 硬顶 ----------

type Part = { draft: Settings; set: (fn: (s: Settings) => void) => void; writable: boolean };

function NumIn({ value, to, from, onSet, label, disabled, field }: { value: number; to: (v: number) => string; from: (s: string) => number | null; onSet: (v: number) => void; label: string; disabled: boolean; field: string }) {
  const [text, setText] = useState(to(value));
  useEffect(() => setText(to(value)), [value, to]);
  const bad = from(text) === null;
  return (
    <input className={`num-in${bad ? " bad" : ""}`} inputMode="decimal" value={text} aria-label={label} aria-invalid={bad} disabled={disabled} data-field={field}
      onChange={(e) => { setText(e.target.value); const v = from(e.target.value); if (v !== null) onSet(v); }} />
  );
}

function Caps({ draft, set, writable }: Part) {
  const c = draft.caps;
  const rows = [
    { key: "practice", word: "练习上限", usd: "practice_usd_milli", wall: "practice_wall_s", where: "图服务 · 只对练习道；与练习道信封同一个数" },
    { key: "open", word: "单任务硬顶", usd: "open_usd_milli", wall: "open_wall_s", where: "图服务 · 所有新建任务，向导也受限；上调下调都只管之后新建的任务" },
    { key: "global", word: "全局硬顶", usd: "global_usd_milli", wall: null, where: "端点代理 · 所有会话累计，立即生效" },
  ] as const;
  const bad = capIssues(c);
  return (
    <div className="caps" data-caps-ok={bad.length === 0}>
      {rows.map((r) => (
        <div key={r.key} className="cap-row" data-cap={r.key}>
          <div className="cap-name"><b>{r.word}</b><span className="t2">{r.where}</span></div>
          <div className="cap-ruler" role="img" aria-label={`${r.word} ${usd(c[r.usd])}`}>
            <b style={{ width: `${rulerFraction(c[r.usd], c.global_usd_milli) * 100}%` }} />
          </div>
          <label className="cap-in">$<NumIn value={c[r.usd]} to={toUsdInput} from={fromUsdInput} label={`${r.word}（美元）`} disabled={!writable} field={r.usd} onSet={(v) => set((s) => { s.caps[r.usd] = v; })} /></label>
          {r.wall ? (
            <label className="cap-in"><NumIn value={c[r.wall]} to={toMinInput} from={fromMinInput} label={`${r.word}（分钟）`} disabled={!writable} field={r.wall} onSet={(v) => set((s) => { s.caps[r.wall!] = v; })} />分钟</label>
          ) : <span className="cap-in muted">不限墙钟</span>}
        </div>
      ))}
    </div>
  );
}

// ---------- 03 模型档案与角色路由 ----------

function Models({ draft, set, writable }: Part) {
  const profiles = draft.models.profiles;
  const edit = (i: number, patch: Partial<ModelProfile>) => set((s) => {
    const old = s.models.profiles[i].name;
    s.models.profiles[i] = { ...s.models.profiles[i], ...patch };
    if (patch.name !== undefined) for (const { role } of ROLES) if (s.models.routes[role] === old) s.models.routes[role] = patch.name; // 改名时路由跟着走
  });
  const cols: { k: keyof ModelProfile; word: string }[] = [
    { k: "name", word: "名称" }, { k: "endpoint", word: "端点" }, { k: "model", word: "模型" }, { k: "family", word: "家族" },
  ];
  return (
    <>
      <div className="table-scroll">
        <table className="mini wide" data-profiles>
          <thead><tr>{cols.map((c) => <th key={c.k}>{c.word}</th>)}<th>档位</th><th>密钥槽</th><th /></tr></thead>
          <tbody>
            {profiles.map((p, i) => (
              <tr key={i} data-profile={p.name}>
                {cols.map((c) => (
                  <td key={c.k}><input value={p[c.k]} disabled={!writable} aria-label={`档案 ${i + 1} ${c.word}`} data-field={`profile.${c.k}`} onChange={(e) => edit(i, { [c.k]: e.target.value })} /></td>
                ))}
                <td>
                  <select value={p.tier} disabled={!writable} aria-label={`档案 ${i + 1} 档位`} onChange={(e) => edit(i, { tier: e.target.value as ModelProfile["tier"] })}>
                    {TIERS.map((t) => <option key={t.tier} value={t.tier}>{t.word}</option>)}
                  </select>
                </td>
                <td><input value={p.key_slot} disabled={!writable} aria-label={`档案 ${i + 1} 密钥槽`} data-field="profile.key_slot" onChange={(e) => edit(i, { key_slot: e.target.value })} /></td>
                <td>
                  <Button tone="bare" size="sm" disabled={!writable || profiles.length <= 1 || ROLES.some((r) => draft.models.routes[r.role] === p.name)}
                    title="还有角色指向它时不能删" onClick={() => set((s) => { s.models.profiles.splice(i, 1); })}>删</Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Button tone="line" size="sm" disabled={!writable} data-action="add-profile"
        onClick={() => set((s) => { s.models.profiles.push({ name: `profile-${s.models.profiles.length + 1}`, endpoint: "", model: "", family: "", tier: "mid", key_slot: "default" }); })}>加一个档案</Button>
      <p className="muted">端点与密钥槽只能在这里改；任务里只能从这些档案里选，不能填端点或密钥。</p>
      <div className="routes" data-routes>
        {ROLES.map(({ role, word }) => (
          <label key={role} className="sel-u">{word}
            <select value={draft.models.routes[role]} disabled={!writable} data-field={`route.${role}`} onChange={(e) => set((s) => { s.models.routes[role] = e.target.value; })}>
              {profiles.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
            </select>
          </label>
        ))}
      </div>
    </>
  );
}

// ---------- 04 风险表 ----------

function Risk({ draft, set, writable }: Part) {
  const edit = (i: number, patch: Partial<RiskRule>) => set((s) => { s.risk[i] = { ...s.risk[i], ...patch }; });
  return (
    <>
      <table className="mini wide" data-risk>
        <thead><tr><th>#</th><th>资源</th><th>模式</th><th>动作</th><th>风险</th><th /></tr></thead>
        <tbody>
          {draft.risk.map((r, i) => (
            <tr key={i}>
              <td className="num">{i + 1}</td>
              <td><input value={r.resource} disabled={!writable} aria-label={`第 ${i + 1} 行资源`} onChange={(e) => edit(i, { resource: e.target.value })} /></td>
              <td><input value={r.pattern} disabled={!writable} aria-label={`第 ${i + 1} 行模式`} onChange={(e) => edit(i, { pattern: e.target.value })} /></td>
              <td><input value={r.actions.join(", ")} disabled={!writable} aria-label={`第 ${i + 1} 行动作`} onChange={(e) => edit(i, { actions: parseActions(e.target.value) })} /></td>
              <td>
                <select value={r.risk} disabled={!writable} aria-label={`第 ${i + 1} 行风险`} onChange={(e) => edit(i, { risk: e.target.value as RiskRule["risk"] })}>
                  {(["r0", "r1", "r2"] as const).map((x) => <option key={x} value={x}>{x}</option>)}
                </select>
              </td>
              <td><Button tone="bare" size="sm" disabled={!writable} onClick={() => set((s) => { s.risk.splice(i, 1); })}>删</Button></td>
            </tr>
          ))}
          <tr className="risk-fallback" data-risk-fallback>
            <td className="num">—</td><td>其它</td><td>任意</td><td>任意</td><td><span className="k-tag">r2</span></td><td className="muted">固定</td>
          </tr>
        </tbody>
      </table>
      <Button tone="line" size="sm" disabled={!writable} data-action="add-risk" onClick={() => set((s) => { s.risk.push(emptyRule()); })}>加一条规则</Button>
    </>
  );
}

// ---------- 练习道信封与预算先验（宪章 03 §2、Q6：只读） ----------

const minutes = (s: number) => `${Math.round((s / 60) * 100) / 100} 分钟`;

function Sources({ version }: { version: number }) {
  const { api } = useServices();
  const [src, setSrc] = useState<SettingsSources | null>(null);
  const [error, setError] = useState<string | null>(null);
  // 设置每保存一版就重读：信封的练习上限抄设置层，摘要跟着变
  useEffect(() => {
    api.settingsSources().then((x) => { setSrc(x); setError(null); }, (e) => setError(errText(e)));
  }, [api, version]);
  if (error) return <section className="settings-sec"><p className="error">读不到信封与先验：<Plain text={error} /></p></section>;
  if (!src) return null;
  const e = src.envelope;
  const p = src.priors;
  return (
    <>
      <section className="settings-sec" aria-labelledby="sec-envelope" data-settings-envelope>
        <SectionHead id="sec-envelope" title="练习道信封"
          note="只读：随起草组件发版；金额与时长上限就是上面的练习上限。新建任务时版本与摘要抄进事件" />
        <table className="bank"><tbody>
          <tr><td>版本</td><td className="k-mono" data-envelope-digest={e.digest ?? ""}>v{e.version} · {e.digest ? shortHash(e.digest) : "内核未加载"}</td></tr>
          <tr><td>零确认</td><td data-zero-confirm={String(e.zero_confirm)}>{e.zero_confirm ? "已放行" : "关着：练习道候选也要你按一下，放行等离线精确率读数"}</td></tr>
          <tr><td>可连的地址</td><td className="k-mono"><Plain text={e.allow.net_patterns.join("  ")} /></td></tr>
          <tr><td>资源与风险</td><td><Plain text={e.allow.resources.join("、")} /> · 风险至多 <span className="k-tag">{e.allow.max_risk}</span></td></tr>
          <tr><td>判定器</td><td><Plain text={e.judge.ids.join("、")} />{e.judge.require_sealed ? " · 答案须在保密库" : ""}</td></tr>
          <tr><td>上限</td><td className="num">{usd(e.budget.usd_milli_max)} · {minutes(e.budget.wall_s_max)} · 最多尝试 {e.goal.max_attempts_max} 次</td></tr>
        </tbody></table>
      </section>

      <section className="settings-sec" aria-labelledby="sec-priors" data-settings-priors>
        <SectionHead id="sec-priors" title="预算先验"
          note="只读：外部注入的“档位 → 默认预算”表；新建任务时预算的默认值从这里来，确认卡上标“估”" />
        <p className={p.placeholder ? "issues" : "muted"} data-priors-version={p.version}>
          <span className="k-mono"><Plain text={p.version} /></span>{p.placeholder ? " · 占位表：数不是校准读数，只为让流程跑通" : ""}
        </p>
        <table className="mini wide" data-priors-table>
          <thead><tr><th>档位</th><th>金额</th><th>时长</th><th>起步占比</th><th>说明</th></tr></thead>
          <tbody>
            {Object.entries(p.tiers).map(([name, t]) => (
              <tr key={name} data-tier={name}>
                <td className="k-mono"><Plain text={name} /></td>
                <td className="num">{usd(t.usd_milli)}</td>
                <td className="num">{minutes(t.wall_s)}</td>
                <td className="num">{t.bootstrap_share === null ? "—" : `${Math.round(t.bootstrap_share * 100)}%`}</td>
                <td className="t2"><Plain text={t.note || "—"} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
