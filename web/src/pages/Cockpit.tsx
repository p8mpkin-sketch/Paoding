// 题内工作区（HMI 设计 §4、§10.2；工作台设计 §1 模块三、线框 f4）。每个面板都是 view(as_of) 的排版；写操作只在链头且实时的时候可用。
// 左：在途会话与待办；中：列表 / 图 / 时间线；右：详情 / 日志 / 成本；底：时间轴与快捷操作。布局偏好只存本机。
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { GRAPH_MIN_NODES, prefs, type WorkspacePrefs } from "../app/config";
import { useServices } from "../app/context";
import { hrefOf, navigate } from "../app/router";
import { canWrite, ProblemSession } from "../app/session";
import { countUsage } from "../app/usage";
import { shortHash } from "../model/text";
import { ApprovalCard } from "../ui/ApprovalCard";
import { CostMeter } from "../ui/CostMeter";
import { TerminalBadge } from "../ui/criterion";
import { ExtensionDialog } from "../ui/ExtensionDialog";
import { Frontier, LevelGroups } from "../ui/Frontier";
import { GraphView } from "../ui/GraphView";
import { HintInject, HintTraceCard } from "../ui/Hints";
import { Inspector } from "../ui/Inspector";
import { Plain, Text } from "../ui/registers";
import { Timeline } from "../ui/Timeline";
import { Todo, todoKey } from "../ui/Todo";
import { CostPanel, EventLogPanel, EventTimeline, QuickActions, Sessions } from "../ui/Workspace";
import { emphasisOf } from "../model/viewmodel";

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

function CockpitView({ session, pid, asOf, node }: { session: ProblemSession; pid: string; asOf: number | null; node: string | null }) {
  const { cfg } = useServices();
  useEffect(() => {
    if (session.getState().asOf !== asOf) void session.setAsOf(asOf);
  }, [session, asOf]);
  const s = useSyncExternalStore(session.subscribe, session.getState);
  const [ws, setWsState] = useState<WorkspacePrefs>(prefs.workspace);
  const setWs = (patch: Partial<WorkspacePrefs>) => setWsState((cur) => { const n = { ...cur, ...patch }; prefs.setWorkspace(n); return n; });
  const [emph, setEmph] = useState<"chain" | "focus" | null>(null);
  const [graphPref, setGraphPref] = useState(prefs.graphView());
  const [sheet, setSheet] = useState<Sheet>(null);
  const [panel, setPanel] = useState<"left" | "main" | "right">("main");

  const vm = s.vm;
  const emphasis = useMemo(() => (vm && emph && node && vm.rows.some((r) => r.id === node) ? emphasisOf(vm.rows, node, emph) : null), [vm, emph, node]);
  const writable = canWrite(s) && cfg.token !== null;
  const go = (patch: { asOf?: number | null; node?: string | null }) =>
    navigate({ page: "problem", pid, asOf: patch.asOf !== undefined ? patch.asOf : asOf, node: patch.node !== undefined ? patch.node : node });
  const select = (id: string) => { countUsage("inspect"); setPanel("right"); if (!ws.rightOpen || ws.tab !== "detail") setWs({ rightOpen: true, tab: "detail" }); go({ node: id }); };

  if (!vm) return <p className={s.error ? "error" : "muted"}>{s.error ? <>读不到题目 <Plain text={pid} />：<Plain text={s.error} /></> : "读取中…"}</p>;

  const graphEnabled = vm.rows.length > GRAPH_MIN_NODES || graphPref === "always";
  const conn = asOf !== null ? `回放于 seq=${vm.seq}` : s.conn === "live" ? "实时" : s.conn === "connecting" ? "连接中" : `已断开，停在 seq=${vm.seq}`;
  const openTodo = sheet?.kind === "todo" ? vm.todo.find((t) => todoKey(t) === sheet.key) : undefined;
  const hint = sheet?.kind === "hint" ? vm.hints.find((h) => h.id === sheet.id) : undefined;
  const link = window.location.origin + hrefOf({ page: "problem", pid, asOf: vm.seq, node });

  return (
    <div className="cockpit" data-left={ws.leftOpen ? "open" : "closed"} data-right={ws.rightOpen ? "open" : "closed"} data-seq={vm.seq} data-conn={asOf !== null ? "replay" : s.conn} data-panel={panel}>
      {/* 顶栏分主次（P2-2）：一眼要看的放主栏——题名、终态与判官、连接、花费；其余收进“详情”。 */}
      <header className="topbar">
        <div className="topbar-primary">
          <h2><Text t={vm.title} block={false} /></h2>
          <TerminalBadge terminal={vm.terminal} badge={vm.goal.badge} level={vm.goal.predicate.level} onOpen={() => select("goal")} />
          <span className="conn" data-conn-label>{conn}</span>
          <CostMeter b={vm.budget} />
          {s.error && <span className="error">刷新失败：<Plain text={s.error} /></span>}
        </div>
        <details className="topbar-secondary" data-topbar="secondary">
          <summary className="badge">详情</summary>
          <div className="topbar-secondary-body">
            <span className="badge" data-goal-attempts>Goal 尝试 {vm.goal.predicate.attempts_used ?? 0}/{vm.goal.predicate.max_attempts ?? "—"}</span>
            <details className="profile">
              <summary className="badge">画像 {vm.profile.info} · {vm.profile.judge} · {vm.profile.reversibility}{vm.profileOverrides.length ? " · 已人工覆盖" : ""}</summary>
              <p className="muted">画像是派生量：reversibility 取 scope 的最高风险，judge 取 Goal 判官的类型，info 取资源是否 external。人不填写，只能事后覆盖（pd profile --override）。</p>
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
      </header>

      {/* 窄屏（< 1024px）三栏改为一栏，用这排按钮切换；宽屏时隐藏，三栏并排。 */}
      <nav className="panel-switch" aria-label="面板">
        {(["left", "main", "right"] as const).map((k) => (
          <button key={k} type="button" aria-pressed={panel === k} data-panel-switch={k} onClick={() => setPanel(k)}>
            {k === "left" ? `待办${vm.todo.length ? `（${vm.todo.length}）` : ""}` : k === "main" ? "前沿与图" : "检视"}
          </button>
        ))}
      </nav>

      <div className="columns">
        <aside className="left" data-collapsed={!ws.leftOpen}>
          <button type="button" className="btn-small collapse" aria-expanded={ws.leftOpen} data-action="toggle-left" onClick={() => setWs({ leftOpen: !ws.leftOpen })}>{ws.leftOpen ? "收起 «" : "»"}</button>
          {ws.leftOpen && <>
          <Sessions rows={vm.sessions} onSelect={select} />
          <Todo items={vm.todo} open={sheet?.kind === "todo" ? sheet.key : null} onOpen={(k) => { if (k) countUsage("todo"); setSheet(k ? { kind: "todo", key: k } : null); if (k) setPanel("main"); }} />
          <button type="button" data-action="open-inject" onClick={() => setSheet(sheet?.kind === "inject" ? null : { kind: "inject" })}>注入 Hint…</button>
          {!writable && <p className="muted" data-readonly-note>{asOf !== null ? "回放中：写操作全部禁用，人的决定只能针对链头。" : vm.closed ? "题目已关闭。" : cfg.token === null ? "还没有配置人的令牌（页面右上角）：现在只读。" : "未连到链头：写操作暂时禁用。"}</p>}
          </>}
        </aside>

        <main className="main">
          {sheet && (
            <div className="sheet">
              <button type="button" className="btn-small sheet-close" onClick={() => setSheet(null)}>收起</button>
              {sheet.kind === "inject" && <HintInject pid={pid} rows={vm.rows} canWrite={writable} />}
              {sheet.kind === "hint" && <HintTraceCard pid={pid} hintId={sheet.id} seq={vm.seq} ts={hint?.ts ?? null} rows={vm.rows} canWrite={writable} />}
              {sheet.kind === "todo" && openTodo?.why === "needs_human" && <ApprovalCard key={openTodo.target} pid={pid} intentId={openTodo.target} head={s.head} canWrite={writable} onInspect={select} />}
              {sheet.kind === "todo" && openTodo?.why === "extension" && <ExtensionDialog pid={pid} head={s.head} canWrite={writable} />}
              {sheet.kind === "todo" && !openTodo && <p className="muted">这一项已不在待办里。</p>}
            </div>
          )}
          <nav className="tabs" aria-label="中心视图">
            <button type="button" aria-pressed={ws.center === "list"} data-center="list" onClick={() => setWs({ center: "list" })}>前沿</button>
            <button type="button" aria-pressed={ws.center === "graph" && graphEnabled} disabled={!graphEnabled} data-action="tab-graph" data-center="graph" onClick={() => { countUsage("graph"); setWs({ center: "graph" }); }}>
              图{graphEnabled ? "" : `（节点超过 ${GRAPH_MIN_NODES} 个时启用，现有 ${vm.rows.length}）`}
            </button>
            <button type="button" aria-pressed={ws.center === "timeline"} data-center="timeline" onClick={() => { countUsage("event_timeline"); setWs({ center: "timeline" }); }}>时间线</button>
            {ws.center === "list" && (
              <label className="muted"><input type="checkbox" checked={ws.groupByLevel} data-action="group-by-level" onChange={(e) => setWs({ groupByLevel: e.target.checked })} /> 按等级分组</label>
            )}
            <label className="muted">
              <input type="checkbox" checked={graphPref === "always"} data-action="graph-always" onChange={(e) => { const v = e.target.checked ? "always" : "auto"; prefs.setGraphView(v); setGraphPref(v); }} />
              {" "}不足 {GRAPH_MIN_NODES} 个节点也显示图（本机开关）
            </label>
          </nav>
          {ws.center === "graph" && graphEnabled ? (
            <GraphView
              vm={vm} selected={node} onSelect={select} emphasis={emphasis}
              toolbar={(
                <span className="emph" role="group" aria-label="突出显示">
                  <button type="button" className="btn-small" aria-pressed={emph === "chain"} disabled={!node} data-action="emph-chain" title="选中节点及其全部前提" onClick={() => { countUsage("focus"); setEmph(emph === "chain" ? null : "chain"); }}>高亮支撑链</button>
                  <button type="button" className="btn-small" aria-pressed={emph === "focus"} disabled={!node} data-action="emph-focus" title="选中节点的上游与下游" onClick={() => { countUsage("focus"); setEmph(emph === "focus" ? null : "focus"); }}>聚焦子图</button>
                  {!node && <span className="muted">先选一个节点</span>}
                </span>
              )}
            />
          ) : ws.center === "timeline" ? (
            <EventTimeline ticks={session.log.ticks} seq={vm.seq} head={s.head} onSeek={(a) => { countUsage("timeline"); go({ asOf: a }); }} />
          ) : ws.groupByLevel ? (
            <LevelGroups vm={vm} selected={node} onSelect={select} />
          ) : (
            <Frontier vm={vm} selected={node} onSelect={select} onOpenHint={(id) => setSheet({ kind: "hint", id })} />
          )}
        </main>

        <aside className="right" data-collapsed={!ws.rightOpen}>
          <nav className="tabs" aria-label="右侧面板">
            <button type="button" className="btn-small collapse" aria-expanded={ws.rightOpen} data-action="toggle-right" onClick={() => setWs({ rightOpen: !ws.rightOpen })}>{ws.rightOpen ? "» 收起" : "«"}</button>
            {ws.rightOpen && (["detail", "log", "cost"] as const).map((t) => (
              <button key={t} type="button" aria-pressed={ws.tab === t} data-right-tab={t} onClick={() => setWs({ tab: t })}>{{ detail: "详情", log: "日志", cost: "成本" }[t]}</button>
            ))}
          </nav>
          {ws.rightOpen && ws.tab === "detail" && <><h3>检视</h3><Inspector vm={vm} nodeId={node} /></>}
          {ws.rightOpen && ws.tab === "log" && <EventLogPanel ticks={session.log.ticks} seq={vm.seq} />}
          {ws.rightOpen && ws.tab === "cost" && <CostPanel vm={vm} />}
        </aside>
      </div>

      <footer className="bottom">
        <Timeline ticks={session.log.ticks} head={s.head} asOf={asOf} onSeek={(a) => { countUsage("timeline"); go({ asOf: a }); }} link={link} />
        <QuickActions pid={pid} canWrite={writable} onInject={() => { setPanel("main"); setSheet({ kind: "inject" }); }} />
      </footer>
    </div>
  );
}
