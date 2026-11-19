// HT-1（零领域词）、HT-12（请求只到图服务 API、操作集合是 human 的子集、没有模型端点）、
// 以及 HMI §2 五条禁令里能静态查的那几条：不内嵌 reducer、不读本机时钟与随机数来算视图、不把日志文本当标记解析。
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";
import { createApi } from "../src/api/client";
import { HUMAN_OPS, ops } from "../src/api/ops";
import type { Op } from "../src/api/types";
import { rig } from "./helpers";

const ROOT = process.cwd();
function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}
const SRC = walk(join(ROOT, "src")).filter((f) => /\.(ts|tsx)$/.test(f));
const read = (f: string) => readFileSync(f, "utf8");
const rel = (f: string) => relative(ROOT, f).replaceAll("\\", "/");
/** 去掉注释再查（注释里可以提到被禁的东西）。 */
const code = (f: string) => read(f).replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "").replace(/([^:"'`])\/\/.*$/gm, "$1");
const offenders = (re: RegExp, files = SRC) => files.filter((f) => re.test(code(f))).map(rel);

describe("HT-1 领域词", () => {
  it("前端源码、假后端与页面里没有领域词", () => {
    const words = read(join(ROOT, "..", "ci", "domain-words.txt")).split("\n").map((w) => w.trim().toLowerCase()).filter((w) => w && !w.startsWith("#"));
    expect(words.length).toBeGreaterThan(5);
    const esc = (w: string) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(`(?<![a-z0-9_])(${words.map(esc).join("|")})(?![a-z0-9_])`, "i");
    const files = [...SRC, ...walk(join(ROOT, "mock")), join(ROOT, "index.html"), join(ROOT, "src", "styles.css")];
    const hits = files.flatMap((f) => read(f).split("\n").flatMap((line, i) => (re.test(line) ? [`${rel(f)}:${i + 1}: ${re.exec(line)![1]}`] : [])));
    expect(hits).toEqual([]);
  });
});

describe("HT-12 请求的去向", () => {
  it("只有 api/client.ts 与 api/stream.ts 发请求；没有别的出网手段", () => {
    expect(offenders(/\bfetch\s*\(/).sort()).toEqual(["src/api/client.ts", "src/api/stream.ts", "src/app/config.ts"]);
    expect(code(join(ROOT, "src/app/config.ts")).match(/fetch\s*\(/g)).toHaveLength(1); // 只是把全局 fetch 交给配置
    expect(offenders(/XMLHttpRequest|WebSocket|EventSource|sendBeacon|importScripts|\bimport\s*\(/)).toEqual([]);
  });

  it("请求的路径都在 /v1/ 之下，基址只来自本机配置", () => {
    const paths = [...(code(join(ROOT, "src/api/client.ts")) + code(join(ROOT, "src/api/stream.ts"))).matchAll(/[`"](\/[a-z0-9_/]*)/g)].map((m) => m[1]);
    expect(paths.length).toBeGreaterThan(10);
    for (const p of paths) expect(p.startsWith("/v1/"), p).toBe(true);
    expect(offenders(/https?:\/\//)).toEqual([]);
  });

  it("源码不引用假后端", () => {
    expect(offenders(/from\s+["'][^"']*mock/)).toEqual([]);
  });

  it("操作集合是规格操作表 human 一行的子集；别的操作在发出请求之前被拒", async () => {
    // 规格 3.1.9 操作表里 human 可提交的操作
    const SPEC_HUMAN = ["open_problem", "register_artifact", "hint", "approve", "profile_override", "abandon_intent", "close_problem", "add_intent", "extend", "budget_add", "pause", "resume", "rule", "accept", "judge_revoke", "intent_done",
      // 运行时扩权（runtime-grants §4，#93 起内核接受人的这两种）
      "grant_scope", "revoke_scope"];
    for (const o of HUMAN_OPS) expect(SPEC_HUMAN).toContain(o);
    const seen = { seq: 1, card_hash: "x" };
    const built: Op[] = [ops.registerInput("h", 1, "t"), ops.hintAdd("t"), ops.hintAdd("t", "f_1"), ops.hintClose("h_1"), ops.approve("i_1", seen), ops.deny("i_1", "r", seen), ops.abandonIntent("i_1"), ops.profileOverride("judge", "none", "r"), ops.closeProblem("r"), ops.extend(seen), ops.budgetAdd(1), ops.grantScope("r_1", seen), ops.grantScope("r_1", seen, ["r2"]), ops.denyScope("r_1", "r", seen), ops.revokeScope(1, "r")];
    for (const o of built) expect(HUMAN_OPS.has(o.op), o.op).toBe(true);
    expect(JSON.stringify(ops.closeProblem("r"))).not.toContain("terminal"); // 终态是派生量
    const r = rig();
    const before = r.fetch.calls.length;
    for (const op of ["add_fact", "judge_verdict", "cost", "lease", "request_judge"]) {
      await expect(createApi(r.cfg).propose("p", [{ op, body: {} } as unknown as Op], "k")).rejects.toThrow(/不是人可提交的操作/);
    }
    expect(r.fetch.calls.length).toBe(before);
  });
});

describe("HMI §2 禁令", () => {
  it("不内嵌 reducer：源码里不按事件种类推导图的状态", () => {
    // 认识事件种类的只有时间轴刻度（model/ticks.ts）；别处出现 add_fact、judge_verdict 这类写状态的事件名就是在复刻 reducer
    expect(offenders(/["'](add_fact|judge_verdict|request_judge|expire_lease|release)["']/).filter((f) => f !== "src/model/ticks.ts" && f !== "src/api/types.ts")).toEqual([]);
  });

  it("视图不读本机时钟与随机数", () => {
    const files = SRC.filter((f) => /src\/(model|ui|pages)\//.test(rel(f)));
    expect(offenders(/Date\.now\s*\(|new Date\s*\(\s*\)|Math\.random|performance\.now/, files)).toEqual([]);
  });

  it("不把日志文本当标记解析", () => {
    expect(offenders(/dangerouslySetInnerHTML|innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\s*\(|new Function/)).toEqual([]);
    expect(offenders(/<a\s[^>]*href=\{(?!hrefOf)/)).toEqual([]); // 唯一的链接是站内路由
  });

  it("构建产物带内容安全策略，只连同源", () => {
    const cfg = read(join(ROOT, "vite.config.ts"));
    expect(cfg).toContain("connect-src 'self'");
    expect(cfg).toContain("frame-src 'none'");
    expect(cfg).toContain("form-action 'none'");
  });
});
