// 应用外壳：左侧栏（导航、⌘K、正在运行）、顶栏（面包屑与本页唯一的主操作，下沿刻度尺）、
// 内容区（十二栏界栏）、底部状态行。工作区（/p/…）把侧栏收成图标栏，把宽度让给图。
import { useEffect, useState, type ReactNode } from "react";
import { FileUp, Plus, Search } from "lucide-react";
import type { ProblemsView } from "../api/types";
import { useNow } from "../app/clock";
import { navigate, type Route } from "../app/router";
import { applyTheme, loadTheme, THEMES, type Theme } from "../app/theme";
import { runningOf } from "../model/dashboard";
import { Kbd, Seal, btnClass } from "../kit";
import { Link } from "../pages/Problems";
import { Plain } from "../ui/registers";
import { CommandPalette } from "./CommandPalette";

export type NavKey = "home" | "inbox" | "tasks" | "readings" | "settings";
type NavItem = { key: NavKey; no: string; word: string; to: Route };
export const NAV: NavItem[] = [
  { key: "home", no: "01", word: "今日", to: { page: "home" } },
  { key: "inbox", no: "02", word: "待办", to: { page: "inbox" } },
  { key: "tasks", no: "03", word: "任务", to: { page: "problems" } },
  { key: "readings", no: "04", word: "读数", to: { page: "readings" } },
  { key: "settings", no: "05", word: "设置", to: { page: "settings" } },
];

/** 路由归哪个导航项、属于第几卷（竖排卷签与状态行用）。 */
export function navOf(r: Route): { key: NavKey | null; vol: string; crumbs: string[] } {
  switch (r.page) {
    case "home": return { key: "home", vol: "卷一", crumbs: ["今日"] };
    case "inbox": return { key: "inbox", vol: "卷二", crumbs: ["待办"] };
    case "problems": return { key: "tasks", vol: "卷三", crumbs: ["任务"] };
    case "new": return { key: "tasks", vol: "卷三", crumbs: ["任务", r.from ? "克隆" : "新建"] };
    case "import": return { key: "tasks", vol: "卷三", crumbs: ["任务", "导入任务集"] };
    case "readings": return { key: "readings", vol: "卷四", crumbs: ["读数"] };
    case "settings": return { key: "settings", vol: "卷五", crumbs: ["设置"] };
    case "problem": return { key: null, vol: "工作区", crumbs: ["任务", r.pid] };
  }
}

/** 顶栏放“导入任务集 / 新建任务”的页面；快捷键 C 也只在这些页面生效。 */
export const hasNewButton = (r: Route) => r.page === "home" || r.page === "problems";

const hm = (ms: number) => new Date(ms).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });

/** 主题（本机偏好）：随、宣、墨、素。 */
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
      <span className="k-cap">主题</span>
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
      if ((e.key === "c" || e.key === "C") && hasNewButton(route)) { e.preventDefault(); navigate({ page: "new" }); }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [route]);

  return (
    <div className={`shell${narrow ? " shell-narrow" : ""}`}>
      <aside className="shell-side" aria-label="主导航">
        <div className="shell-brand">
          <Seal size={narrow ? 30 : 32} />
          {!narrow && <><b>庖丁</b><small>v0.4</small></>}
        </div>
        {!narrow && (
          <button type="button" className="shell-find" onClick={() => setPalette(true)} data-action="open-palette">
            <Search aria-hidden="true" /><span>搜索，或输入命令</span><Kbd>⌘K</Kbd>
          </button>
        )}
        <nav className="shell-nav">
          {NAV.map((n) => (
            <Link key={n.key} to={n.to} className={`shell-nav-item${nav.key === n.key ? " on" : ""}`} data-nav={n.key}>
              <span className="no" aria-hidden="true">{narrow ? n.word.slice(0, 1) : n.no}</span>
              <span className={narrow ? "sr-only" : "word"}>{n.word}</span>
              {!narrow && n.key === "tasks" && problems && <span className="ct num">{problems.items.length}</span>}
              {!narrow && n.key === "inbox" && waiting > 0 && <span className="ct hot num">{waiting}<span className="sr-only"> 项等你处理</span></span>}
            </Link>
          ))}
        </nav>
        {!narrow && running.length > 0 && (
          <>
            <div className="shell-group k-cap">正在运行</div>
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
          {!narrow && <ThemeSwitch />}
          {token}
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
                <Link to={{ page: "new" }} className={btnClass("ink", "md")}><Plus aria-hidden="true" />新建任务 <Kbd>C</Kbd></Link>
              </>
            )}
          </header>
        )}
        <main className={narrow ? "shell-work" : "shell-page"} id="content">{children}</main>
        {/* 状态行只留一件主事（连得上、能不能写），其余退成灰字；数字都在页面里，不在这里重复（阅读质量轮第 6 条） */}
        <footer className="shell-status" aria-label="状态">
          {problemsError && !problems ? <span className="bad">连不上图服务</span>
            : problemsError ? <span className="bad">刷新失败，显示的是上一次读到的</span>
            : <span className="ok">{problems ? "已连接" : "连接中"}<span className="sub">{canWrite ? " · 可写" : " · 只读（未配置令牌）"}</span></span>}
          <span className="grow" />
          <span className="dim">庖丁 v0.4 · <Clock /></span>
        </footer>
      </div>
      <CommandPalette open={palette} onOpenChange={setPalette} problems={problems} />
    </div>
  );
}

function Clock() {
  const now = useNow(30_000);
  return <span className="num">{hm(now)}</span>;
}
