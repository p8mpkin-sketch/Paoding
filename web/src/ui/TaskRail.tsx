// 任务页右栏（v5 第三期）：花费、用时、钱花在哪（按会话，地图 Q15）、模型、可以访问、会话、你的指导。
// 量具只显示，不驱动任何按钮的默认值；数字都取 /budget 与 /status 的原样字段。
import type { ViewModel } from "../model/viewmodel";
import { usd } from "../model/text";
import { Plain } from "./registers";
import { HintRowView } from "./Frontier";
import { LEASE_WORD, Sessions } from "./Sessions";

const mmss = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
const KIND_WORD: Record<string, string> = { ...LEASE_WORD, solve: "求解", verify: "复核", recall: "回忆", other: "其他" };

export function TaskRail({ vm, onSelect, onOpenHint }: { vm: ViewModel; onSelect: (id: string) => void; onOpenHint: (id: string) => void }) {
  const b = vm.budget;
  const reservedEnd = Math.min(1000, b.spentPermille + b.reservedPermille);
  const rows = b.byLease.length > 0
    ? b.byLease.map((l) => ({ key: l.lease, word: `${KIND_WORD[l.kind] ?? l.kind}${l.active ? "（在做）" : ""}`, sub: l.model ?? l.lease, usd: l.usd_milli }))
    : b.byKind.map((k) => ({ key: k.kind, word: KIND_WORD[k.kind] ?? k.kind, sub: "", usd: k.usd_milli }));
  const top = Math.max(1, ...rows.map((r) => r.usd));
  const reach = vm.scope.filter((r) => r.resource !== "workspace");
  const openHints = vm.hints.filter((h) => !h.closed);
  const live = vm.leases.filter((l) => l.active).length;
  return (
    <aside className="tk-rail" aria-label="花费、模型与会话">
      <section className="cost" data-cost>
        <h3>花费</h3>
        <div className="tk-big"><span data-cost-spent>{usd(b.spent)}</span><small data-cost-cap> / {usd(b.cap)}</small></div>
        <div className="bar" role="meter" aria-valuemin={0} aria-valuemax={b.cap} aria-valuenow={b.spent} aria-label="预算">
          <div className="bar-spent" style={{ width: `${b.spentPermille / 10}%` }} />
          <div className="bar-reserved" style={{ left: `${b.spentPermille / 10}%`, width: `${(reservedEnd - b.spentPermille) / 10}%` }} />
          {b.markLines.map((m) => <div key={m} className={`bar-mark${b.marks.includes(m) ? " crossed" : ""}`} data-mark={m} style={{ left: `${m}%` }} title={`${m}% 标记`} />)}
        </div>
        <p className="t2" data-cost-reserved>{b.reserved > 0 ? `在途会话预留 ${usd(b.reserved)}` : "没有在途会话的预留"}{b.marks.length ? ` · 已越过 ${b.marks.map((m) => `${m}%`).join("、")}` : ""}</p>
      </section>
      <section>
        <h3>用时</h3>
        <div className="tk-big">{mmss(b.wallSpent)}<small> / {mmss(b.wallCap)}</small></div>
      </section>
      {rows.length > 0 && (
        <section data-cost-split>
          <h3>{b.byLease.length > 0 ? "钱花在哪个会话" : "钱花在哪"}</h3>
          <ul className="tk-split">
            {rows.map((r) => (
              <li key={r.key} data-split={r.key}>
                <span className="w">{r.word}{r.sub && <span className="t2 k-mono"> {r.sub}</span>}</span>
                <span className="k-mono r">{usd(r.usd)}</span>
                <span className="tk-splitbar" aria-hidden="true"><b style={{ width: `${Math.round((r.usd * 100) / top)}%` }} /></span>
              </li>
            ))}
          </ul>
        </section>
      )}
      <section data-rail-model>
        <h3>模型</h3>
        <p>{vm.prefs?.model ? <>执行用 <b><Plain text={vm.prefs.model} /></b></> : "按默认分配"}</p>
      </section>
      <section data-rail-scope>
        <h3>可以访问</h3>
        {reach.length === 0 ? <p className="t2">不联网，只在自己的工作区里做。</p> : (
          <ul className="tk-reach">{reach.map((r, i) => (
            <li key={i} className={"revoked" in r ? "off" : ""}><span className="k-mono"><Plain text={r.pattern} /></span>{"granted" in r && <span className="t2"> · 运行时批的</span>}{"revoked" in r && <span className="t2"> · 已撤销</span>}</li>
          ))}</ul>
        )}
      </section>
      <section>
        <h3>会话<span className="ct">{live} 个在途</span></h3>
        <Sessions leases={vm.leases} onSelect={onSelect} />
      </section>
      <section>
        <h3>你的指导<span className="ct">{openHints.length} 条生效</span></h3>
        {openHints.length === 0 ? <p className="t2">还没有给过指导。按 H 给一条。</p> : (
          <ul className="rows ws-hints">{openHints.map((h) => <HintRowView key={h.id} hint={h} onOpen={onOpenHint} />)}</ul>
        )}
      </section>
    </aside>
  );
}
