// 标志：两片斜切的刀面，一实一虚。对读屏器隐藏；旁边总有“庖丁”二字。
// v4 的印、朱圈、笔触、套准十字已删（v5 不用装饰）。
export function Logo({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" className="k-logo" aria-hidden="true" focusable="false">
      <path d="M2 2h9.5L6 18H2z" fill="currentColor" />
      <path d="M14.5 2H18v16H9z" fill="currentColor" opacity=".38" />
    </svg>
  );
}
