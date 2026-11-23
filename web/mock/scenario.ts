// 假服务的剧本：三道题的事件序列。内容是编的，只为让每种界面状态都有数据可看。
import type { Actor, Event } from "../src/api/types";

export type Api = {
  append(pid: string, actor: Actor, kind: string, body: Record<string, unknown>): Event;
  putBlob(data: string): string;
  stateOf(pid: string): { decisions: Map<string, { decision: string }> };
  sha256(data: string): string;
};
export type Step = { run(api: Api): void; waitFor?: (s: ReturnType<Api["stateOf"]>) => boolean };
export type Script = { pid: string; steps: Step[]; preload?: number };

const HUMAN: Actor = { kind: "human", id: "local" };
const SINAN: Actor = { kind: "sinan", id: "sinan" };
const GRAPH: Actor = { kind: "graph", id: "graph" };
const EXEC: Actor = { kind: "executor", id: "executor" };
const JUDGE: Actor = { kind: "judge", id: "judgebox" };
const SHUKU: Actor = { kind: "graph", id: "shuku" }; // 书库的组件令牌：登记 knowledge 类、记 kb_query
const WATCHDOG: Actor = { kind: "watchdog", id: "watchdog" };
/** 会话即租约 id；剧本里用租约的名字，运行时换成真正的 l_<seq>。 */
const adapter = (lease: string, role: string) => (ids: Record<string, string>): Actor => ({ kind: "adapter", id: "adapter", session: ids[lease], role });

class Builder {
  steps: Step[] = [];
  ids: Record<string, string> = {};
  constructor(readonly pid: string) {}
  /** 追加一步；name 给出时把新对象的 id（前缀_seq）记下来供后面引用。 */
  ev(actorIn: Actor | ((ids: Record<string, string>) => Actor), kind: string, body: (ids: Record<string, string>, api: Api) => Record<string, unknown>, name?: string, waitFor?: Step["waitFor"]) {
    const prefix = { register_artifact: "a", add_fact: "f", add_intent: "i", request_judge: "j", hint: "h", lease: "l", request_scope: "r", deliver: "d" }[kind];
    this.steps.push({
      waitFor,
      run: (api) => {
        const actor = typeof actorIn === "function" ? actorIn(this.ids) : actorIn;
        const e = api.append(this.pid, actor, kind, body(this.ids, api));
        if (name && prefix) this.ids[name] = `${prefix}_${e.seq}`;
      },
    });
    return this;
  }
  input(name: string, text: string) {
    return this.ev(HUMAN, "register_artifact", (_i, api) => ({ hash: api.putBlob(text), size: text.length, media_type: "text/plain", class: "input", producer: { actor: "local" }, parents: [] }), name);
  }
  exec(name: string, session: string, tool: string, command: string, output: string, exit = 0, truncated = false) {
    return this.ev(EXEC, "register_artifact", (_i, api) => ({
      hash: api.putBlob(output), size: output.length, media_type: "text/plain", class: "exec", producer: { actor: "executor", session: _i[session] },
      exec: { sandbox_id: `sb-${this.pid}`, base: "default", baseline_ref: "base@1", tool, command, cwd: "/work", exit_code: exit, touched: ["target:8080"], started_at: 0, ended_at: 0, truncated },
      parents: [],
    }), name);
  }
  /** 会话查资料（资料库第二期）：kb_query 记查询词与命中；kb_read 读到的段落由书库登记为 knowledge 类。
   * chunk 与假后端知识页的段落 id 同一算法（sha256(资料:段号) 前 16 位），证据抽屉能取到原文。 */
  kb(name: string, session: string, query: string, source: string, para: number, text: string, locator: string) {
    const chunk = (api: Api) => `k_${api.sha256(`${source}:${para}`).slice(0, 16)}`;
    this.ev(SHUKU, "kb_query", (i, api) => ({ lease: i[session], query, hits: [chunk(api)] }));
    return this.ev(SHUKU, "register_artifact", (_i, api) => ({
      hash: api.putBlob(text), size: text.length, media_type: "text/plain; charset=utf-8", class: "knowledge", producer: { actor: "shuku" },
      knowledge: { source, revision: 1, chunk: chunk(api), locator }, parents: [],
    }), name);
  }
  authored(name: string, session: string, text: string, media = "text/plain") {
    return this.ev(adapter(session, "reason"), "register_artifact", (_i, api) => ({ hash: api.putBlob(text), size: text.length, media_type: media, class: "authored", producer: { actor: "adapter", session: _i[session] }, parents: [] }), name);
  }
  lease(name: string, kind: string, target?: string, waitFor?: Step["waitFor"]) {
    return this.ev(SINAN, "lease", (i) => ({ kind, ...(target ? { target: i[target] } : {}), holder: "sinan", reserve: { usd_milli: 400, wall_s: 600 }, ttl_s: 600, attempt: 1 }), name, waitFor);
  }
  release(id: string, role: string, usd: number) {
    this.ev(adapter(id, role), "cost", (i) => ({ task_id: i[id], source: "proxy", model: "model-a", tokens_in: usd * 90, tokens_cached: 0, tokens_out: usd * 12, usd_milli: usd, wall_s: 40 + (usd % 50), price_table: "prices@1" }));
    return this.ev(SINAN, "release", (i) => ({ lease: i[id], outcome: "done" }));
  }
  judge(name: string, target: string, judgeId: string, result: "pass" | "fail" | "inconclusive", output: string, candidate?: string) {
    this.ev(SINAN, "request_judge", (i) => ({ target: i[target] ?? target, judge_id: judgeId, ...(candidate ? { candidate: i[candidate] } : {}) }), name);
    this.ev(JUDGE, "lease", (i) => ({ kind: "judge", target: i[name], holder: "judgebox", reserve: { usd_milli: 50, wall_s: 60 }, ttl_s: 120, attempt: 1 }), `${name}_lease`);
    this.ev(JUDGE, "register_artifact", (i, api) => ({
      hash: api.putBlob(output), size: output.length, media_type: "text/plain", class: "judge", producer: { actor: "judgebox" },
      exec: { sandbox_id: "judge-clean", base: "judge", baseline_ref: "base@1", tool: judgeId, command: `${judgeId} --request ${i[name]}`, cwd: "/judge", exit_code: result === "pass" ? 0 : 1, touched: [], started_at: 0, ended_at: 0, truncated: false },
      parents: [],
    }), `${name}_out`);
    this.ev(JUDGE, "cost", (i) => ({ task_id: i[`${name}_lease`], source: "judge", tokens_in: 0, tokens_cached: 0, tokens_out: 0, usd_milli: 10, wall_s: 3, price_table: "prices@1" }));
    this.ev(JUDGE, "judge_verdict", (i) => ({ request: i[name], result, version: "1", grade: "decisive", evidence: [i[`${name}_out`]] }));
    return this.ev(JUDGE, "release", (i) => ({ lease: i[`${name}_lease`], outcome: "done" }));
  }
  open(title: string, statement: string, extra: Record<string, unknown>) {
    return this.ev(HUMAN, "open_problem", (i) => ({
      title, origin: { statement_ref: i.statement, materials: [] },
      goal: { statement, check: { judge_id: "exact_match", sealed: [{ vault: `answers/${this.pid}`, digest: "9f2c".repeat(16) }] }, max_attempts: 5, accept: "judge" },
      scope: [{ resource: "net", pattern: "target:8080", actions: ["connect"], risk: "r0" }],
      budget: { usd_milli: 11500, wall_s: 7200, verify_share: 0.2, bootstrap_share: 0.333 },
      env: { base: "default", baseline_ref: "base@1" }, judges: ["exact_match", "replay"],
      profile: { info: "complete", judge: "hard", reversibility: "r0" },
      ...extra,
    }));
  }
}

const OUT_INDEX = "HTTP/1.1 200 OK\nServer: demo\n\n<html><title>登录</title><form action=/login method=post>…</form>\n<!-- 运维备忘：归档接口在 8081 -->\n";
const OUT_LOGIN = "HTTP/1.1 401 Unauthorized\n\n{\"error\":\"bad credentials\",\"hint\":\"账号见归档\"}\n";
const OUT_ARCHIVE = "HTTP/1.1 200 OK\n\naccounts.txt\nreadme.txt\n";
const OUT_ACCOUNTS = "HTTP/1.1 200 OK\n\nops:winter-harbor-42\n";

export function demoScript(): Script {
  const b = new Builder("demo-1");
  b.input("statement", "目标服务在 target:8080。取得登录后页面上显示的答案串并提交。\n授权范围：只许连接 target:8080。\n");
  b.open("示例题：取得登录后显示的答案串", "提交登录后页面显示的答案串", {});
  // 第 1 轮：摸底
  b.lease("L1", "bootstrap");
  b.exec("x_index", "L1", "http_get", "http_get http://target:8080/", OUT_INDEX);
  b.ev(adapter("L1", "bootstrap"), "add_fact", (i) => ({ title: "首页是一个登录表单", summary: "GET / 返回 200，页面含指向 /login 的表单。", claim_type: "observation", check: { judge_id: "replay", spec_ref: i.x_index, expect: { status: 200, contains: "form action=/login" } }, premises: [], grounds: [i.x_index] }), "f_index");
  b.release("L1", "bootstrap", 310);
  b.judge("j1", "f_index", "replay", "pass", "replay: status=200 contains=ok\nverdict: pass\n");
  // 第 2 轮：Reason
  b.lease("L2", "reason");
  b.ev(adapter("L2", "reason"), "add_intent", (i) => ({ title: "试默认账号登录", summary: "用常见默认账号组合请求 /login，看返回。", premises: [i.f_index], risk: "r0", budget: { usd_milli: 400, wall_s: 600 }, expected_gain: 0.3 }), "i_login");
  b.ev(adapter("L2", "reason"), "add_intent", (i) => ({ title: "枚举隐藏路径", summary: "按常见路径表逐个请求。", premises: [i.f_index], risk: "r0", budget: { usd_milli: 600, wall_s: 900 }, expected_gain: 0.1 }), "i_enum");
  b.release("L2", "reason", 520);
  b.lease("L3", "explore", "i_login");
  b.exec("x_login", "L3", "shell", "curl -s -i -d 'user=admin&pass=admin' http://target:8080/login", OUT_LOGIN);
  b.ev(adapter("L3", "explore"), "add_fact", (i) => ({ title: "默认账号被拒，返回里提到归档", summary: "POST /login 返回 401，正文提示账号见归档。", claim_type: "observation", check: { judge_id: "replay", spec_ref: i.x_login, expect: { status: 401 } }, premises: [i.f_index], grounds: [i.x_login] }), "f_401");
  b.ev(adapter("L3", "explore"), "add_fact", (i) => ({ title: "账号放在 8081 的归档接口里", summary: "首页注释说归档接口在 8081，登录返回又说账号见归档，两者合起来推断。", claim_type: "inference", premises: [i.f_index, i.f_401], grounds: [] }), "f_guess");
  b.release("L3", "explore", 450);
  b.judge("j2", "f_401", "replay", "pass", "replay: status=401\nverdict: pass\n");
  b.ev(HUMAN, "hint", (i) => ({ text: "别在 8080 上枚举了，先看 8081 的归档接口有没有鉴权。", about: i.f_guess }), "h1");
  // 第 3 轮：读过 Hint 的 Reason
  b.lease("L4", "reason");
  b.ev(adapter("L4", "reason"), "add_intent", (i) => ({ title: "读取 8081 的归档目录", summary: "连接 target:8081 列出归档内容。需要把授权范围扩到 8081。", premises: [i.f_guess], risk: "r1", budget: { usd_milli: 500, wall_s: 600 }, needs_scope: [{ resource: "net", pattern: "target:8081", actions: ["connect"], risk: "r1" }], expected_gain: 0.6 }), "i_archive");
  b.ev(adapter("L4", "reason"), "abandon_intent", (i) => ({ intent: i.i_enum }));
  b.ev(adapter("L4", "reason"), "add_fact", (i) => ({ title: "拿到账号后登录即可见答案串", summary: "只依赖一条尚未达成的 Intent，没有任何采集记录。", claim_type: "inference", premises: [i.i_archive], grounds: [] }), "f_noroot");
  b.release("L4", "reason", 640);
  const preload = b.steps.length;
  // 以下等人批准 i_archive 之后才继续
  b.lease("L5", "explore", "i_archive", (s) => [...s.decisions.values()].some((a) => a.decision === "approve"));
  b.exec("x_arch", "L5", "http_get", "http_get http://target:8081/", OUT_ARCHIVE);
  b.exec("x_acct", "L5", "http_get", "http_get http://target:8081/accounts.txt", OUT_ACCOUNTS);
  b.ev(adapter("L5", "explore"), "add_fact", (i) => ({ title: "归档接口无鉴权，列出两个文件", summary: "GET 8081/ 返回 200 与文件清单。", claim_type: "observation", check: { judge_id: "replay", spec_ref: i.x_arch, expect: { status: 200 } }, premises: [i.f_guess], grounds: [i.x_arch] }), "f_arch");
  b.ev(adapter("L5", "explore"), "add_fact", (i) => ({ title: "归档里的账号是 admin", summary: "accounts.txt 里是 admin 的口令。", claim_type: "observation", check: { judge_id: "replay", spec_ref: i.x_acct, expect: { contains: "admin:" } }, premises: [i.f_arch], grounds: [i.x_acct] }), "f_wrong");
  b.release("L5", "explore", 2300);
  b.ev(GRAPH, "budget_mark", () => ({ mark: 50, axis: "usd_milli" }));
  b.judge("j3", "f_arch", "replay", "pass", "replay: status=200\nverdict: pass\n");
  b.judge("j4", "f_wrong", "replay", "fail", "replay: contains 'admin:' → false（实际为 ops:…）\nverdict: fail\n");
  b.lease("L6", "reason");
  b.ev(adapter("L6", "reason"), "add_intent", (i) => ({ title: "用归档里的 ops 账号登录并取答案串", summary: "accounts.txt 的账号是 ops，登录后读页面。", premises: [i.f_arch], risk: "r0", budget: { usd_milli: 400, wall_s: 600 }, expected_gain: 0.8 }), "i_final");
  b.release("L6", "reason", 700);
  b.lease("L7", "explore", "i_final");
  b.exec("x_final", "L7", "shell", "curl -s -d 'user=ops&pass=winter-harbor-42' http://target:8080/login", "HTTP/1.1 200 OK\n\n欢迎 ops。答案串：PD{demo-answer}\n");
  b.authored("cand1", "L7", "PD{demo-answe}");
  b.release("L7", "explore", 900);
  b.judge("j5", "goal", "exact_match", "fail", "exact_match: 不相符（原因类别：值不同）\nverdict: fail\n", "cand1");
  b.authored("cand2", "L7", "PD{demo-answer}");
  b.judge("j6", "goal", "exact_match", "pass", "exact_match: 相符\nverdict: pass\n", "cand2");
  b.ev(GRAPH, "close_problem", () => ({ terminal: "solved", by: "graph", card_hash: null }));
  return { pid: b.pid, steps: b.steps, preload };
}

export function staticScripts(): Script[] {
  // demo-2：越过 80% 而无进展（续期门），另有一条缺回退声明的 r2 Intent。
  const b = new Builder("demo-2");
  b.input("statement", "把配置项恢复到上周的值，并确认服务指标回到基线。\n");
  b.open("示例题：恢复配置并确认指标", "指标在观察窗内回到基线", {
    scope: [
      { resource: "telemetry", pattern: "svc/*", actions: ["read"], risk: "r0" },
      { resource: "config", pattern: "svc/main", actions: ["write"], risk: "r2" },
    ],
    goal: { statement: "指标在观察窗内回到基线", check: { judge_id: "window_assert", expect: { metric: "error_rate", below: 0.01, window_s: 600 } }, max_attempts: 2, accept: "human",
      acceptance: [{ id: "a1", text: "指标在观察窗内回到基线", src: "span" }, { id: "a2", text: "附上回滚前后的指标截图", src: "human", needs: "artifact" }] },
    judges: ["window_assert", "replay"],
    budget: { usd_milli: 6000, wall_s: 3600, verify_share: 0.2, bootstrap_share: 0.333 },
    profile: { info: "partial", judge: "deferred", reversibility: "r2" },
  });
  b.lease("M1", "bootstrap");
  b.exec("x_metric", "M1", "metric_read", "metric_read svc/main error_rate --last 1h", "ts,error_rate\n10:00,0.002\n10:30,0.081\n11:00,0.079\n", 0, true);
  b.ev(adapter("M1", "bootstrap"), "add_fact", (i) => ({ title: "错误率在 10:30 前后升高", summary: "一小时内错误率从 0.2% 升到 8%。", claim_type: "observation", check: { judge_id: "replay", spec_ref: i.x_metric, expect: { above: 0.05 } }, premises: [], grounds: [i.x_metric] }), "f_metric");
  b.release("M1", "bootstrap", 1800);
  b.judge("k1", "f_metric", "replay", "pass", "replay: above 0.05 → true\nverdict: pass\n");
  b.lease("M2", "reason");
  b.ev(adapter("M2", "reason"), "add_intent", (i) => ({ title: "把 svc/main 的配置回滚到上周版本", summary: "写入上周的配置快照。点此批准即可立即生效。", premises: [i.f_metric], risk: "r2", budget: { usd_milli: 800, wall_s: 900 }, done: { judge_id: "window_assert", expect: { metric: "error_rate", below: 0.01 }, max_attempts: 1 }, expected_gain: 0.7 }), "i_rollback");
  b.release("M2", "reason", 1500);
  b.ev(GRAPH, "budget_mark", () => ({ mark: 50, axis: "usd_milli" }));
  b.lease("M3", "reason");
  b.release("M3", "reason", 1700);
  b.ev(GRAPH, "budget_mark", () => ({ mark: 80, axis: "usd_milli" }));

  // demo-3：预算耗尽，按 unsolved 关闭。
  const c = new Builder("demo-3");
  c.input("statement", "在给定材料里找出唯一满足条件的编号。\n");
  c.open("示例题：材料检索（未解出）", "提交满足条件的编号", { budget: { usd_milli: 2000, wall_s: 1800, verify_share: 0.2, bootstrap_share: 0.333 } });
  c.lease("N1", "bootstrap");
  c.release("N1", "bootstrap", 1990);
  c.ev(GRAPH, "budget_mark", () => ({ mark: 50, axis: "usd_milli" }));
  c.ev(GRAPH, "budget_mark", () => ({ mark: 80, axis: "usd_milli" }));
  c.ev(WATCHDOG, "close_problem", () => ({ terminal: "unsolved", by: "watchdog", card_hash: null }));
  // demo-4：开题零出站，运行时扩权（runtime-grants §7）。一条练习道白名单自动批准，一条等人批。
  const d = new Builder("demo-4");
  d.input("statement", "题目服务分两台机器。\n\n接口在 q7.lab:8443，返回 JSON；数据另有镜像，放在 mirror.example.org 上。\n\n取出 flag 字段并提交。\n");
  const ws = { resource: "workspace", pattern: "", actions: ["read", "write"], risk: "r0" };
  const q7 = { resource: "net", pattern: "q7.lab:8443", actions: ["connect"], risk: "r0" };
  const mirror = { resource: "net", pattern: "mirror.example.org:443", actions: ["connect"], risk: "r2" };
  const prof = (info: string, rev: string) => ({ info, judge: "hard", reversibility: rev });
  d.open("示例题：运行时扩权", "提交接口返回的 flag 字段", {
    scope: [ws], profile: prof("complete", "r0"),
  });
  d.lease("P1", "bootstrap");
  d.ev(adapter("P1", "bootstrap"), "request_scope", () => ({ rules: [q7], risk_from: [0], why: "题面说接口在 q7.lab:8443，需要读它的返回", auto: true }), "r_q7");
  d.ev(GRAPH, "grant_scope", (i) => ({ request: i.r_q7, via: "auto", decision: "approve", policy: { version: 3, digest: "7e1a".repeat(16) }, rules: [q7], derived: prof("partial", "r0") }));
  d.ev(adapter("P1", "bootstrap"), "request_scope", () => ({
    rules: [mirror], risk_from: [null], why: "接口返回里给了一个镜像地址，想从那里取完整数据", auto: false,
    blockers: ["mirror.example.org:443 不在练习道信封的地址段里", "风险表未命中，按缺省 r2，高于练习道上限 r0"],
  }), "r_mirror");
  const q9 = { resource: "net", pattern: "q9.lab:9000", actions: ["connect"], risk: "r0" };
  d.ev(adapter("P1", "bootstrap"), "request_scope", () => ({
    rules: [q9], risk_from: [0], why: "接口的错误信息指向 q9.lab:9000 的日志服务", auto: false, blockers: ["任务预算超过练习上限"],
  }), "r_q9");
  // demo-5：人工验收（宪章 D3、02 §3.3）。交付物已过结构检查（只是读数），等人按清单逐条判。
  const e = new Builder("demo-5");
  e.input("statement", "帮我调研一下主流的智能体框架，写一份对比。\n");
  e.open("示例题：框架对比（人工验收）", "写一份主流智能体框架的对比", {
    goal: {
      statement: "写一份主流智能体框架的对比", check: { judge_id: "structure_check", expect: { format: "text", min_bytes: 200 } }, max_attempts: 3, accept: "human",
      acceptance: [
        { id: "a1", text: "帮我调研一下主流的智能体框架，写一份对比。", src: "span" },
        { id: "a2", text: "对比覆盖至少三个框架，并附上对比表", src: "human", needs: "artifact" },
        { id: "a3", text: "写明没覆盖的部分与原因", src: "human", needs: "note" },
      ],
    },
    judges: ["structure_check", "replay"],
    profile: { info: "partial", judge: "deferred", reversibility: "r0" },
  });
  e.lease("Q1", "bootstrap");
  e.exec("x_report", "Q1", "shell", "cat report.md", "# 框架对比\n\n| 框架 | 编排 | 工具调用 |\n| --- | --- | --- |\n| A | 图 | 有 |\n| B | 链 | 有 |\n| C | 角色 | 有 |\n");
  e.release("Q1", "bootstrap", 900);
  e.judge("k_struct", "goal", "structure_check", "pass", "format: text\nsize: 212\nproblems: []\n", "x_report");
  // demo-6：开放道（open-lane §3.4）。一句话开题，会话做完交付：答案、主张与依据、自检、没验证的；等人看。
  const o = new Builder("demo-6");
  const said = "对比 LangGraph、AutoGen、CrewAI 三个框架的状态持久化方式，各自崩溃后能恢复到哪一步，给出选型建议。";
  o.input("statement", `${said}\n`);
  o.open("示例题：三个框架的状态持久化", said, {
    goal: { statement: said, accept: "open", self_checks: [{ text: "对照原话：三个框架、恢复粒度、选型建议都答到", src: "human" }] },
    scope: [{ resource: "workspace", pattern: "", actions: ["read", "write"], risk: "r0" }, { resource: "net", pattern: "github.com:443", actions: ["connect"], risk: "r0" }],
    budget: { usd_milli: 2000, wall_s: 1800, verify_share: 0.2, bootstrap_share: 0.3 },
    judges: [], profile: { info: "complete", judge: "none", reversibility: "r0" },
    prefs: { model: "default" },
  });
  o.lease("S1", "solve");
  o.authored("notes", "S1", "# 计划\n1. 读三家的持久化接口\n2. 各写一个中途杀进程的复现\n3. 按恢复粒度对比\n");
  o.exec("e_clone", "S1", "shell", "rg -l checkpoint langgraph/libs | head -2", "libs/checkpoint/langgraph/checkpoint/base/__init__.py\nlibs/checkpoint-sqlite/langgraph/checkpoint/sqlite/__init__.py\n");
  o.exec("e_lg", "S1", "shell", "python repro/crash_test.py --fw langgraph", "step1 done\nstep2 killed (SIGKILL)\n--- restart, same thread_id ---\nresume -> next=('step2',)\nstep2 done · step3 done\n");
  o.kb("kb_team", "S1", "崩溃 恢复 回滚 约定", "s_team01", 0, "上线前先在 staging 跑全量测试。回滚用上一个标签重新发布，数据库迁移必须能反向执行。", "团队约定.md / 上线与回滚");
  o.exec("e_ag", "S1", "shell", "python repro/crash_test.py --fw autogen", "step1 done\nstep2 killed (SIGKILL)\n--- restart ---\nload_state: FileNotFoundError: state.json\n-> 从头开始\n");
  o.exec("e_ag2", "S1", "shell", "python repro/crash_test.py --fw autogen --save-each-step", "step1 done · state saved\nstep2 killed (SIGKILL)\n--- restart ---\nload_state ok -> 从 step2 继续\n");
  o.exec("e_cr", "S1", "shell", "python repro/crash_test.py --fw crewai", "flow.step1 done · persisted\ncrew task 1/3 done\ncrew task 2/3 killed (SIGKILL)\n--- restart ---\nflow resumes at step2 -> crew 从 task 1/3 重跑\n");
  o.authored("answer", "S1", "需要崩溃后自动续跑，选 LangGraph：三者里只有它默认按步落盘，杀进程后从没做完的那一步接着跑。\n\n| 框架 | 什么时候落盘 | 崩溃后恢复到哪 |\n| --- | --- | --- |\n| LangGraph | 每步结束，自动 | 没做完的那一步 |\n| AutoGen | 手动调 save_state | 上次手动保存的地方；没存就从头 |\n| CrewAI | Flow 的步骤结束 | Flow 的当前步；步里的 Crew 整组重跑 |\n\n已经在用 AutoGen 的话，每个回合后加一次保存能做到差不多的效果，代价是自己管状态文件。\n", "text/markdown");
  o.ev(adapter("S1", "solve"), "deliver", (i) => ({
    outcome: "answered", answer: i.answer,
    claims: [
      { text: "LangGraph 每个 super-step 结束自动写检查点，崩溃后从没做完的那一步重跑", refs: [i.e_lg, i.e_clone] },
      { text: "AutoGen 不自动落盘，不主动调 save_state 的话崩溃就从头开始", refs: [i.e_ag] },
      { text: "AutoGen 每步手动保存后，可以恢复到上一步", refs: [i.e_ag2] },
      { text: "CrewAI 的 @persist 只保存 Flow 级状态，Crew 里面的任务会整组重跑", refs: [i.e_cr] },
      { text: "三者里只有 LangGraph 支持回到任意历史检查点分叉", refs: [] },
      { text: "按团队约定，上线前要在 staging 跑全量测试，选型后的迁移脚本要能反向执行", refs: [i.kb_team] },
    ],
    self_check: [
      { what: "三个复现脚本各重跑一次，结果和第一次一样", result: "pass", refs: [i.e_lg, i.e_cr] },
      { what: "对照原话：三个框架、恢复粒度、选型建议都答到", result: "pass", refs: [], item: "c1" },
      { what: "“回到任意检查点分叉”只读了 LangGraph 的文档，另外两家没试", result: "fail", refs: [] },
    ],
    unverified: ["只测了 SQLite 后端；Postgres 和 Redis 的行为是按文档推的", "用的是各仓库今天的主分支，没测已发布的旧版本"],
    needs: [],
  }), "dlv");
  // 端点代理按请求记账：前四次模型调用各一条，第五条随会话收尾（release）记
  for (const [u, ti, tc, to] of [[230, 5200, 0, 610], [250, 5900, 4800, 520], [290, 6800, 5700, 660], [300, 7400, 6600, 700]] as const)
    o.ev(adapter("S1", "solve"), "cost", (i) => ({ task_id: i.S1, source: "proxy", model: "model-a", tokens_in: ti, tokens_cached: tc, tokens_out: to, usd_milli: u, wall_s: 8, price_table: "prices@1" }));
  o.release("S1", "solve", 300);
  // 复核（地图 Q34）：另起一个会话逐条核这次交付，只给读数，不改终态
  o.lease("V1", "verify", "dlv");
  o.exec("e_rr", "V1", "shell", "python repro/crash_test.py --fw langgraph", "step1 done\nstep2 killed (SIGKILL)\n--- restart, same thread_id ---\nresume -> next=('step2',)\nstep2 done · step3 done\n");
  o.ev(adapter("V1", "verify"), "review", (i) => ({
    delivery: i.dlv,
    claims: [
      { claim: 0, verdict: "supported", note: "重启后 next=('step2',)，确是从没做完的那一步接着跑", refs: [i.e_lg] },
      { claim: 1, verdict: "supported", note: "没保存时重启报 FileNotFoundError 并从头开始", refs: [i.e_ag] },
      { claim: 2, verdict: "supported", note: "加 --save-each-step 后从 step2 继续", refs: [i.e_ag2] },
      { claim: 3, verdict: "supported", note: "输出里 Crew 从 task 1/3 重跑", refs: [i.e_cr] },
      { claim: 4, verdict: "unclear", note: "没有引用；另外两家是否支持分叉没有执行记录", refs: [] },
      { claim: 5, verdict: "unsupported", note: "引用的是团队上线约定，与框架选型的恢复能力无关", refs: [] },
    ],
    reruns: [
      { check: 0, result: "pass", refs: [i.e_rr] },
      { check: 1, result: "not_rerun", note: "对照原话是读的，不是能重跑的命令", refs: [] },
    ],
    counterexamples: [],
    summary: "6 条主张里 4 条有执行输出直接支撑；“任意检查点分叉”没有依据，引用团队约定的一条与问题无关。",
  }));
  o.release("V1", "verify", 120);
  // demo-7：开放道，求解会话在跑（会话活动面板的示例）。图台按设计是空的，进度只在会话活动里。
  const r = new Builder("demo-7");
  const ask = "把仓库里的单元测试跑起来，找出最近一次提交让哪些测试变红了，给出原因。";
  r.input("statement", `${ask}\n`);
  r.open("示例题：找出变红的测试", ask, {
    goal: { statement: ask, accept: "open" },
    scope: [{ resource: "workspace", pattern: "", actions: ["read", "write"], risk: "r0" }],
    budget: { usd_milli: 2000, wall_s: 1800, verify_share: 0.2, bootstrap_share: 0.3 },
    judges: [], profile: { info: "complete", judge: "none", reversibility: "r0" },
  });
  r.lease("S1", "solve");
  r.exec("e_ls", "S1", "shell", "git log --oneline -3", "9c1d2e4 重构 parse_date\n71aa03b 加缓存\n5f2e9d0 初始化\n");
  r.exec("e_t0", "S1", "shell", "python -m pytest -q", "..F.F......\n2 failed, 9 passed\n", 1);
  // 端点代理按请求记账：一次模型调用一条 cost（与会话活动里的 turn 按序号对齐）
  for (const [u, w, ti, to, tc] of [[52, 6, 4200, 600, 0], [61, 7, 4700, 640, 3800], [58, 6, 5600, 690, 4500], [65, 7, 6500, 670, 5800]] as const)
    r.ev(adapter("S1", "solve"), "cost", (i) => ({ task_id: i.S1, source: "proxy", model: "model-a", tokens_in: ti, tokens_cached: tc, tokens_out: to, usd_milli: u, wall_s: w, price_table: "prices@1" }));
  // demo-8：开放道，部分完成（任务页排版的示例）。答案是一份长的 Markdown：多级标题、九列的清单表（含档位列）、
  // 带 sha256 的产物对照表、代码块、嵌套列表；交付里有“要你补的”。用来看长内容的滚动与表格、摘要值的排版。
  const w = new Builder("demo-8");
  const want = "梳理这个仓库里各处的重试与超时写法，列一份清单，标出值得统一的地方，并给出改造的先后顺序。";
  w.input("statement", `${want}\n`);
  w.open("示例题：梳理重试与超时的写法", want, {
    goal: { statement: want, accept: "open" },
    scope: [{ resource: "workspace", pattern: "", actions: ["read", "write"], risk: "r0" }],
    budget: { usd_milli: 3000, wall_s: 2400, verify_share: 0.2, bootstrap_share: 0.3 },
    judges: [], profile: { info: "complete", judge: "none", reversibility: "r0" },
    prefs: { model: "default" },
  });
  w.lease("S1", "solve");
  w.exec("e_grep", "S1", "shell", "rg -n 'retry|timeout|backoff' --type py -c | sort -t: -k2 -nr | head -8", "svc/client/http.py:41\nsvc/queue/consumer.py:27\nsvc/storage/blob.py:19\nsvc/jobs/runner.py:14\nsvc/notify/mail.py:9\nsvc/auth/token.py:6\nsvc/search/index.py:5\nsvc/export/csv.py:3\n");
  w.exec("e_test", "S1", "shell", "python -m pytest tests/resilience -q", "..............F...\n1 failed, 17 passed in 12.41s\n", 1);
  w.exec("e_sum", "S1", "shell", "sha256sum out/inventory.csv out/unify-plan.md out/retry_policy.py", "3fa2c1d09b7e4a6f8d2c5e1b0a9f7c3d4e6b8a1c2d5f7e9b0c3a6d8f1e4b9e4b  out/inventory.csv\n8c1e5a7d3b9f0246ace8135790bdf2468ace13579bdf02468ace13579bdf0a1c  out/unify-plan.md\nd4b7a9c2e6f1083b5d7f9a1c3e5b7d9f0a2c4e6b8d0f1a3c5e7b9d1f3a5c7e2f  out/retry_policy.py\n");
  w.authored("answer", "S1", [
    "仓库里有 9 处各写各的重试与超时，其中 4 处值得先统一：HTTP 客户端、队列消费、对象存储和任务执行器。它们占了全部重试代码的八成，而且彼此的退避算法不一致。",
    "",
    "# 清单",
    "",
    "| 编号 | 做法 | 主要位置 | 价值 | 置信 | 难度 | 风险 | 优先级 | 建议 |",
    "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    "| R-01 | 固定间隔重试 3 次，不区分错误类型 | `svc/client/http.py` | 高 | 高 | 低 | 低 | P0 | 换成带抖动的指数退避，只对 5xx 与连接错误重试 |",
    "| R-02 | 消费失败立即重新入队，没有上限 | `svc/queue/consumer.py` | 高 | 高 | 中 | 中 | P0 | 加最大次数与死信队列；重试间隔跟着次数涨 |",
    "| R-03 | 读超时写死 30 秒，写操作没有超时 | `svc/storage/blob.py` | 高 | 中 | 低 | 中 | P1 | 超时改成配置项，写操作补上超时 |",
    "| R-04 | 任务整体超时后不取消子进程 | `svc/jobs/runner.py` | 高 | 中 | 高 | 高 | P1 | 超时后先发终止信号，宽限期过了再强杀 |",
    "| R-05 | 发信失败只记日志，不重试 | `svc/notify/mail.py` | 中 | 高 | 低 | 低 | P2 | 接入统一策略即可 |",
    "| R-06 | 令牌刷新失败时无限循环 | `svc/auth/token.py` | 中 | 中 | 低 | 高 | P1 | 加上限；到上限后把错误抛给调用方 |",
    "| R-07 | 建索引时遇到 429 会原地等 60 秒 | `svc/search/index.py` | 低 | 中 | 低 | 低 | P3 | 读响应里的等待秒数，没有再退避 |",
    "| R-08 | 导出大文件没有总超时 | `svc/export/csv.py` | 低 | 低 | 中 | 低 | P3 | 先观察，暂不动 |",
    "| R-09 | 测试里用真实的 sleep 等重试 | `tests/resilience/` | 中 | 高 | 低 | 低 | P2 | 换成可注入的时钟，测试能快十倍 |",
    "",
    "## 各处的耗时",
    "",
    "| 位置 | 重试代码行数 | 最坏等待 | 占比 |",
    "| :--- | ---: | ---: | ---: |",
    "| HTTP 客户端 | 41 | 9 秒 | 33% |",
    "| 队列消费 | 27 | 无上限 | 22% |",
    "| 对象存储 | 19 | 30 秒 | 15% |",
    "| 任务执行器 | 14 | 无上限 | 11% |",
    "| 其余五处 | 23 | 60 秒 | 19% |",
    "",
    "# 统一方案",
    "",
    "建议抽出一个策略对象，各处只声明“重试几次、等多久、哪些错误值得重试”：",
    "",
    "```python",
    "@dataclass(frozen=True)",
    "class RetryPolicy:",
    "    attempts: int = 4",
    "    base_delay: float = 0.2      # 秒",
    "    max_delay: float = 8.0",
    "    jitter: float = 0.25         # 上下浮动 25%",
    "    retry_on: tuple[type[Exception], ...] = (ConnectionError, TimeoutError)",
    "```",
    "",
    "改造顺序：",
    "",
    "1. 先落 **R-01** 与 **R-02**：改动小、收益最大，而且互不依赖",
    "2. 再做 R-03、R-06：都只是加上限和配置项",
    "   - R-06 要先确认调用方能处理抛出来的错误",
    "   - R-03 的默认值沿用现在的 30 秒，不改行为",
    "3. 最后做 R-04：要动子进程管理，单独排期",
    "",
    "> 没有把握的地方：R-04 的宽限期该设多长，取决于最慢的任务要多久才能安全退出，这个我没有数据。",
    "",
    "# 产物对照",
    "",
    "| 产物 | 说明 | 大小 | sha256 |",
    "| --- | --- | --- | --- |",
    "| `out/inventory.csv` | 上面这份清单的原始数据 | 2.1 KB | 3fa2c1d09b7e4a6f8d2c5e1b0a9f7c3d4e6b8a1c2d5f7e9b0c3a6d8f1e4b9e4b |",
    "| `out/unify-plan.md` | 统一方案的完整说明 | 6.4 KB | 8c1e5a7d3b9f0246ace8135790bdf2468ace13579bdf02468ace13579bdf0a1c |",
    "| `out/retry_policy.py` | 策略对象的草稿实现 | 1.3 KB | d4b7a9c2e6f1083b5d7f9a1c3e5b7d9f0a2c4e6b8d0f1a3c5e7b9d1f3a5c7e2f |",
    "",
    "三份产物都在工作区的 `out/` 目录里；对照值是交付前用 `sha256sum` 算的。",
    "",
  ].join("\n"), "text/markdown");
  w.ev(adapter("S1", "solve"), "deliver", (i) => ({
    outcome: "partial", answer: i.answer,
    claims: [
      { text: "仓库里与重试、超时有关的代码集中在 8 个文件，HTTP 客户端最多", refs: [i.e_grep] },
      { text: "现有的韧性测试 18 条里有 1 条本来就是红的，与这次梳理无关", refs: [i.e_test] },
      { text: "三份产物的 sha256 与答案里的对照表一致", refs: [i.e_sum] },
      { text: "R-04 超时后子进程会留下来继续跑", refs: [] },
    ],
    self_check: [
      { what: "清单里的 9 处逐个打开文件核对过行号", result: "pass", refs: [i.e_grep] },
      { what: "产物写完后重新算了一遍 sha256", result: "pass", refs: [i.e_sum] },
      { what: "没有在真实流量下验证“占八成”这个说法，只按代码行数估的", result: "skipped", refs: [] },
    ],
    unverified: ["R-04 的子进程残留只读了代码，没有实际复现", "各处的“最坏等待”是按代码里的常数算的，没有测"],
    needs: ["R-04 的宽限期：最慢的任务从收到终止信号到安全退出，大概要多久？", "队列的死信处理：你们现在有没有死信队列，叫什么名字？", "能不能给一份最近一周的重试次数统计，我好核对“占八成”这个说法"],
  }), "dlv");
  for (const [u, ti, tc, to] of [[260, 6100, 0, 720], [310, 7400, 5600, 880], [340, 8800, 7000, 1400]] as const)
    w.ev(adapter("S1", "solve"), "cost", (i) => ({ task_id: i.S1, source: "proxy", model: "model-a", tokens_in: ti, tokens_cached: tc, tokens_out: to, usd_milli: u, wall_s: 9, price_table: "prices@1" }));
  w.release("S1", "solve", 280);
  return [{ pid: b.pid, steps: b.steps }, { pid: c.pid, steps: c.steps }, { pid: d.pid, steps: d.steps }, { pid: e.pid, steps: e.steps }, { pid: o.pid, steps: o.steps }, { pid: r.pid, steps: r.steps }, { pid: w.pid, steps: w.steps }];
}

/** 复核会话（地图 Q34）的示例活动：读交付里的依据、重跑一条自检、交回读数。 */
export function reviewActivityDemo(): Record<string, unknown>[] {
  return [
    { kind: "think", text: "逐条读主张引用的留档，看输出里有没有直接支撑；复现脚本能重跑的重跑一遍。" },
    { ...turn(4100, 180, 0) },
    { kind: "call", tool: "show", gist: "artifact 留档", id: "v1" },
    { kind: "result", id: "v1", ok: true, gist: "resume -> next=('step2',)", size: 96 },
    { kind: "call", tool: "exec", gist: "python repro/crash_test.py --fw langgraph", id: "v2" },
    { kind: "result", id: "v2", ok: true, gist: "exit 0", size: 120 },
    { ...turn(5200, 420, 3900) },
    { kind: "call", tool: "review", gist: "6 条主张，2 条自检", id: "v3" },
    { kind: "result", id: "v3", ok: true, gist: "{\"id\": \"rv_1\"}", size: 14 },
    { ...turn(5400, 60, 5000, "end_turn") },
  ];
}

/** 会话活动（GET /v1/leases/{id}/activity）的示例条目：假后端不跑 CLI，按会话种类与在途与否给一份固定的流水。
 *  含模型调用（turn：模型、token、停止原因）与思考（think）；t（本机毫秒）由假后端按留档登记的时刻补上。 */
const turn = (inp: number, out: number, cache: number, stop = "tool_use") => ({ kind: "turn", model: "model-a", in: inp, out, cache_read: cache, cache_write: cache ? 0 : inp - 400, stop });
export function activityDemo(live: boolean, pid = ""): Record<string, unknown>[] {
  if (pid === "demo-6") {
    return [
      { kind: "think", text: "要比较的是“崩溃后能恢复到哪一步”，光读文档不够，得每家写一个中途杀进程的复现，看重启后从哪接着跑。先记计划，再找各家的持久化接口。" },
      { ...turn(5200, 240, 0) },
      { kind: "say", text: "先在三个仓库里找持久化相关的接口，再各写一个中途杀进程的复现脚本。" },
      { kind: "call", tool: "Write", gist: "NOTES.md", id: "t1" },
      { kind: "result", id: "t1", ok: true, gist: "Wrote NOTES.md", size: 14 },
      { ...turn(5900, 90, 4800) },
      { kind: "call", tool: "exec", gist: "rg -l checkpoint langgraph/libs | head -2", id: "t2" },
      { kind: "result", id: "t2", ok: true, gist: "libs/checkpoint/langgraph/checkpoint/base/__init__.py", size: 118 },
      { kind: "think", text: "LangGraph 的检查点在 checkpoint/base 里，每个 super-step 结束都会写。AutoGen 没有对应的目录，可能要手动 save_state。先跑 AutoGen 的复现确认。" },
      { ...turn(6800, 130, 5700) },
      { kind: "call", tool: "exec", gist: "python repro/crash_test.py --fw autogen", id: "t3" },
      { kind: "result", id: "t3", ok: true, gist: "load_state: FileNotFoundError: state.json\n-> 从头开始", size: 96 },
      { ...turn(7400, 160, 6600) },
      { kind: "say", text: "AutoGen 不自动落盘。再试一次每步手动保存，看能不能恢复到上一步，然后交付。" },
      { kind: "call", tool: "deliver", gist: "answered", id: "t4" },
      { kind: "result", id: "t4", ok: true, gist: "{\"delivery\": \"d_1\"}", size: 19 },
      { ...turn(8100, 40, 7300, "end_turn") },
      { kind: "end", ok: true, turns: 9, gist: "success", ms: 41000 },
    ].map((x, i) => ({ n: i + 1, round: 1, ...x }));
  }
  const xs: Record<string, unknown>[] = [
    { kind: "think", text: "变红是相对上一次提交说的。先看最近几次提交改了什么，再整体跑一遍测试，拿到失败名单。" },
    { ...turn(4200, 180, 0) },
    { kind: "say", text: "先看看最近的提交，再把测试整体跑一遍，确认是哪几个变红。" },
    { kind: "call", tool: "exec", gist: "git log --oneline -3", id: "t1" },
    { kind: "result", id: "t1", ok: true, gist: "9c1d2e4 重构 parse_date\n71aa03b 加缓存\n5f2e9d0 初始化", size: 58 },
    { ...turn(4700, 70, 3800) },
    { kind: "call", tool: "exec", gist: "python -m pytest -q", id: "t2" },
    { kind: "result", id: "t2", ok: false, gist: "..F.F......\n2 failed, 9 passed", size: 1840 },
    { kind: "think", text: "两个失败都在 test_dates.py，断言里出现了带时区的日期字符串。最近一次提交正好重构了 parse_date，格式串很可能把时区丢了。把旧版本代回去重跑能直接确认因果。" },
    { ...turn(6100, 210, 4500) },
    { kind: "say", text: "两个失败都在 test_dates.py。最近一次提交重构了 parse_date，先对比这个函数在两次提交间的差别，再把旧版本代回去重跑确认。" },
    { kind: "call", tool: "Read", gist: "src/dates.py", id: "t3" },
    { kind: "result", id: "t3", ok: true, gist: "def parse_date(s):\n    return datetime.strptime(s, \"%Y-%m-%d\")", size: 612 },
    { ...turn(6900, 120, 5800) },
    { kind: "call", tool: "exec", gist: "git stash && git checkout 71aa03b -- src/dates.py && python -m pytest -q tests/test_dates.py", id: "t4" },
  ];
  if (!live) xs.push({ kind: "result", id: "t4", ok: true, gist: "4 passed", size: 8 }, { ...turn(7300, 60, 6700, "end_turn") }, { kind: "end", ok: true, turns: 6, gist: "success" });
  return xs.map((x, i) => ({ n: i + 1, round: 1, ...x }));
}
