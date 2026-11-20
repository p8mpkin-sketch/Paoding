import { useEffect, useMemo, useState } from "react";
import { Toaster } from "sonner";
import { createApi, type ApiConfig } from "./api/client";
import { loadToken, saveToken } from "./app/config";
import { ServicesContext } from "./app/context";
import { useRoute } from "./app/router";
import { useNow } from "./app/clock";
import { Cockpit } from "./pages/Cockpit";
import { Dashboard } from "./pages/Dashboard";
import { Import } from "./pages/Import";
import { PlatformImport } from "./pages/PlatformImport";
import { Inbox } from "./pages/Inbox";
import { Kaiti } from "./pages/Kaiti";
import { ModelsPage } from "./pages/Models";
import { Problems, useProblems } from "./pages/Problems";
import { Readings } from "./pages/Readings";
import { SettingsPage } from "./pages/Settings";
import { Wizard } from "./pages/Wizard";
import { AppShell } from "./shell/AppShell";

const clock = (ms: number) => new Date(ms).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });

/** 人的令牌只在本标签页，带到期时间。读端点不带它；没有它时整页只读。 */
function TokenBox({ token, expiresAt, onSave }: { token: string | null; expiresAt: number | null; onSave: (t: string | null) => void }) {
  const [draft, setDraft] = useState("");
  return (
    <details className="token-box" data-token={token ? "set" : "unset"}>
      <summary>
        <span className={`token-dot${token ? " on" : ""}`} aria-hidden="true" />
        <span className="grow">{token ? `令牌已配置${expiresAt ? ` · ${clock(expiresAt)} 到期` : ""}` : "未配置令牌（只读）"}</span>
      </summary>
      <form onSubmit={(e) => { e.preventDefault(); onSave(draft.trim() || null); setDraft(""); }}>
        <label>人的令牌<span className="muted">图服务主目录下的 human.token</span>
          <input type="password" autoComplete="off" value={draft} data-field="token" onChange={(e) => setDraft(e.target.value)} />
        </label>
        <p className="muted">只存在本标签页，关掉标签页或到期后要重新填。</p>
        <button type="submit" className="k-btn k-btn-ink k-btn-sm" data-action="save-token">{draft.trim() ? "保存" : "清除"}</button>
      </form>
    </details>
  );
}

function Today() {
  return <Dashboard now={useNow()} />;
}

/** 外壳要的题目列表：正在运行、状态行与命令面板用。15 秒一次，页面不可见时不读。 */
const SHELL_POLL_MS = 15_000;

function Shell({ cfg, token }: { cfg: ApiConfig; token: React.ReactNode }) {
  const route = useRoute();
  const { view, error } = useProblems(SHELL_POLL_MS);
  return (
    <AppShell route={route} problems={view} problemsError={error} canWrite={!!cfg.token} token={token}>
      {route.page === "home" && <Kaiti home />}
      {route.page === "today" && <Today />}
      {route.page === "problems" && <Problems filter={{ q: route.q ?? "", terminal: route.terminal ?? "", judge: route.judge ?? "" }} />}
      {route.page === "new" && !route.advanced && <Kaiti />}
      {route.page === "new" && route.advanced && <Wizard key={route.from ?? ""} from={route.from} />}
      {route.page === "import" && <Import />}
      {route.page === "platform" && <PlatformImport key={route.id ?? ""} id={route.id} />}
      {route.page === "readings" && <Readings />}
      {route.page === "inbox" && <Inbox />}
      {route.page === "settings" && <SettingsPage />}
      {route.page === "models" && <ModelsPage />}
      {route.page === "problem" && <Cockpit key={route.pid} pid={route.pid} asOf={route.asOf} node={route.node} />}
    </AppShell>
  );
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
  const token = <TokenBox token={cfg.token} expiresAt={expiresAt} onSave={(t) => { setExpiresAt(saveToken(t)?.expires_at ?? null); setCfg({ ...cfg, token: t }); }} />;
  return (
    <ServicesContext.Provider value={services}>
      <Shell cfg={cfg} token={token} />
      <Toaster position="bottom-right" offset={40} toastOptions={{ unstyled: true, classNames: { toast: "k-toast", title: "k-toast-title", description: "k-toast-desc", actionButton: "k-btn k-btn-line k-btn-sm" } }} />
    </ServicesContext.Provider>
  );
}
