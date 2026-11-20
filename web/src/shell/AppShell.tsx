// 应用外壳（v5）：左侧栏（标志、新任务、⌘K、导航、进行中、主题与连接状态）、顶栏（位置与本页主操作）、内容区。
// 工作区（/p/…）把侧栏收成图标栏，把宽度让给图。
import { useEffect, useState, type ReactNode } from "react";
import { Boxes, FileUp, Gauge, Inbox, LayoutList, Plus, Search, Settings, Sun } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ProblemsView } from "../api/types";
import { navigate, type Route } from "../app/router";
import { applyTheme, loadTheme, THEMES, type Theme } from "../app/theme";
import { runningOf } from "../model/dashboard";
import { Kbd, Logo, btnClass } from "../kit";
import { Link } from "../pages/Problems";
import { Plain } from "../ui/registers";
import { CommandPalette } from "./CommandPalette";

export type NavKey = "today" | "inbox" | "tasks" | "models" | "readings" | "settings";
type NavItem = { key: NavKey; word: string; icon: LucideIcon; to: Route };
export const NAV: NavItem[] = [
  { key: "today", word: "今日", icon: Sun, to: { page: "today" } },
  { key: "tasks", word: "任务", icon: LayoutList, to: { page: "problems" } },
  { key: "inbox", word: "待你处理", icon: Inbox, to: { page: "inbox" } },
  { key: "models", word: "模型", icon: Boxes, to: { page: "models" } },
  { key: "readings", word: "读数", icon: Gauge, to: { page: "readings" } },
];
const SETTINGS: NavItem = { key: "settings", word: "设置", icon: Settings, to: { page: "settings" } };

/** 路由归哪个导航项，顶栏写什么位置。 */
export function navOf(r: Route): { key: NavKey | null; crumbs: string[] } {
  switch (r.page) {
    case "home": return { key: null, crumbs: ["新建任务"] };
    case "today": return { key: "today", crumbs: ["今日"] };
    case "inbox": return { key: "inbox", crumbs: ["待你处理"] };
    case "problems": return { key: "tasks", crumbs: ["任务"] };
    case "new": return { key: "tasks", crumbs: ["任务", r.from ? "克隆" : r.advanced ? "高级模式" : "新建"] };
    case "import": return { key: "tasks", crumbs: ["任务", "导入任务集"] };
    case "platform": return { key: "tasks", crumbs: ["任务", "从平台导入"] };
    case "readings": return { key: "readings", crumbs: ["读数"] };
    case "settings": return { key: "settings", crumbs: ["设置"] };
    case "models": return { key: "models", crumbs: ["模型"] };
    case "problem": return { key: null, crumbs: ["任务", r.pid] };
  }
}

/** 顶栏放“导入任务集 / 新建任务”的页面；快捷键 C 也只在这些页面生效。 */
export const hasNewButton = (r: Route) => r.page === "today" || r.page === "problems";

/** 主题（本机偏好）：跟随系统、亮、暗、高对比。 */
function ThemeSwitch() {
  const [t, setT] = useState<Theme>(loadTheme);
  useEffect(() => applyTheme(t), [t]);
  useEffect(() => {
    const on = (e: Event) => setT((e as CustomEvent<Theme>).detail);
    window.addEventListener("paoding:theme", on);
    return () => window.removeEventListener("paoding:theme", on);
  }, []);
  return (
    <label className="shell-theme">
      <span className="sr-only">主题</span>
      <select value={t} data-field="theme" onChange={(e) => setT(e.target.value as Theme)}>
        {THEMES.map((x) => <option key={x.id} value={x.id}>{x.word}</option>)}
      </select>
    </label>
  );
}

type Props = {
  route: Route;
  problems: ProblemsView | null;
  problemsError: string | null;
  canWrite: boolean;
  token: ReactNode;
  children: ReactNode;
};

export function AppShell({ route, problems, problemsError, canWrite, token, children }: Props) {
  const [palette, setPalette] = useState(false);
  const nav = navOf(route);
  const narrow = route.page === "problem";
  const openPid = route.page === "problem" ? route.pid : null;
  const running = problems ? runningOf(problems.items) : [];
  const waiting = running.reduce((a, p) => a + p.human_todo, 0);

  // 全局快捷键：⌘K / Ctrl+K 命令面板；C 新建任务（在输入框里不触发）
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((v) => !v); return; }
      const el = e.target as HTMLElement | null;
      const typing = !!el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
      // 只在顶栏有“新建任务”按钮的页面生效；工作区键盘操作多，不抢它的键
      if ((e.key === "c" || e.key === "C") && hasNewButton(route)) { e.preventDefault(); navigate({ page: "home" }); }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [route]);

  const status = problemsError && !problems ? <span className="bad">连不上图服务</span>
    : problemsError ? <span className="bad">刷新失败，显示的是上一次读到的</span>
    : <span className="ok">{problems ? "已连接" : "连接中"}<span className="sub">{canWrite ? " · 可写" : " · 只读（未配置令牌）"}</span></span>;
  const item = (n: NavItem) => {
    const Icon = n.icon;
    return (
      <Link key={n.key} to={n.to} className={`shell-nav-item${nav.key === n.key ? " on" : ""}`} data-nav={n.key}>
        <Icon aria-hidden="true" className="ic" />
        <span className={narrow ? "sr-only" : "word"}>{n.word}</span>
        {!narrow && n.key === "tasks" && problems && <span className="ct num">{problems.items.length}</span>}
        {n.key === "inbox" && waiting > 0 && <span className="ct hot num">{waiting}<span className="sr-only"> 项等你处理</span></span>}
      </Link>
    );
  };

  return (
    <div className={`shell${narrow ? " shell-narrow" : ""}`}>
      <aside className="shell-side" aria-label="主导航">
        <div className="shell-brand">
          <Logo size={20} />
          {!narrow && <b>庖丁</b>}
        </div>
        {!narrow && (
          <>
            <Link to={{ page: "home" }} className={btnClass("ink", "md", "shell-new")} data-action="side-new"><Plus aria-hidden="true" /><span className="grow">新任务</span><Kbd>C</Kbd></Link>
            <button type="button" className="shell-find" onClick={() => setPalette(true)} data-action="open-palette">
              <Search aria-hidden="true" /><span>搜索或跳转</span><Kbd>⌘K</Kbd>
            </button>
          </>
        )}
        <nav className="shell-nav">{NAV.map(item)}</nav>
        {!narrow && running.length > 0 && (
          <>
            <div className="shell-group">进行中</div>
            <ul className="shell-pins">
              {running.slice(0, 6).map((p) => (
                <li key={p.id}>
                  <Link to={{ page: "problem", pid: p.id, asOf: null, node: null }} className={`shell-pin${openPid === p.id ? " on" : ""}`}>
                    <span className={`pulse${p.human_todo > 0 ? " hot" : ""}`} aria-hidden="true" />
                    <span className="ell"><Plain text={String(p.title.value) || p.id} /></span>
                    {p.human_todo > 0 && <span className="sr-only">，等你处理 {p.human_todo} 项</span>}
                  </Link>
                </li>
              ))}
            </ul>
          </>
        )}
        <div className="shell-foot">
          {item(SETTINGS)}
          {!narrow && <ThemeSwitch />}
          {token}
          {/* 状态行只说一件主事：连得上、能不能写；数字都在页面里，不在这里重复（阅读质量轮第 6 条） */}
          <div className="shell-status" aria-label="状态" role="status">{status}</div>
        </div>
      </aside>

      <div className="shell-main">
        {!narrow && (
          <header className="shell-top">
            <nav aria-label="位置" className="shell-crumbs">
              {nav.crumbs.map((c, i) => <span key={i} className={i === nav.crumbs.length - 1 ? "here" : undefined}>{i > 0 && <span className="sep" aria-hidden="true">/</span>}{c}</span>)}
            </nav>
            <span className="grow" />
            {hasNewButton(route) && (
              <>
                <Link to={{ page: "import" }} className={btnClass("line", "md")}><FileUp aria-hidden="true" />导入任务集</Link>
                <Link to={{ page: "home" }} className={btnClass("ink", "md")}><Plus aria-hidden="true" />新建任务</Link>
              </>
            )}
          </header>
        )}
        <main className={narrow ? "shell-work" : "shell-page"} id="content">{children}</main>
      </div>
      <CommandPalette open={palette} onOpenChange={setPalette} problems={problems} />
    </div>
  );
}
