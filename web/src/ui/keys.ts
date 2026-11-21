// 列表页的键盘：j/k 在带 data-krow 的元素之间移动焦点（Enter 由被聚焦的链接或按钮自己处理），/ 聚焦搜索框。
// 焦点在输入框、下拉或可编辑区域里时不抢键。
import { useEffect, type RefObject } from "react";

export function useRowKeys(root: RefObject<HTMLElement | null>, opts: { search?: RefObject<HTMLInputElement | null>; extra?: (key: string, row: HTMLElement | null) => boolean } = {}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target;
      if (e.metaKey || e.ctrlKey || e.altKey || (t instanceof Element && t.closest("input, textarea, select, [contenteditable]"))) return;
      const rows = [...(root.current?.querySelectorAll<HTMLElement>("[data-krow]") ?? [])];
      const cur = rows.findIndex((r) => r === document.activeElement || r.contains(document.activeElement));
      if (e.key === "j" || e.key === "k") {
        if (!rows.length) return;
        e.preventDefault();
        const n = e.key === "j" ? Math.min(rows.length - 1, cur + 1) : Math.max(0, cur < 0 ? 0 : cur - 1);
        rows[n].focus();
        rows[n].scrollIntoView?.({ block: "nearest" });
      } else if (e.key === "/" && opts.search?.current) {
        e.preventDefault(); opts.search.current.focus();
      } else if (opts.extra?.(e.key, cur >= 0 ? rows[cur] : null)) {
        e.preventDefault();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
}
