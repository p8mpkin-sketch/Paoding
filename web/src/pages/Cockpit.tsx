// 任务页（v5 第三期；HMI 设计 §4、§10.2）。上面是状态、标题、执行流程条与原话；中间四栏：结果、过程、结构（前沿与图、检视）、文件；
// 右栏是花费、用时、钱花在哪、模型、可以访问、会话与指导；开放道底部是“补充一句 / 接着问”。
// 每个面板都是 view(as_of) 的排版；写操作只在链头且实时的时候可用。
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { GRAPH_MIN_NODES, prefs } from "../app/config";
import { useServices } from "../app/context";
import { hrefOf, navigate } from "../app/router";
import { canWrite, ProblemSession } from "../app/session";
import { countUsage } from "../app/usage";
import { shortHash } from "../model/text";
import { AcceptanceCard } from "../ui/AcceptanceCard";
import { ApprovalCard } from "../ui/ApprovalCard";
import { ScopeCard } from "../ui/ScopeCard";
import { TerminalBadge } from "../ui/criterion";
import { ExtensionDialog } from "../ui/ExtensionDialog";
import { Frontier } from "../ui/Frontier";
import { GraphView } from "../ui/GraphView";
import { HintInject, HintTraceCard } from "../ui/Hints";
import { Inspector } from "../ui/Inspector";
import { Plain, Text } from "../ui/registers";
import { Timeline } from "../ui/Timeline";
import { Kbd, btnClass } from "../kit";
import { MessageSquare } from "lucide-react";
import { IN_RESULT, Todo, todoKey } from "../ui/Todo";
import { flowLive, flowOf, type FlowStep } from "../model/flow";
import { terminalWord } from "../model/levels";
import type { ViewModel } from "../model/viewmodel";
import { FeedbackButtons, HaltButton, TaskDock } from "../ui/TaskActions";
import { TaskFiles } from "../ui/TaskLog";
import { TaskTrace, TraceSummary, useTrace } from "../ui/TaskTrace";
import { ExecGraph } from "../ui/ExecGraph";
import type { Filter } from "../model/trace";
import { TaskRail } from "../ui/TaskRail";
import { SessionActivity } from "../ui/SessionActivity";
import { TaskResult } from "../ui/TaskResult";

type Sheet = { kind: "todo"; key: string } | { kind: "hint"; id: string } | { kind: "inject" } | null;

export function Cockpit({ pid, asOf, node }: { pid: string; asOf: number | null; node: string | null }) {
  const { api, cfg } = useServices();
  const [session, setSession] = useState<ProblemSession | null>(null);
  useEffect(() => {
    const s = new ProblemSession(api, cfg, pid, { asOf });
    setSession(s);
    void s.start();
    return () => s.close();
  }, [api, cfg, pid]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!session) return <p className="muted">读取中…</p>;
  return <CockpitView session={session} pid={pid} asOf={asOf} node={node} />;
}

type Tab = "result" | "steps" | "struct" | "files";
const TAB_WORD: Record<Tab, string> = { result: "结果", steps: "过程", struct: "结构", files: "文件" };

/** 任务现在的状态（一句话）：等人看、等你处理、受阻、执行中、排队；关了就是终态。 */
function statusOf(vm: ViewModel): { key: string; word: string } {
  const whys = vm.todo.map((t) => t.why);
  if (vm.closed) return { key: "end", word: terminalWord(vm.terminal) };
  if (whys.includes("blocked")) return { key: "need", word: "受阻，要你补" };
  if (whys.some((w) => !IN_RESULT.has(w))) return { key: "need", word: "等你处理" };
  if (whys.includes("delivered")) return { key: "look", word: "做完了，等你看" };
  if (vm.leases.some((l) => l.active)) return { key: "live", word: vm.open.halted ? "收尾中" : "执行中" };
  return { key: "idle", word: "排队中" };
}

function Flow({ steps, live }: { steps: FlowStep[]; live: boolean }) {
  return (
    <ol className="tk-flow" aria-label="执行流程" data-flow>
      {steps.map((s) => (
        <li key={s.key} className={`${s.state}${s.state === "cur" && live ? " live" : ""}`} data-flow-step={s.key} data-state={s.state} aria-current={s.state === "cur" ? "step" : undefined}>
          {s.word}{s.state === "off" && <span className="sr-only">（未开启）</span>}
        </li>
      ))}
    </ol>
  );
}

function CockpitView({ session, pid, asOf, node }: { session: ProblemSession; pid: string; asOf: number | null; node: string | null }) {
  const { cfg } = useServices();
  useEffect(() => {
    if (session.getState().asOf !== asOf) void session.setAsOf(asOf);
  }, [session, asOf]);
  const s = useSyncExternalStore(session.subscribe, session.getState);
  const [view, setView] = useState<"frontier" | "graph">("frontier");
  const [graphPref, setGraphPref] = useState(prefs.graphView());
  const [sheet, setSheet] = useState<Sheet>(null);
  const [tab, setTab] = useState<Tab | null>(node ? "struct" : null);
  // 开放道的会话活动面板：默认跟着在途（没有就最近）的求解会话；右栏“看活动”可以换一个看
  const [pickLease, setPickLease] = useState<string | null>(null);
  const [actOpen, setActOpen] = useState<boolean | null>(null); // null：按有没有在途的求解会话自动展开
  const actRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const tabsRef = useRef<HTMLDivElement>(null);
  // 过程的筛选（概要条的数字点过来会套上）与执行图“在过程里定位”的条目
  const [filter, setFilter] = useState<Filter>("all");
  const [focus, setFocus] = useState<string | null>(null);
  const [structView, setStructView] = useState<"exec" | "reason" | null>(node ? "reason" : null);

  // H 打开“给出指导”，Esc 收起卡片；焦点在输入框里时不抢键
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (e.metaKey || e.ctrlKey || e.altKey || (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)))) return;
      if (e.key === "h" || e.key === "H") { e.preventDefault(); setSheet({ kind: "inject" }); }
      else if (e.key === "Escape") setSheet(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const vm = s.vm;
  const tr = useTrace(pid, vm, asOf);
  const writable = canWrite(s) && cfg.token !== null;
  const go = (patch: { asOf?: number | null; node?: string | null }) =>
    navigate({ page: "problem", pid, asOf: patch.asOf !== undefined ? patch.asOf : asOf, node: patch.node !== undefined ? patch.node : node });
  const select = (id: string) => { countUsage("inspect"); setTab("struct"); setStructView("reason"); go({ node: id }); };

  if (!vm) return <p className={s.error ? "error" : "muted"}>{s.error ? <>读不到任务 <Plain text={pid} />：<Plain text={s.error} /></> : "读取中…"}</p>;

  const open = vm.goal.accept === "open";
  const hasResult = vm.closed || (open && vm.open.deliveries.length > 0);
  const cur: Tab = tab === "result" && !hasResult ? "steps" : tab ?? (hasResult ? "result" : "steps");
  const graphEnabled = vm.rows.length > GRAPH_MIN_NODES || graphPref === "always";
  const conn = asOf !== null ? `回放于 seq=${vm.seq}` : s.conn === "live" ? "实时" : s.conn === "connecting" ? "连接中" : `已断开，停在 seq=${vm.seq}`;
  const openTodo = sheet?.kind === "todo" ? vm.todo.find((t) => todoKey(t) === sheet.key) : undefined;
  const hint = sheet?.kind === "hint" ? vm.hints.find((h) => h.id === sheet.id) : undefined;
  const link = window.location.origin + hrefOf({ page: "problem", pid, asOf: vm.seq, node });
  const cards = vm.todo.filter((t) => !IN_RESULT.has(t.why));
  const scopeAsks = asOf === null ? vm.todo.filter((t) => t.why === "scope_request") : [];
  const live = vm.leases.some((l) => l.active);
  const st = statusOf(vm);
  const last = vm.open.deliveries.at(-1);
  const waitingLook = open && !vm.closed && !!last && (vm.open.followUps.at(-1)?.seq ?? 0) < last.seq;
  const flowIn = {
    accept: vm.goal.accept, closed: vm.closed, terminal: vm.terminal, active: vm.leases.filter((l) => l.active).map((l) => l.kind), started: vm.leases.length > 0,
    todo: vm.todo.map((t) => t.why), deliveries: vm.open.deliveries.length, lastDeliverySeq: last?.seq ?? 0, lastHadSelfCheck: (last?.self_check.length ?? 0) > 0,
    lastFollowUpSeq: vm.open.followUps.at(-1)?.seq ?? 0, judged: vm.goal.predicate.verdicts.length > 0, lastReviewed: !!last?.review,
  };
  const solves = vm.leases.filter((l) => l.kind === "solve");
  // 回放时也给面板（可回放的实时性）：只排那一刻已入账的活动
  const actLease = open ? (pickLease ?? (solves.filter((l) => l.active).at(-1) ?? solves.at(-1))?.id ?? null) : null;
  const actKind = vm.leases.find((l) => l.id === actLease)?.kind ?? "solve";
  const actHidden = !(actOpen ?? solves.some((l) => l.active));
  const openLease = (id: string) => { setPickLease(id); setActOpen(true); requestAnimationFrame(() => actRef.current?.scrollIntoView?.({ block: "nearest" })); };
  const elapsed = vm.budget.wallSpent;
  // 结构：开放道只有执行图；严格判定缺省推理图（原来的前沿与图），可切到执行图
  const sview = open ? "exec" : structView ?? "reason";
  const openScope = (rid: string) => { const t = vm.todo.find((x) => x.why === "scope_request" && x.target === rid); if (t) { countUsage("todo"); setSheet({ kind: "todo", key: todoKey(t) }); } };
  const dock = open && !vm.closed && asOf === null;
  const replyInDock = () => document.getElementById("tk-dock-in")?.focus();
  // 换栏：新的一栏从头看起。标签条已经吸在顶上时，把它留在顶上（不跳回页首）；没吸顶就不动
  const pickTab = (k: Tab) => {
    setTab(k);
    // 标签条原本的位置 = 面板的上沿减去标签条的高（标签条吸顶后自己的 offsetTop 会跟着滚动走，不能用）
    const box = scrollRef.current, bar = tabsRef.current, pane = bar?.nextElementSibling as HTMLElement | null;
    if (!box || !bar || !pane) return;
    const home = pane.offsetTop - bar.offsetHeight;
    if (box.scrollTop > home) box.scrollTop = home;
  };
  // 左右方向键在四栏之间走，Home / End 到头尾（标签页的惯例）；只有当前一栏在 Tab 键顺序里
  const onTabKey = (e: React.KeyboardEvent, keys: Tab[]) => {
    const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    const to = e.key === "Home" ? keys[0] : e.key === "End" ? keys[keys.length - 1] : d ? keys[(keys.indexOf(cur) + d + keys.length) % keys.length] : null;
    if (!to) return;
    e.preventDefault();
    pickTab(to);
    tabsRef.current?.querySelector<HTMLElement>(`[data-task-tab="${to}"]`)?.focus();
  };
  const tabKeys = (["result", "steps", "struct", "files"] as const).filter((k) => k !== "result" || hasResult);
  const meta = vm.closed ? `用了 ${Math.floor(elapsed / 60)} 分 ${elapsed % 60} 秒` : `已跑 ${Math.floor(elapsed / 60)} 分 ${elapsed % 60} 秒`;

  return (
    <div className="cockpit task" data-seq={vm.seq} data-conn={asOf !== null ? "replay" : s.conn} data-inspect={node ? "node" : "none"} data-tab={cur} data-lane={vm.goal.accept}>
      <div className="tk-col">
        <div className="tk-scroll" data-task-scroll ref={scrollRef}>
        <header className="topbar tk-head">
          <div className="topbar-primary tk-l1">
            <span className={`tk-st ${st.key}`} data-status={st.key}><i aria-hidden="true" />{st.word}</span>
            <span className="t2">{meta}</span>
            <span className="conn t2" data-conn-label>{conn}</span>
            <span className="grow" />
            {open && waitingLook && <FeedbackButtons pid={pid} head={s.head} disabled={!writable} />}
            {open && !vm.closed && live && !vm.open.halted && <HaltButton pid={pid} disabled={!writable} />}
            {!vm.closed && (
              <button type="button" className={btnClass(open ? "bare" : "ink", "sm")} data-action="open-inject" aria-pressed={sheet?.kind === "inject"} onClick={() => setSheet(sheet?.kind === "inject" ? null : { kind: "inject" })}>
                <MessageSquare aria-hidden="true" />给出指导<Kbd>H</Kbd>
              </button>
            )}
          </div>
          <h1 className="ws-title"><Text t={vm.title} block={false} /></h1>
          <div className="tk-l3">
            {open ? <span className="badge" data-terminal={vm.terminal ?? "running"}>{vm.closed ? `${terminalWord(vm.terminal)}，未经判定` : "开放道：做完附证据，不经判定器"}</span>
              : <TerminalBadge terminal={vm.terminal} badge={vm.goal.badge} level={vm.goal.predicate.level} onOpen={() => select("goal")} />}
            <details className="topbar-secondary" data-topbar="secondary">
              <summary className="k-link">详情</summary>
              <div className="topbar-secondary-body">
                <span className="k-mono t2">任务 <Plain text={pid} /></span>
                <span className="badge" data-goal-attempts>目标尝试 {vm.goal.predicate.attempts_used ?? 0}/{vm.goal.predicate.max_attempts ?? "—"}</span>
                <details className="profile">
                  <summary className="badge">画像 {vm.profile.info} · {vm.profile.judge} · {vm.profile.reversibility}{vm.profileOverrides.length ? " · 已人工覆盖" : ""}</summary>
                  <p className="muted">画像是派生量：reversibility 取 scope 的最高风险，judge 取目标判定器的类型，info 取资源是否 external。人不填写，只能事后覆盖（pd profile --override）。</p>
                  <p>推导值：{vm.derivedProfile.info} · {vm.derivedProfile.judge} · {vm.derivedProfile.reversibility}</p>
                  {vm.profileOverrides.map((o) => (
                    <div key={o.seq} data-override={o.axis}>
                      <span>{o.axis}：{o.derived ?? "—"} 改为 {o.value} · seq {o.seq}</span>
                      <Text t={o.reason} meta={{ author: o.by }} />
                    </div>
                  ))}
                </details>
                <span className="muted">state <code>{vm.state_hash ? shortHash(vm.state_hash) : "—"}</code></span>
              </div>
            </details>
          </div>
          <Flow steps={flowOf(flowIn)} live={flowLive(flowIn)} />
          <p className="tk-said" data-said><span className="t2">你说的：</span><Plain text={vm.goal.statement.value} /></p>
          <TraceSummary trace={tr.trace} spent={vm.budget.spent} onPick={(f) => { setFilter(f); setFocus(null); setTab("steps"); }} />
        </header>

        {cards.length > 0 && (
          <section className="tk-todo" aria-label="等你处理">
            <h2 className="ws-h">等你处理<span className="ct hot">{cards.length}</span></h2>
            <Todo items={cards} open={sheet?.kind === "todo" ? sheet.key : null} onOpen={(k) => { if (k) countUsage("todo"); setSheet(k ? { kind: "todo", key: k } : null); }} />
          </section>
        )}
        {scopeAsks.length > 0 && (
          <button type="button" className="ws-banner" data-banner="scope" onClick={() => { countUsage("todo"); setSheet({ kind: "todo", key: todoKey(scopeAsks[0]) }); }}>
            等你批准访问 {scopeAsks.length} 个地址<span className="t2">点开处理</span>
          </button>
        )}
        {!writable && <p className="t2 tk-ro" data-readonly-note>{asOf !== null ? "回放中：写操作全部禁用，人的决定只能针对链头。" : vm.closed ? "任务已关闭。" : cfg.token === null ? "还没有配置人的令牌（左下角）：现在只读。" : "未连到链头：写操作暂时禁用。"}</p>}
        {sheet && (
          <div className="sheet" data-sheet={sheet.kind}>
            <button type="button" className={`${btnClass("bare", "sm")} sheet-close`} onClick={() => setSheet(null)}>收起<Kbd>Esc</Kbd></button>
            {sheet.kind === "inject" && <HintInject pid={pid} rows={vm.rows} canWrite={writable} />}
            {sheet.kind === "hint" && <HintTraceCard pid={pid} hintId={sheet.id} seq={vm.seq} ts={hint?.ts ?? null} rows={vm.rows} canWrite={writable} />}
            {sheet.kind === "todo" && openTodo?.why === "needs_human" && <ApprovalCard key={openTodo.target} pid={pid} intentId={openTodo.target} head={s.head} canWrite={writable} onInspect={select} />}
            {sheet.kind === "todo" && openTodo?.why === "scope_request" && <ScopeCard key={openTodo.target} pid={pid} requestId={openTodo.target} head={s.head} canWrite={writable} statementRef={vm.statementRef} />}
            {sheet.kind === "todo" && openTodo?.why === "extension" && <ExtensionDialog pid={pid} head={s.head} canWrite={writable} />}
            {sheet.kind === "todo" && openTodo?.why === "acceptance" && <AcceptanceCard pid={pid} head={s.head} canWrite={writable} log={vm.goal.acceptLog} />}
            {sheet.kind === "todo" && !openTodo && <p className="muted">这一项已不在待办里。</p>}
          </div>
        )}

        {actLease && !actHidden && (
          <div ref={actRef} className="tk-act-wrap">
            <SessionActivity key={`${actLease}@${asOf ?? "live"}`} lease={actLease} kind={actKind} spent={vm.budget.byLease.find((l) => l.lease === actLease)?.usd_milli}
              asOf={asOf} seq={vm.seq} onClose={() => setActOpen(false)} />
          </div>
        )}
        {actLease && actHidden && (
          <button type="button" className="ws-banner tk-act-show" data-action="activity-show" onClick={() => setActOpen(true)}>会话活动<span className="t2">{solves.some((l) => l.active) ? "已收起，点开看智能体在做什么" : "会话已结束，点开看它做过的每一步"}</span></button>
        )}

        <div className="tk-tabs" role="tablist" aria-label="任务视图" ref={tabsRef} onKeyDown={(e) => onTabKey(e, tabKeys)}>
          {tabKeys.map((k) => (
            <button key={k} type="button" role="tab" id={`tk-tab-${k}`} aria-selected={cur === k} aria-controls="tk-pane" tabIndex={cur === k ? 0 : -1} data-task-tab={k} onClick={() => pickTab(k)}>{TAB_WORD[k]}</button>
          ))}
          <span className="grow" />
          {live && asOf === null && <span className="tl-live t2"><span className="tl-dot" aria-hidden="true" />实时更新</span>}
        </div>
        <div className="tk-pane" role="tabpanel" id="tk-pane" aria-labelledby={`tk-tab-${cur}`} data-pane={cur}>
          {cur === "result" && <TaskResult vm={vm} onReply={dock ? replyInDock : undefined} />}
          {cur === "steps" && <TaskTrace data={tr} vm={vm} seq={vm.seq} live={live && asOf === null} filter={filter} onFilter={setFilter} focus={focus} onScope={openScope} />}
          {cur === "files" && <TaskFiles pid={pid} seq={vm.seq} />}
          {cur === "struct" && (
            <nav className="tabs ws-tabs tk-structnav" aria-label="结构">
              <button type="button" aria-pressed={sview === "exec"} data-action="struct-exec" onClick={() => setStructView("exec")}>执行图</button>
              {!open && <button type="button" aria-pressed={sview === "reason"} data-action="struct-reason" onClick={() => setStructView("reason")}>推理图</button>}
              <span className="grow" />
              <span className="t2">{sview === "exec" ? "会话、模型调用、工具调用与留档，按时间从左到右；在做的节点闪动" : "事实、计划与前沿：严格判定任务的推理结构"}</span>
            </nav>
          )}
          {cur === "struct" && sview === "exec" && <ExecGraph data={tr} vm={vm} seq={vm.seq} live={live && asOf === null} onLocate={(k) => { setFocus(k); setFilter("all"); setTab("steps"); }} />}
          {cur === "struct" && sview === "reason" && (
            <div className="tk-struct">
              <div className="main">
                <nav className="tabs ws-tabs" aria-label="结构视图">
                  <button type="button" aria-pressed={view === "frontier"} onClick={() => setView("frontier")}>前沿</button>
                  <button type="button" aria-pressed={view === "graph"} disabled={!graphEnabled} data-action="tab-graph" onClick={() => { countUsage("graph"); setView("graph"); }}>
                    图{graphEnabled ? "" : <span className="t2">（节点超过 {GRAPH_MIN_NODES} 个时启用，现有 {vm.rows.length}）</span>}
                  </button>
                  <span className="grow" />
                  <label className="t2">
                    <input type="checkbox" checked={graphPref === "always"} data-action="graph-always" onChange={(e) => { const v = e.target.checked ? "always" : "auto"; prefs.setGraphView(v); setGraphPref(v); if (v === "auto" && vm.rows.length <= GRAPH_MIN_NODES) setView("frontier"); }} />
                    {" "}不足 {GRAPH_MIN_NODES} 个节点也显示图
                  </label>
                </nav>
                {view === "graph" && graphEnabled
                  ? <GraphView vm={vm} selected={node} onSelect={select} />
                  : <Frontier vm={vm} selected={node} onSelect={select} onOpenHint={(id) => setSheet({ kind: "hint", id })} />}
              </div>
              <aside className="right" aria-label="检视">
                <h2 className="ws-h">检视{node && <span className="ct k-mono">{node}</span>}</h2>
                <Inspector vm={vm} nodeId={node} />
              </aside>
            </div>
          )}
        </div>
        </div>
        <footer className="bottom">
          <Timeline ticks={session.log.ticks} head={s.head} asOf={asOf} onSeek={(a) => { countUsage("timeline"); go({ asOf: a }); }} link={link} />
        </footer>
        {dock && (
          <TaskDock pid={pid} head={s.head} mode={waitingLook ? "follow" : "hint"} disabled={!writable} />
        )}
      </div>
      <TaskRail vm={vm} trace={tr.trace} onSelect={select} onOpenHint={(id) => setSheet({ kind: "hint", id })}
        {...(open && asOf === null ? { onOpenLease: openLease, openLease: actHidden ? null : actLease } : {})} />
    </div>
  );
}
