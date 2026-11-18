import { useEffect, useMemo, useState } from "react";
import { createApi, type ApiConfig } from "./api/client";
import { loadToken, saveToken } from "./app/config";
import { ServicesContext } from "./app/context";
import { useRoute } from "./app/router";
import { useNow } from "./app/clock";
import { applyTheme, loadTheme, THEMES, type Theme } from "./app/theme";
import { Cockpit } from "./pages/Cockpit";
import { Dashboard } from "./pages/Dashboard";
import { Import } from "./pages/Import";
import { Link, Problems } from "./pages/Problems";
import { Readings } from "./pages/Readings";
import { Wizard } from "./pages/Wizard";

const clock = (ms: number) => new Date(ms).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });

/** 人的令牌只在本标签页，带到期时间。读端点不带它；没有它时整页只读。 */
function TokenBox({ token, expiresAt, onSave }: { token: string | null; expiresAt: number | null; onSave: (t: string | null) => void }) {
  const [draft, setDraft] = useState("");
  return (
    <details className="token-box" data-token={token ? "set" : "unset"}>
      <summary className="badge">{token ? `人的令牌：已配置${expiresAt ? `，${clock(expiresAt)} 到期` : ""}` : "人的令牌：未配置（只读）"}</summary>
      <p className="muted">只存在本标签页（sessionStorage），关掉标签页或到期后要重新填。</p>
      <form onSubmit={(e) => { e.preventDefault(); onSave(draft.trim() || null); setDraft(""); }}>
        <label>令牌（图服务主目录下的 human.token）
          <input type="password" autoComplete="off" value={draft} data-field="token" onChange={(e) => setDraft(e.target.value)} />
        </label>
        <button type="submit" className="btn-small" data-action="save-token">{draft.trim() ? "保存" : "清除"}</button>
      </form>
    </details>
  );
}

/** 主题切换（本机偏好）：跟随系统、亮色、暗色、高对比。 */
function ThemeSwitch() {
  const [t, setT] = useState<Theme>(loadTheme);
  useEffect(() => applyTheme(t), [t]);
  return (
    <label className="theme-switch">主题{" "}
      <select value={t} data-field="theme" onChange={(e) => setT(e.target.value as Theme)}>
        {THEMES.map((x) => <option key={x.id} value={x.id}>{x.word}</option>)}
      </select>
    </label>
  );
}

function Home() {
  return <Dashboard now={useNow()} />;
}

export function App({ cfg: initial }: { cfg: ApiConfig }) {
  const [cfg, setCfg] = useState(initial);
  const [expiresAt, setExpiresAt] = useState<number | null>(() => loadToken()?.expires_at ?? null);
  // 到期即清：之后的写请求不再带它，界面回到只读
  useEffect(() => {
    if (expiresAt === null) return;
    const t = setTimeout(() => { saveToken(null); setExpiresAt(null); setCfg((c) => ({ ...c, token: null })); }, Math.max(0, expiresAt - Date.now()));
    return () => clearTimeout(t);
  }, [expiresAt]);
  const services = useMemo(() => ({ api: createApi(cfg), cfg }), [cfg]);
  const route = useRoute();
  return (
    <ServicesContext.Provider value={services}>
      <nav className="site-nav">
        <strong>庖丁</strong>
        <Link to={{ page: "home" }} className={route.page === "home" ? "on" : undefined}>总览</Link>
        <Link to={{ page: "problems" }} className={route.page === "problems" ? "on" : undefined}>题库</Link>
        <Link to={{ page: "new" }} className={route.page === "new" || route.page === "import" ? "on" : undefined}>开题</Link>
        <Link to={{ page: "readings" }} className={route.page === "readings" ? "on" : undefined}>读数</Link>
        <span className="nav-space" />
        <ThemeSwitch />
        <TokenBox token={cfg.token} expiresAt={expiresAt} onSave={(t) => { setExpiresAt(saveToken(t)?.expires_at ?? null); setCfg({ ...cfg, token: t }); }} />
      </nav>
      {route.page === "home" && <Home />}
      {route.page === "problems" && <Problems filter={{ q: route.q ?? "", terminal: route.terminal ?? "", judge: route.judge ?? "" }} />}
      {route.page === "new" && <Wizard key={route.from ?? ""} from={route.from} />}
      {route.page === "import" && <Import />}
      {route.page === "readings" && <Readings />}
      {route.page === "problem" && <Cockpit key={route.pid} pid={route.pid} asOf={route.asOf} node={route.node} />}
    </ServicesContext.Provider>
  );
}
