/* 焚决 · 方案分析界面原型（EN16）。内容取自 docs/design/fenjue/engine/examples 的验收夹具丁（case-d）。
   界面用词照 09 §12 与 fenjue-ui v0.3：吞噬引擎→方案分析，异火榜→候选方案，识火/萃意/入位→发现/抽象/映射，
   火意→核心机制，火序→集成顺序，闸点→待你确认，试算→预评估，火位→模块槽。 */
const D = window.DATA;
const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const SLOT = { H1: "会话策略", H2: "调度编排", H3: "工具集", H4: "上下文管理", H5: "知识检索", H6: "可观测性", H7: "结果呈现", H8: "任务解析" };
const KERNEL = { T1: "独立判定", T2: "网络隔离", T3: "预算上限", T4: "事件日志", T5: "证据分级" };
const FIRE = { "h1.solo": "单会话执行", "h7.result": "结果页", "h3.base": "基础工具集", "h6.activity-ledger": "可回放的实时活动流", "h4.views-notes": "三层视图和接力笔记",
  "h6.workbench": "工作台视图", "h7.dual-proof": "证据自动关联", "h1.staged": "阶段证据确认", "h7.result-stages": "结果页（按阶段分组）", "h4.anchored-fold": "带锚压缩" };
const fireName = (ref) => { const id = String(ref).split("@")[0]; return FIRE[id] ?? id; };
const fireRef = (ref) => `${esc(fireName(ref))} <span class="mono t3">${esc(ref)}</span>`;
const W = {
  rec: { recommend: ["推荐", "ok"], optional: ["可选", ""], not_recommend: ["不推荐", "off"] },
  flag: { license_restricted: "许可证受限，只借思路", injection_flagged_sources: "来源含疑似指令（已忽略）", self_ref: "涉及分析本身", profile_stale: "能力剖面过期", needs_new_slot: "需要新模块槽", needs_kernel_split: "需拆出内核变更" },
  gap: { missing: "缺失", weaker: "更弱", new_dim: "新维度" },
  stop: { saturated: "已饱和", weak_signal: "信号太弱", budget: "预算到线", focus_excluded: "不在关注范围", budget_cut: "预算截断" },
  holds: { yes: ["成立", "ok"], partial: ["部分成立", "need"], no: ["不成立", "bad"] },
  costKind: { latency: "时延", storage: "存储", security: "安全", complexity: "复杂度", auditability: "可审计性", spend: "花费", human_attention: "人的注意力" },
  here: { already_paid_by_kernel: "内核已承担", would_pay: "我们也要付", avoided_by_fusion: "融合方案已避免", not_applicable: "不适用" },
  rel: { duplicate: "重复", partial: "部分重叠", complement: "互补" },
  ckind: { kernel: "内核", semantic: "语义", parametric: "参数" },
  res: { fused_away: "融合化解", split_to_kernel: "拆出走内核变更", replace: "替换", partition: "分区并存", param: "参数化", reject: "不采纳", coexist: "并存" },
  outcome: { promising_huolian: ["有望新增能力", "ok"], at_most_helian: ["至多全面提升", ""], maybe_binghuo: ["可能无增益", "need"] },
  rkind: { 新生: "新增", 异火: "外部方案优势", 基线: "基线保障", 本火: "基线保障", 共有: "通用" },
  arms: { B: "基线", A1: "外部方案移植", F: "融合方案", B1: "基线复跑", A0: "外部原版" },
  measure: { structural: "结构读数（CI 可证）", run: "运行读数" },
  bang: { identified: ["已识别", ""], dry_run: ["预评估过", ""], selected: ["选中", "run"], handed_off: ["已交实现线", "run"], absorbed: ["已集成", "ok"], rejected: ["不采纳", "off"], excluded: ["已排除", "off"], superseded: ["已并入", "off"], reverted: ["已回滚", "off"] },
};
const K = { K1: "结构", K2: "无来源专有名词", K3: "不引用代码结构", K4: "不抄写", K5: "有据", K6: "去来源独立（盲审）", K7: "多种实现", K8: "无指令痕迹" };
const V = { V1: "结构", V2: "编号", V3: "引用真实", V4: "公式复算", V5: "禁词", V6: "不抄写", V7: "许可证", V8: "模块清单", V9: "内核", V10: "预登记", V11: "与你的决定一致", V12: "金丝雀" };
const plain = (s) => String(s ?? "").replace(/A′/g, "外部方案移植").replace(/新火/g, "新模块").replace(/G3 搁置/g, "第 3 次确认时搁置");
const chip = (t, cls = "", dot = true) => `<span class="chip ${cls}">${dot ? `<i class="dot${cls === "off" ? " ring" : ""}${cls === "run" ? " live" : ""}"></i>` : ""}${t}</span>`;
const usd = (x) => `$${x.toFixed(2)}`;
const CANDS = D.cand.candidates;
const cand = (id) => CANDS.find((c) => c.id === id);

/* ---------------- 状态 ---------------- */
const S = {
  theme: new URLSearchParams(location.search).get("theme"),
  g: "g1",           // 分析 d1 的阶段：g1 s4 g2 s5 g3 done
  pick: Object.fromEntries(CANDS.map((c) => [c.id, c.recommend.level === "recommend"])),
  excl: {}, title: {}, add: "", note: "",
  e2: {},            // 第 2 次确认：{C1: {act:'confirm'|'back'|'drop', why, edits:{statement}}}
  e3: { C1: "impl", C2: "impl", C3: "hold" }, why3: { C3: "与 C2 都动会话策略，等 C2 评审定论后再看" }, lib: true,
  ctab: "C1", expand: {}, newOpen: false, nf: { mode: "formal", srcs: [{ via: "upload", v: "agent-src.tar.gz", ref: "" }], text: "", focus: [], max: 5 },
  paused: false, fail: false, unparsed: false, sent: null,
};
const Q = new URLSearchParams(location.search);
if (Q.get("g")) S.g = Q.get("g");
for (const k of ["fail", "unparsed", "paused"]) if (Q.get(k)) S[k] = true;
if (S.theme) document.documentElement.dataset.theme = S.theme;

/* ---------------- 运行 ---------------- */
const SPENT = { g1: 6.1, s4: 8.4, g2: 11.9, s5: 13.2, g3: 15.2, done: 15.6 };
function runs() {
  const gi = ["g1", "s4", "g2", "s5", "g3", "done"].indexOf(S.g);
  const d1 = { id: "d1", pid: "p_fixture_delta", mode: "formal", title: "看看这个编码智能体在“证据、阶段、长上下文”上有什么值得借的做法",
    src: "代码归档 · agent-src.tar.gz（你上传的）", lic: "GPL-3.0 · 只借思路", inj: 1, tier: "S", cap: 18, spent: SPENT[S.g], at: ["S3", "S4", "S4", "S5", "S5", "S6"][gi],
    state: S.g.startsWith("g") ? "wait" : S.g === "done" ? "done" : "run", gate: S.g.startsWith("g") ? +S.g[1] : null, started: "今天 09:12" };
  if (S.paused) Object.assign(d1, { state: "paused" });
  return [
    d1,
    { id: "d3", pid: "p_docqa_0412", mode: "formal", title: "一个文档问答服务在检索与引用上的做法", src: "仓库 example/docqa @ v2.4.1 · 服务地址", lic: "Apache-2.0", inj: 0, tier: "M", cap: 26, spent: 4.3, at: "S3", state: "run", gate: null, started: "今天 10:02" },
    { id: "d5", pid: "p_bang_y005", mode: "from_bang", title: "从候选方案取：覆盖可核、可验子代理", src: "候选方案 Y-005、Y-004 · 需补读来源", lic: "待探测", inj: 0, tier: "—", cap: 9, spent: 0.2, at: "S1", state: "grant", gate: null, started: "今天 10:20" },
    { id: "d4", pid: "p_orch_0388", mode: "formal", title: "一个任务编排框架的调度与重试", src: "仓库 example/flowkit @ 3f9c2e1", lic: "MIT", inj: 0, tier: "L", cap: 31, spent: 31, at: "S4", state: "paused", gate: null, started: "昨天 16:40" },
    { id: "d2", pid: "p_fixture_delta_dry", mode: "dry_run", title: "同一归档的预评估：值不值得正式走一遍", src: "代码归档 · agent-src.tar.gz（与上面同一快照）", lic: "GPL-3.0 · 只借思路", inj: 1, tier: "S", cap: 9, spent: 7.4, at: "done", state: "done", gate: null, started: "今天 08:31" },
    { id: "d6", pid: "p_live_0201", mode: "formal", title: "实时执行流的可回放做法", src: "仓库 example/livepanel @ a91d0c7", lic: "MIT", inj: 0, tier: "S", cap: 14, spent: 12.8, at: "done", state: "done", gate: null, started: "11-19", dossier: "001" },
  ];
}
const run = (id) => runs().find((r) => r.id === id);
const MODE = { formal: "正式", dry_run: "预评估", from_bang: "从候选方案取", replace: "重新映射" };
const STEP_ORDER = ["S0", "S1", "S2", "S3", "G1", "S4", "G2", "S5", "G3", "S6"];
const STEP_W = { S0: "立项", S1: "快照", S2: "勘察", S3: "发现", G1: "待你确认", S4: "抽象", G2: "待你确认", S5: "映射", G3: "待你确认", S6: "交接" };
function stateChip(r) {
  if (r.state === "wait") return chip(`待你确认 · 第 ${r.gate} 次`, "need");
  if (r.state === "grant") return chip("待你批准联网", "need");
  if (r.state === "paused") return chip("预算用完，已暂停", "need");
  if (r.state === "run") return chip(`${STEP_W[r.at]}中`, "run");
  if (r.mode === "dry_run") return chip("报告已出", "ok");
  return chip(r.dossier ? `已交接 · 集成记录 ${r.dossier}` : "已交接", "ok");
}
function stepper(r) {
  const cur = r.state === "wait" ? `G${r.gate}` : r.at === "done" ? "END" : r.at;
  const ci = cur === "END" ? 99 : STEP_ORDER.indexOf(cur);
  const order = r.mode === "dry_run" ? STEP_ORDER.filter((x) => !x.startsWith("G")) : STEP_ORDER;
  return `<div class="steps" role="list" aria-label="分析进度">${order.map((k) => {
    const i = STEP_ORDER.indexOf(k);
    const cls = i < ci ? "done" : i === ci ? (k.startsWith("G") || r.state === "grant" || r.state === "paused" ? "wait" : "now") : "";
    return `<div role="listitem" class="st ${k.startsWith("G") ? "gate" : ""} ${cls}"><span class="bar"></span><span>${k.startsWith("G") ? `◆ ${STEP_W[k]}` : STEP_W[k]}</span></div>`;
  }).join("")}</div>`;
}

/* ---------------- 外壳 ---------------- */
const LOGO = `<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 1.5c3.2 4.2 4.3 8.2 0 16.5c-4.3-8.3-3.2-12.3 0-16.5z" fill="currentColor"/><path d="M2.2 7.5c3.4 1.2 5.6 4.6 7 10.5C4.6 16.4 2.2 12.4 2.2 7.5zM17.8 7.5c-3.4 1.2-5.6 4.6-7 10.5c4.6-1.6 7-5.6 7-10.5z" fill="currentColor" opacity=".42"/></svg>`;
function waitingCount() { return runs().filter((r) => ["wait", "grant", "paused"].includes(r.state)).length; }
function shell(page, body) {
  const nv = (h, t, n, on) => `<a class="nv" href="#${h}"${on ? ' aria-current="page"' : ""}>${t}${n ? `<span class="n">${n}</span>` : ""}</a>`;
  return `<div class="mob-top">${LOGO}焚决<span class="t3" style="font-weight:400;margin-left:auto">能力配置 · 方案分析</span></div>
  <div class="app"><nav class="side" aria-label="主导航"><div class="brand">${LOGO}焚决<span class="v">v2</span></div>
    ${nv("", "今日")}${nv("", "任务")}${nv("inbox", "待你处理", waitingCount() + 4, page === "inbox")}${nv("", "知识")}${nv("", "模型")}
    ${nv("runs", "能力配置", waitingCount(), page !== "inbox")}${nv("", "读数")}<span class="sp"></span>${nv("", "设置")}
    <div class="foot">分析实例 · 已连接<br><span class="mono">analysis.local</span></div></nav>
  <main class="main" id="main">${body}</main></div>`;
}
function capTabs(cur) {
  const t = (h, w, c) => `<a href="#${h}"${cur === h ? ' aria-current="page"' : ""}>${w}${c ?? ""}</a>`;
  return `<nav class="tabs" aria-label="能力配置">${t("evo", "演进读数")}${t("runs", "方案分析", waitingCount() ? `<span class="c need">${waitingCount()}</span>` : "")}${t("bang", "候选方案", `<span class="c">${D.bang.length}</span>`)}</nav>`;
}
function capHead(cur, extra = "") {
  return `<div class="crumb">能力配置</div><div style="display:flex;align-items:flex-start;gap:12px;flex-wrap:wrap"><div style="flex:1;min-width:260px"><h1>能力配置 <span class="t2 mono" style="font-weight:400">v2</span></h1>
  <p class="dek">${{ runs: "把一个外部系统交给方案分析：它找出值得借鉴的做法、抽成不带来源细节的核心机制、映射到我们的模块槽，每一步都停下来等你确认。分析只出设计，不写代码。", bang: "所有分析过的外部做法都留在这里，按优先级排序；排除过的也留着理由，避免同一件事被反复提起。", evo: "" }[cur]}</p></div>${extra}</div>${capTabs(cur)}`;
}

/* ---------------- 方案分析列表 ---------------- */
function vRuns() {
  const rs = runs();
  const waiting = rs.filter((r) => ["wait", "grant", "paused"].includes(r.state));
  const row = (r) => `<a class="row g-runs" href="#${r.mode === "dry_run" ? "dry" : "run"}/${r.id}" data-run="${r.id}">
    <span style="min-width:0"><div class="t ell">${esc(r.title)}</div><div class="s ell">${MODE[r.mode]} · ${esc(r.src)}</div></span>
    <span class="h2">${stateChip(r)}</span>
    <span class="h2 t2">${r.at === "done" ? "已完成" : `${STEP_W[r.state === "wait" ? `G${r.gate}` : r.at]}`}</span>
    <span class="h2"><span class="mono t2">${usd(r.spent)} / ${usd(r.cap)}</span><span class="meter ${r.state === "paused" ? "need" : r.state === "run" ? "run" : ""}"><b style="width:${Math.min(100, (r.spent / r.cap) * 100)}%"></b></span></span>
    <span class="r t3">${r.started}</span></a>`;
  return shell("cap", `${capHead("runs", `<div style="display:flex;gap:8px;padding-top:30px"><button class="btn" data-act="from-bang">从候选方案里挑</button><button class="btn pri" data-act="new">新建分析</button></div>`)}
  ${waiting.length ? `<div class="ask"><div class="w"><b>${waiting.length} 个分析在等你</b>${waiting.map((r) => `${esc(r.title.slice(0, 18))}…：${r.state === "wait" ? `第 ${r.gate} 次确认` : r.state === "grant" ? "批准抓取来源" : "追加预算或缩小范围"}`).join("；")}</div><a class="btn sm need" href="#run/${waiting[0].id}">去处理</a></div>` : ""}
  <div class="rows"><div class="row head g-runs"><span>分析</span><span class="h2">状态</span><span class="h2">走到</span><span class="h2">花费 / 上限</span><span class="r">开始</span></div>${rs.map(row).join("")}</div>
  <p class="note">每个分析是分析实例里的一个开放任务：联网只经你批准、预算到线即停、每一步都记进事件日志可回放；它看不到你的真实任务与资料库。</p>`);
}

/* ---------------- 新建分析 ---------------- */
const VIA = { upload: "上传归档", library: "资料库已有", repo: "仓库地址", service: "服务地址", doc: "文档地址", inline: "写在描述里" };
const EST = [["S", "≤ 500 个文件", 2.26, 146, 45, 14], ["M", "≤ 3000 个文件", 2.91, 181, 60, 18], ["L", "≤ 12000 个文件", 3.76, 216, 80, 24], ["XL", "更大", 4.54, 241, 95, 29]];
function vNew() {
  const f = S.nf;
  const src = (s, i) => {
    const needRef = s.via === "repo" && !/^[0-9a-f]{7,40}$|^v?\d+\.\d+/.test(s.ref.trim());
    const localBank = /paoding-bank|calib/i.test(s.v);
    return `<div class="srcrow"><select class="in" data-nf-via="${i}" aria-label="来源类型">${Object.entries(VIA).map(([k, w]) => `<option value="${k}"${s.via === k ? " selected" : ""}>${w}</option>`).join("")}</select>
      <span><input class="in" data-nf-v="${i}" value="${esc(s.v)}" placeholder="${{ upload: "选择 .tar.gz / .zip", library: "资料名", repo: "https://… 仓库地址", service: "https://… 服务地址", doc: "https://… 文档地址", inline: "—" }[s.via]}" aria-label="来源">
      ${localBank ? `<span class="err">这是本机题库或校准目录，按规定不会读取，已拒收。</span>` : ""}</span>
      <span class="h2">${s.via === "repo" ? `<input class="in" data-nf-ref="${i}" value="${esc(s.ref)}" placeholder="提交或标签" aria-label="提交或标签">${needRef && s.v ? `<span class="err">要固定的提交或标签，不抓会变的默认分支</span>` : ""}` : s.via === "service" ? `<button type="button" class="btn sm" style="width:100%">写探测计划…</button>` : `<span class="t3">${s.via === "upload" ? "上传即定版" : s.via === "inline" ? "" : "抓取前要你批准联网"}</span>`}</span>
      <button type="button" class="btn sm bare" data-act="nf-del" data-i="${i}" aria-label="删去这个来源">✕</button></div>`;
  };
  const share = f.mode === "dry" ? 0.5 : 1;
  return `<div class="shade" data-act="new-close"></div><aside class="sheet" role="dialog" aria-label="新建分析">
  <div style="display:flex;align-items:center;gap:10px"><h2 style="flex:1">新建分析</h2><button class="btn sm bare" data-act="new-close">关闭</button></div>
  <p class="t2">分析在单独的分析实例里跑，碰不到你的真实任务与资料库。它只出设计（候选做法、核心机制、映射方案），不写代码、不改能力配置。</p>
  <label class="f">想看这个系统的什么<textarea class="in" data-nf="text" placeholder="例：它在长任务里怎么管上下文、怎么证明每一步做到了">${esc(f.text)}</textarea><span class="h">原话会原样记进事件日志。</span></label>
  <div class="fset"><div class="lg">来源<small>1–8 个；之后的联网申请只能指向这里登记的来源</small></div>${f.srcs.map(src).join("")}
    <button type="button" class="btn sm" data-act="nf-add"${f.srcs.length >= 8 ? " disabled" : ""}>添加来源</button></div>
  <div class="fset"><div class="lg">方式</div>
    <div class="seg" role="group" aria-label="方式"><button type="button" data-act="nf-mode" data-v="formal" aria-pressed="${f.mode === "formal"}">正式</button><button type="button" data-act="nf-mode" data-v="dry" aria-pressed="${f.mode === "dry"}">预评估</button></div>
    <p class="t2" style="margin:8px 0 0">${f.mode === "formal" ? "发现、抽象、映射各停一次等你确认，最后由你决定哪些交实现线。" : "不停下来：自动取优先级前 3 个，一口气走到映射，告诉你“如果做会怎样”。约正式的一半预算；结果不能直接交实现线，要再正式走一遍（会复用已读的内容）。"}</p></div>
  <details class="fset"><summary class="lg" style="cursor:pointer">范围（可选）</summary>
    <div class="checks" style="margin:6px 0 10px">${Object.entries(SLOT).map(([k, w]) => `<label><input type="checkbox" data-nf-focus="${k}"${f.focus.includes(k) ? " checked" : ""}>${w}</label>`).join("")}</div>
    <label class="f" style="max-width:220px">最多给几个候选<input class="in" type="number" min="1" max="12" value="${f.max}" data-nf="max"></label></details>
  <div class="fset"><div class="lg">预计花费<small>大小档要勘察后才知道，这里按四档列出〔占位，来自预算先验数据源〕</small></div>
    <div class="tw"><table class="t"><thead><tr><th>大小</th><th>规模</th><th class="r">输入 token</th><th class="r">输出 token</th><th class="r">机器时间</th><th class="r">预算上限</th></tr></thead><tbody>
    ${EST.map((e) => `<tr><td class="mono">${e[0]}</td><td>${e[1]}</td><td class="r mono">${(e[2] * share).toFixed(2)}M</td><td class="r mono">${Math.round(e[3] * share)}k</td><td class="r mono">${Math.round(e[4] * share)} 分</td><td class="r mono">${usd(e[5] * share)}</td></tr>`).join("")}</tbody></table></div>
    <p class="note">按选中 3 个候选估。不含你三次确认的等待时间。预算是硬上限，用完会停下并交出已完成的部分，你可以追加后续做。</p></div>
  ${f.srcs.some((s) => s.v === "agent-src.tar.gz") ? `<div class="info t2">同一份归档有一个分析已完成（<a href="#dry/d2">预评估</a>）、一个在进行（<a href="#run/d1">正式</a>）。可以继续新建；已读过的内容会按快照复用，不重复花钱。</div>` : ""}
  <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px"><button class="btn" data-act="new-close">取消</button><button class="btn pri" data-act="new-go"${f.text.trim() ? "" : " disabled"}>开始分析</button></div>
  <p class="note" style="text-align:right">本机题库与校准目录一律不读；分析也不会请求你电脑上的文件夹。</p></aside>`;
}

/* ---------------- 分析详情 ---------------- */
function rail(r) {
  const shares = [["发现", 0.45, r.id === "d1" ? Math.min(SPENT[S.g], 7.4) : r.spent], ["抽象", 0.35, r.id === "d1" ? Math.max(0, Math.min(SPENT[S.g] - 7.4, 6.3)) : 0], ["映射", 0.2, r.id === "d1" ? Math.max(0, SPENT[S.g] - 13.7) : 0]];
  const units = r.id === "d3" ? "ddddddddddnnn........" : S.g === "g1" ? "dddddddddddddddd" : "dddddddddddddddd";
  const u16 = units.padEnd(16, ".").slice(0, 16).split("");
  return `<aside class="rail">
  <div class="card pad"><h3>预算<span class="grow"></span><span class="mono t2">${usd(r.spent)} / ${usd(r.cap)}</span></h3>
    ${shares.map(([w, sh, sp]) => `<div class="t2" style="margin-top:6px">${w} <span class="mono">${usd(sp)}</span> / <span class="mono">${usd(r.cap * sh)}</span></div><span class="meter ${sp >= r.cap * sh * 0.98 && r.state === "paused" ? "need" : ""}"><b style="width:${Math.min(100, (sp / (r.cap * sh)) * 100)}%"></b></span>`).join("")}
    <p class="note">整题是硬上限（预算上限由内核执行），最后 10% 留给收尾交付。每步按比例软上限〔占位〕。</p></div>
  <div class="card pad"><h3>进度<span class="grow"></span><span class="t3">模块槽 × 轮次</span></h3>
    <div class="ulab">${Object.keys(SLOT).map((k) => `<span>${k}</span>`).join("")}</div>
    <div class="units" aria-label="发现阶段的单元">${u16.map((c) => `<i class="${c === "d" ? "d" : c === "n" ? "n live" : ""}"></i>`).join("")}</div>
    <p class="t3" style="margin:6px 0 0">上排广度轮，下排深度轮。${r.id === "d3" ? "正在读：上下文管理、知识检索、结果呈现（深度轮）" : "发现 16 个单元全部完成"}</p>
    ${r.id === "d1" && S.g !== "g1" ? `<div class="t2" style="margin-top:10px">抽象：${["C1", "C2", "C3"].map((c) => `<span class="chip ${S.g === "s4" && c !== "C1" ? (c === "C2" ? "run" : "off") : "ok"}" style="margin-right:4px">${c}</span>`).join("")}</div>` : ""}
    <dl class="kv" style="margin-top:10px"><dt>接力会话</dt><dd class="mono">${r.id === "d3" ? 0 : 1} / 8</dd><dt>检查点</dt><dd class="mono">run.json · 10:38</dd></dl></div>
  <div class="card pad"><h3>模型配置</h3><dl class="kv"><dt>读取模型</dt><dd>轻量 · 每批 8 段并行</dd><dt>主模型</dt><dd>高性能</dd><dt>抽取</dt><dd>高性能 × 2（三稿互证）</dd><dt>盲审</dt><dd>标准</dd><dt>映射</dt><dd>标准</dd></dl>
    <p class="note">原文只交给读取模型，主模型只看结构化观察，不能自由执行命令。</p></div>
  <div class="card pad"><h3>依据</h3><dl class="kv"><dt>能力配置</dt><dd class="mono">v2 · 2e56…de21</dd><dt>能力剖面</dt><dd class="mono">4b29…94e2</dd><dt>快照</dt><dd class="mono">8ef7…476d</dd><dt>大小</dt><dd>${r.tier} 档</dd></dl>
    <p class="note">能力配置或剖面变了，这份分析的分数会标“需复算”。</p></div></aside>`;
}
function vRun(id, tab = "now") {
  const r = run(id);
  if (!r) return shell("cap", `<p>没有这个分析。<a href="#runs">回列表</a></p>`);
  const head = `<div class="crumb"><a href="#runs">能力配置 › 方案分析</a></div>
  <div style="display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap"><div style="flex:1;min-width:280px"><h1 style="font-size:var(--fs-xl);line-height:1.4">${esc(r.title)}</h1>
  <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">${stateChip(r)}<span class="chip">${MODE[r.mode]}</span><span class="chip">${esc(r.src)}</span><span class="chip ${r.lic.includes("GPL") ? "need" : ""}">${esc(r.lic)}</span>${r.inj ? `<span class="chip need" title="勘察时发现来源里有一段像是写给智能体的指令；它只被当作数据，没有执行">来源含疑似指令 ${r.inj} 处 · 已忽略</span>` : ""}<span class="mono t3">${r.pid}</span></div></div>
  <div style="display:flex;gap:8px">${r.state === "run" ? `<button class="btn">叫停</button>` : ""}<button class="btn">更多</button></div></div>${stepper(r)}`;
  const tabs = `<nav class="tabs" aria-label="分析">${[["now", r.state === "wait" ? "待你确认" : "当前"], ["report", "报告"], ["trace", "过程"], ["files", "文件"]].map(([k, w]) => `<a href="#run/${id}${k === "now" ? "" : "/" + k}"${tab === k ? ' aria-current="page"' : ""}>${w}${k === "now" && r.state === "wait" ? `<span class="c need">${r.gate}</span>` : ""}</a>`).join("")}</nav>`;
  let body = "";
  if (tab === "trace") body = vTrace(r);
  else if (tab === "files") body = vFiles(r);
  else if (tab === "report") body = vReport(r);
  else if (r.id === "d1") body = S.paused ? vPaused(r) : S.g === "g1" ? vG1() : S.g === "g2" ? vG2() : S.g === "g3" ? vG3() : S.g === "done" ? vDone() : vWorking(S.g === "s4" ? "抽象" : "映射");
  else if (r.state === "grant") body = vGrant();
  else if (r.state === "paused") body = vPaused(r);
  else if (r.state === "run") body = vWorking("发现", r);
  else body = `<div class="info">分析已完成，交接给了实现线，见<a href="#evo">集成记录 ${r.dossier}</a>。</div>`;
  return shell("cap", `${head}${tabs}<div class="grid2"><div style="min-width:0">${body}</div>${rail(r)}</div>`);
}
function vWorking(step, r) {
  const items = step === "发现"
    ? [["10:31", "读取", "上下文管理 · 深度轮：读 8 段，记 5 条观察"], ["10:33", "主模型", "比对上下文管理的差距：压缩 0 → 外部 2"], ["10:36", "读取", "知识检索 · 深度轮：读 6 段"], ["10:38", "检查点", "写 run.json：13 / 16 个单元完成"]]
    : step === "抽象"
      ? [["11:02", "主模型", "C1 核心机制：三稿一致度 1.7 / 2"], ["11:05", "校验", "C1：K1–K8 全过（K6 盲审未猜中来源）"], ["11:07", "主模型", "C2 机制骨架：6 步"], ["11:09", "抽取模型", "C2 第二稿…"]]
      : [["11:40", "映射", "C1 拆成 1 个决策点，归到结果呈现"], ["11:43", "映射", "C2 替换单会话执行，带结果页分组"], ["11:45", "计算", "集成顺序：C1 → C2 → C3"]];
  return `<div class="card pad"><div style="display:flex;align-items:center;gap:10px"><span class="dot live" style="color:var(--dai)"></span><b>正在${step}</b><span class="t2">做完会停下来等你确认，不需要你盯着</span></div>
    <ol class="trace" style="margin-top:10px">${items.map((x) => `<li><span class="mono t3">${x[0]}</span><b>${x[1]}</b><span class="ell">${x[2]}</span></li>`).join("")}</ol>
    <p class="note">完整过程在“过程”一栏，和任务页同一份记录。</p></div>`;
}
function vGrant() {
  return `<div class="ask" style="align-items:flex-start"><div class="w"><b>要你批准：抓取来源</b>为了补读“覆盖可核”“可验子代理”两条候选的来源，分析要从 <span class="mono">github.com/example/planbench</span> 浅克隆提交 <span class="mono">5b02e7d</span>。只抓这一个地址、只读这一个版本，抓完立刻撤销联网权限。</div>
  <div style="display:flex;flex-direction:column;gap:6px"><button class="btn sm pri">批准一次</button><button class="btn sm">改为我来上传</button><button class="btn sm bare">拒绝</button></div></div>
  <p class="note">这是任务页里同一种联网授权卡；分析只能申请新建时登记过的来源。</p>`;
}
function vPaused(r) {
  return `<div class="ask" style="align-items:flex-start"><div class="w"><b>预算用完，停在抽象这一步</b>${r.id === "d1" ? "C1、C2 的核心机制已完成；C3 做到第二稿时预算到线。" : "C1 的核心机制已完成；C2 做到第二稿时预算到线。"}已完成的部分已经交给你，下次接着做时不会重做。</div></div>
  <div class="card pad"><h3 style="margin-bottom:8px">怎么继续</h3>
  <label class="f" style="max-width:280px">追加预算（美元）<input class="in" value="6.00"></label>
  <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap"><button class="btn pri" data-act="resume">追加并继续</button><button class="btn" data-act="resume">只做完已完成的部分</button><button class="btn bare">结束分析</button></div>
  <p class="note">“只做完已完成的部分”等于缩小范围：放弃未完成的候选，直接进入你的第 2 次确认。</p></div>`;
}

/* ----- 第 1 次确认：发现 ----- */
function decisionBlock(n) {
  const L = [`【决定 v1】闸点 ${n}`];
  if (n === 1) {
    const ch = selected();
    L.push(`选：${ch.join("，") || "无"}`);
    const ex = Object.entries(S.excl).filter(([, v]) => v !== undefined);
    if (ex.length) L.push(`排除：${ex.map(([k, v]) => `${k}（${v || "未写理由"}）`).join("，")}`);
    Object.entries(S.title).forEach(([k, v]) => L.push(`改：${k}.title = ${v}`));
  }
  if (n === 2) {
    const sel = selected();
    const by = (a) => sel.filter((c) => (S.e2[c]?.act ?? "confirm") === a);
    L.push(`确认：${by("confirm").join("，") || "无"}`);
    sel.forEach((c) => Object.entries(S.e2[c]?.edits ?? {}).forEach(([k, v]) => L.push(`改：${c}.essence.${k} = ${v}`)));
    L.push(`退回：${by("back").map((c) => `${c}（${S.e2[c]?.why || "未写理由"}）`).join("，") || "无"}`);
    L.push(`放弃：${by("drop").map((c) => `${c}（${S.e2[c]?.why || "未写理由"}）`).join("，") || "无"}`);
  }
  if (n === 3) {
    const sel = kept();
    const by = (a) => sel.filter((c) => S.e3[c] === a);
    L.push(`交实现线：${by("impl").join("，") || "无"}`);
    if (by("hold").length) L.push(`搁置：${by("hold").map((c) => `${c}（${S.why3[c] || "未写理由"}）`).join("，")}`);
    if (by("excl").length) L.push(`排除：${by("excl").map((c) => `${c}（${S.why3[c] || "未写理由"}）`).join("，")}`);
    if (S.lib) L.push("存入资料库：报告");
  }
  if (S.note.trim()) L.push(`备注：${S.note.trim()}`);
  return L.join("\n");
}
const selected = () => CANDS.filter((c) => S.pick[c.id] && S.excl[c.id] === undefined).map((c) => c.id);
const kept = () => selected().filter((c) => !["drop"].includes(S.e2[c]?.act));
function decideBar(n, label, ok = true) {
  return `<div class="decide"><div style="min-width:0"><div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:6px"><b>${label}</b><span class="opt" style="display:contents">
    <label class="t2" style="display:inline-flex;gap:6px;align-items:center">追加预算 $<input class="in" style="width:80px;height:28px" data-s="add" value="${esc(S.add)}" placeholder="0"></label>
    <input class="in" style="flex:1;min-width:160px;height:28px" data-s="note" value="${esc(S.note)}" placeholder="备注（可选），会一起记下"></span></div>
    <details><summary>记进事件日志的原文（分析按这段执行）</summary><pre data-block>${esc(decisionBlock(n))}</pre></details></div>
    <div class="acts"><button class="btn pri" data-act="submit" data-n="${n}"${ok ? "" : " disabled"}>${n === 3 ? "提交裁决" : "确认，继续下一步"}</button><span class="t3" style="text-align:center">提交后无法撤回，但可以在下一次确认时退回</span></div></div>`;
}
function topWarnings(n) {
  let s = "";
  if (S.fail && n === 1) s += `<div class="warn"><div class="w"><b>交付带“未过”标记：校验 V5 禁词</b>给人看的摘要里出现了内部名词。分析已重写 2 次仍未通过，按规定照实交给你；内容可以看，但建议退回重做。<div style="margin-top:6px"><button class="btn sm">退回重做发现</button></div></div></div>`;
  if (S.unparsed && n === 2) s += `<div class="ask"><div class="w"><b>上次的确认里有 1 行没读懂</b><span class="mono">改：C9.title = 带锚折叠</span> —— 没有候选 C9。分析没有猜，其余几行已照办；请在下面重新确认这一项。</div></div>`;
  return s;
}
function vG1() {
  const c0 = D.cand;
  const n = selected().length;
  const rows = CANDS.map((c) => {
    const ex = S.excl[c.id] !== undefined;
    const rec = W.rec[c.recommend.level];
    const title = S.title[c.id] ?? c.title;
    const open = S.expand[c.id];
    return `<div class="row g-cand ${ex ? "excl" : ""}" data-cand="${c.id}">
      <span><input type="checkbox" class="pick" data-pick="${c.id}"${S.pick[c.id] && !ex ? " checked" : ""}${ex ? " disabled" : ""} aria-label="选中 ${esc(title)}"></span>
      <span class="mono t2 h2">${c.id}</span>
      <span style="min-width:0"><div class="t">${S.retitling === c.id ? `<input class="in" style="height:28px;max-width:260px" data-retitle="${c.id}" value="${esc(title)}" aria-label="新名字"> <button class="btn sm" data-act="retitle-ok" data-id="${c.id}">好</button>` : `<span class="edit ${S.title[c.id] ? "edited" : ""}" data-act="retitle" data-id="${c.id}" title="点击改名">${esc(title)}</span>`}${c.dedupe ? ` <a class="chip" href="#bang/${c.dedupe.bang}" style="text-decoration:none">已在候选方案 ${c.dedupe.bang}</a>` : ` <span class="chip">新登记</span>`}</div>
        <div class="s">${esc(c.seed.shihuo.phenomenon)}</div>
        <div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:4px">${(c.flags || []).map((f) => `<span class="t3">· ${W.flag[f] ?? f}</span>`).join("")}</div></span>
      <span class="h1 h2"><span>${SLOT[c.slot]}</span><div class="t3">${(c.also_slots || []).map((s) => SLOT[s]).join("、")}</div></span>
      <span class="h2"><span class="pbar"><span class="mono">${c.priority.toFixed(1)}</span><span class="meter"><b style="width:${(c.priority / 4) * 100}%"></b></span></span><div class="mono t3" title="价值 · 置信 · 难度 · 风险">V${c.value} · C${c.confidence.toFixed(1)} · D${c.difficulty} · ${c.risk}</div></span>
      <span>${chip(rec[0], rec[1])}<div><button class="linkbtn t3" data-act="expand" data-id="${c.id}" aria-expanded="${!!open}">${open ? "收起" : "依据"}</button> · <button class="linkbtn t3" data-act="exclude" data-id="${c.id}">${ex ? "撤销排除" : "排除"}</button></div></span>
      ${ex ? `<div class="cand-x"><label class="f">排除理由（会记进候选方案，避免以后反复提起）<input class="in" data-excl="${c.id}" value="${esc(S.excl[c.id])}" placeholder="例：已在待办里，不必走分析"></label></div>` : ""}
      ${open ? `<div class="cand-x"><div class="t2"><b>推荐理由：</b>${esc(c.recommend.why)}</div><div class="t2"><b>差距：</b>${esc(c.seed.shihuo.gap)}</div>
        <div class="tw"><table class="t"><thead><tr><th>维度</th><th class="r">我们</th><th class="r">外部</th><th>类型</th><th class="r">权重</th><th class="r">痛点</th><th>痛点依据</th><th>观察</th></tr></thead><tbody>
        ${c.gaps.map((g) => `<tr><td class="mono">${g.dim}</td><td class="r mono">${g.ours}${g.ours_by ? `<div class="t3">${fireName(g.ours_by)}</div>` : ""}</td><td class="r mono">${g.theirs}</td><td>${W.gap[g.type]}</td><td class="r mono">${g.weight}</td><td class="r mono">${g.pain}</td><td class="t3">${esc(plain(g.pain_basis))}</td><td class="mono t3">${g.observations.join(" ")}</td></tr>`).join("")}</tbody></table></div>
        <p class="note">优先级 P = 价值 × 置信 ÷ (难度 × (1 + 风险))，校验器会按同一公式复算。推荐不是决定。</p></div>` : ""}
    </div>`;
  }).join("");
  return `${topWarnings(1)}<div class="card pad"><p class="sum">${esc(c0.plain_summary)}</p></div>
  <div class="sec"><div class="sec-h"><h2>候选做法</h2><small>勾选要继续抽象的；点标题可改名</small><span class="grow"></span><span class="t2">已选 ${n} 个 · 抽象预计 <span class="mono">$${(n * 2.1).toFixed(2)}</span>〔占位〕</span></div>
  <div class="rows"><div class="row head g-cand"><span></span><span class="h2">编号</span><span>做法</span><span class="h1 h2">模块槽</span><span class="h2" title="P = 价值 × 置信 ÷ (难度 × (1 + 风险))">优先级</span><span>建议</span></div>${rows}</div></div>
  <div class="sec"><div class="sec-h"><h2>我们已有且不差</h2><small>外部有、我们持平或更强；证明这些地方也看过了</small></div>
  <div class="rows">${c0.already_have.map((a) => `<div class="row g-have"><span class="mono">${a.dim}</span><span class="mono t2">我们 ${a.ours} · 外部 ${a.theirs}</span><span class="t2">${fireName(a.by)}</span></div>`).join("")}</div></div>
  <div class="sec"><div class="sec-h"><h2>只是普通需求</h2><small>不是一种可复用的做法</small></div>
  <div class="rows">${c0.not_fire.map((a) => `<div class="row g-half"><span>${esc(a.what)}</span><span class="t2">${esc(a.why)}</span></div>`).join("")}</div></div>
  <div class="sec"><div class="sec-h"><h2>覆盖情况</h2><small>每个模块槽读了多少、为什么停；没见到相关机制：${c0.unseen_slots.map((s) => SLOT[s]).join("、")}</small></div>
  <div class="tw"><table class="t"><thead><tr><th>模块槽</th><th class="r">读了几段</th><th class="r">输入 token</th><th style="width:30%"></th><th>停下的原因</th></tr></thead><tbody>
  ${c0.coverage.map((v) => `<tr><td>${SLOT[v.slot]}</td><td class="r mono">${v.excerpts}</td><td class="r mono">${(v.tokens_in / 1000).toFixed(0)}k</td><td><span class="meter"><b style="width:${(v.excerpts / 6) * 100}%"></b></span></td><td>${W.stop[v.stop]}</td></tr>`).join("")}</tbody></table></div>
  <p class="note">校验 V1–V12 全过。原文只交给读取模型；这一页的每一句都能点回观察记录和来源位置。</p></div>
  ${decideBar(1, `第 1 次确认 · 选 ${n} 个做抽象`, n > 0)}`;
}

/* ----- 第 2 次确认：抽象 ----- */
function essenceCard(id) {
  const e = D.ess[id]; const m = e.masked; const st = S.e2[id] ?? {}; const act = st.act ?? "confirm";
  const editedStmt = st.edits?.statement;
  const holdChip = (h) => chip(W.holds[h][0], W.holds[h][1], false);
  const ksEdit = editedStmt && /agent|Claude|codex|\//i.test(editedStmt);
  return `<article class="mcard ${act === "drop" ? "dropped" : ""}" data-essence="${id}">
  <div class="mh"><span class="mono t2">${id}</span><b>${esc(S.title[id] ?? cand(id).title)}</b>${chip(`${SLOT[cand(id).slot]}`, "", false)}
    <span class="grow" style="flex:1"></span>
    <div class="seg" role="group" aria-label="${id} 的决定">${[["confirm", "确认"], ["back", "退回重做"], ["drop", "放弃"]].map(([k, w]) => `<button type="button" data-act="e2" data-id="${id}" data-v="${k}" aria-pressed="${act === k}">${w}</button>`).join("")}</div></div>
  ${act !== "confirm" ? `<label class="f" style="margin-top:10px">${act === "back" ? "退回理由（分析会按这句重做这一个）" : "放弃理由（记进候选方案）"}<input class="in" data-e2why="${id}" value="${esc(st.why ?? "")}"></label>` : ""}
  <div class="t3" style="margin-top:12px">核心机制（一句话，4–80 字，不提实现）</div>
  ${S.editing === id ? `<textarea class="in" data-e2edit="${id}" style="font-size:var(--fs-lg)">${esc(editedStmt ?? m.statement)}</textarea><div style="display:flex;gap:8px;margin-top:6px"><button class="btn sm pri" data-act="e2save" data-id="${id}">保存修改</button><button class="btn sm" data-act="e2cancel">取消</button><span class="t3">保存后会重跑 K1–K8</span></div>`
    : `<p class="stmt"><span class="${editedStmt ? "edited" : ""}">${esc(editedStmt ?? m.statement)}</span> <button class="linkbtn t3" data-act="e2edit" data-id="${id}">改</button></p>`}
  ${ksEdit ? `<div class="warn" style="margin:8px 0"><div class="w"><b>你的改动没过 K2：出现了来源专有名词</b>可以再改，也可以坚持；坚持会记为“人改，检验未过：K2”，一路带进集成记录。</div></div>` : ""}
  <p class="t2" style="margin:4px 0 0">${esc(plain(e.plain_summary))}</p>
  <div class="sub-h">它怎么运作<small>${m.mechanism.length} 步；只用通用词，不含来源的代码结构</small></div>
  <div class="mflow">${m.mechanism.map((s) => `<div class="mstep"><div class="k">${s.step} · 当 ${esc(s.trigger)}</div><div class="tr">${esc(s.transform)}</div><div class="io">${esc(s.input)} → ${esc(s.output)}</div>${s.invariant ? `<div class="inv">始终保证：${esc(s.invariant)}</div>` : ""}<div>${(s.primitives || []).map((p) => `<span class="prim">${esc(p)}</span>`).join("")}</div></div>`).join("")}</div>
  <div class="sub-h">它依赖的前提<small>在我们这里成不成立</small></div>
  <div class="tw"><table class="t"><tbody>${m.premises.map((p) => `<tr><td style="width:38%">${esc(p.statement)}</td><td style="width:96px">${holdChip(p.holds_here)}</td><td>${esc(plain(p.why))}${p.replaced_by ? `<div class="t2">改用：${esc(plain(p.replaced_by))}</div>` : ""}</td></tr>`).join("")}</tbody></table></div>
  <div class="sub-h">代价<small>原系统付了什么，在我们这里谁来付</small></div>
  <div class="tw"><table class="t"><tbody>${m.costs.map((c) => `<tr><td style="width:38%">${esc(c.cost)}</td><td style="width:96px">${W.costKind[c.kind]}</td><td>${W.here[c.here]}${c.kernel ? ` <span class="t3">· 涉及${KERNEL[c.kernel]}</span>` : ""}</td></tr>`).join("")}</tbody></table></div>
  <div class="sub-h">和现有模块的关系</div>
  <div class="tw"><table class="t"><tbody>${(m.overlaps || []).map((o) => `<tr><td style="width:38%">${fireRef(o.fire)}</td><td style="width:96px">${W.rel[o.relation]}</td><td class="t2">${esc(plain(o.note ?? ""))}</td></tr>`).join("") || `<tr><td class="t2">没有重叠</td></tr>`}</tbody></table></div>
  <div class="sub-h">冲突与化解</div>
  <div class="tw"><table class="t"><tbody>${(m.conflicts || []).map((c) => `<tr><td style="width:38%">${esc(plain(c.statement))}<div class="t3">与${c.with.startsWith("T") ? KERNEL[c.with] : fireName(c.with)} · ${W.ckind[c.kind]}冲突</div></td><td style="width:96px">${W.res[c.resolution]}</td><td class="t2">${esc(plain(c.how ?? ""))}</td></tr>`).join("") || `<tr><td class="t2">没有冲突</td></tr>`}</tbody></table></div>
  <div class="sub-h">融合假设<small>和我们现有的结合后，能得到两边都没有的什么</small></div>
  <p style="margin:0">${esc(plain(m.fusion.statement))}</p>
  ${m.fusion.emergent.length ? `<div class="tw" style="margin-top:8px"><table class="t"><thead><tr><th>新增指标</th><th>为什么基线做不到</th><th>为什么照搬也做不到</th><th>怎么量</th><th class="r">门槛</th></tr></thead><tbody>
    ${m.fusion.emergent.map((x) => `<tr><td><b>${esc(x.dim)}</b> ${x.dir === "down" ? "↓" : "↑"}</td><td>${esc(plain(x.why_zero_B))}</td><td>${esc(plain(x.why_zero_A1))}</td><td>${W.measure[x.measure]}${x.how ? `<div class="t3">${esc(plain(x.how))}</div>` : ""}</td><td class="r mono">${x.gate}</td></tr>`).join("")}</tbody></table></div>` : `<p class="t2">没有新增指标：最好的结局是“全面提升”。</p>`}
  <div class="sub-h">至少两种实现思路<small>证明抽到的是机制，不是原系统的那一种写法</small></div>
  <ol style="margin:0;padding-left:20px">${m.implementations.map((x) => `<li>${esc(x.sketch)} <span>${x.primitives.map((p) => `<span class="prim">${esc(p)}</span>`).join("")}</span></li>`).join("")}</ol>
  <div class="sub-h">自检<small>${e.drafts.n === 3 ? `三稿互证，一致度 ${e.drafts.agreement} / 2` : "单稿（预评估）"}</small></div>
  ${e.drafts.disagreements?.length ? `<p class="t2" style="margin:0 0 6px">分歧：${e.drafts.disagreements.map((x) => esc(plain(x))).join("；")}</p>` : ""}
  <div class="ks">${["K1", "K2", "K3", "K4", "K5", "K6", "K7", "K8"].map((k) => { const r = (e.checks || []).find((x) => x.id === k); const bad = ksEdit && k === "K2"; return r ? `<span class="${bad ? "bad" : r.advisory ? "adv" : r.ok ? "ok" : "bad"}" title="${K[k]}${r.detail ? "：" + esc(r.detail) : ""}">${k} ${K[k]} ${bad ? "✕" : r.ok ? "✓" : "✕"}</span>` : ""; }).join("")}</div>
  </article>`;
}
function vG2() {
  const sel = selected();
  if (!sel.includes(S.ctab)) S.ctab = sel[0];
  const n = sel.filter((c) => (S.e2[c]?.act ?? "confirm") === "confirm").length;
  return `${topWarnings(2)}<div class="card pad"><p class="sum">${sel.length} 个做法的核心机制已经抽好，都去掉了来源细节。请逐个看：确认、改一句，或退回重做。</p></div>
  <div class="ctabs" role="group" aria-label="候选">${sel.map((c) => { const a = S.e2[c]?.act ?? "confirm"; return `<button type="button" data-act="ctab" data-id="${c}" aria-pressed="${S.ctab === c}">${c} ${esc(S.title[c] ?? cand(c).title)} <span class="t3">${a === "confirm" ? (S.e2[c]?.edits ? "已改" : "") : a === "back" ? "退回" : "放弃"}</span></button>`; }).join("")}</div>
  ${essenceCard(S.ctab)}
  ${decideBar(2, `第 2 次确认 · ${n} 个继续映射`, true)}`;
}

/* ----- 第 3 次确认：映射与集成顺序 ----- */
function placementCard(id) {
  const p = D.pl[id];
  const dry = D.dry.items.find((x) => x.candidate === id);
  const v = S.e3[id];
  const head = `<div class="mh"><span class="mono t2">${id}</span><b>${esc(S.title[id] ?? cand(id).title)}</b><span style="flex:1"></span>
    <div class="seg" role="group" aria-label="${id} 的裁决">${[["impl", "交实现线"], ["hold", "搁置"], ["excl", "排除"]].map(([k, w]) => `<button type="button" data-act="e3" data-id="${id}" data-v="${k}" aria-pressed="${v === k}">${w}</button>`).join("")}</div></div>
    ${v !== "impl" ? `<label class="f" style="margin-top:10px">${v === "hold" ? "搁置理由" : "排除理由"}<input class="in" data-e3why="${id}" value="${esc(S.why3[id] ?? "")}"></label>` : ""}`;
  if (!p) return `<article class="mcard">${head}<p class="t2" style="margin-top:10px">映射方案（节选）：主模块槽 ${SLOT[dry.slot]}；${dry.conflicts.map((x) => esc(plain(x))).join("；")}；内核改动预判：无；难度 ${dry.difficulty}。和 C2 都会动会话策略，集成顺序排在 C2 之后。</p></article>`;
  const f = p.fire;
  return `<article class="mcard" data-placement="${id}">${head}
  <p class="t2" style="margin:10px 0 0">${esc(plain(p.plain_summary))}</p>
  <dl class="kv" style="grid-template-columns:110px minmax(0,1fr);margin-top:12px">
    <dt>新模块</dt><dd>${fireRef(`${f.id}@${f.ver}`)} · ${SLOT[f.slot]}${f.also_touches?.length ? `，兼及${f.also_touches.map((s) => SLOT[s]).join("、")}` : ""}</dd>
    ${p.group?.length ? `<dt>模块组</dt><dd>${p.group.map((g) => fireRef(`${g.id}@${g.ver}`)).join("、")}</dd>` : ""}
    <dt>替换</dt><dd>${p.replaces ? `${fireRef(p.replaces)} <span class="t3">（被替换的进 Holdout 对照）</span>` : "不替换，新增"}</dd>
    <dt>内核改动</dt><dd><b>0 行</b> <span class="t3">（预判必须为空，否则不合格）</span></dd>
    <dt>难度</dt><dd class="mono">${p.difficulty.value} / 5 <span class="t3">${Object.entries(p.difficulty.parts).filter(([, x]) => x).map(([k, x]) => `${{ base: "基础", behavior_slots_minus_1: "多动一个模块槽", extra_ports: "多要接口", new_tool: "新工具", kernel_split: "拆内核", a1_infeasible: "无法照搬", run_only_emergent: "只能运行时量" }[k]} +${x}`).join("，")}</span></dd></dl>
  <div class="sub-h">对照组<small>评估时同时跑这几组</small></div>
  <div class="tw"><table class="t"><tbody>${Object.entries(p.arms).map(([k, x]) => `<tr><td style="width:120px">${W.arms[k]}</td><td>${esc(plain(x))}</td></tr>`).join("")}</tbody></table></div>
  <div class="sub-h">预登记指标<small>先登记、后评估；做完不许改门槛</small></div>
  <div class="tw"><table class="t"><thead><tr><th>指标</th><th>类别</th><th>方向</th><th class="r">门槛</th><th>怎么量</th></tr></thead><tbody>
  ${p.readings.map((x) => `<tr><td>${esc(x.dim)}${x.mandatory ? ` <span class="chip" style="font-size:11px">必登</span>` : ""}</td><td>${W.rkind[x.kind] ?? x.kind}</td><td title="${x.dir === "down" ? "越低越好" : "越高越好"}">${x.dir === "down" ? "↓" : "↑"}</td><td class="r mono">${esc(String(x.gate ?? "—"))}</td><td class="mono t3">${esc(x.test ?? x.run ?? "")}</td></tr>`).join("")}</tbody></table></div>
  <div class="sub-h">实现步骤<small>交给实现线；分析本身不写代码</small></div>
  <div class="tw"><table class="t"><thead><tr><th class="r">#</th><th>做什么</th><th>在哪</th><th>验收</th><th class="r">内核</th></tr></thead><tbody>
  ${p.steps.map((s) => `<tr><td class="r mono">${s.n}</td><td>${esc(plain(s.do))}</td><td class="mono t3">${(s.where || []).map(esc).join("<br>")}</td><td>${esc(plain(s.accept))}</td><td class="r mono">${s.kernel_lines}</td></tr>`).join("")}</tbody></table></div>
  <div class="sub-h">冲突</div>
  <div class="tw"><table class="t"><tbody>
  ${p.conflicts.fires.map((c) => `<tr><td style="width:38%">${fireRef(c.fire)}</td><td style="width:96px">${W.res[c.resolution] ?? c.resolution}</td><td class="t2">${esc(plain(c.note))}</td></tr>`).join("")}
  ${p.conflicts.kernel.map((c) => `<tr><td>内核 · ${KERNEL[c.kernel]}</td><td>${W.res[c.resolution]}</td><td class="t2">${esc(plain(c.note))}</td></tr>`).join("")}
  ${(p.conflicts.candidates || []).map((c) => `<tr><td>候选 · ${esc(c.other)}</td><td>${esc({ compatible: "兼容", order: "有先后", depends: "依赖", exclusive: "互斥" }[c.relation] ?? c.relation)}</td><td class="t2">${esc(plain(c.note ?? ""))}</td></tr>`).join("")}</tbody></table></div>
  </article>`;
}
function vG3() {
  const sel = kept();
  if (!sel.includes(S.ctab)) S.ctab = sel[0];
  const held = Object.fromEntries(D.held.map((h) => [h.candidate, h]));
  return `<div class="card pad"><p class="sum">映射方案已出：${sel.length} 个做法都不用改内核。下面是建议的集成顺序；逐个决定交给实现线、搁置还是排除。</p></div>
  <div class="sec"><div class="sec-h"><h2>集成顺序</h2><small>按优先级排，同一模块槽有先后的串行；前一个评审定论后，后一个自动做一次映射复核</small></div>
  <div class="card pad"><div class="order">${D.order.filter((o) => sel.includes(o.candidate)).map((o) => `<div class="ord ${held[o.candidate] || S.e3[o.candidate] !== "impl" ? "held" : ""}"><span class="pos">${o.position}</span>
    <span><b>${o.candidate} ${esc(S.title[o.candidate] ?? cand(o.candidate).title)}</b>${o.waits_for ? ` <span class="t3">等 ${o.waits_for.join("、")}</span>` : ""}<div class="t3 mono">${esc(o.why)}</div>${held[o.candidate] ? `<div class="t2">${esc(plain(held[o.candidate].note))}</div>` : ""}</span>
    <span class="r">${S.e3[o.candidate] === "impl" ? chip("交实现线", "run") : S.e3[o.candidate] === "hold" ? chip("搁置", "need") : chip("排除", "off")}</span></div>`).join("")}</div></div></div>
  <div class="sec"><div class="ctabs" role="group" aria-label="候选">${sel.map((c) => `<button type="button" data-act="ctab" data-id="${c}" aria-pressed="${S.ctab === c}">${c} ${esc(S.title[c] ?? cand(c).title)}</button>`).join("")}</div>
  ${placementCard(S.ctab)}</div>
  <label class="t2" style="display:flex;gap:8px;align-items:center;margin-top:8px"><input type="checkbox" data-s="lib"${S.lib ? " checked" : ""}>把这次的分析报告以你的身份存进资料库（只作参考，不作依据）</label>
  ${decideBar(3, `第 3 次确认 · ${sel.filter((c) => S.e3[c] === "impl").length} 个交实现线`, true)}`;
}
function vDone() {
  const impl = kept().filter((c) => S.e3[c] === "impl");
  return `<div class="card pad"><p class="sum">分析完成。${impl.length} 个做法已打包交给实现线，接下来每个都会开一份集成记录，走内核测试和对照评估，最后回到你这里评审。</p></div>
  <div class="sec"><div class="sec-h"><h2>接下来</h2></div><div class="rows">
  ${impl.map((c, i) => `<div class="row" style="grid-template-columns:34px minmax(0,1fr) 150px"><span class="mono">${i + 1}</span><span><b>${c} ${esc(S.title[c] ?? cand(c).title)}</b><div class="s">导入后分配集成记录编号 → 设计 PR 给你评审 → 实现 → 内核测试 → 对照评估 → 你评审</div></span><span>${chip(i === 0 ? "等实现线导入" : "排队：等前一个定论", i === 0 ? "run" : "")}</span></div>`).join("")}</div></div>
  <div class="sec"><div class="sec-h"><h2>候选方案的变化</h2><small>由导入命令写入，随 PR 给你审</small></div><div class="rows">
  ${D.bang_updates.map((u) => `<a class="row" href="#bang/${u.id}" style="grid-template-columns:70px minmax(0,1fr) 140px"><span class="mono">${u.id}</span><span>${esc(D.bang.find((b) => b.id === u.id)?.title ?? "")}<div class="s">${esc(plain(u.note ?? u.run?.outcome ?? ""))}</div></span><span>${u.op === "set_status" ? chip(W.bang[u.status][0], W.bang[u.status][1]) : chip("记一次分析", "")}</span></a>`).join("")}</div></div>`;
}

/* ----- 报告、过程、文件 ----- */
function vReport(r) {
  const gi = ["g1", "s4", "g2", "s5", "g3", "done"].indexOf(S.g);
  const parts = [["交付 1 · 发现报告", D.cand.plain_summary, 0], ["交付 2 · 核心机制", "三个做法的核心机制已抽好：" + ["C1", "C2", "C3"].map((c) => `${cand(c).title}——${D.ess[c].masked.statement}`).join("；"), 2], ["交付 3 · 映射与集成顺序", "C1 证据自动关联放在结果呈现，新增；C2 阶段证据确认替换单会话执行，带结果页按阶段分组；C3 带锚压缩与 C2 都动会话策略，排在 C2 后。三个都不改内核。", 4]];
  if (r.id !== "d1") return `<div class="info">报告随每次交付更新，这个分析还没有交付。</div>`;
  return parts.filter((p) => gi >= p[2]).map((p) => `<article class="card pad" style="margin-bottom:12px"><h3>${p[0]}</h3><p style="margin:8px 0 0">${esc(plain(p[1]))}</p><p class="note">每条关键判断都引用了勘察输出或快照；结构化产物见“文件”。</p></article>`).join("");
}
function vTrace(r) {
  const T = [["0:00", "立项", "开题：开放任务，预算上限 $18.00"], ["0:01", "快照", "上传的归档定版 · 8ef7…476d · 许可证 GPL-3.0（只借思路）"], ["0:02", "勘察", "412 个文件、18 个模块；来源专有名词 37 个；疑似指令 1 处（已标出，只当数据）"], ["0:04", "读取", "会话策略 · 广度轮：读 6 段 → 6 条观察"], ["0:06", "读取", "上下文管理 · 广度轮：读 6 段 → 5 条观察"], ["0:09", "主模型", "差距比对：结果呈现 自动关联 0 → 2"], ["0:15", "主模型", "深度轮：会话策略、上下文管理、结果呈现"], ["0:27", "校验", "候选清单 V1–V12 全过"], ["0:28", "交付", "发现报告 · 3 个候选 · 等你第 1 次确认"]];
  return `<div class="card pad"><ol class="trace">${T.map((x) => `<li><span class="mono t3">${x[0]}</span><b>${x[1]}</b><span>${esc(x[2])}</span></li>`).join("")}</ol>
  <p class="note">这一栏直接复用任务页的“过程”视图（同一份事件与活动记录，可回放到任一时刻）。读取模型看到的原文不进主会话；这里只显示观察。</p></div>`;
}
function vFiles(r) {
  const F = [["快照 · agent-src.tar.gz", "你给的材料", "8ef7…476d"], ["勘察单", "执行输出", "3c10…a9e2"], ["观察库 obs.jsonl（38 条）", "执行输出", "71be…0c44"], ["候选清单 candidates.json", "分析写的", "d2a1…5f03"], ["核心机制 C1 / C2 / C3", "分析写的", "…"], ["映射方案 C1 / C2", "分析写的", "…"], ["交接包 handoff.json", "分析写的", "…"], ["运行状态 run.json", "执行输出", "检查点"]];
  return `<div class="rows">${F.map((f) => `<div class="row" style="grid-template-columns:minmax(0,1fr) 110px 110px"><span>${f[0]}</span><span class="t2">${f[1]}</span><span class="mono t3 r">${f[2]}</span></div>`).join("")}</div>
  <p class="note">“分析写的”只能当说明，不能当依据；分析交付里的每条判断只能引用“执行输出”和“你给的材料”。</p>`;
}

/* ---------------- 预评估报告 ---------------- */
function vDry() {
  const r = run("d2"); const d = D.dry; const t = d.estimate.tokens;
  return shell("cap", `<div class="crumb"><a href="#runs">能力配置 › 方案分析</a></div><h1 style="font-size:var(--fs-xl)">${esc(r.title)}</h1>
  <div style="display:flex;gap:6px;flex-wrap:wrap">${stateChip(r)}<span class="chip">预评估</span><span class="chip need">${r.lic}</span><span class="mono t3">${r.pid}</span></div>${stepper(r)}
  <div class="card pad" style="margin-top:14px"><p class="sum">${esc(plain(d.plain_summary))}</p>
    <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap"><button class="btn pri" data-act="formal">正式走一遍</button><span class="t2" style="align-self:center">会复用这次读过的内容，从你的第 1 次确认开始</span></div></div>
  <div class="sec"><div class="sec-h"><h2>正式走一遍要多少</h2><small>按自动取的 3 个估〔占位〕</small></div>
  <div class="tw"><table class="t"><thead><tr><th>模型档位</th><th class="r">输入</th><th class="r">输出</th></tr></thead><tbody>
  ${[["轻量（读取）", t.light], ["标准（盲审、映射）", t.mid], ["高性能（主模型、抽取）", t.heavy]].map(([w, x]) => `<tr><td>${w}</td><td class="r mono">${(x.in / 1e6).toFixed(2)}M</td><td class="r mono">${(x.out / 1e3).toFixed(0)}k</td></tr>`).join("")}
  <tr><td><b>机器时间</b></td><td class="r mono" colspan="2">约 ${d.estimate.minutes} 分钟，外加你三次确认</td></tr></tbody></table></div></div>
  <div class="sec"><div class="sec-h"><h2>如果做，可能会怎样</h2><small>只是预判，不进任何读数</small></div>
  ${d.items.map((x) => { const c = cand(x.candidate); const o = W.outcome[x.likely_outcome]; return `<article class="mcard"><div class="mh"><span class="mono t2">${x.candidate}</span><b>${esc(c.title)}</b>${chip(o[0], o[1])}<span style="flex:1"></span><span class="t2">${SLOT[x.slot]}${x.group_slots.length ? " + " + x.group_slots.map((s) => SLOT[s]).join("、") : ""} · 难度 ${x.difficulty}</span></div>
    <p class="stmt" style="font-size:var(--fs-lg)">${esc(D.ess[x.candidate].masked.statement)}</p>
    <dl class="kv" style="grid-template-columns:110px minmax(0,1fr)"><dt>为什么这么判</dt><dd>${esc(plain(x.why))}</dd><dt>替换</dt><dd>${x.replaces ? fireRef(x.replaces) : "不替换，新增"}</dd><dt>冲突</dt><dd>${x.conflicts.map((y) => esc(plain(y).replace(/(\S+)@\d+/, (m) => fireName(m)).replace(/none → coexist/, "无冲突，并存").replace(/parametric → replace/, "参数冲突，替换").replace(/parametric → partition/, "参数冲突，分区并存"))).join("<br>")}</dd><dt>内核改动</dt><dd>预判无</dd>
    <dt>自检</dt><dd><div class="ks">${x.checks.map((k) => `<span class="${k.ok ? "ok" : "bad"}">${k.id} ${K[k.id]} ${k.ok ? "✓" : "✕"}</span>`).join("")}</div></dd></dl></article>`; }).join("")}
  <p class="note">预评估是单稿、不盲审、不写实现步骤；结果进候选方案，状态“预评估过”，不能直接交实现线。</p></div>`);
}

/* ---------------- 候选方案 ---------------- */
function bangStatus(b) {
  const done = S.g === "done";
  const up = done ? D.bang_updates.find((u) => u.id === b.id && u.op === "set_status") : null;
  return up ? up.status : b.id === "Y-002" || b.id === "Y-003" || b.id === "Y-007" ? "dry_run" : b.status;
}
function vBang(sel) {
  const list = D.bang.map((b) => ({ ...b, st: bangStatus(b), p: { "Y-003": 4.0, "Y-007": 1.0, "Y-002": 1.0, "Y-005": 0.8, "Y-004": 0.5, "Y-006": 0.3 }[b.id] ?? null }))
    .sort((a, b) => (b.p ?? -1) - (a.p ?? -1));
  const row = (b) => { const s = W.bang[b.st]; return `<a class="row g-bang" href="#bang/${b.id}"${sel === b.id ? ' style="background:var(--sel)"' : ""}><span class="mono">${b.id}</span>
    <span style="min-width:0"><div class="t">${esc(b.title)}</div><div class="s ell">${esc(b.essence)}</div></span><span class="h2">${SLOT[b.slot]}</span><span>${chip(b.id === "Y-001" ? "已集成 · v2" : s[0], s[1])}</span>
    <span class="h2 r mono">${b.p !== null ? b.p.toFixed(1) : "—"}</span><span class="h2 t3">${b.id === "Y-001" ? "集成记录 001" : ["Y-002", "Y-003", "Y-007"].includes(b.id) ? "今天 · 两次分析" : b.id === "Y-005" || b.id === "Y-004" ? "分析中 · 需补读来源" : "需复算：能力配置已到 v2"}</span></a>`; };
  const b = sel ? D.bang.find((x) => x.id === sel) : null;
  const drawer = b ? `<aside class="card pad" data-bang="${b.id}"><div style="display:flex;gap:8px;align-items:center"><span class="mono t2">${b.id}</span><b style="flex:1">${esc(b.title)}</b><a class="btn sm bare" href="#bang">关闭</a></div>
    <p class="stmt" style="font-size:var(--fs-lg)">${esc(b.essence)}</p>
    <dl class="kv"><dt>模块槽</dt><dd>${SLOT[b.slot]}</dd><dt>状态</dt><dd>${chip(W.bang[bangStatus(b)][0], W.bang[bangStatus(b)][1])}</dd>${b.fusion ? `<dt>融合假设</dt><dd>${esc(b.fusion)}</dd>` : ""}<dt>预计内核</dt><dd>${esc(String(b.kernel_lines_expected ?? "0 行"))}</dd></dl>
    <div class="sub-h">分析记录<small>每次分析留一行，失败的也留</small></div>
    <ol class="trace">${(["Y-002", "Y-003", "Y-007"].includes(b.id) ? [["08:31", "预评估", "走完 · 有望新增能力"], ["11:52", "正式", S.g === "done" ? (b.id === "Y-002" ? "第 3 次确认：搁置，等 Y-007 定论" : "第 3 次确认：交实现线") : "进行中"]] : b.id === "Y-001" ? [["11-19", "正式", "交实现线 → 集成记录 001 → 新增能力，v2"]] : [["11-20", "整理", "由案例文档迁入"]]).map((x) => `<li><span class="mono t3">${x[0]}</span><b>${x[1]}</b><span>${esc(x[2])}</span></li>`).join("")}</ol>
    <div class="sub-h">状态史</div><ol class="trace">${(b.history || []).map((h) => `<li><span class="mono t3">${esc(String(h.date ?? h.at ?? "").slice(5))}</span><b>${esc(W.bang[h.status]?.[0] ?? h.status)}</b><span class="t2">${esc(plain(h.note ?? h.why ?? ""))}</span></li>`).join("") || `<li><span></span><span class="t2">—</span></li>`}</ol>
    <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap"><button class="btn sm pri" data-act="new">以它为起点分析</button><button class="btn sm">排除…</button></div></aside>` : "";
  return shell("cap", `${capHead("bang", `<div style="display:flex;gap:8px;padding-top:30px"><button class="btn pri" data-act="from-bang">找点什么分析</button></div>`)}
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">${["全部", "可以分析", "进行中", "已集成", "已排除与不采纳"].map((w, i) => `<button class="chip" style="cursor:pointer;${i === 0 ? "background:var(--ink);color:var(--btn-ink-fg);border-color:var(--ink)" : ""}">${w}</button>`).join("")}</div>
  <div class="${b ? "grid2" : ""}" style="${b ? "grid-template-columns:minmax(0,1fr) 380px" : ""}"><div class="rows"><div class="row head g-bang"><span>编号</span><span>做法</span><span class="h2">模块槽</span><span>状态</span><span class="h2 r">优先级</span><span class="h2">最近</span></div>${list.map(row).join("")}</div>${drawer}</div>
  <p class="note">“找点什么分析”先从这里取：状态是已识别或预评估过、没被排除、模块槽没被占用的前 3 个，复算后直接进你的第 1 次确认；这里没有存货才会问你要一个外部系统。排除过的只有在模块槽的配置变了、来源出了新版本、或你明说要再看时才会被再次提起。</p>`);
}

/* ---------------- 待你处理 ---------------- */
function vInbox() {
  const rs = runs().filter((r) => ["wait", "grant", "paused"].includes(r.state));
  return shell("inbox", `<div class="crumb">待你处理</div><h1>待你处理</h1><p class="dek">方案分析的确认和其他待办在同一处，按种类分组。</p>
  <div class="sec-h"><h2>方案分析</h2><small>${rs.length} 件</small></div>
  <div class="rows">${rs.map((r) => `<a class="row g-inbox" href="#run/${r.id}"><span>${r.state === "wait" ? chip(`第 ${r.gate} 次确认`, "need") : r.state === "grant" ? chip("联网授权", "need") : chip("预算用完", "need")}</span><span style="min-width:0"><div class="t ell">${esc(r.title)}</div><div class="s">${r.state === "wait" ? ["", "从 3 个候选做法里挑要继续的", "确认核心机制，可以改一句", "决定哪些交给实现线"][r.gate] : r.state === "grant" ? "批准抓取 github.com/example/planbench @ 5b02e7d" : "追加预算继续，或缩小范围"}</div></span><span class="h2 r t3">${r.started}</span></a>`).join("")}</div>
  <div class="sec-h" style="margin-top:22px"><h2>任务</h2><small>4 件（略）</small></div>`);
}
function vEvo() {
  return shell("cap", `${capHead("evo")}<div class="info">这里是现有的“演进读数”页面（版本、集成记录、Holdout 对照），不变。方案分析交接出的做法，导入后在这里出现为新的集成记录。</div>`);
}

/* ---------------- 原型控制条 ---------------- */
function proto() {
  const g = [["g1", "第 1 次确认"], ["s4", "抽象中"], ["g2", "第 2 次确认"], ["g3", "第 3 次确认"], ["done", "已交接"]];
  return `<details class="proto" ${S.protoOpen ? "open" : ""}><summary>原型控制（不是界面的一部分）</summary><b style="margin-top:6px">分析 d1 走到</b><div class="bs">${g.map(([k, w]) => `<button data-act="g" data-v="${k}" aria-pressed="${S.g === k}">${w}</button>`).join("")}</div>
  <b style="margin-top:6px">异常</b><div class="bs"><button data-act="tog" data-v="fail" aria-pressed="${S.fail}">校验未过</button><button data-act="tog" data-v="unparsed" aria-pressed="${S.unparsed}">有一行没读懂</button><button data-act="tog" data-v="paused" aria-pressed="${S.paused}">预算用完</button></div>
  <b style="margin-top:6px">主题</b><div class="bs">${[["", "跟随"], ["light", "亮"], ["dark", "暗"]].map(([k, w]) => `<button data-act="theme" data-v="${k}" aria-pressed="${(S.theme ?? "") === k}">${w}</button>`).join("")}</div></details>`;
}

/* ---------------- 路由与事件 ---------------- */
function render() {
  const h = location.hash.slice(1) || "runs";
  const [a, b, c] = h.split("/");
  let html = a === "run" ? vRun(b, c) : a === "dry" ? vDry() : a === "bang" ? vBang(b) : a === "inbox" ? vInbox() : a === "evo" ? vEvo() : vRuns();
  if (S.newOpen) html += vNew();
  const keep = document.activeElement?.dataset ? Object.entries(document.activeElement.dataset)[0] : null;
  const pos = document.activeElement?.selectionStart;
  $("#root").innerHTML = html + (Q.get("shot") ? "" : proto());
  if (keep) { const el = $(`[data-${keep[0].replace(/[A-Z]/g, (m) => "-" + m.toLowerCase())}="${keep[1]}"]`); if (el && el.focus) { el.focus(); try { el.setSelectionRange(pos, pos); } catch { /* 不是文本框 */ } } }
}
window.addEventListener("hashchange", () => { window.scrollTo(0, 0); render(); });
document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-act]"); if (!el) return;
  const a = el.dataset.act, id = el.dataset.id, v = el.dataset.v;
  if (a === "new") { S.newOpen = true; S.nf.mode = "formal"; }
  else if (a === "from-bang") { S.newOpen = true; S.nf = { ...S.nf, mode: "formal", text: "从候选方案里挑优先级最高、还能做的 3 个", srcs: [{ via: "inline", v: "候选方案 Y-005、Y-004、Y-006", ref: "" }] }; }
  else if (a === "new-close") S.newOpen = false;
  else if (a === "nf-mode") S.nf.mode = v;
  else if (a === "nf-add") S.nf.srcs.push({ via: "repo", v: "", ref: "" });
  else if (a === "nf-del") S.nf.srcs.splice(+el.dataset.i, 1);
  else if (a === "new-go") { S.newOpen = false; location.hash = "run/d5"; }
  else if (a === "expand") S.expand[id] = !S.expand[id];
  else if (a === "exclude") { if (S.excl[id] !== undefined) delete S.excl[id]; else S.excl[id] = ""; }
  else if (a === "retitle") S.retitling = id;
  else if (a === "retitle-ok") { const t = $(`[data-retitle="${id}"]`).value.trim(); if (t && t !== cand(id).title) S.title[id] = t; else delete S.title[id]; S.retitling = null; }
  else if (a === "ctab") S.ctab = id;
  else if (a === "e2") S.e2[id] = { ...(S.e2[id] ?? {}), act: v };
  else if (a === "e2edit") S.editing = id;
  else if (a === "e2cancel") S.editing = null;
  else if (a === "e2save") { const t = $(`[data-e2edit="${id}"]`).value.trim(); S.e2[id] = { ...(S.e2[id] ?? {}), edits: t && t !== D.ess[id].masked.statement ? { statement: t } : undefined }; S.editing = null; }
  else if (a === "e3") S.e3[id] = v;
  else if (a === "submit") { const n = +el.dataset.n; S.note = ""; S.add = ""; S.g = n === 1 ? "s4" : n === 2 ? "s5" : "done"; if (n < 3) setTimeout(() => { S.g = n === 1 ? "g2" : "g3"; render(); }, 2400); window.scrollTo(0, 0); }
  else if (a === "resume") { S.paused = false; }
  else if (a === "formal") { location.hash = "run/d1"; }
  else if (a === "g") { S.g = v; S.protoOpen = true; }
  else if (a === "tog") { S[v] = !S[v]; S.protoOpen = true; }
  else if (a === "theme") { S.theme = v || null; if (v) document.documentElement.dataset.theme = v; else delete document.documentElement.dataset.theme; S.protoOpen = true; }
  else return;
  e.preventDefault(); render();
});
document.addEventListener("input", (e) => {
  const t = e.target, d = t.dataset;
  if (d.pick) S.pick[d.pick] = t.checked;
  else if (d.excl) S.excl[d.excl] = t.value;
  else if (d.s === "lib") S.lib = t.checked;
  else if (d.s) S[d.s] = t.value;
  else if (d.e2why) S.e2[d.e2why] = { ...(S.e2[d.e2why] ?? {}), why: t.value };
  else if (d.e3why) S.why3[d.e3why] = t.value;
  else if (d.nf) S.nf[d.nf] = t.value;
  else if (d.nfVia) { S.nf.srcs[+d.nfVia].via = t.value; }
  else if (d.nfV) S.nf.srcs[+d.nfV].v = t.value;
  else if (d.nfRef) S.nf.srcs[+d.nfRef].ref = t.value;
  else if (d.nfFocus) { S.nf.focus = t.checked ? [...S.nf.focus, d.nfFocus] : S.nf.focus.filter((x) => x !== d.nfFocus); }
  else if (d.e2edit || d.retitle) return;
  else return;
  if (d.s === "note" || d.s === "add" || d.excl || d.e2why || d.e3why || d.nf || d.nfV || d.nfRef) { const b = $("[data-block]"); if (b) b.textContent = decisionBlock(+($("[data-act=submit]")?.dataset.n ?? 1)); if (d.nf === "text" || d.nfV || d.nfRef) render(); return; }
  render();
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && S.newOpen) { S.newOpen = false; render(); } });
render();
