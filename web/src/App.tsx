import { useMemo, useState } from "react";
import { createApi, type ApiConfig } from "./api/client";
import { saveToken } from "./app/config";
import { ServicesContext } from "./app/context";
import { useRoute } from "./app/router";
import { Cockpit } from "./pages/Cockpit";
import { Link, Problems } from "./pages/Problems";
import { Readings } from "./pages/Readings";
import { Wizard } from "./pages/Wizard";

/** 人的令牌只存在本机。读端点不带它；没有它时整页只读。 */
function TokenBox({ token, onSave }: { token: string | null; onSave: (t: string | null) => void }) {
  const [draft, setDraft] = useState("");
  return (
    <details className="token-box" data-token={token ? "set" : "unset"}>
      <summary className="badge">{token ? "人的令牌：已配置" : "人的令牌：未配置（只读）"}</summary>
      <form onSubmit={(e) => { e.preventDefault(); onSave(draft.trim() || null); setDraft(""); }}>
        <label>令牌（图服务主目录下的 human.token）
          <input type="password" autoComplete="off" value={draft} data-field="token" onChange={(e) => setDraft(e.target.value)} />
        </label>
        <button type="submit" className="btn-small" data-action="save-token">{draft.trim() ? "保存" : "清除"}</button>
      </form>
    </details>
  );
}

export function App({ cfg: initial }: { cfg: ApiConfig }) {
  const [cfg, setCfg] = useState(initial);
  const services = useMemo(() => ({ api: createApi(cfg), cfg }), [cfg]);
  const route = useRoute();
  return (
    <ServicesContext.Provider value={services}>
      <nav className="site-nav">
        <strong>庖丁</strong>
        <Link to={{ page: "problems" }}>题目</Link>
        <Link to={{ page: "new" }}>开题</Link>
        <Link to={{ page: "readings" }}>读数</Link>
        <TokenBox token={cfg.token} onSave={(t) => { saveToken(t); setCfg({ ...cfg, token: t }); }} />
      </nav>
      {route.page === "problems" && <Problems />}
      {route.page === "new" && <Wizard />}
      {route.page === "readings" && <Readings />}
      {route.page === "problem" && <Cockpit key={route.pid} pid={route.pid} asOf={route.asOf} node={route.node} />}
    </ServicesContext.Provider>
  );
}
