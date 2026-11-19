// 前端发出的全部 HTTP 请求都从这里与 stream.ts 走（HT-12：只到图服务 API，没有任何模型端点）。
// 契约是 graph/SPEC.md 的「HTTP 绑定」：读用 GET；写只有 POST /v1/problems、POST …/proposals 与 PUT /v1/blobs，
// 都带人的令牌，与 pd 是同一条提议通道。设置层（宪章 03 §7）另有 PUT /v1/settings 与 /v1/keys 的 PUT/DELETE，
// 也只认人的令牌；密钥只经 PUT 发出一次，没有任何读端点能把它读回来。
import type {
  ArtifactView, BudgetResponse, SnapshotPart, SnapshotResponse, TicksResponse, CardKind, CardResponse, Catalog, ErrorBody, EventsResponse, GraphView, HintTrace, JudgeEntry,
  NodeEvidence, Op, OpResult, ProblemInput, ProblemsView, ProfilePreview, ProposalResponse, ScopeRule, StatusView, WorkView,
} from "./types";
import { HUMAN_OPS } from "./ops";
import type { KeySlot, KeysView, Settings, SettingsDoc, SettingsLogEntry } from "./settings-types";

export type ApiConfig = {
  /** 图服务的基址；同源部署时为空串。 */
  base: string;
  /** 人的令牌（本机配置）。组件令牌永不进入前端。读端点不带它。 */
  token: string | null;
  fetch: typeof fetch;
};

export class ApiError extends Error {
  constructor(readonly status: number, readonly code: string | null, readonly detail: string, readonly extra?: unknown) {
    super(code ? `${code}${detail ? `：${detail}` : ""}` : detail);
  }
}

/** 幂等键只用于"同一请求的重试"。改正后重交必须换新键（graph/SPEC.md 的调用方惯例）。 */
export const newIdemKey = (): string => crypto.randomUUID();

const enc = encodeURIComponent;
const withAsOf = (path: string, asOf?: number, extra: Record<string, string> = {}) => {
  const q = new URLSearchParams(extra);
  if (asOf !== undefined) q.set("as_of", String(asOf));
  const s = q.toString();
  return s ? `${path}?${s}` : path;
};

export function createApi(cfg: ApiConfig) {
  async function call(method: "GET" | "POST" | "PUT" | "DELETE", path: string, body?: BodyInit, contentType?: string, auth = false): Promise<Response> {
    const write = method !== "GET" || auth;
    if (write && !cfg.token) throw new ApiError(401, "forbidden_op", "还没有配置人的令牌（页面右上角）");
    const res = await cfg.fetch(cfg.base + path, {
      method,
      headers: { ...(write ? { authorization: `Bearer ${cfg.token}` } : {}), ...(contentType ? { "content-type": contentType } : {}) },
      body,
      credentials: "omit",
    });
    if (!res.ok) {
      let e: Partial<ErrorBody> = {};
      try {
        e = (await res.json()) as ErrorBody;
      } catch {
        /* 非 JSON 的错误体 */
      }
      const { ok: _ok, code: _c, detail: _d, ...extra } = e as Record<string, unknown>;
      throw new ApiError(res.status, e.code ?? null, e.detail ?? `HTTP ${res.status}`, Object.keys(extra).length ? extra : undefined);
    }
    return res;
  }
  const get = async <T>(path: string): Promise<T> => (await call("GET", path)).json() as Promise<T>;
  const post = async <T>(path: string, body: unknown): Promise<T> =>
    (await call("POST", path, JSON.stringify(body), "application/json")).json() as Promise<T>;

  const json = (body: unknown) => JSON.stringify(body);

  /** 一批提议被内核拒绝仍是 200，逐条结果在 results 里；这里把"整批被拒"变成异常。 */
  function accepted(r: ProposalResponse): Extract<OpResult, { ok: true }>[] {
    if (!r.ok) {
      const bad = r.results.find((x) => !x.ok && x.code !== "batch_aborted") ?? r.results.find((x) => !x.ok);
      const b = bad as Extract<OpResult, { ok: false }> | undefined;
      throw new ApiError(200, b?.code ?? "schema_error", b?.detail ?? "提议被拒", b?.card);
    }
    return r.results as Extract<OpResult, { ok: true }>[];
  }
  function onlyHuman(ops: Op[]) {
    for (const o of ops) if (!HUMAN_OPS.has(o.op)) throw new Error(`不是人可提交的操作：${o.op}`);
  }

  return {
    problems: () => get<ProblemsView>("/v1/problems"),
    status: (pid: string, asOf?: number) => get<StatusView>(withAsOf(`/v1/problems/${enc(pid)}/status`, asOf, { state_hash: "1" })),
    /** 只取前沿：节点本身在 status 里已经有了。 */
    view: (pid: string, asOf?: number) => get<GraphView>(withAsOf(`/v1/problems/${enc(pid)}/view`, asOf, { layer: "title" })),
    budget: (pid: string, asOf?: number) => get<BudgetResponse>(withAsOf(`/v1/problems/${enc(pid)}/budget`, asOf)),
    work: (pid: string, asOf?: number) => get<WorkView>(withAsOf(`/v1/problems/${enc(pid)}/work`, asOf)),
    /** 合并读：一次取 status（带 state_hash）、view（layer=title）、budget、work；parts 只要其中几份。 */
    snapshot: (pid: string, asOf?: number, parts?: readonly SnapshotPart[]) =>
      get<SnapshotResponse>(withAsOf(`/v1/problems/${enc(pid)}/snapshot`, asOf, {
        state_hash: "1", ...(parts ? { parts: parts.join(",") } : {}),
      })),
    /** 时间轴刻度：每条事件只有 seq、ts、种类，外加链尾哈希。冷启动用它，不再分页读全部事件。 */
    ticks: (pid: string, asOf?: number) => get<TicksResponse>(withAsOf(`/v1/problems/${enc(pid)}/ticks`, asOf)),
    /** 审计日志的一段。不带 wait：有就返回，没有也立刻返回。 */
    events: (pid: string, after: number) => get<EventsResponse>(`/v1/problems/${enc(pid)}/events?after=${after}&limit=1000`),
    node: (id: string, asOf?: number) => get<NodeEvidence>(withAsOf(`/v1/nodes/${enc(id)}`, asOf, { layer: "evidence" })),
    card: <F = Record<string, unknown>, D = Record<string, unknown>>(pid: string, kind: CardKind, id: string, asOf?: number) =>
      get<CardResponse<F, D>>(withAsOf(`/v1/problems/${enc(pid)}/cards/${kind}/${enc(id)}`, asOf)),
    hintTrace: (hid: string, asOf?: number) => get<HintTrace>(withAsOf(`/v1/hints/${enc(hid)}/trace`, asOf)),
    judges: () => get<{ items: JudgeEntry[]; external_resources: string[] }>("/v1/judges"),
    templates: () => get<Catalog>("/v1/templates"),
    renderers: () => get<Catalog>("/v1/renderers"),
    artifact: (id: string, asOf?: number) => get<ArtifactView>(withAsOf(`/v1/artifacts/${enc(id)}`, asOf)),
    /** 取回 Blob 的字节。调用方自己算 sha256 与登记值比对，不信任服务端的回显。 */
    blob: async (hash: string): Promise<Uint8Array> => new Uint8Array(await (await call("GET", `/v1/blobs/${enc(hash)}`)).arrayBuffer()),

    /** 画像预检：与开题同一个推导函数，不写日志。 */
    profilePreview: (p: { scope: Partial<ScopeRule>[]; goal: { check: { judge_id: string } } }) => post<ProfilePreview>("/v1/profile/preview", p),
    putBlob: async (bytes: Uint8Array): Promise<{ hash: string; size: number }> =>
      (await (await call("PUT", "/v1/blobs", bytes as BodyInit, "application/octet-stream")).json()) as { hash: string; size: number },
    /** 开题：若干条 input 类登记加最后一条 open_problem，Origin 用 "$<下标>" 指向前面的材料。整批原子。 */
    openProblem: async (id: string, materials: Op[], problem: ProblemInput, idemKey: string) => {
      const ops: Op[] = [...materials, { op: "open_problem", body: problem as unknown as Record<string, unknown> }];
      onlyHuman(ops);
      return accepted(await post<ProposalResponse>("/v1/problems", { id, idem_key: idemKey, ops }));
    },
    // ---- 设置层 ----
    settings: () => get<SettingsDoc>("/v1/settings"),
    settingsLog: () => get<{ items: SettingsLogEntry[] }>("/v1/settings/log"),
    /** base_digest 不是当前摘要 → 409 stale_view（extra.current 是当前摘要）：重读再改。 */
    putSettings: async (baseDigest: string, settings: Settings) =>
      (await call("PUT", "/v1/settings", json({ base_digest: baseDigest, settings }), "application/json")).json() as Promise<SettingsDoc>,
    keys: async () => (await call("GET", "/v1/keys", undefined, undefined, true)).json() as Promise<KeysView>,
    /** 密钥只在这一次请求里出现；调用方发完即清空输入框，不在任何存储里留它。 */
    putKey: async (slot: string, key: string) =>
      (await call("PUT", `/v1/keys/${enc(slot)}`, json({ key }), "application/json")).json() as Promise<KeySlot & { note: string }>,
    clearKey: async (slot: string) => (await call("DELETE", `/v1/keys/${enc(slot)}`)).json() as Promise<KeySlot>,
    clearKeys: async () => (await call("DELETE", "/v1/keys")).json() as Promise<KeysView>,

    /** 人的其余操作都走这里。批内只能有人可提交的操作。 */
    propose: async (pid: string, ops: Op[], idemKey: string) => {
      onlyHuman(ops);
      return accepted(await post<ProposalResponse>(`/v1/problems/${enc(pid)}/proposals`, { idem_key: idemKey, ops }));
    },
  };
}
export type Api = ReturnType<typeof createApi>;
