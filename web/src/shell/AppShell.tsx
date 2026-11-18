// 应用外壳：左侧栏（导航、⌘K、正在运行）、顶栏（面包屑与本页唯一的主操作，下沿刻度尺）、
// 内容区（十二栏界栏）、底部状态行。工作区（/p/…）把侧栏收成图标栏，把宽度让给图。
import { useEffect, useState, type ReactNode } from "react";
import { FileUp, Plus, Search } from "lucide-react";
import type { ProblemsView } from "../api/types";
import { useNow } from "../app/clock";
import { navigate, type Route } from "../app/router";
import { applyTheme, loadTheme, THEMES, type Theme } from "../app/theme";
import { runningOf } from "../model/dashboard";
import { usd } from "../model/text";
import { Kbd, Seal, btnClass } from "../kit";
import { Link } from "../pages/Problems";
import { Plain } from "../ui/registers";
import { CommandPalette } from "./CommandPalette";

export type NavKey = "home" | "tasks" | "readings";
type NavItem = { key: NavKey; no: string; word: string; to: Route };
export const NAV: NavItem[] = [
  { key: "home", no: "01", word: "今日", to: { page: "home" } },
  { key: "tasks", no: "02", word: "任务", to: { page: "problems" } },
  { key: "readings", no: "03", word: "读数", to: { page: "readings" } },
];

/** 路由归哪个导航项、属于第几卷（竖排卷签与状态行用）。 */
export function navOf(r: Route): { key: NavKey | null; vol: string; crumbs: string[] } {
  switch (r.page) {
    case "home": return { key: "home", vol: "卷一", crumbs: ["今日"] };
    case "problems": return { key: "tasks", vol: "卷二", crumbs: ["任务"] };
    case "new": return { key: "tasks", vol: "卷二", crumbs: ["任务", r.from ? "克隆" : "新建"] };
    case "import": return { key: "tasks", vol: "卷二", crumbs: ["任务", "导入任务集"] };
    case "readings": return { key: "readings", vol: "卷三", crumbs: ["读数"] };
    case "problem": return { key: null, vol: "工作区", crumbs: ["任务", r.pid] };
  }
}

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

  // 全局快捷键：⌘K / Ctrl+K 命令面板；C 新建任务（在输入框里不触发）
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((v) => !v); return; }
      const el = e.target as HTMLElement | null;
      const typing = !!el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "c" || e.key === "C") { if (route.page !== "new") { e.preventDefault(); navigate({ page: "new" }); } }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [route.page]);

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
            {(route.page === "home" || route.page === "problems") && (
              <>
                <Link to={{ page: "import" }} className={btnClass("line", "md")}><FileUp aria-hidden="true" />导入任务集</Link>
                <Link to={{ page: "new" }} className={btnClass("ink", "md")}><Plus aria-hidden="true" />新建任务 <Kbd>C</Kbd></Link>
              </>
            )}
          </header>
        )}
        <main className={narrow ? "shell-work" : "shell-page"} id="content">{children}</main>
        <footer className="shell-status" aria-label="状态">
          {problemsError && !problems ? <span className="bad">连不上图服务</span> : <span className={problemsError ? "bad" : "ok"}>{problemsError ? "刷新失败" : problems ? "已连接" : "连接中"}</span>}
          <i aria-hidden="true">/</i><span>{canWrite ? "令牌有效 · 可写" : "未配置令牌 · 只读"}</span>
          {problems && <>
            <i aria-hidden="true">/</i><span>在途 {running.length}</span>
            <i aria-hidden="true">/</i><span>等你 {running.reduce((a, p) => a + p.human_todo, 0)}</span>
            <i aria-hidden="true">/</i><span>累计花费 {usd(problems.totals.spent_usd_milli)}</span>
          </>}
          <span className="grow" />
          <span>{nav.vol} · 庖丁 v0.4</span>
          <i aria-hidden="true">/</i><Clock />
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
