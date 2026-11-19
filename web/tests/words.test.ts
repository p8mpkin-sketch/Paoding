// 阅读质量轮：用词统一与字体系统收敛的静态检查。
// 1) 界面文字只用一套词（见 SPEC“界面用词”）：旧词不得出现在 src 的字符串与 JSX 文本里。
// 2) 样式只用三族字体与六级字号令牌，不写裸 px 字号。
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { BANNED_WORDS } from "../src/ui/words";

const SRC = join(__dirname, "..", "src");
function files(dir: string, ext: RegExp): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? files(p, ext) : ext.test(n) ? [p] : [];
  });
}
/** 去掉注释（块注释与行注释），保留字符串。够用于本仓库的写法。 */
function stripComments(s: string): string {
  return s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`])\/\/.*$/gm, "$1");
}

describe("界面用词", () => {
  it("src 里的界面文字不出现旧词（导入时认的列名别名除外）", () => {
    const hits: string[] = [];
    for (const f of files(SRC, /\.tsx?$/)) {
      if (f.endsWith(join("ui", "words.ts"))) continue;
      stripComments(readFileSync(f, "utf8")).split("\n").forEach((line, i) => {
        if (/ALIASES|find\(/.test(line)) return;               // 读入别名：认旧列名，不显示
        for (const { old, re } of BANNED_WORDS) if (re.test(line)) hits.push(`${f.slice(SRC.length + 1)}:${i + 1} ${old}: ${line.trim().slice(0, 80)}`);
      });
    }
    expect(hits).toEqual([]);
  });
});

describe("字体系统", () => {
  const css = files(SRC, /\.css$/).map((f) => ({ f, s: stripComments(readFileSync(f, "utf8")) }));
  it("字号只用 --fs-* 令牌，不写裸 px（index.css 里定义令牌本身除外）", () => {
    const bad = css.flatMap(({ f, s }) => [...s.matchAll(/(?<![-\w])font(?:-size)?\s*:([^;{}]*)/g)]
      .filter((m) => /\d+(?:\.\d+)?px/.test(m[1].replace(/\/\S+/g, "").replace(/var\([^)]*\)/g, "")))
      .map((m) => `${f.slice(SRC.length + 1)}: ${m[0].trim()}`));
    expect(bad).toEqual([]);
  });
  it("字体族只用三个令牌：--serif（标题）、--sans（正文）、--mono（编号与金额）", () => {
    const bad = css.flatMap(({ f, s }) => [...s.matchAll(/font-family\s*:\s*([^;}]+)/g)]
      .filter((m) => !/^(var\(--(serif|sans|mono)\)|inherit)\s*$/.test(m[1].trim()) && !f.endsWith("index.css"))
      .map((m) => `${f.slice(SRC.length + 1)}: ${m[0]}`));
    expect(bad).toEqual([]);
  });
});
