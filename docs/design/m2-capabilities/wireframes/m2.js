/* M2 三项能力的线框：延续 v4（纸、墨、朱印、界栏、编号）。只用 kit.css / screens.css 的既有类，新增样式写在 M2CSS。 */
const M2CSS = `<style>
.mrow{display:grid;grid-template-columns:22px 18px minmax(0,1fr) auto auto;gap:10px;align-items:center;padding:10px 0;border-bottom:1px solid var(--rule);font-size:13px}
.mrow .src{font:11px var(--mono);color:var(--ink-3)}
.mrow.off{opacity:.45}
.cbx{width:14px;height:14px;border:1.25px solid var(--ink-2);display:inline-grid;place-items:center;font-size:10px}
.cbx.on{background:var(--ink);border-color:var(--ink);color:var(--paper)}
.st{font:500 11px var(--mono);padding:0 6px;border:1px solid currentColor;line-height:17px;border-radius:2px;white-space:nowrap}
.st.act{color:var(--qing)} .st.dor{color:var(--ink-3);border-style:dashed} .st.sta{color:var(--zhe)} .st.ret{color:var(--ink-4);text-decoration:line-through}
.chain{display:flex;flex-direction:column;gap:0;border-left:1px solid var(--rule-3);margin-left:6px}
.chain>div{position:relative;padding:6px 0 6px 16px;font-size:12.5px}
.chain>div::before{content:"";position:absolute;left:-4px;top:12px;width:7px;height:7px;background:var(--paper);border:1.25px solid var(--ink-2);border-radius:50%}
.chain>div.ok::before{background:var(--qing);border-color:var(--qing)}
.chain>div.bad::before{background:var(--zhe);border-color:var(--zhe)}
.lanes{position:absolute;inset:44px 24px 24px 24px}
.lane{display:grid;grid-template-columns:150px 1fr;align-items:center;height:46px;border-bottom:1px solid var(--rule)}
.lane .nm{font-size:12.5px} .lane .nm small{display:block;font:11px var(--mono);color:var(--ink-3)}
.lane .tr{position:relative;height:100%}
.seg{position:absolute;top:11px;height:24px;border:1px solid var(--ink);background:var(--sheet);font-size:11.5px;padding:0 8px;line-height:22px;white-space:nowrap;overflow:hidden}
.seg.cut{background:var(--ink);color:var(--paper)}
.seg.brk span{background:var(--paper);padding:0 3px} .seg.brk{background:repeating-linear-gradient(45deg,var(--ink-3) 0 1px,transparent 1px 5px);border-color:var(--ink-3);color:var(--ink-2)}
.seg.wait{border-style:dashed;border-color:var(--ink-3);color:var(--ink-3);background:transparent}
.seg.res{top:15px;height:16px;line-height:14px;font:10.5px var(--mono);border-color:var(--zhu-line);background:var(--zhu-soft);color:var(--zhu-ink)}
.vline2{position:absolute;top:-8px;bottom:-8px;width:0;border-left:1.5px solid var(--zhu)}
.axis{position:absolute;left:150px;right:0;bottom:-22px;font:10.5px var(--mono);color:var(--ink-3)}
.modeb{display:inline-flex;gap:8px;align-items:center;border:1px solid var(--ink);padding:3px 10px;font-size:12px;background:var(--sheet)}
.tl{display:grid;grid-template-columns:52px 1fr auto;gap:8px;padding:7px 0;border-bottom:1px solid var(--rule);font-size:12.5px;align-items:baseline}
.cmd{font:11.5px var(--mono);color:var(--ink-2)}
.armt{width:100%;border-collapse:collapse;font-size:12.5px}
.armt td,.armt th{padding:7px 8px;border-bottom:1px solid var(--rule);text-align:right}
.armt th{font-weight:500;color:var(--ink-3);font-size:11px;letter-spacing:.1em;border-bottom:1px solid var(--ink)}
.armt td:first-child,.armt th:first-child{text-align:left}
.ttabs2{display:flex;gap:22px;border-bottom:1px solid var(--rule);margin:6px 0 4px}
.ttabs2 span{padding:8px 0;color:var(--ink-3);border-bottom:1.5px solid transparent;margin-bottom:-1px;font-size:13px}
.ttabs2 span.on{color:var(--ink);border-color:var(--ink);font-weight:500}
.ttabs2 em{font:normal 11px var(--mono);color:var(--ink-4);margin-left:5px}
</style>`;

const cb = (on) => `<span class="cbx ${on ? 'on' : ''}">${on ? '✓' : ''}</span>`;
const ST = { act: '活跃', dor: '休眠', sta: '过期', ret: '退役' };
const st = (k) => `<span class="st ${k}">${ST[k]}</span>`;

/* 一、开题向导第四步：带入的记忆 */
function wizRecall() {
  const stp = (n, t, d, c) => `<div class="stp ${c}"><span class="n">${n}</span><div><div class="tt">${t}</div><div class="ds">${d}</div></div></div>`;
  const row = (on, mk, t, src, s, extra = '') => `<div class="mrow ${on ? '' : 'off'}">${cb(on)}${mk}<div><div class="ell">${t}</div><div class="src">${src}</div></div>${extra}${s}</div>`;
  const ld = (k, v, c = '') => `<div class="lead"><span class="k">${k}</span><span class="dots"></span><span class="v" style="${c}">${v}</span></div>`;
  return M2CSS + shell(hdr('<b>任务</b><span>/</span><span>新建</span>'), `
  <div class="wz">
    <div>${stp('一', '从哪开始', '题面与材料', 'done')}${stp('二', '怎样算完成', '脚本重放 · window_assert@2', 'done')}${stp('三', '允许它做什么', '2 条授权 · 最高 r1', 'done')}${stp('四', '预算与记忆', '花费、用时、带入哪些记忆', 'on')}</div>
    <div style="max-width:720px"><div class="cap">第四步 · 共四步</div><div class="q1">这次带上哪些过去的经验？</div>
      <div class="ink2">下面是同一环境、同类任务留下的东西。带入的事实会在开工前由判定器在这次的环境里重跑一遍，跑通了才算数，跑不通的不会被当成事实。</div>
      <div class="sh" style="margin-top:22px"><h2>这台目标上的事实</h2><span class="ink3" style="font-size:12px">环境 login-lab · 上次 T-0142</span><span class="sp"></span><span class="cap">开工前复核</span></div>
      ${row(1, '<span class="mk jie">忆</span>', '8081 端口有可列目录的归档', 'f_52 · T-0142 · 判定通过（window_assert@2）', st('act'), '<span class="tag">在链 3 次</span>')}
      ${row(1, '<span class="mk jie">忆</span>', '登录表单提交到 /auth，字段 user 与 pass', 'f_18 · T-0142 · 判定通过（http_probe@1）', st('act'), '<span class="tag">在链 2 次</span>')}
      ${row(0, '<span class="mk jie">忆</span>', '默认账号 admin 可登录', 'f_21 · T-0131 · 上次复核未通过', st('sta'), '<span class="tag">你去掉了</span>')}
      <div class="sh" style="margin-top:22px"><h2>上次走不通的路</h2><span class="ink3" style="font-size:12px">只作提醒，不复核</span></div>
      ${row(1, '<span class="mk wei">排</span>', '爆破 /auth 会触发锁定', 'f_33 · T-0142 · 已证伪（http_probe@1）', '<span class="cap">叙述</span>')}
      <div class="sh" style="margin-top:22px"><h2>预算</h2><span class="ink3" style="font-size:12px">按同类 6 个任务的花费画像</span></div>
      <div class="row" style="gap:28px;margin-top:12px"><div><div class="cap">花费上限</div><div class="big" style="font-size:28px">$4.00<small>同类中位 $1.30 · P80 $2.90</small></div></div><div><div class="cap">先单会话试的份额</div><div class="big" style="font-size:28px">1/3<small>同类单会话解出 4/6</small></div></div></div>
    </div>
    <div class="sheetcard"><div class="cap">任务单 · 预览</div><h3>取得登录后显示的答案串</h3>
      ${ld('判定', 'window_assert@2')}${ld('授权', '2 条 · 最高 r1')}${ld('花费上限', '$4.00')}${ld('带入事实', '2 条 · 开工前复核')}${ld('提醒', '1 条走不通的路')}${ld('留出', '本题未被抽中', 'color:var(--ink-3)')}
      <div class="voice" style="margin-top:16px"><div class="who">复核会花</div><div class="tx" style="font-family:var(--sans);font-size:12.5px">约 20 秒判定器时间，不花模型 token。</div></div>
      <span class="zhupi" style="margin-top:14px;font-size:16px">旧事须重验 方可为据</span></div>
  </div>
  <div class="wfoot"><span class="btn bare">上一步</span><span style="flex:1"></span><span class="btn">存为草稿</span><span class="btn ink">开题 ${ic('arrowr', 's')}</span></div>`);
}

/* 工作区框架（取自 v4 workspace 的版式） */
function wsFrame(center, tabs, panel, rail) {
  const ticks = Array.from({ length: 68 }, (_, i) => `<span style="position:absolute;left:${(i / 67) * 100}%;bottom:16px;width:1px;height:${i % 10 === 0 ? 12 : 5}px;background:var(--rule-3)"></span>${i % 10 === 0 ? `<span style="position:absolute;left:${(i / 67) * 100}%;bottom:2px;transform:translateX(-50%);font:10px var(--mono);color:var(--ink-3)">${i}</span>` : ''}`).join('');
  return shell('', `
  <div class="wbar"><div class="grow"><div class="cap">任务 T-0157 · 脚本重放 · 环境 login-lab</div><h1>取得登录后显示的答案串（第二次）</h1></div>
    <span class="row" style="font-size:12.5px"><span class="pulse"></span>运行中</span>
    <div style="width:210px;margin-left:12px"><div class="row num" style="justify-content:space-between;font-size:11.5px"><span class="ink3">花费</span><span class="mono">$0.61<span class="ink3"> / $4.00</span></span></div><div class="rule-meter" style="margin-top:3px"><b style="width:15%"></b><s style="left:50%"></s><s style="left:100%"></s></div></div>
    <span class="btn ink" style="margin-left:10px">${ic('msg', 's')}给出指导 <kbd>H</kbd></span></div>
  <div class="wgrid">
    <div class="rail">${rail || `
      <div><div class="sh"><h2>会话</h2><span class="sp"></span><span class="ink3" style="font-size:12px">3 个在途</span></div>
        <div class="ss"><div class="row"><span class="pulse"></span><b style="font-weight:500">探索 #2</b><span style="flex:1"></span><span class="mono ink3">i_7</span></div><div class="row ink3" style="font-size:11.5px;justify-content:space-between;margin-top:6px"><span>占 规则 1 · 写</span><span class="mono">$0.18</span></div></div>
        <div class="ss"><div class="row"><span class="pulse"></span><b style="font-weight:500">探索 #3</b><span style="flex:1"></span><span class="mono ink3">i_8</span></div><div class="row ink3" style="font-size:11.5px;justify-content:space-between;margin-top:6px"><span>占 规则 0 · 读</span><span class="mono">$0.09</span></div></div>
        <div class="ss"><div class="row"><span class="pulse" style="background:var(--ink-3);box-shadow:none"></span><b style="font-weight:500">探索 #4</b><span style="flex:1"></span><span class="mono ink3">i_9</span></div><div class="row ink3" style="font-size:11.5px;justify-content:space-between;margin-top:6px"><span>等 规则 1 · 被 #2 占着</span><span class="mono">$0.00</span></div></div></div>`}
    </div>
    <div class="cv">${center}</div>
    <div class="pr"><div class="ptabs">${tabs}</div><div class="pb">${panel}</div></div>
  </div>
  <div class="ruler"><div class="lbl"><div class="row"><span class="pulse"></span><b style="font-weight:600">实时</b><span class="mono ink3">seq 41</span></div><div class="ink3" style="font-size:11.5px">拖动刻度回放到任意一刻</div></div><div class="scale" style="margin:0 28px 0 18px">${ticks}<span style="position:absolute;right:-1px;top:6px;bottom:14px;width:2px;background:var(--zhu)"></span></div></div>`, { narrow: true });
}
const tabsOf = (on) => [['detail', '详情'], ['log', '日志'], ['cost', '花费'], ['memory', '记忆'], ['tools', '工具']].map(([k, t]) => `<span class="${k === on ? 'on' : ''}">${t}</span>`).join('');

/* 二、工作区 · 记忆页签：召回与复核 */
function wsRecall() {
  const center = `<div class="cvtools"><div class="tx-tabs"><span>图</span><span class="on">列表</span><span>时间线</span><span>泳道</span></div></div>
    <div style="position:absolute;inset:52px 28px 20px 28px;overflow:hidden">
      <div class="sh"><h2>前沿</h2><span class="ink3" style="font-size:12px">按等级</span></div>
      <div class="li"><span class="ix">01</span><span class="lv e3"><i></i>E3</span><div class="grow"><div class="ell"><span class="ink3">[忆]</span> 8081 端口有可列目录的归档</div><div class="t2 ell">判定通过（window_assert@2）· seq 4 · 来自 T-0142</div></div></div>
      <div class="li"><span class="ix">02</span><span class="lv e3"><i></i>E3</span><div class="grow"><div class="ell"><span class="ink3">[忆]</span> 登录表单提交到 /auth，字段 user 与 pass</div><div class="t2 ell">判定通过（http_probe@1）· seq 5 · 来自 T-0142</div></div></div>
      <div class="li"><span class="ix">03</span><span class="lv e0"><i></i>E0</span><div class="grow"><div class="ell">归档里的 .bak 含配置备份</div><div class="t2 ell">猜想 · 探索 #2 · 引用 01</div></div></div>
    </div>`;
  const panel = `
    <div><div class="sh" style="border-bottom:0;padding-bottom:10px"><h2 style="font-size:13.5px">三层记忆</h2><span class="ink3" style="font-size:12px">由近及远</span></div>
      <div class="strata"><div class="stratum"><span class="tier">工作</span><div><div style="font-weight:500">本会话上下文</div><div class="ink3" style="font-size:12px">会话结束即丢弃</div></div><span class="mono">61k</span></div>
      <div class="stratum" style="background:var(--sheet)"><span class="tier">任务</span><div><div style="font-weight:500">任务图</div><div class="ink3" style="font-size:12px">新会话从这里接续</div></div><span class="mono">14 节点</span></div>
      <div class="stratum" style="background:var(--paper-2)"><span class="tier">跨任务</span><div><div style="font-weight:500">通鉴带入</div><div class="ink3" style="font-size:12px">开题时登记，之后不变</div></div><span class="mono">3 条</span></div></div></div>
    <div><div class="sh" style="border-bottom-color:var(--rule-2);padding-bottom:6px"><h2 style="font-size:13.5px">开工前复核</h2><span class="sp"></span><span class="mono ink3" style="font-size:11px">判定器 18 秒 · 0 token</span></div>
      <div class="tl"><span class="mono ink3">seq 4</span><span>8081 有可列目录的归档</span><span class="lv e3"><i></i>通过</span></div>
      <div class="tl"><span class="mono ink3">seq 5</span><span>/auth 的字段 user 与 pass</span><span class="lv e3"><i></i>通过</span></div>
      <div class="tl"><span class="mono ink3">seq 6</span><span>默认账号 admin 可登录</span><span class="st sta">未通过</span></div>
      <div class="ink3" style="font-size:12px;margin-top:8px">未通过的那条在本题里只是猜想，不会被当作前提。关题时会记一次过期。</div></div>
    <div><div class="sh" style="border-bottom-color:var(--rule-2);padding-bottom:6px"><h2 style="font-size:13.5px">只作提醒</h2></div>
      <div class="voice"><div class="who">上次走不通 · T-0142</div><div class="tx">爆破 /auth 会触发锁定。</div></div></div>
    <div class="row" style="gap:8px"><span class="btn sm">${ic('plus', 's')}给下一个会话留一句话</span><span class="btn sm bare">关题时把一条指导记下来</span></div>`;
  return M2CSS + wsFrame(center, tabsOf('memory'), panel);
}

/* 三、知识 · 通鉴：记忆台账与资产 */
function tongjian() {
  const ti = (t, c, on) => `<div class="ti ${on ? 'on' : ''}"><span class="cat">${t}</span><span class="c">${c}</span></div>`;
  const en = (t, k, s, used, hit, upd, on) => `<div class="entry ${on ? 'on' : ''}"><div class="et">${t}</div><div>${s}</div><div class="em">${k} · ${upd}</div><div class="st2 ink2" style="font-size:12px;text-align:right">召回 ${used} · 复核通过 ${hit}</div></div>`;
  return M2CSS + shell(hdr('<b>知识</b><span>/</span><span>通鉴</span>', `<span class="btn">待审经验 <span class="mk dai" style="width:16px;height:16px;font-size:10px">2</span></span><span class="btn">${ic('upload', 's')}导入标准案例</span><span class="btn ink">${ic('upload', 's')}上传参考材料</span>`), `
  <div class="kg" style="margin:-28px -40px 0;height:calc(100% + 28px)">
    <div class="tree"><div class="cap" style="margin-bottom:10px">通鉴</div>${ti('环境事实', 31, 1)}${ti('走不通的路', 12)}${ti('判例', 58)}${ti('判据模板', 9)}${ti('切口先验', 6)}${ti('花费画像', 6)}${ti('锦囊', 11)}${ti('练习题组', 2)}
      <div class="cap" style="margin:22px 0 8px">环境</div>${ti('login-lab', 14)}${ti('cfg-stage', 9)}${ti('ops-sim', 8)}
      <div class="cap" style="margin:22px 0 8px">状态</div><div class="row" style="gap:6px;flex-wrap:wrap">${st('act')}${st('dor')}${st('sta')}${st('ret')}</div></div>
    <div class="cat-list"><div class="mast" style="padding-bottom:14px"><div><div class="cap">通鉴 · 环境事实 · login-lab</div><h1 style="font-size:28px;margin-top:6px">十四条，十一条仍然成立</h1><div class="dek">每条都是某次任务里判定通过的观察。下次在这个环境开工前会先重跑一遍，跑通才算数。</div></div></div>
      ${en('8081 端口有可列目录的归档', '出自 T-0142', st('act'), 4, 4, '上次复核 T-0157', 1)}
      ${en('登录表单提交到 /auth，字段 user 与 pass', '出自 T-0142', st('act'), 4, 4, '上次复核 T-0157')}
      ${en('默认账号 admin 可登录', '出自 T-0131', st('sta'), 3, 2, '上次复核未通过')}
      ${en('/health 返回构建号', '出自 T-0120', st('dor'), 10, 10, '连续 10 次不在解题链上')}
      ${en('8080 上有调试接口', '出自 T-0098', st('ret'), 5, 3, '你在 11-12 遗忘')}
    </div>
    <div class="reader"><div class="row"><span class="cap">环境事实</span><span style="flex:1"></span>${st('act')}</div>
      <div><h2>8081 端口有可列目录的归档</h2><div class="ink3" style="font-size:12px">标题是当时会话写的，作叙述看；下面的判据才是它说了什么</div></div>
      <div class="code" style="font-size:12px;white-space:normal"><span class="k">judge</span> window_assert@2 · <span class="k">spec</span> 3f9c…a1 · <span class="k">对照</span> 不通过（8082）</div>
      <div><div class="sh" style="border-bottom-color:var(--rule-2);padding-bottom:6px"><h2 style="font-size:13.5px">出处</h2></div>
        <div class="chain"><div class="ok">T-0142 · seq 31 · 判定通过（window_assert@2，带对照）</div><div>T-0142 关题封存 · 链头 seq 88 · solved</div><div class="ok">T-0150 复核通过 · 在解题链上</div><div class="ok">T-0157 复核通过 · 在解题链上</div></div></div>
      <div class="row" style="gap:8px;margin-top:6px"><span class="btn sm">钉住</span><span class="btn sm">遗忘…</span><span class="ink3" style="font-size:11.5px;margin-left:auto">钉不住已过期的事实</span></div>
      <span class="zhupi" style="font-size:16px;margin-left:auto">四次带入 四次成立</span></div>
  </div><div class="proto-tag">线框 · 示例数据</div>`);
}

/* 四、分析 · 复做 */
function redo() {
  const rows = [['登录取答案串', 1.30, 0.71], ['配置格式升级', 2.10, 1.62], ['接口文档补例', 0.90, 0.85], ['依赖锁定修复', 3.20, 2.05], ['日志定位超时', 2.60, 2.90], ['归档目录检索', 1.10, 0.52]];
  const sx = (v) => 170 + v * 70;
  const dumb = rows.map(([t, a, b], i) => { const y = 30 + i * 32; return `<text x="0" y="${y + 4}" font-size="12" fill="var(--ink)">${t}</text><line x1="${sx(Math.min(a, b))}" x2="${sx(Math.max(a, b))}" y1="${y}" y2="${y}" stroke="${b < a ? 'var(--ink)' : 'var(--zhu)'}" stroke-width="1.5"/><circle cx="${sx(a)}" cy="${y}" r="4" fill="var(--paper)" stroke="var(--ink-2)" stroke-width="1.25"/><circle cx="${sx(b)}" cy="${y}" r="4" fill="${b < a ? 'var(--ink)' : 'var(--zhu)'}"/><text x="440" y="${y + 4}" text-anchor="end" font-size="11" font-family="IBM Plex Mono" fill="${b < a ? 'var(--qing)' : 'var(--zhu)'}">${b < a ? '−' : '+'}${Math.round(Math.abs(b - a) / a * 100)}%</text>`; }).join('');
  const axis = [0, 1, 2, 3].map((v) => `<line x1="${sx(v)}" x2="${sx(v)}" y1="12" y2="200" stroke="var(--rule)"/><text x="${sx(v)}" y="216" text-anchor="middle" font-size="10" font-family="IBM Plex Mono" fill="var(--ink-3)">${v ? v + '0万' : '0'}</text>`).join('');
  const arm = (n, s, t, w, p, b) => `<tr><td>${n}</td><td class="mono">${s}</td><td class="mono">${t}</td><td class="mono">${w}</td><td class="mono">${p}</td><td>${b}</td></tr>`;
  return M2CSS + shell(hdr('<b>分析</b><span>/</span><span>复做</span>', `<span class="row" style="gap:18px;font-size:12.5px;margin-right:10px"><span class="ink3">概览</span><span class="ink3">对比</span><span style="border-bottom:1.5px solid var(--ink)">复做</span><span class="ink3">并行</span><span class="ink3">花费</span></span><span class="btn">导出报告</span>`), `
  <div class="mast" style="position:relative;border-bottom:0"><div class="vlabel" style="position:absolute;left:-30px;top:4px"><b>卷五</b><span>分析</span></div><div><div class="cap">复做题组 R-12 · 预登记 9e1c… · 每格 3 次 · 第二个实例换了答案</div><h1 style="margin-top:8px">带上记忆，第二次省了 <span class="zhuo">三成二</span> 的 token</h1><div class="dek">对比的是同一个第二实例在记忆关闭时的花费，不是第一次。墙钟省了一成八，解题率持平。</div></div><span class="sp"></span><span class="zhupi" style="margin-bottom:6px">方向性 · 十二对</span></div>${BRUSH}
  <div class="pair"><div><span class="lt">甲</span><span class="ink3">对照</span><span style="font-weight:500">冷 · 全栈（记忆关）</span></div><div><span class="lt">乙</span><span class="ink3">实验</span><span style="font-weight:500">记忆 · 全栈（召回并复核）</span></div></div>
  <div class="dl"><div><div class="cap">token 节省率</div><div class="big" style="font-size:32px">32%<small>90% 区间 18–44</small></div><div class="ink3" style="font-size:12px;margin-top:6px">阈值 ≥ 25% · 过</div></div><div><div class="cap">墙钟节省率</div><div class="big" style="font-size:32px">18%<small>区间 6–29</small></div><div class="ink3" style="font-size:12px;margin-top:6px">阈值 ≥ 15% · 过</div></div><div><div class="cap">解题率</div><div class="big" style="font-size:32px">10/12<small>甲 10/12</small></div><div class="ink3" style="font-size:12px;margin-top:6px">不降 · 过</div></div><div><div class="cap">污染率（漂移变体）</div><div class="big" style="font-size:32px">0/12<small>不复核 4/12</small></div><div class="ink3" style="font-size:12px;margin-top:6px">复核挡下了 4 次</div></div></div>
  <div style="display:grid;grid-template-columns:minmax(0,1fr) 520px;gap:48px;margin-top:24px">
    <div><div class="sh"><h2>逐模板 · 第二实例的 token</h2><span class="sp"></span><span class="cap">○ 甲 · ● 乙</span></div><svg viewBox="0 0 450 224" style="width:100%;margin-top:10px">${axis}${dumb}</svg>
      <div class="ink3" style="font-size:12px">"日志定位超时"变贵了：召回的两条事实复核都没通过，白花了判定器时间。</div></div>
    <div><div class="sh"><h2>各臂</h2><span class="sp"></span><span class="cap">相对冷 · 全栈</span></div>
      <table class="armt" style="margin-top:8px"><thead><tr><th>臂</th><th>节省 token</th><th>节省墙钟</th><th>解题</th><th>污染</th><th>结论</th></tr></thead><tbody>
      ${arm('冷 · 薄（单会话）', '41%', '35%', '9/12', '—', '<span class="ink3">参照</span>')}
      ${arm('笔记 · 薄', '44%', '37%', '8/12', '3/12', '<span class="ink3">诚实基线</span>')}
      ${arm('记忆 · 薄', '55%', '46%', '10/12', '0/12', '<span style="color:var(--qing)">过 P2</span>')}
      ${arm('记忆 · 全', '32%', '18%', '10/12', '0/12', '<span style="color:var(--qing)">过 P1</span>')}
      ${arm('资产 · 全（换环境）', '17%', '11%', '10/12', '—', '<span style="color:var(--qing)">过 P5</span>')}
      ${arm('召回不复核', '35%', '20%', '8/12', '4/12', '<span style="color:var(--zhu)">污染</span>')}
      </tbody></table>
      <div class="ink3" style="font-size:12px;margin-top:10px">读数只显示，不改任何默认值。结论按预登记的 P1–P8 判，改阈值要开新题组。</div></div>
  </div><div class="proto-tag">线框 · 示例数据</div>`);
}

/* 五、工作区 · 泳道：多会话并行与工具台账 */
function wsLanes() {
  const x = (s) => `${(s / 41) * 100}%`;
  const seg = (a, b, cls, t) => `<span class="seg ${cls}" style="left:${x(a)};width:calc(${x(b - a)} - 2px)">${t}</span>`;
  const lane = (nm, sub, segs) => `<div class="lane"><div class="nm">${nm}<small>${sub}</small></div><div class="tr">${segs}</div></div>`;
  const center = `<div class="cvtools"><div class="tx-tabs"><span>图</span><span>列表</span><span>时间线</span><span class="on">泳道</span></div><span class="ink4" style="color:var(--rule-3)">|</span><span class="modeb"><b>串行</b><span class="ink3">seq 33 起 · 同伴冲突 2 次</span></span></div>
    <div class="lanes">
      ${lane('推理', 'reason · 唯一', seg(0, 6, 'cut', '#1 切出 3 个尝试') + seg(18, 22, 'cut', '#2 换缝') + seg(30, 33, 'cut', '#3'))}
      ${lane('探索 #1', 'i_4 · 规则 0 读', seg(7, 16, 'cut', 'i_4 达成'))}
      ${lane('探索 #2', 'i_5 · 规则 1 写', seg(7, 20, 'brk', '<span>i_5 前提被 #3 证伪 · 放弃</span>'))}
      ${lane('探索 #3', 'i_6 · 规则 0 读', seg(7, 12, 'cut', 'i_6 反证 f_9') + seg(22, 29, 'brk', '<span>i_8 重复命令</span>'))}
      ${lane('探索 #4', 'i_7 · 规则 1 写', seg(7, 20, 'wait', '等规则 1') + seg(34, 41, 'cut', 'i_7 进行中'))}
      ${lane('规则 1（写）', '/srv/app/config', seg(7, 20, 'res', '#2 占') + seg(34, 41, 'res', '#4 占'))}
      <span class="vline2" style="left:calc(150px + (100% - 150px) * ${33 / 41})"></span>
      <div class="axis"><span style="position:absolute;left:0">seq 0</span><span style="position:absolute;left:${x(20)}">20</span><span style="position:absolute;right:0">41</span></div>
    </div>`;
  const panel = `
    <div><div class="sh" style="border-bottom:0;padding-bottom:8px"><h2 style="font-size:13.5px">并行度</h2><span class="sp"></span><span class="mono">1 / 3</span></div>
      <div class="ink2" style="font-size:12.5px;line-height:1.7">seq 33 起退回串行：最近 6 个并行会话里，同伴冲突 2 次（达到阈值 2），并行折损率 38%（阈值 35%）。再完成 3 个无争议的串行会话后恢复。</div></div>
    <div><div class="sh" style="border-bottom-color:var(--rule-2);padding-bottom:6px"><h2 style="font-size:13.5px">并行折损</h2><span class="sp"></span><span class="mono ink3" style="font-size:11px">$0.23 / $0.61</span></div>
      <div class="tl"><span class="mono ink3">$0.14</span><span>前提被同伴证伪而放弃</span><span class="ink3">1 次</span></div>
      <div class="tl"><span class="mono ink3">$0.06</span><span>两会话跑了同一条命令</span><span class="ink3">2 次</span></div>
      <div class="tl"><span class="mono ink3">$0.03</span><span>竞速落败</span><span class="ink3">1 次</span></div>
      <div class="tl"><span class="mono ink3">—</span><span>等资源（只计次数）</span><span class="ink3">13 次</span></div></div>
    <div><div class="sh" style="border-bottom-color:var(--rule-2);padding-bottom:6px"><h2 style="font-size:13.5px">工具台账 · 探索 #3</h2></div>
      <div class="tl"><span class="mono ink3">seq 9</span><span class="cmd ell">curl -s target:8081/archive/</span><span class="ink3">规则 0</span></div>
      <div class="tl"><span class="mono ink3">seq 11</span><span class="cmd ell">grep -l pass *.bak</span><span class="ink3">→ f_9</span></div>
      <div class="tl"><span class="mono ink3">seq 24</span><span class="cmd ell">curl -s target:8081/archive/</span><span style="color:var(--zhu)">与 #2 重复</span></div></div>`;
  const rail = `<div><div class="sh"><h2>会话</h2><span class="sp"></span><span class="ink3" style="font-size:12px">串行 · 1 个在途</span></div>
        <div class="ss"><div class="row"><span class="pulse"></span><b style="font-weight:500">探索 #4</b><span style="flex:1"></span><span class="mono ink3">i_7</span></div><div class="row ink3" style="font-size:11.5px;justify-content:space-between;margin-top:6px"><span>占 规则 1 · 写</span><span class="mono">$0.07</span></div></div>
        <div class="ss"><div class="row"><span class="pulse" style="background:var(--ink-3);box-shadow:none"></span><b style="font-weight:500">i_9</b><span style="flex:1"></span><span class="mono ink3">可开</span></div><div class="row ink3" style="font-size:11.5px;margin-top:6px"><span>串行中，等 #4 结束</span></div></div></div>
      <div><div class="sh"><h2>分账</h2><span class="sp"></span><span class="ink3" style="font-size:12px">按会话</span></div>
        <div class="tl"><span class="mono ink3">推理</span><span>3 轮</span><span class="mono">$0.12</span></div><div class="tl"><span class="mono ink3">#1</span><span>割</span><span class="mono">$0.09</span></div><div class="tl"><span class="mono ink3">#2</span><span>折</span><span class="mono">$0.14</span></div><div class="tl"><span class="mono ink3">#3</span><span>割 · 折</span><span class="mono">$0.19</span></div><div class="tl"><span class="mono ink3">#4</span><span>在途</span><span class="mono">$0.07</span></div></div>`;
  return M2CSS + wsFrame(center, tabsOf('tools'), panel, rail);
}

Object.assign(RT, { 'wiz-recall': wizRecall, 'ws-recall': wsRecall, tongjian, redo, 'ws-lanes': wsLanes });
document.getElementById('root').innerHTML = (RT[S] || dashboard)();
