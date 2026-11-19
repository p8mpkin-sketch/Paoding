// 基础组件（shadcn 模式：代码在仓库里，样式只用设计令牌）。页面只从这里拿外观，不各自定义颜色。
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Brush } from "./flavor";

export { Brush, Quan, Seal } from "./flavor";

type Tone = "ink" | "zhu" | "line" | "bare";
type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { tone?: Tone; size?: "sm" | "md" };

/** 按钮只有四种：墨（主操作）、朱（只给“需要你”的那一下）、线框（次要）、无框（工具）。 */
export const Button = forwardRef<HTMLButtonElement, BtnProps>(function Button({ tone = "line", size = "md", className, type = "button", ...rest }, ref) {
  return <button ref={ref} type={type} className={btnClass(tone, size, className)} {...rest} />;
});
export const btnClass = (tone: Tone = "line", size: "sm" | "md" = "md", extra?: string) =>
  ["k-btn", `k-btn-${tone}`, size === "sm" ? "k-btn-sm" : "", extra ?? ""].filter(Boolean).join(" ");

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="k-kbd">{children}</kbd>;
}

/** 单字方印：状态记号。字本身就是状态的说法，颜色只是第二重编码。 */
export type MarkTone = "jie" | "wei" | "xing" | "dai" | "yan" | "cao";
export function Mark({ ch, tone, label }: { ch: string; tone: MarkTone; label?: string }) {
  return <span className={`k-mk k-mk-${tone}`} title={label} aria-label={label} role={label ? "img" : undefined}>{ch}</span>;
}

/** 刻度细尺：代替进度条。value、cap 都是服务端给的量；marks 是刻度位置（0–1）。 */
export function Meter({ value, cap, marks = [], hot = false, label }: { value: number; cap: number | null; marks?: number[]; hot?: boolean; label: string }) {
  const f = cap && cap > 0 ? Math.min(1, Math.max(0, value / cap)) : 0;
  return (
    <div className="k-meter" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={cap ?? undefined} aria-valuenow={value}>
      <b className={hot ? "hot" : undefined} style={{ width: `${f * 100}%` }} />
      {marks.map((m) => <s key={m} style={{ left: `${m * 100}%` }} />)}
    </div>
  );
}

/** 页眉：左侧竖排卷签，大标题（写成结论句，是整页唯一焦点），一行导语，右侧操作，下方一笔墨线。
 *  导语不重复页面里另有的数字（阅读质量轮第 2 条）。 */
export function Mast({ vol, cap, title, dek, actions }: { vol?: [string, string]; cap?: ReactNode; title: ReactNode; dek?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="k-mast-wrap">
      <div className="k-mast">
        {vol && <div className="k-vlabel" aria-hidden="true"><b>{vol[0]}</b><span>{vol[1]}</span></div>}
        <div className="k-mast-main">
          {cap && <div className="k-cap">{cap}</div>}
          <h1>{title}</h1>
          {dek && <div className="k-dek">{dek}</div>}
        </div>
        <span className="grow" />
        {actions && <div className="k-mast-actions">{actions}</div>}
      </div>
      <Brush />
    </header>
  );
}

/** 小节标题：前面自动带等宽编号（CSS 计数器），右侧放说明或链接。 */
export function SectionHead({ title, note, right, id }: { title: ReactNode; note?: ReactNode; right?: ReactNode; id?: string }) {
  return (
    <div className="k-sh">
      <h2 id={id}>{title}</h2>
      {note && <span className="k-sh-note">{note}</span>}
      <span className="grow" />
      {right}
    </div>
  );
}

/** 空状态即教程：说明这里会出现什么、怎么让它出现。 */
export function Empty({ title, children, action }: { title: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="k-empty">
      <div className="k-empty-title">{title}</div>
      {children && <div className="k-empty-body">{children}</div>}
      {action && <div className="k-empty-action">{action}</div>}
    </div>
  );
}
