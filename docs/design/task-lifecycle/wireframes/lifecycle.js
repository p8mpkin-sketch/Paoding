/* 任务生命周期地图的交互稿：叠在 v4 原型（base.js）上，只用 kit.css / screens.css 的令牌与既有类；新增样式写在 LCSS。
   屏：map（地图总览）、set-models（设置·模型与密钥）、set-budget（设置·预算与硬顶）、confirm（确认道·自由任务）、
       ws-stations（工作区站位条与扩权差异卡）、accept（按验收清单验收）。原型里的数字都是示例；预算数字来自占位表。 */
const LCSS = `<style>
.lc-lanes{display:grid;grid-template-columns:76px repeat(6,minmax(0,1fr));border-top:1px solid var(--ink);margin-top:6px}
.lc-lanes>div{border-bottom:1px solid var(--rule);border-right:1px solid var(--rule);min-height:74px;padding:5px 7px;position:relative}
.lc-lanes>div:nth-child(7n){border-right:0}
.lc-lanes .ln{font:500 12px var(--serif);color:var(--ink-3);display:flex;flex-direction:column;justify-content:center;gap:2px;border-right:1px solid var(--ink)!important}
.lc-lanes .ln b{color:var(--ink);font-weight:600;font-size:13px}
.lc-lanes .hd{min-height:0;padding:6px 9px;font:11px var(--mono);color:var(--ink-3);border-bottom:1px solid var(--rule-2)}
.stn{border:1px solid var(--ink);background:var(--sheet);padding:6px 8px;height:100%;display:flex;flex-direction:column;gap:2px}
.stn .no{font:500 10.5px var(--mono);color:var(--ink-3);display:flex;justify-content:space-between}
.stn .nm{font:600 14px var(--serif)}
.stn .cm{font:10.5px/1.45 var(--mono);color:var(--ink-3)}
.stn.agent{border-style:dashed}
.stn.hum{border-color:var(--zhu);box-shadow:inset 3px 0 0 var(--zhu)}
.stn .st{margin-top:auto;font:11px var(--sans);color:var(--ink-2)}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;border:1.25px solid var(--ink-2);vertical-align:-1px;margin-right:4px}
.dot.full{background:var(--ink-2)} .dot.half{background:linear-gradient(90deg,var(--ink-2) 50%,transparent 50%)}
.lc-track{display:grid;grid-template-columns:76px repeat(6,minmax(0,1fr));align-items:center;height:20px;font-size:11.5px}
.lc-track .tl{font:500 11px var(--mono);color:var(--ink-3)}
.lc-track .seg{height:0;border-top:1.5px solid var(--ink);position:relative}
.lc-track .seg.skip{border-top:1.5px dashed var(--ink-3)}
.lc-track .seg.zhu::after{content:"";position:absolute;left:50%;top:-5px;width:8px;height:8px;border-radius:50%;background:var(--zhu)}
.legend{display:flex;gap:18px;font-size:12px;color:var(--ink-2);margin-top:6px;flex-wrap:wrap}
.legend i{display:inline-block;width:18px;height:11px;border:1px solid var(--ink);vertical-align:-1px;margin-right:5px;background:var(--sheet)}
.sec{margin-top:22px}
.tbl{width:100%;border-collapse:collapse;font-size:12.5px}
.tbl th{font:500 11px var(--sans);letter-spacing:.08em;color:var(--ink-3);text-align:left;padding:8px 8px 6px 0;border-bottom:1px solid var(--rule-2)}
.tbl td{padding:9px 8px 9px 0;border-bottom:1px solid var(--rule);vertical-align:middle}
.tbl td.m{font:12px var(--mono)} .tbl td.r{text-align:right}
.pill{font:500 11px var(--mono);padding:0 6px;border:1px solid currentColor;border-radius:2px;line-height:17px;white-space:nowrap;display:inline-block}
.pill.r0{color:var(--qing)} .pill.r1{color:var(--zhe)} .pill.r2{color:var(--zhu)}
.pill.src{color:var(--ink-3)}
.keybox{display:flex;align-items:center;gap:10px;border:1px solid var(--rule-3);height:30px;padding:0 10px;font:12px var(--mono);color:var(--ink-3);width:260px;background:var(--sheet)}
.note{font-size:12px;color:var(--ink-3);margin-top:8px}
.warn{border:1px solid var(--zhu-line);border-left:3px solid var(--zhu);background:var(--zhu-soft);padding:10px 12px;font-size:12.5px;margin-top:14px}
.capr{display:grid;grid-template-columns:90px minmax(0,1fr) 130px 230px;gap:14px;align-items:center;padding:10px 0;border-bottom:1px solid var(--rule);font-size:12.5px}
.capr b{font:600 13.5px var(--serif)}
.trk{position:relative;height:12px;border-bottom:1px solid var(--rule-3)}
.trk i{position:absolute;left:0;bottom:0;height:12px;border:1px solid var(--ink);border-bottom:0;background:var(--sheet)}
.trk u{position:absolute;left:0;bottom:0;height:5px;background:var(--ink)}
.caps{position:relative;height:118px;margin:18px 0 6px;border-bottom:1px solid var(--ink)}
.caps .bar{position:absolute;bottom:0;border:1px solid var(--ink);background:var(--sheet)}
.caps .lbl{position:absolute;font-size:12px;white-space:nowrap}
.caps .lbl b{font:600 13px var(--serif);display:block}
.caps .spent{position:absolute;bottom:0;height:8px;background:var(--ink)}
.strip{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));border:1px solid var(--rule-2);background:var(--sheet)}
.strip div{padding:6px 7px;font-size:11.5px;border-right:1px solid var(--rule);color:var(--ink-3);white-space:nowrap;overflow:hidden}
.strip div:last-child{border-right:0}
.strip div small{display:block;font:10px var(--mono);color:var(--ink-4)}
.strip .done{color:var(--ink-2)} .strip .done small{color:var(--ink-3)}
.strip .cur{background:var(--ink);color:var(--paper)} .strip .cur small{color:var(--paper);opacity:.7}
.strip .wait{background:var(--zhu-soft);color:var(--zhu-ink);box-shadow:inset 0 -2px 0 var(--zhu)} .strip .wait small{color:var(--zhu-ink)}
.cblk{border-top:1px solid var(--ink);padding:14px 0 6px;display:grid;grid-template-columns:150px minmax(0,1fr);gap:18px}
.cblk .h{font:600 15px var(--serif)} .cblk .h small{display:block;font:11px var(--mono);color:var(--ink-3);font-weight:400;margin-top:3px}
.acc{display:grid;grid-template-columns:30px minmax(0,1fr) auto;gap:12px;align-items:start;padding:12px 0;border-bottom:1px solid var(--rule)}
.acc .id{font:500 12px var(--mono);color:var(--ink-3);padding-top:2px}
.acc .evd{font:11.5px var(--mono);color:var(--ink-3);margin-top:5px}
.yn{display:inline-flex;border:1px solid var(--rule-3);border-radius:2px}
.yn span{padding:3px 12px;font-size:12px;color:var(--ink-2);border-right:1px solid var(--rule-3)} .yn span:last-child{border-right:0}
.yn span.y{background:var(--qing);color:#fff} .yn span.n{background:var(--zhu);color:#fff}
.steps3{display:flex;gap:0;border:1px solid var(--rule-2);margin-top:16px}
.steps3 div{flex:1;padding:10px 14px;border-right:1px solid var(--rule-2);font-size:12.5px;color:var(--ink-3)} .steps3 div:last-child{border-right:0}
.steps3 b{font:600 14px var(--serif);display:block;color:inherit}
.steps3 .ok{color:var(--ink-2)} .steps3 .on{background:var(--ink);color:var(--paper)}
.dcols{display:grid;grid-template-columns:1fr;gap:10px;margin-top:8px}
.dcols>div{border:1px solid var(--rule-2);padding:8px 10px;background:var(--sheet)}
.dcols .r{font:11.5px/1.8 var(--mono)} .dcols .add{background:var(--zhu-soft);color:var(--zhu-ink);margin:0 -4px;padding:0 4px}
</style>`;

const stDot = (s) => `<span class="dot ${s === '●' ? 'full' : s === '◐' ? 'half' : ''}"></span>`;
const stLbl = { '●': '完整', '◐': '部分', '○': '无' };

/* 站位条：十二站，cur 为当前站，wait 为等人的站 */
const STN = [['00', '设置'], ['01', '说出来'], ['02', '起草'], ['03', '校验'], ['04', '确认'], ['05', '登记'], ['06', '执行'], ['07', '判定'], ['08', '人介入'], ['09', '关题'], ['10', '验收'], ['11', '沉淀']];
const strip = (cur, wait = -1, note = {}) => `<div class="strip" role="list" aria-label="任务所在的站">${STN.map(([n, t], i) => `<div role="listitem" class="${i === wait ? 'wait' : i === cur ? 'cur' : i < cur ? 'done' : ''}"><small>S${+n} ${i < cur && i !== wait ? '✓' : ''}</small>${note[i] || t}</div>`).join('')}</div>`;

/* 一 地图总览 */
function lcMap() {
  const card = (no, nm, cm, st, cls = '') => `<div class="stn ${cls}"><div class="no"><span>S${no}</span><span>${stDot(st)}${stLbl[st]}</span></div><div class="nm">${nm}</div><div class="cm">${cm}</div></div>`;
  const lane = (who, sub, cells) => `<div class="ln"><b>${who}</b><span>${sub}</span></div>${cells.map(c => `<div>${c || ''}</div>`).join('')}`;
  const head = (a) => `<div class="hd"></div>${a.map(t => `<div class="hd">${t}</div>`).join('')}`;
  const track = (lbl, segs) => `<div class="lc-track"><span class="tl">${lbl}</span>${segs.map(s => `<div class="seg ${s}"></div>`).join('')}</div>`;
  const pre = `${head(['00 设置就绪', '01 说出来', '02 起草', '03 校验', '04 确认', '05 登记开题'])}
    ${lane('人', '拍板', [card(0, '设置就绪', '模型档案 · 密钥槽<br>三道硬顶 · 风险表', '◐', 'hum'), card(1, '说出来', '一句话 · 导入 · 克隆', '○', 'hum'), '', '', card(4, '确认', '确认卡 · /new/advanced', '◐', 'hum'), ''])}
    ${lane('系统', '确定性', ['', '', '', card(3, '校验', 'vet() → Vetted<br>出处账 · 道别', '◐'), '', card(5, '登记开题', 'open_problem · 信封<br>判据入日志', '●')])}
    ${lane('智能体', '只能起草', ['', '', card(2, '起草', 'qicao · Draft<br>只指认原文区间', '○', 'agent'), '', '', ''])}`;
  const post = `${head(['06 执行', '07 判定', '08 人介入', '09 关题', '10 验收', '11 沉淀'])}
    ${lane('人', '拍板', ['', '', card(8, '人介入', '扩权 · r2 · 续期门<br>指导 · 停滞', '◐', 'hum'), '', card(10, '验收', 'solved 核证据根<br>accepted 逐条验收', '◐', 'hum'), ''])}
    ${lane('系统', '确定性', ['', card(7, '判定', 'exact_match · replay<br>洁净重放 · 保密库', '●'), '', card(9, '关题', '四顾 · 满志 · 藏刀', '◐'), '', card(11, '沉淀', '判例封存 · 通鉴<br>资产 · 读数', '◐')])}
    ${lane('智能体', '只能提议', [card(6, '执行', '司南 · 会话 · 沙箱<br>代理计量 · 硬顶', '●', 'agent'), '', '', '', '', ''])}`;
  return LCSS + shell(hdr('<b>今日</b><span>/</span><span>任务怎样走完</span>', NEW), `
  <div class="mast" style="position:relative;padding-bottom:10px"><div class="vlabel" style="position:absolute;left:-30px;top:4px"><b>卷一</b><span>宪章</span></div><div><div class="cap">工作台宪章 · v0.1 · 待裁决</div><h1 style="margin-top:6px;font-size:28px">一件任务的十二站</h1><div class="dek">每个页面都钉在某一站上。凡是让一个量成为事实的站，责任方都是系统；智能体只起草、只提议。朱红标出需要你的站。</div></div><span class="sp"></span><span class="zhupi">新需求即修图</span></div>${BRUSH}
  <div class="cap" style="margin-top:8px">开题之前</div>
  <div class="lc-lanes">${pre}</div>
  ${track('练习道', ['', '', '', '', 'skip', ''])}
  ${track('确认道', ['', '', '', '', 'zhu', ''])}
  <div class="cap" style="margin-top:6px">开题之后</div>
  <div class="lc-lanes">${post}</div>
  ${track('有答案', ['', '', '', '', 'skip', ''])}
  ${track('无答案', ['', '', '', '', 'zhu', ''])}
  <div class="legend"><span><i></i>系统</span><span><i style="border-style:dashed"></i>智能体</span><span><i style="border-color:var(--zhu);box-shadow:inset 3px 0 0 var(--zhu)"></i>人</span><span>${stDot('●')}完整 20</span><span>${stDot('◐')}部分 12</span><span>${stDot('○')}无 15</span><span style="color:var(--ink-3)">虚线：该道跳过此站　朱点：该道在此站必须有人</span></div>`);
}

/* 设置页外框 */
function setShell(on, title, dek, body) {
  const nav = [['个人', ''], ['外观', 'look'], ['快捷键', 'keys'], ['访问令牌', 'tok'], ['系统', ''], ['模型与密钥', 'models'], ['预算与硬顶', 'budget'], ['风险表', 'risk'], ['练习道信封', 'env'], ['预算先验', 'prior'], ['判定器', 'judge'], ['运行环境', 'rt'], ['变更记录', 'log']]
    .map(([t, k]) => k ? `<div class="${k === on ? 'on' : ''}">${t}</div>` : `<div class="cap">${t}</div>`).join('');
  return LCSS + shell(hdr(`<b>设置</b><span>/</span><span>系统</span><span>/</span><span>${title}</span>`, `<span class="ink3 mono" style="font-size:11.5px">设置 v14 · sha256:7c1e…a90b</span>`), `
  <div class="mast" style="position:relative;border-bottom:0"><div class="vlabel" style="position:absolute;left:-30px;top:4px"><b>卷六</b><span>设置</span></div><div><div class="cap">系统 · 只有人的令牌能改 · 每次改动记入变更记录</div><h1 style="margin-top:8px">${title}</h1><div class="dek">${dek}</div></div></div>${BRUSH}
  <div class="sg" style="grid-template-columns:150px minmax(0,860px)"><div class="sn"><div class="cap" style="padding-top:0">个人</div>${nav.replace('<div class="cap">个人</div>', '')}</div><div>${body}</div></div>`);
}

/* 二 设置·模型与密钥 */
function setModels() {
  const prof = (n, ep, m, fam, tier, price, last) => `<tr><td><b style="font-weight:500">${n}</b></td><td class="m">${ep}</td><td class="m">${m}</td><td>${fam}</td><td><span class="tag">${tier}</span></td><td class="m r">${price}</td><td class="r"><span class="lnk" style="font-size:12px">${last}</span></td></tr>`;
  const route = (r, p, n) => `<tr><td>${r}</td><td><span class="row" style="gap:6px">${p}${ic('chevd', 's')}</span></td><td class="ink3" style="font-size:12px">${n}</td></tr>`;
  return setShell('models', '模型与密钥', '模型档案与路由写进设置存储；密钥只活在这次运行的内存里，重启后要重新输入。', `
  <div class="sh"><h2>模型档案</h2><span class="sp"></span><span class="btn sm">${ic('plus', 's')}新增档案</span></div>
  <table class="tbl"><tr><th>名称</th><th>端点</th><th>模型</th><th>家族</th><th>档位</th><th style="text-align:right">输入 / 输出 $/M</th><th></th></tr>
    ${prof('强 · A', 'api.anthropic.com', 'claude-opus-5-5', 'A', '强', '4.00 / 20.00', '编辑')}
    ${prof('中 · A', 'api.anthropic.com', 'claude-sonnet-5-5', 'A', '中', '2.00 / 10.00', '编辑')}
    ${prof('轻 · A', 'api.anthropic.com', 'claude-haiku-5-5', 'A', '轻', '0.10 / 0.50', '编辑')}
    ${prof('异家族 · D', 'api.deepseek.com/anthropic', 'deepseek-chat', 'D', '中', '0.27 / 1.10', '编辑')}</table>
  <div class="note">价目取自价目表 anthropic@2026-11-03+deepseek@2026-11；任务只能从这里登记过的档案里选，不能在任务里填端点。</div>
  <div class="sh sec"><h2>角色路由</h2><span class="sp"></span><span class="ink3" style="font-size:12px">新会话起生效 · 会话中途不换模型</span></div>
  <table class="tbl">${route('起草（一句话开题）', '轻 · A', '只做指认，不做推理')}${route('Bootstrap · Reason', '强 · A', '')}${route('Explore', '中 · A', '')}${route('Verify', '异家族 · D', '异家族复核（M1）')}</table>
  <div class="sh sec"><h2>密钥</h2><span class="sp"></span><span class="btn sm bare">全部锁定</span></div>
  <div class="row" style="gap:8px;margin:10px 0 2px;font-size:12.5px"><span class="mk wei">时</span><b style="font-weight:600">密钥重启后失效，可用环境变量持久注入</b><span class="ink3 mono" style="font-size:11.5px">anthropic → ANTHROPIC_API_KEY · deepseek → DEEPSEEK_API_KEY</span></div>
  <table class="tbl"><tr><th>槽</th><th>端点</th><th>状态</th><th></th></tr>
    <tr><td><b style="font-weight:500">anthropic</b></td><td class="m">api.anthropic.com</td><td><span class="row" style="gap:8px"><span class="mk jie">设</span><span class="mono" style="font-size:12px">指纹 3f9a…c1d2 · 08:12 设</span></span></td><td class="r"><span class="btn sm">清除</span></td></tr>
    <tr><td><b style="font-weight:500">deepseek</b></td><td class="m">api.deepseek.com</td><td><span class="keybox">••••••••••••••••</span></td><td class="r"><span class="btn sm ink">设置</span></td></tr></table>
  <div class="warn"><b style="font-weight:600">anthropic 槽的密钥来自配置文件</b>（backend.api_key）。请在这里重新输入，并把它从配置文件删掉；下一版起，配置文件里写密钥将拒绝启动。</div>
  <div class="note">密钥不进配置文件、不进日志与事件、不进备份与任何导出物，也不进模型容器；页面上看不到、也读不回来，只显示指纹。服务重启后需要重新输入，或由环境变量注入。</div>`);
}

/* 三 设置·预算与硬顶（含风险表、信封、先验摘要） */
function setBudget() {
  const capBar = (left, w, h, lbl, val, sub, cls = '') => `<div class="bar ${cls}" style="left:${left}%;width:${w}%;height:${h}px"></div><div class="lbl" style="left:${left + w + 1}%;bottom:${h - 30}px"><b>${lbl}</b><span class="mono">${val}</span> <span class="ink3">${sub}</span></div>`;
  const risk = (res, mode, r, src) => `<tr><td class="m">${res}</td><td>${mode}</td><td><span class="pill ${r}">${r}</span></td><td class="ink3" style="font-size:12px">${src}</td></tr>`;
  return setShell('budget', '预算与硬顶', '三道顶从小到大：练习上限 ≤ 单题硬顶 ≤ 全局硬顶。保存时校验这个次序；下调立即生效，上调只对新开的任务。', `
  <div class="sh"><h2>三道硬顶</h2><span class="sp"></span><span class="ink3" style="font-size:12px">金额 · 墙钟</span></div>
  <div class="capr"><span><b>练习上限</b></span><div class="trk"><i style="width:9%"></i></div><span class="mono">$0.50 · 30 分钟</span><span class="ink3">练习道信封与此同数 · 图服务校验</span></div>
  <div class="capr"><span><b>单题硬顶</b></span><div class="trk"><i style="width:46%"></i></div><span class="mono">$20.00 · 2 小时</span><span class="ink3">所有开题，向导也受限 · 图服务校验</span></div>
  <div class="capr"><span><b>全局硬顶</b></span><div class="trk"><i style="width:100%"></i><u style="width:8%"></u></div><span class="mono">$500.00</span><span class="ink3">已花 $41.20 · 端点代理执行</span></div>
  <div class="note">长度按对数画，已花按全局硬顶的比例画；三道顶必须从上到下递增，保存时校验。</div>
  <div class="row" style="gap:28px;margin-top:10px;font-size:12.5px"><span>开题起草累计 <b class="mono">$0.36</b></span><span class="ink3">记在“开题”账户下，受全局硬顶约束</span></div>
  <div class="sh sec"><h2>风险表</h2><span class="sp"></span><span class="ink3" style="font-size:12px">查不到的一律按 r2</span></div>
  <table class="tbl"><tr><th>资源 · 模式</th><th>动作</th><th>风险</th><th>说明</th></tr>
    ${risk('net · 127.0.0.1:*', '读', 'r0', '本机练习环境')}${risk('net · q*:*', '读', 'r0', '题目网络')}${risk('workspace · /work/**', '读写', 'r1', '只在执行容器里')}${risk('其它', '任意', 'r2', '缺省')}</table>
  <div class="sh sec"><h2>预算先验</h2><span class="sp"></span><span class="zhupi" style="font-size:16px">占位表 · 数字没有读数依据</span></div>
  <table class="tbl"><tr><th>档位</th><th style="text-align:right">金额</th><th style="text-align:right">墙钟</th><th>用于</th></tr>
    <tr><td>easy</td><td class="m r">$0.50</td><td class="m r">10 分钟</td><td class="ink3" style="font-size:12px">练习道只用这一档</td></tr>
    <tr><td>medium</td><td class="m r">$2.00</td><td class="m r">30 分钟</td><td class="ink3" style="font-size:12px">确认道的默认</td></tr>
    <tr><td>hard</td><td class="m r">$6.00</td><td class="m r">60 分钟</td><td class="ink3" style="font-size:12px">确认道的默认</td></tr></table>
  <div class="note">来源 placeholder · 版本 placeholder-0。表由外部注入（部署时放置文件并重启起草服务），本页只读；系统不读取任何本机题库或校准目录。</div>`);
}

/* 四 确认道：自由任务（B2）的一步确认卡。版式以一句话开题 kt-confirm 为准，这里画本图补的“验收清单”与“模型”两块 */
function lcConfirm() {
  const span = (n) => `<span class="pill src">摘 ¶${n}</span>`;
  const acc = (id, t, src, need) => `<div class="acc" style="grid-template-columns:30px minmax(0,1fr) auto auto"><span class="id">${id}</span><div>${t}</div>${src}<span class="ink3" style="font-size:11.5px">${need}</span></div>`;
  const sc = (r, res, act, risk, src) => `<tr><td class="m">${r}</td><td class="m">${res}</td><td>${act}</td><td><span class="row" style="gap:4px"><span class="pill ${risk}">${risk}</span>${ic('chevd', 's')}</span></td><td>${src}</td></tr>`;
  return LCSS + shell(hdr('<span>任务</span><span>/</span><b>新建</b><span>/</span><span>确认</span>', `<span class="ink3" style="font-size:12px">确认道 · 校验通过 · 未开题</span>`), `
  <div style="max-width:980px">
  <div class="row" style="align-items:flex-end;gap:20px"><div style="flex:1"><div class="cap">一步确认 · 开题后判据与验收清单不可改</div><h1 class="serif" style="font-size:28px;margin:8px 0 0">整理三季度采购单并给出差异说明</h1></div><span class="stamp" style="position:static;transform:rotate(-3deg)">终态最多：人工验收</span></div>
  <div style="margin:14px 0 12px">${strip(4, 4, { 4: '确认 · 等你' })}</div>
  <div class="cblk"><div class="h">01 目标<small>原文 ¶1</small></div><div>把 /work/q3 下的三份采购单合并成一张表，按供应商汇总，并写出与二季度的差异说明。</div></div>
  <div class="cblk"><div class="h">02 验收清单<small>没有判官 · 由你逐条验收</small></div><div>
    ${acc('a1', '合并表包含三份采购单的全部行，不重不漏', span(2), '附交付物')}
    ${acc('a2', '按供应商汇总的金额与原单合计一致', span(2), '附交付物')}
    ${acc('a3', '差异说明列出金额变化超过 10% 的供应商及原因', span(3), '附说明')}
    ${acc('a4', '不改动 /work/q3 下的原始文件', '<span class="pill src">人</span>', '附说明')}
    <div class="row" style="gap:10px;margin-top:10px;font-size:12px"><span class="lnk">+ 加一条</span><span class="ink3">只能写原文里有的，或你自己写；模型不起草验收条目。结构检查：a1、a2 的交付物存在且为 CSV（只给读数）。</span></div></div></div>
  <div class="cblk"><div class="h">03 授权<small>默认拒绝 · 风险查风险表</small></div><div>
    <table class="tbl">${sc('1', 'workspace · /work/q3/**', '读', 'r0', span(1))}${sc('2', 'workspace · /work/out/**', '写', 'r1', span(4))}</table>
    <div class="note">已删去：<span class="mono">net · erp.internal:443</span>（原文里没有这个入口）</div></div></div>
  <div class="cblk"><div class="h">04 预算<small>先验 medium 档 · 占位表</small></div><div class="row" style="gap:28px;align-items:center">
    <span><span class="cap">金额</span><br><b class="mono" style="font-size:18px">$2.00</b></span><span><span class="cap">墙钟</span><br><b class="mono" style="font-size:18px">30 分钟</b></span>
    <span class="ink3" style="font-size:12px">单题硬顶 $20.00 · 全局余额 $458.80<br>预算默认值来自占位表</span></div></div>
  <div class="cblk"><div class="h">05 模型<small>只能选已登记的档案</small></div><div class="row" style="gap:12px"><span class="uline" style="width:260px;display:flex;justify-content:space-between"><span>跟随全局路由</span>${ic('chevd', 's')}</span><span class="ink3" style="font-size:12px">Reason 强 · A，Explore 中 · A，Verify 异家族 · D</span></div></div>
  </div>
  <div class="wfoot"><span class="btn bare">改原文</span><span style="flex:1"></span><span class="btn">编辑草案（高级）</span><span class="btn ink">开始 <kbd>↵</kbd></span></div>`);
}

/* 五 工作区：站位条 + 扩权差异卡 */
function wsStations() {
  const center = `<div style="padding:16px 22px">${strip(6, 8, { 8: '人介入 · 1' })}
    <div class="ink3" style="font-size:12px;margin-top:8px">站位条只读服务端已有的字段（终态、在途会话、待人处理数），不推断进度。</div></div>
    <div style="position:absolute;left:22px;right:22px;top:120px;bottom:20px;border:1px dashed var(--rule-2);display:grid;place-items:center;color:var(--ink-3);font-size:12.5px">前沿 · 图（第三期已实现，略）</div>`;
  const panel = `<div class="appr"><div class="row"><span class="mk dai">待</span><b style="font-weight:600">扩权申请 · i_12</b><span style="flex:1"></span><span class="mono ink3" style="font-size:11px">seq 58</span></div>
      <div style="font-size:12.5px;margin-top:6px">Explore 想读取导出目录，以便核对汇总数。智能体只能申请；放行由闸门在你批准后执行。</div>
      <div class="dcols"><div><div class="cap">开题时的授权</div><div class="r">1 /work/q3/** 读 r0<br>2 /work/out/** 写 r1</div></div><div><div class="cap">申请之后</div><div class="r">1 /work/q3/** 读 r0<br>2 /work/out/** 写 r1<br><span class="add">3 /work/export/** 读 r1 ＋</span></div></div></div>
      <div class="row" style="gap:8px;margin-top:12px"><span class="btn sm zhu">批准这一条</span><span class="btn sm">拒绝并写理由</span><span style="flex:1"></span><span class="ink3 mono" style="font-size:11px">card 9e01…</span></div></div>
    <div><div class="sh"><h2>此题的点位</h2></div>
      <div class="lead"><span class="k">开题确认</span><span class="dots"></span><span class="v">已确认 · 08:31</span></div>
      <div class="lead"><span class="k">扩权</span><span class="dots"></span><span class="v" style="color:var(--zhu)">1 项等你</span></div>
      <div class="lead"><span class="k">续期门</span><span class="dots"></span><span class="v">未到 80%</span></div>
      <div class="lead"><span class="k">验收</span><span class="dots"></span><span class="v">关题时 · 4 条</span></div></div>`;
  const tabs = ['详情', '日志', '花费', '记忆'].map((t, i) => `<span class="${i === 0 ? 'on' : ''}">${t}</span>`).join('');
  return LCSS + shell('', `
  <div class="wbar"><div class="grow" style="flex:1"><div class="cap">任务 T-0163 · 人工验收 · 确认道</div><h1>整理三季度采购单并给出差异说明</h1></div>
    <span class="row" style="font-size:12.5px"><span class="pulse"></span>运行中</span>
    <div style="width:210px;margin-left:12px"><div class="row num" style="justify-content:space-between;font-size:11.5px"><span class="ink3">花费</span><span class="mono">$0.74<span class="ink3"> / $2.00</span></span></div><div class="rule-meter" style="margin-top:3px"><b style="width:37%"></b><s style="left:50%"></s><s style="left:80%"></s></div></div>
    <span class="btn ink" style="margin-left:10px">${ic('msg', 's')}给出指导 <kbd>H</kbd></span></div>
  <div class="wgrid">
    <div class="rail"><div><div class="sh"><h2>待你</h2><span class="sp"></span><span class="ink3" style="font-size:12px">1</span></div><div class="ss"><div class="row"><span class="mk dai">待</span><b style="font-weight:500;margin-left:6px">扩权 · i_12</b></div><div class="ink3" style="font-size:11.5px;margin-top:6px">多一条 r1 读</div></div></div>
      <div><div class="sh"><h2>会话</h2><span class="sp"></span><span class="ink3" style="font-size:12px">2 个在途</span></div>
        <div class="ss"><div class="row"><span class="pulse"></span><b style="font-weight:500">探索 #2</b><span style="flex:1"></span><span class="mono ink3">中 · A</span></div><div class="row ink3" style="font-size:11.5px;justify-content:space-between;margin-top:6px"><span>i_9</span><span class="mono">$0.21</span></div></div>
        <div class="ss"><div class="row"><span class="pulse" style="background:var(--ink-3);box-shadow:none"></span><b style="font-weight:500">探索 #3</b><span style="flex:1"></span><span class="mono ink3">中 · A</span></div><div class="row ink3" style="font-size:11.5px;justify-content:space-between;margin-top:6px"><span>i_12 · 等扩权</span><span class="mono">$0.00</span></div></div></div></div>
    <div class="cv">${center}</div>
    <div class="pr"><div class="ptabs">${tabs}</div><div class="pb">${panel}</div></div>
  </div>`, { narrow: true });
}

/* 六 验收：按开题时登记的清单逐条验收（B2） */
function lcAccept() {
  const row = (id, t, yn, ev) => `<div class="acc"><span class="id">${id}</span><div><div>${t}</div><div class="evd">${ev}</div></div><span class="yn"><span class="${yn === 1 ? 'y' : ''}">通过</span><span class="${yn === 0 ? 'n' : ''}">不通过</span></span></div>`;
  return LCSS + shell(hdr('<span>任务</span><span>/</span><span>T-0163</span><span>/</span><b>验收</b>'), `
  <div style="max-width:1020px">
  <div class="row" style="align-items:flex-end;gap:20px"><div style="flex:1"><div class="cap">关题 · 人工验收 · 清单开题时登记，不可改</div><h1 class="serif" style="font-size:28px;margin:8px 0 0">整理三季度采购单并给出差异说明</h1></div><span class="row" style="gap:6px;font-size:12.5px"><span class="mk wei">止</span>执行已停 · 花费 $1.62 / $2.00</span></div>
  <div style="margin:14px 0 4px">${strip(10, 10, { 10: '验收 · 等你' })}</div>
  <div class="steps3"><div class="ok"><b>四顾 ✓</b>影响面 2 项已确认</div><div class="on"><b>满志</b>逐条验收，定终态</div><div><b>藏刀</b>销毁容器 · 作废令牌 · 封存判例</div></div>
  <div style="display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:36px;margin-top:18px">
    <div><div class="sh"><h2>验收清单</h2><span class="sp"></span><span class="ink3" style="font-size:12px">3 / 4 已判</span></div>
      ${row('a1', '合并表包含三份采购单的全部行，不重不漏', 1, '依据 · exec · out/merged.csv · sha256 4be2…71d0 · 本机校验 ✓')}
      ${row('a2', '按供应商汇总的金额与原单合计一致', 1, '依据 · exec · out/by_vendor.csv · sha256 09af…c3e2 · 结构检查 ✓')}
      ${row('a3', '差异说明列出金额变化超过 10% 的供应商及原因', 1, '依据 · 说明：“五家，原因见 out/diff.md 第 2 节”')}
      ${row('a4', '不改动 /work/q3 下的原始文件', -1, '<span style="color:var(--zhu)">待判 · 需要附说明</span> · 四顾显示该目录无写入记录')}
    </div>
    <div><div class="sheetcard" style="position:relative"><div class="cap">终态预览</div>
      <div class="lead"><span class="k">终态</span><span class="dots"></span><span class="v">人工验收（accepted）</span></div>
      <div class="lead"><span class="k">根结论等级上限</span><span class="dots"></span><span class="v mono">E0</span></div>
      <div class="lead"><span class="k">报告首行</span><span class="dots"></span><span class="v">不写“已证明”</span></div>
      <div class="note">全部通过才能验收；任何一条不通过，只能退回（写指导继续）或以未解出关闭。</div>
      <div class="row" style="gap:8px;margin-top:14px"><span class="btn ink" style="opacity:.4">验收</span><span class="btn">退回</span><span class="btn bare">以未解出关闭</span></div>
      <div class="ink3" style="font-size:11.5px;margin-top:8px">验收不可用：a4 未判</div></div></div>
  </div></div>`);
}

Object.assign(RT, { map: lcMap, 'set-models': setModels, 'set-budget': setBudget, confirm: lcConfirm, 'ws-stations': wsStations, accept: lcAccept });
document.getElementById('root').innerHTML = (RT[S] || dashboard)();
