// 装饰层：印、圈、笔触、朱批、套准十字。全部对读屏器隐藏；要表达的意思另有文字在页面里。
import { useId, type CSSProperties } from "react";

/** 朱文印：位移滤镜做出印泥不匀与边缘毛糙。两个字竖排。 */
export function Seal({ size = 30, text = ["庖", "丁"] }: { size?: number; text?: [string, string] }) {
  const id = useId().replace(/:/g, "");
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" className="k-seal" aria-hidden="true" focusable="false">
      <defs>
        <filter id={`r${id}`} x="-10%" y="-10%" width="120%" height="120%">
          <feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves={2} seed={7} />
          <feDisplacementMap in="SourceGraphic" scale={1.4} />
        </filter>
        <filter id={`i${id}`}>
          <feTurbulence type="fractalNoise" baseFrequency="1.6" numOctaves={1} seed={3} result="n" />
          <feColorMatrix in="n" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 -0.55 1.3" result="m" />
          <feComposite in="SourceGraphic" in2="m" operator="in" />
        </filter>
      </defs>
      <g filter={`url(#r${id})`}>
        <g filter={`url(#i${id})`}>
          <rect x="2" y="2" width="36" height="36" rx="2.5" fill="var(--zhu)" />
          <text x="20" y="18" textAnchor="middle" fontFamily="Noto Serif SC, serif" fontWeight="600" fontSize="15" fill="var(--paper)">{text[0]}</text>
          <text x="20" y="35" textAnchor="middle" fontFamily="Noto Serif SC, serif" fontWeight="600" fontSize="15" fill="var(--paper)">{text[1]}</text>
        </g>
      </g>
    </svg>
  );
}

/** 手绘朱圈：圈住一个要紧的数或节点。位置由调用方给（相对最近的定位祖先）。 */
export function Quan({ style, rot = -6 }: { style: CSSProperties; rot?: number }) {
  return (
    <svg className="k-quan" style={style} viewBox="0 0 100 60" preserveAspectRatio="none" aria-hidden="true" focusable="false">
      <path d="M12 34 C 8 12, 52 2, 80 10 C 100 16, 98 44, 70 52 C 44 60, 6 54, 10 30 C 12 20, 30 12, 46 10" fill="none" stroke="var(--zhu)" strokeWidth="2.6" strokeLinecap="round" vectorEffect="non-scaling-stroke" opacity=".85" transform={`rotate(${rot} 50 30)`} />
    </svg>
  );
}

/** 页眉下的一笔：起笔重、收笔尖；两端放套准十字。 */
export function Brush() {
  return (
    <div className="k-brush" aria-hidden="true">
      <span className="k-reg" style={{ left: -22 }}><b /></span>
      <span className="k-reg" style={{ right: -22 }}><b /></span>
      <svg viewBox="0 0 1000 14" preserveAspectRatio="none">
        <path d="M0 6 C 120 3, 260 8, 420 5 S 760 4, 1000 7 L 1000 8 C 760 7, 520 10, 300 9 S 80 10, 0 11 Z" fill="var(--ink)" />
      </svg>
    </div>
  );
}
