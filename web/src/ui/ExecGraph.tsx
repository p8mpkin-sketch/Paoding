// 任务页“结构”的执行图（任务详情 v6 §2.3）：一行一个会话（泳道），从左到右是轨迹次序。每次模型调用一个节点，
// 后面挂它发起的工具调用（命令方角、其他工具圆角），exec 下面挂它登记的留档；会话之间用接力箭头连；
// 人的操作（指导、授权、追问、叫停）画在单独的“你”泳道上，虚线连到它之后的第一步。
// 在途的节点闪动，图随轮询向右生长并跟到最新；时间轴拨到哪一刻，图就停在哪一刻（数据本身就是那一刻的）。
// 点节点，右侧检视给出与“过程”里同一条目的完整详情。布局是纯函数（model/trace.ts 的 layoutGraph）。
import { useEffect, useMemo, useRef, useState } from "react";
import type { GNode, Level } from "../model/trace";
import { dur, layoutGraph, tok } from "../model/trace";
import type { ActTurn } from "../api/activity-types";
import { btnClass } from "../kit";
import { usd } from "../model/text";
import type { ViewModel } from "../model/viewmodel";
import { EntryBody, kindWord, labelOf, type TraceData } from "./TaskTrace";
import { EvidenceDrawer } from "./TaskResult";
import { Plain } from "./registers";

const COL = 124, NW = 108, NH = 38, LANE = 72, BELOW = 34, YOU = 56, PAD = 16, FH = 24;

const mmss = (ms: number) => { const s = Math.max(0, Math.floor(ms / 1000)); return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`; };


function rx(n: GNode): number {
  if (n.kind === "call") return n.entry.tool === "exec" || n.entry.ev?.kind === "register_artifact" ? 2 : 10;
  if (n.kind === "turn" || n.kind === "human") return NH / 2;
  if (n.kind === "file") return 3;
  return 6;
}

export function ExecGraph({ data, vm, seq, live, onLocate }: { data: TraceData; vm: ViewModel; seq: number; live: boolean; onLocate: (key: string) => void }) {
  const { trace, error, t0 } = data;
  const [level, setLevel] = useState<Level>("compact");
  const [sel, setSel] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const [ev, setEv] = useState<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const g = useMemo(() => (trace ? layoutGraph(trace, level, labelOf) : null), [trace, level]);

  // 实时：图向右生长时跟到最新（可关；用户往左拖就关掉）
  useEffect(() => {
    const el = scroller.current;
    if (el && live && follow) el.scrollLeft = el.scrollWidth;
  }, [g?.nodes.length, live, follow]);

  if (!trace || !g) return <p className="t2">{error ? <>读不到执行过程：<Plain text={error} /></> : "读取执行过程…"}</p>;
  if (g.nodes.length === 0) return <p className="t2" data-exec-empty>{live ? "正在起会话，第一步出来后图会从这里长出来。" : "这一刻还没有执行过程。"}</p>;

  // 泳道的纵向位置：“你”泳道窄一些；有留档挂在下面的泳道加高
  const hasBelow = new Set(g.nodes.filter((n) => n.below).map((n) => n.lane));
  const tops: number[] = [];
  let y = 0;
  g.lanes.forEach((_, i) => { tops.push(y); y += i === 0 ? YOU : LANE + (hasBelow.has(i) ? BELOW : 0); });
  const height = y;
  const width = PAD * 2 + Math.max(1, g.cols) * COL;
  const pos = new Map(g.nodes.map((n) => {
    const top = tops[n.lane] + ((n.lane === 0 ? YOU : LANE) - NH) / 2;
    return [n.id, n.below ? { x: PAD + n.col * COL + 8, y: top + NH + 14, w: NW - 16, h: FH } : { x: PAD + n.col * COL, y: top, w: NW, h: NH }];
  }));
  const selNode = g.nodes.find((n) => n.id === sel) ?? null;
  const group = selNode ? trace.sessions.find((s) => s.lease === selNode.entry.lease) : undefined;

  return (
    <div className="xg" data-exec-graph data-level={level} data-inspect={selNode ? "node" : "none"}>
      <div className="xg-bar">
        <div className="tr-seg" role="group" aria-label="详略">
          <button type="button" aria-pressed={level === "compact"} data-action="xg-compact" onClick={() => setLevel("compact")}>紧凑</button>
          <button type="button" aria-pressed={level === "full"} data-action="xg-full" onClick={() => setLevel("full")}>完整</button>
        </div>
        <span className="t2 xg-legend">
          <span><i className="lg turn" />模型调用</span><span><i className="lg exec" />命令</span><span><i className="lg tool" />其他工具</span>
          <span><i className="lg done" />交付</span><span><i className="lg you" />你</span>{level === "full" && <span><i className="lg file" />留档</span>}
        </span>
        <span className="grow" />
        <span className="t2 k-mono">{g.nodes.length} 个节点 · {trace.sessions.length} 个会话</span>
        {live && <button type="button" className={`tr-follow${follow ? " on" : ""}`} aria-pressed={follow} data-action="xg-follow" onClick={() => setFollow((v) => !v)}><span className="tl-dot" aria-hidden="true" />跟到最新</button>}
      </div>
      <div className="xg-body">
        <div className="xg-canvas">
          <ul className="xg-lanes" aria-label="泳道" style={{ height }}>
            {g.lanes.map((l, i) => {
              const s = trace.sessions.find((x) => x.lease === l.key);
              return (
                <li key={l.key} className={`xg-lane${l.active && i > 0 ? " on" : ""}`} style={{ top: tops[i], height: (i === 0 ? YOU : LANE + (hasBelow.has(i) ? BELOW : 0)) }} data-lane={l.key}>
                  {i === 0 ? <><b>你</b><span className="t2">{l.sub}</span></> : (
                    <>
                      <b><span className={`pulse${l.active ? "" : " off"}`} aria-hidden="true" />{kindWord(l.label)}</b>
                      <span className="k-mono t2">{l.sub}</span>
                      {s && <span className="t2">{s.active ? "在做" : s.outcome ?? "已结束"}{s.model ? ` · ${s.model}` : ""}</span>}
                    </>
                  )}
                </li>
              );
            })}
          </ul>
          <div className="xg-scroll" ref={scroller} onWheel={(e) => { if (e.deltaX < 0 || (e.shiftKey && e.deltaY < 0)) setFollow(false); }} onPointerDown={() => setFollow(false)} data-graph-scroll>
            <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="group" aria-label="执行图">
              <defs>
                <marker id="xg-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L8,4 L0,8 z" className="xg-arrowhead" /></marker>
              </defs>
              {g.lanes.map((l, i) => i > 0 && <line key={l.key} className="xg-lane-line" x1={0} x2={width} y1={tops[i]} y2={tops[i]} />)}
              {g.edges.map((e, i) => {
                const a = pos.get(e.from), b = pos.get(e.to);
                if (!a || !b) return null;
                if (e.kind === "file") return <line key={i} className="xg-e file" x1={a.x + a.w / 2} y1={a.y + a.h} x2={b.x + b.w / 2} y2={b.y} />;
                if (e.kind === "human") return <path key={i} className="xg-e human" d={`M${a.x + a.w / 2},${a.y + a.h} C${a.x + a.w / 2},${b.y - 20} ${b.x + b.w / 2},${a.y + a.h + 20} ${b.x + b.w / 2},${b.y}`} markerEnd="url(#xg-arrow)" />;
                const x1 = a.x + a.w, y1 = a.y + a.h / 2, x2 = b.x, y2 = b.y + b.h / 2;
                if (e.kind === "relay") { const mx = (x1 + x2) / 2; return <path key={i} className="xg-e relay" d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`} markerEnd="url(#xg-arrow)" />; }
                return <line key={i} className="xg-e seq" x1={x1} y1={y1} x2={x2} y2={y2} />;
              })}
              {g.nodes.map((n, ni) => {
                const p = pos.get(n.id)!;
                const turn = n.kind === "turn" ? (n.entry.item as ActTurn | undefined) : undefined;
                return (
                  <g key={n.id} className={`xg-n ${n.kind} ${n.state}${n.entry.tool === "exec" || n.entry.ev?.kind === "register_artifact" ? " exec" : ""}${sel === n.id ? " sel" : ""}`}
                    transform={`translate(${p.x},${p.y})`} role="button" tabIndex={0} data-node={n.id} data-node-kind={n.kind} data-node-state={n.state}
                    aria-label={`${n.label} ${n.sub}`} aria-pressed={sel === n.id}
                    onClick={() => setSel(sel === n.id ? null : n.id)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSel(n.id); } }}>
                    <rect width={p.w} height={p.h} rx={rx(n)} />
                    {n.state === "now" && <rect className="xg-pulse" width={p.w} height={p.h} rx={rx(n)} />}
                    {/* 框里放完整的字，超出框的部分裁掉（不在文字里加省略号，也不另放 title）：框里的字与节点的名字（aria-label）是同一串，读屏与语音操作对得上；完整内容点开在检视里看 */}
                    <clipPath id={`xg-clip-${ni}`}><rect width={Math.max(p.w - 14, 0)} height={p.h} /></clipPath>
                    <g clipPath={`url(#xg-clip-${ni})`}>
                      {/* 一个 text 里两行（tspan），中间一个空格：文字内容与 aria-label 逐字相同 */}
                      <text x={10} y={16}>
                        <tspan className="xg-t">{n.label}</tspan>{!n.below && " "}
                        {!n.below && <tspan className="xg-s" x={10} y={30}>{turn ? `${tok(turn.in)}→${tok(turn.out)}` : n.sub}</tspan>}
                      </text>
                    </g>
                  </g>
                );
              })}
            </svg>
          </div>
        </div>
        <aside className="xg-insp" aria-label="检视" data-exec-inspect>
          <h2 className="ws-h">检视{selNode && <span className="ct k-mono">{selNode.entry.key}</span>}</h2>
          {!selNode ? <p className="t2">点图上的任意节点，看这一步的完整详情：命令与输出、模型与 token、思考全文、谁发起的。</p> : (
            <div className="xg-detail">
              <p className="xg-meta t2">
                <span className="k-mono">{mmss(selNode.entry.at - t0)}</span>
                {selNode.entry.lease && <span>{kindWord(group?.kind ?? "")}会话 <span className="k-mono">{selNode.entry.lease}</span></span>}
                {selNode.entry.round > 0 && <span>第 {selNode.entry.round} 轮</span>}
                {selNode.entry.dur !== undefined && selNode.entry.dur !== null && <span>耗时 {dur(selNode.entry.dur)}</span>}
                {selNode.entry.cost && <span>花费 {usd(selNode.entry.cost.usd_milli)}</span>}
              </p>
              <div className="xg-body-d"><EntryBody x={selNode.entry} h={{ onEvidence: setEv, pendingScope: new Set(vm.todo.filter((t) => t.why === "scope_request").map((t) => t.target)), expandAll: true }} open /></div>
              <div className="xg-acts">
                <button type="button" className={btnClass("bare", "sm")} data-action="xg-locate" onClick={() => onLocate(selNode.entry.key)}>在过程里定位</button>
                <button type="button" className={btnClass("bare", "sm")} onClick={() => setSel(null)}>收起</button>
              </div>
            </div>
          )}
        </aside>
      </div>
      <EvidenceDrawer id={ev} seq={seq} onClose={() => setEv(null)} />
    </div>
  );
}
