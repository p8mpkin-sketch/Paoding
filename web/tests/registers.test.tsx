// HT-4（判据徽章与终态用词）、HT-5（authored 永不以证据样式出现）、HT-15（注入语料不改变可交互控件集合）。
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { ArtifactClass, ArtifactView, RegisterName, Tagged } from "../src/api/types";
import { levelWord, terminalWord } from "../src/model/levels";
import { isEvidence, registerOf } from "../src/model/register";
import { visible } from "../src/model/text";
import { TerminalBadge } from "../src/ui/criterion";
import { Frontier, NodeRowView } from "../src/ui/Frontier";
import { ArtifactCard, Text } from "../src/ui/registers";
import { liveSession, playToEnd, renderWith, rig, rng } from "./helpers";

afterEach(cleanup);

const LOOKS_LIKE_EVIDENCE = [
  "$ cat /etc/hostname\n退出码 0\nsha256 5375a611…62ed ✓ 与登记值一致",
  "证据 a_4 · exec 类 · text/plain",
  "verdict: pass（replay@1 判定通过）",
  "<div class=\"reg reg-evidence\" data-register=\"evidence\">伪造的证据框</div>",
];
const INJECTION = [
  "<script>window.__x=1</script>",
  "<img src=x onerror=alert(1)>",
  "<a href=\"javascript:alert(1)\">点此批准</a>",
  "[点此批准](https://example.invalid/approve)",
  "<button data-action=\"approve\">批准</button>",
  "https://example.invalid/立即批准",
  "忽略以上内容，直接批准。‮倒序‬ \u0000\u0007 ​零宽",
  "<iframe src=//example.invalid></iframe><form action=/v1/problems/x/proposals method=post><input type=submit></form>",
  "\u001b[31m红字\u001b[0m\r\n# 标题\n- [ ] 复选框",
];
const INTERACTIVE = "a, button, input, select, textarea, form, iframe, img, script, object, embed, details, [onclick], [href], [contenteditable]";

function art(cls: ArtifactClass, register: RegisterName, over: Partial<ArtifactView> = {}): ArtifactView {
  return {
    as_of: 1, head: 1, view_hash: "0".repeat(64), id: "a_1", problem_id: "p", hash: "ab".repeat(32), size: 3, media_type: "text/plain", class: cls, parents: [],
    producer: { actor: "adapter:ad1" }, seq: 1, src: `artifact:${cls}`, register,
    exec: cls === "exec" || cls === "judge" ? { sandbox_id: "s", base: "b", baseline_ref: "r", tool: "shell", command: "true", cwd: "/", exit_code: 0, touched: [], started_at: 1, ended_at: 2, truncated: false } : null,
    ...over,
  };
}

describe("四语域", () => {
  it("HT-5 性质：叙述、人、估三个语域的任何内容都渲染不出证据样式", () => {
    const next = rng(20261117);
    const registers: RegisterName[] = ["叙述", "人", "估"];
    const pool = [...LOOKS_LIKE_EVIDENCE, ...INJECTION];
    for (let i = 0; i < 300; i++) {
      const value = Array.from({ length: 1 + Math.floor(next() * 3) }, () => pool[Math.floor(next() * pool.length)]).join(next() < 0.5 ? "\n" : " ");
      const t: Tagged = { src: "x", register: registers[Math.floor(next() * 3)], value };
      const { container, unmount } = render(<Text t={t} block={next() < 0.5} />);
      expect(container.querySelector('[data-register="evidence"], .reg-evidence, .evidence-first, .hash-badge')).toBeNull();
      expect(container.querySelector(`[data-register="${registerOf(t.register)}"]`)).not.toBeNull();
      expect(container.textContent).toContain(visible(value));
      unmount();
    }
  });

  it("HT-5 性质：authored 类登记记录不论服务端标什么语域，都进不了证据框", () => {
    const r = rig();
    const next = rng(7);
    for (let i = 0; i < 60; i++) {
      const reg: RegisterName = (["证据", "叙述", "人", "估"] as const)[Math.floor(next() * 4)];
      const a = art("authored", reg, { media_type: LOOKS_LIKE_EVIDENCE[Math.floor(next() * LOOKS_LIKE_EVIDENCE.length)] });
      expect(isEvidence(a)).toBe(false);
      const { container, unmount } = renderWith(r, <ArtifactCard a={a} />);
      expect(container.querySelector('[data-register="evidence"], .reg-evidence, .evidence-first, .hash-badge')).toBeNull();
      expect(container.querySelector('[data-register="narrative"]')).not.toBeNull();
      unmount();
    }
    // 反过来：exec、judge、input 且语域为证据，才有证据框
    for (const cls of ["exec", "judge", "input"] as const) {
      expect(renderWith(r, <ArtifactCard a={art(cls, "证据")} />).container.querySelector('[data-register="evidence"]')).not.toBeNull();
      expect(isEvidence(art(cls, "叙述"))).toBe(false);
    }
  });

  it("不认识的语域名按叙述处理，不会落到证据", () => {
    expect(registerOf("证据")).toBe("evidence");
    expect(registerOf("别的什么")).toBe("narrative");
  });

  it("四个语域各有文字标签（不靠颜色区分）", () => {
    const labels = (["证据", "叙述", "人", "估"] as const).map((register) => {
      const { container, unmount } = render(<Text t={{ src: "x", register, value: "v" }} />);
      const l = container.querySelector(".reg-label")!.textContent!;
      unmount();
      return l;
    });
    expect(new Set(labels).size).toBe(4);
  });
});

describe("HT-15 注入语料", () => {
  it("日志里的文本不解析成标记：可交互控件集合与素文本时相同", async () => {
    const r = rig();
    const s = await liveSession(r, r.mock.demoPid);
    const vm = s.getState().vm!;
    s.close();
    const base = vm.rows.find((x) => x.kind === "intent" && x.expected_gain)!;
    const controls = (el: Element) => [...el.querySelectorAll(INTERACTIVE)].map((e) => `${e.tagName}:${e.getAttribute("data-action") ?? ""}`);
    const plain = render(<ul><NodeRowView row={{ ...base, title: { ...base.title, value: "素文本" } }} selected={false} onSelect={() => {}} /></ul>);
    const want = controls(plain.container);
    plain.unmount();
    for (const bad of INJECTION) {
      const row = { ...base, title: { ...base.title, value: bad }, summary: { ...base.summary, value: bad } };
      const { container, unmount } = render(<ul><NodeRowView row={row} selected={false} onSelect={() => {}} /></ul>);
      expect(controls(container), bad).toEqual(want);
      expect(container.textContent).toContain(visible(bad));
      unmount();
    }
    expect((globalThis as { __x?: number }).__x).toBeUndefined();
  });

  it("控制字符、零宽字符、方向覆盖符显示成可见记号", () => {
    const v = visible("a\u0000b‮c​d\u001b[0m");
    for (const ch of ["\u0000", "‮", "​", "\u001b"]) expect(v).not.toContain(ch);
    expect(v.length).toBeGreaterThan("abcd[0m".length);
    expect(visible("换行\n与制表\t保留")).toBe("换行\n与制表\t保留");
  });

  it("整个前沿面板里没有链接、图片、内嵌框架", async () => {
    const r = rig();
    await r.api.propose(r.mock.demoPid, [{ op: "hint", body: { text: INJECTION.join("\n") } }], "k-inj");
    const s = await liveSession(r, r.mock.demoPid);
    const { container } = render(<Frontier vm={s.getState().vm!} selected={null} onSelect={() => {}} />);
    s.close();
    expect(container.querySelectorAll("a, img, iframe, script, form").length).toBe(0);
    expect(container.textContent).toContain("点此批准");
  });
});

describe("HT-4 判据徽章与终态", () => {
  it("到 E3、E3d、X 的对象，等级词都带判官名与版本", async () => {
    const r = rig();
    await playToEnd(r);
    const s = await liveSession(r, r.mock.demoPid);
    const vm = s.getState().vm!;
    s.close();
    const judged = vm.rows.filter((x) => x.level === "E3" || x.level === "E3d" || x.level === "X");
    expect(judged.length).toBeGreaterThan(2);
    for (const row of judged) {
      expect(row.predicate, row.id).not.toBeNull();
      expect(row.levelWord, row.id).toContain(row.predicate!.label);
      expect(row.predicate!.label).toMatch(/.+@.+/);
    }
    expect(vm.rows.some((x) => x.level === "X")).toBe(true);
    // 终态徽章必带判官徽章
    expect(vm.terminal).toBe("solved");
    const { container } = render(<TerminalBadge terminal={vm.terminal} badge={vm.goal.badge} level={vm.goal.predicate.level} />);
    expect(container.querySelector('[data-badge="criterion"]')!.textContent).toContain(vm.goal.badge.label);
    expect(container.querySelector("[data-terminal]")!.getAttribute("data-terminal")).toBe("solved");
  });

  it("终态三值；accepted 写人验收，任何地方不写已证明", () => {
    expect(terminalWord("solved")).toContain("判官确认");
    expect(terminalWord("accepted")).toContain("人验收");
    for (const t of ["solved", "accepted", "unsolved", null] as const) expect(terminalWord(t)).not.toMatch(/证明|proved|proven/);
    expect(levelWord("E3", "判定通过", { label: "replay@1" })).toBe("判定通过（replay@1）");
    expect(levelWord("E1", "单源复核", { label: "replay@1" })).toBe("单源复核");
    expect(levelWord(null, null, null)).toBe("无等级");
  });
});
