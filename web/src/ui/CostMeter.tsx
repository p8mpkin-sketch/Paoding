// 成本仪表（量具；HMI 设计 §3.10）。常驻顶栏，读 /budget：已花、预留、上限，50% 与 80% 两道刻度，
// 验证池，按角色分项，墙钟。量具只显示，不驱动任何按钮的默认值。
import { usd } from "../model/text";
import type { BudgetVM } from "../model/viewmodel";

export function CostMeter({ b }: { b: BudgetVM }) {
  const reservedEnd = Math.min(1000, b.spentPermille + b.reservedPermille);
  return (
    <div className="cost" data-cost>
      <div className="cost-line">
        <span data-cost-spent>已花 {usd(b.spent)}</span>
        <span data-cost-reserved>预留 {usd(b.reserved)}</span>
        <span data-cost-cap>上限 {usd(b.cap)}</span>
        <span>{(b.spentPermille / 10).toFixed(1)}%</span>
      </div>
      <div className="bar" role="meter" aria-valuemin={0} aria-valuemax={b.cap} aria-valuenow={b.spent} aria-label="预算">
        <div className="bar-spent" style={{ width: `${b.spentPermille / 10}%` }} />
        <div className="bar-reserved" style={{ left: `${b.spentPermille / 10}%`, width: `${(reservedEnd - b.spentPermille) / 10}%` }} />
        {b.markLines.map((m) => <div key={m} className={`bar-mark${b.marks.includes(m) ? " crossed" : ""}`} data-mark={m} style={{ left: `${m}%` }} title={`${m}% 标记`} />)}
      </div>
      <details>
        <summary>验证池 {usd(b.verifySpent)} / {usd(b.verifyCap)} · 墙钟 {b.wallSpent}s / {b.wallCap}s · 标记 {b.marks.length ? b.marks.map((m) => `${m}%`).join(" ") : "未越过"}{b.review ? " · 预算复盘期" : ""}</summary>
        <table className="mini">
          <thead><tr><th>角色</th><th>花费</th></tr></thead>
          <tbody>{b.byKind.map((k) => <tr key={k.kind}><td>{k.kind}</td><td>{usd(k.usd_milli)}</td></tr>)}</tbody>
        </table>
        <p className="muted">数值以端点代理的计量为准（/budget）。</p>
      </details>
    </div>
  );
}
