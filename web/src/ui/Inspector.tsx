// 检视与下钻（HMI 设计 §3.4、§10.2 右栏）。自上而下按证据、叙述、估值排列，人的判断以作者行插入。
// 任何论断三次点击内到达证据根（H6 的四种终点）：
//   节点行 → 支持记录或前提链条目 → Artifact 卡（命令行、退出码、哈希、本地校验）
//   推断类沿前提链展开；链上没有任何登记过的 Artifact 时显式标"无证据根"（由图服务判定，字段 no_evidence_root）。
import { useEffect, useState } from "react";
import type { GroundRef, NodeEvidence } from "../api/types";
import { useServices } from "../app/context";
import { INTENT_STATE_WORD } from "../model/levels";
import { premiseChain, type NodeRow, type ViewModel } from "../model/viewmodel";
import { CriterionCard, LevelBadge } from "./criterion";
import { ArtifactChip, Plain, Text } from "./registers";

function PremiseChain({ rows, id, seq }: { rows: ReadonlyMap<string, NodeRow>; id: string; seq: number }) {
  const chain = premiseChain(rows, id);
  if (chain.length === 0) return null;
  return (
    <section>
      <h4>前提链</h4>
      <ul className="tree">
        {chain.map(({ row, depth }) => (
          <li key={row.id}>
            <details data-action="open-premise" data-premise={row.id}>
              <summary>{"· ".repeat(depth - 1)}{row.id} · {row.kind === "fact" ? `${row.level} ${row.levelWord}` : row.state ? INTENT_STATE_WORD[row.state] : "尝试"} · {row.grounds.length} 份 Artifact</summary>
              <Text t={row.title} />
              {row.grounds.length === 0 ? <p className="muted">这一环没有登记 Artifact</p> : <ul className="tree">{row.grounds.map((a) => <ArtifactChip key={a} id={a} seq={seq} />)}</ul>}
            </details>
          </li>
        ))}
      </ul>
    </section>
  );
}

function NodeView({ ev, vm }: { ev: NodeEvidence; vm: ViewModel }) {
  const rows = new Map(vm.rows.map((r) => [r.id, r]));
  const seq = vm.seq;
  if (ev.type === "hint") {
    return (
      <div className="inspector" data-node={ev.id}>
        <header className="inspector-head"><strong>{ev.id}</strong><span className="muted">指导{ev.closed ? "（已关闭）" : ""}</span></header>
        <Text t={ev.text} meta={{ author: ev.author, note: ev.about ? `about ${ev.about}` : undefined }} />
        <p className="muted">指导是人的判断，不是证据，不能作前提。</p>
      </div>
    );
  }
  const row = rows.get(ev.id);
  const grounds: GroundRef[] = ev.type === "fact" ? ev.grounds : [];
  // 整条链有没有证据根由图服务判定（裁决 005-4）；前提链的展开只用来摆出下钻的入口
  const rooted = !ev.no_evidence_root;
  return (
    <div className="inspector" data-node={ev.id}>
      <header className="inspector-head">
        <strong>{ev.id}</strong>
        <span className="muted">{ev.type === "fact" ? (ev.claim_type === "observation" ? "观察类论断" : "推断类论断") : "尝试"}</span>
        <LevelBadge level={ev.level} word={row?.levelWord ?? ""} />
        {ev.type === "intent" && <span className="badge">{INTENT_STATE_WORD[ev.status]}</span>}
        {ev.type === "intent" && <span className="badge">{ev.risk}</span>}
        {ev.type === "fact" && ev.disputed && <span className="badge">争议</span>}
        {ev.type === "fact" && ev.stale && <span className="badge">stale</span>}
        {ev.type === "fact" && ev.unstable && <span className="badge">unstable</span>}
      </header>

      {/* —— 证据 —— */}
      {ev.predicate ? <CriterionCard p={ev.predicate} seq={seq} /> : <p className="muted">没有判据：{ev.type === "fact" ? "推断类论断只有前提与 grounds。" : "这次尝试不带 done。"}</p>}
      {ev.type === "fact" && (
        <section>
          <h4>grounds</h4>
          {grounds.length === 0 ? <p className="muted">无</p> : <ul className="tree">{grounds.map((g) => <ArtifactChip key={g.id} id={g.id} seq={seq} hint={`${g.class} 类`} />)}</ul>}
        </section>
      )}
      <PremiseChain rows={rows} id={ev.id} seq={seq} />
      {ev.type === "fact" && !rooted && (
        <p className="no-root" data-evidence-root="none">无证据根：沿前提链到不了任何登记过的 Artifact。</p>
      )}

      {/* —— 叙述 —— */}
      <section>
        <h4>叙述</h4>
        <Text t={ev.title} />
        <Text t={ev.summary} />
      </section>

      {/* —— 人的判断 —— */}
      {ev.type === "intent" && ev.decision && (
        <Text t={ev.decision.reason.value ? ev.decision.reason : { ...ev.decision.reason, value: "（未写理由）" }} meta={{ author: ev.decision.by, note: `${ev.decision.decision === "approve" ? "批准" : "拒绝"} · seq ${ev.decision.seq}` }} />
      )}

      {/* —— 估值（折叠） —— */}
      {ev.type === "intent" && ev.expected_gain && (
        <details className="estimates"><summary>估值</summary><Text t={ev.expected_gain} meta={{ what: "期望增益" }} /></details>
      )}
    </div>
  );
}

function GoalView({ vm }: { vm: ViewModel }) {
  return (
    <div className="inspector" data-node="goal">
      <header className="inspector-head">
        <strong>目标</strong>
        <LevelBadge level={vm.goal.predicate.level} word={vm.goal.levelWord} />
        <span className="badge">accept: {vm.goal.accept}</span>
      </header>
      <CriterionCard p={vm.goal.predicate} seq={vm.seq} />
      <section><h4>目标陈述</h4><Text t={vm.goal.statement} meta={{ note: "新建任务时写下" }} /></section>
    </div>
  );
}

export function Inspector({ vm, nodeId }: { vm: ViewModel; nodeId: string | null }) {
  const { api } = useServices();
  const [ev, setEv] = useState<NodeEvidence | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const seq = vm.seq;
  useEffect(() => {
    setEv(null);
    setErr(null);
    if (!nodeId || nodeId === "goal") return;
    let live = true;
    api.node(nodeId, seq).then((r) => live && setEv(r), (e: Error) => live && setErr(e.message));
    return () => { live = false; };
  }, [api, nodeId, seq]);
  if (!nodeId) return <p className="t2" data-inspect-empty>选一个节点，这里显示它的判据与证据。</p>;
  if (nodeId === "goal") return <GoalView vm={vm} />;
  if (err) return <p className="error">取不到 {nodeId} 在 seq {seq} 的证据层：<Plain text={err} /></p>;
  if (!ev || ev.id !== nodeId) return <p className="muted">读取中…</p>;
  return <NodeView ev={ev} vm={vm} />;
}
