// 答案正文的排版（任务页“结果”一栏）：切块（model/prose.ts）与组件（ui/Prose.tsx）。
// 边界：表格里的竖线与缺格、紧跟段落的列表与表格、没闭合的代码块、摘要值的认法、控制字符、不产出标记与链接。
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cells, hashOf, inline, levelOf, LIST_DEPTH, parse, plainOf, tsv, type ListBlock, type TableBlock } from "../src/model/prose";
import { Prose } from "../src/ui/Prose";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const SHA = "3fa2c1d09b7e4a6f8d2c5e1b0a9f7c3d4e6b8a1c2d5f7e9b0c3a6d8f1e4b9e4b";
const tableOf = (md: string) => parse(md).find((b) => b.k === "table") as TableBlock;

describe("切块（纯函数）", () => {
  it("标题、段落、列表、表格、代码、引文、分隔线各成一块；标题最深排到三级", () => {
    const b = parse("结论一句。\n\n# 一\n## 二\n##### 五\n\n- a\n- b\n\n| x | y |\n| - | - |\n| 1 | 2 |\n\n```py\nprint(1)\n```\n\n> 引一句\n\n---\n尾段");
    expect(b.map((x) => x.k)).toEqual(["p", "h", "h", "h", "list", "table", "code", "quote", "hr", "p"]);
    expect(b.filter((x) => x.k === "h").map((x) => (x.k === "h" ? x.level : 0))).toEqual([1, 2, 3]);
    expect(b[6]).toMatchObject({ k: "code", lang: "py", text: "print(1)" });
  });

  it("列表与表格紧跟在段落后面（中间没有空行）也认得；段落不会把它们吞掉", () => {
    const b = parse("改造顺序：\n1. 先做甲\n2. 再做乙\n说明：\n| a | b |\n|---|---|\n| 1 | 2 |");
    expect(b.map((x) => x.k)).toEqual(["p", "list", "table"]);
    expect(b[1]).toMatchObject({ ordered: true, start: 1 });
    // 列表项后面不是列表的行算续行，并进上一项
    expect(plainOf((b[1] as Extract<typeof b[number], { k: "list" }>).items[1].inl)).toBe("再做乙\n说明：");
  });

  it("嵌套列表按缩进成树；有序列表记住起始号；空行隔开的同类项仍是一个列表", () => {
    const b = parse("3. 甲\n   - 子一\n   - 子二\n4. 乙\n\n5. 丙");
    expect(b).toHaveLength(1);
    const l = b[0] as Extract<typeof b[number], { k: "list" }>;
    expect(l).toMatchObject({ ordered: true, start: 3 });
    expect(l.items).toHaveLength(3);
    expect(l.items[0].children).toMatchObject({ ordered: false });
    expect(l.items[0].children!.items.map((i) => plainOf(i.inl))).toEqual(["子一", "子二"]);
  });

  it("没闭合的代码块一直收到文末，不丢字；波浪线围栏同样认", () => {
    expect(parse("```\nA\nB")).toEqual([{ k: "code", lang: "", text: "A\nB" }]);
    expect(parse("~~~sh\nls\n~~~\n后文").map((x) => x.k)).toEqual(["code", "p"]);
  });

  it("只有一行竖线的不算表格；空串与全空白没有块", () => {
    expect(parse("| 只是一行 |").map((x) => x.k)).toEqual(["p"]);
    expect(parse("")).toEqual([]);
    expect(parse(" \n\n \r\n")).toEqual([]);
  });
});

/** 列表树的最深层数与全部项的文字（不递归地走，免得测试自己先爆栈）。 */
function walk(root: ListBlock): { depth: number; texts: string[] } {
  const texts: string[] = [];
  let depth = 0;
  const todo: [ListBlock, number][] = [[root, 1]];
  while (todo.length) {
    const [b, d] = todo.pop()!;
    depth = Math.max(depth, d);
    for (let i = b.items.length - 1; i >= 0; i--) if (b.items[i].children) todo.push([b.items[i].children!, d + 1]);
    for (const it of b.items) texts.push(plainOf(it.inl));
  }
  return { depth, texts };
}

describe("畸形的列表（cz 2026-11-24 审出的白屏：缩进每行多一格，上万层）", () => {
  it("嵌套有上限：超过的缩进并进最深一层当同级项，一个字不丢；回到浅缩进时照常回到外层", () => {
    const md = Array.from({ length: 40 }, (_, i) => `${" ".repeat(i)}- 第 ${i} 项`).join("\n") + "\n- 回到最外层";
    const l = parse(md)[0] as ListBlock;
    const w = walk(l);
    expect(w.depth).toBe(LIST_DEPTH);
    expect(w.texts).toHaveLength(41);
    expect(new Set(w.texts)).toEqual(new Set([...Array.from({ length: 40 }, (_, i) => `第 ${i} 项`), "回到最外层"]));
    expect(l.items.map((i) => plainOf(i.inl))).toEqual(["第 0 项", "回到最外层"]);
    // 最深一层收下了所有更深的项：32 层用掉 32 项，其余 8 项是它的同级
    let deepest = l;
    while (deepest.items[0].children) deepest = deepest.items[0].children;
    expect(deepest.items).toHaveLength(40 - LIST_DEPTH + 1);
  });

  it("两万行阶梯缩进：切得出、排得出，不爆栈；两万项的字都在页面上", () => {
    const N = 20_000;
    const text = Array.from({ length: N }, (_, i) => `${" ".repeat(i)}- 第 ${i} 项`).join("\n");
    const blocks = parse(text);
    expect(blocks).toHaveLength(1);
    const w = walk(blocks[0] as ListBlock);
    expect(w.depth).toBe(LIST_DEPTH);
    expect(w.texts).toHaveLength(N);
    const { container } = render(<Prose text={text} />);
    const items = container.querySelectorAll("li");
    expect(items).toHaveLength(N);
    const seen = new Set<string>();
    for (const li of items) seen.add(li.firstElementChild!.textContent!);
    expect(seen.size).toBe(N);
    for (const i of [0, 1, 31, 32, 9_999, N - 1]) expect(seen.has(`第 ${i} 项`), String(i)).toBe(true);
    expect(container.querySelectorAll("ul").length).toBe(LIST_DEPTH);
  }, 120_000);

  it("同样的阶梯用在有序列表、引文与表格行上也不爆栈", () => {
    const N = 12_000;
    expect(walk(parse(Array.from({ length: N }, (_, i) => `${" ".repeat(i)}${i + 1}. 项`).join("\n"))[0] as ListBlock).texts).toHaveLength(N);
    expect(parse(Array.from({ length: N }, () => "> 引").join("\n"))).toHaveLength(1);
    expect((parse(`| a |\n|---|\n${Array.from({ length: N }, (_, i) => `| ${i} |`).join("\n")}`)[0] as TableBlock).rows).toHaveLength(N);
    expect(parse(Array.from({ length: N }, (_, i) => `${"#".repeat((i % 6) + 1)} 标题`).join("\n"))).toHaveLength(N);
  }, 60_000);
});

describe("缩进不规整的列表（cz 2026-11-24 第二轮审出的丢项：后来的浅缩进子项把已有的子列表盖掉）", () => {
  const all = (md: string) => {
    const b = parse(md);
    expect(b).toHaveLength(1);
    return walk(b[0] as ListBlock).texts;
  };

  it("先 4 格后 2 格的两个子项都在：四项一项不少，后一个并进已有的子列表", () => {
    const md = "- a\n    - a1\n  - a2\n- b";
    expect(all(md).sort()).toEqual(["a", "a1", "a2", "b"]);
    const l = parse(md)[0] as ListBlock;
    expect(l.items.map((i) => plainOf(i.inl))).toEqual(["a", "b"]);
    expect(l.items[0].children!.items.map((i) => plainOf(i.inl))).toEqual(["a1", "a2"]);
    const { container } = render(<Prose text={md} />);
    expect([...container.querySelectorAll("li")].map((li) => li.firstElementChild!.textContent)).toEqual(["a", "a1", "a2", "b"]);
  });

  it("有序列表 6 格、4 格、3 格逐步变浅：五项都在，原文次序不变", () => {
    const md = "1. 一\n      1. 一甲\n    2. 一乙\n   3. 一丙\n2. 二";
    expect(all(md).sort()).toEqual(["一", "一丙", "一乙", "一甲", "二"].sort());
    const l = parse(md)[0] as ListBlock;
    expect(l.items.map((i) => plainOf(i.inl))).toEqual(["一", "二"]);
    expect(l.items[0].children!.items.map((i) => plainOf(i.inl))).toEqual(["一甲", "一乙", "一丙"]);
    const { container } = render(<Prose text={md} />);
    expect([...container.querySelectorAll("li")].map((li) => li.firstElementChild!.textContent)).toEqual(["一", "一甲", "一乙", "一丙", "二"]);
  });

  it("变浅以后再变深：接在并进去的那一项下面，不丢", () => {
    expect(all("- a\n      - a1\n   - a2\n     - a2x\n      - a2y\n  - a3\n- b").sort()).toEqual(["a", "a1", "a2", "a2x", "a2y", "a3", "b"]);
  });

  it("性质：随机缩进的列表，切出的项数等于原文行数，每一行的字都在，文档次序不变", () => {
    // 固定种子的伪随机（mulberry32），失败时能照种子重放
    const rng = (seed: number) => () => {
      seed = (seed + 0x6d2b79f5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    const order = (root: ListBlock) => {
      // 先序（文档次序），不递归
      const out: string[] = [];
      const todo: ListBlock["items"] = [...root.items].reverse();
      while (todo.length) {
        const it = todo.pop()!;
        out.push(plainOf(it.inl));
        if (it.children) for (let i = it.children.items.length - 1; i >= 0; i--) todo.push(it.children.items[i]);
      }
      return out;
    };
    for (let seed = 1; seed <= 600; seed++) {
      const r = rng(seed);
      const n = 2 + Math.floor(r() * 40);
      const maxIndent = [3, 8, 20, 90][seed % 4];
      const want: string[] = [];
      const lines = Array.from({ length: n }, (_, i) => {
        const indent = i === 0 && seed % 3 ? 0 : Math.floor(r() * (maxIndent + 1));
        const pad = seed % 7 === 0 && indent >= 4 ? "\t".repeat(Math.floor(indent / 4)) + " ".repeat(indent % 4) : " ".repeat(indent);
        const mark = seed % 5 === 0 ? ["-", "*", "+", `${i + 1}.`, `${i + 1})`][Math.floor(r() * 5)] : seed % 2 ? "-" : `${i + 1}.`;
        want.push(`第 ${i} 行`);
        return `${pad}${mark} 第 ${i} 行`;
      });
      const md = lines.join("\n");
      const blocks = parse(md);
      expect(blocks.map((b) => b.k), `种子 ${seed}\n${md}`).toEqual(["list"]);
      expect(walk(blocks[0] as ListBlock).texts, `种子 ${seed}\n${md}`).toHaveLength(n);
      expect(order(blocks[0] as ListBlock), `种子 ${seed}\n${md}`).toEqual(want);
    }
  });

  it("性质：随机缩进的列表排出来，li 的个数等于原文行数", () => {
    let seed = 20261124;
    const r = () => { seed = (Math.imul(seed, 1664525) + 1013904223) | 0; return (seed >>> 0) / 4294967296; };
    for (let k = 0; k < 40; k++) {
      const n = 2 + Math.floor(r() * 30);
      const md = Array.from({ length: n }, (_, i) => `${" ".repeat(Math.floor(r() * 12))}- 第 ${i} 行`).join("\n");
      const { container, unmount } = render(<Prose text={md} />);
      expect([...container.querySelectorAll("li")].map((li) => li.firstElementChild!.textContent), md).toEqual(Array.from({ length: n }, (_, i) => `第 ${i} 行`));
      unmount();
    }
  });
});

describe("表格", () => {
  it("格里的竖线：反引号里的与转义的不算分隔", () => {
    expect(cells("| `a | b` | c \\| d | e |")).toEqual(["`a | b`", "c | d", "e"]);
    expect(cells("x | y")).toEqual(["x", "y"]);
  });

  it("缺格补空、多格并进最后一列；分隔行给出对齐；没有分隔行时第一行仍是表头", () => {
    const t = tableOf("| a | b | c |\n| :-- | --: | :-: |\n| 1 |\n| 1 | 2 | 3 | 4 |");
    expect(t.align).toEqual(["left", "right", "center"]);
    expect(t.rows.map((r) => r.map(plainOf))).toEqual([["1", "", ""], ["1", "2", "3 | 4"]]);
    const u = tableOf("| a | b |\n| 1 | 2 |");
    expect(u.head.map(plainOf)).toEqual(["a", "b"]);
    expect(u.rows).toHaveLength(1);
    expect(u.align).toEqual([null, null]);
  });

  it("列的种类由整列内容看出：首列短的是名字，数（含单位、百分号）是数，档位词是档位，摘要值是摘要，其余是文字", () => {
    const t = tableOf(`| 编号 | 做法 | 行数 | 占比 | 风险 | 有无 | sha256 |\n|---|---|---|---|---|---|---|\n| R-01 | 固定间隔重试三次，不区分错误类型 | 41 | 33% | 高 | 有 | ${SHA} |\n| R-02 | 失败立即重新入队 | 1,027 | 2.5% | 中 | 无 | \`${SHA}\` |`);
    expect(t.kinds).toEqual(["key", "text", "num", "num", "tag", "tag", "hash"]);
    // “有 / 有 / 有”这种没有一个档位词的短列不当档位；首列很长时不当名字
    expect(tableOf("| 名 | 备注 |\n|---|---|\n| 甲 | 有 |\n| 乙 | 有 |").kinds).toEqual(["key", "text"]);
    expect(tableOf("| 说明 | x |\n|---|---|\n| 这是一段超过十六个字的很长很长很长的说明文字 | 1 |").kinds[0]).toBe("text");
    // 全空的列是文字；混了一个非数的不算数
    expect(tableOf("| a | b | c |\n|---|---|---|\n| k |  | 3 |\n| k |  | 无上限 |").kinds).toEqual(["key", "text", "text"]);
  });

  it("档位词分三级，认不得的是 null；整表抄成制表符分隔的文本", () => {
    expect(["高", "P0", "High", "中", "p1", "低", "P3", "也许"].map(levelOf)).toEqual(["hi", "hi", "hi", "mid", "mid", "lo", "lo", null]);
    expect(tsv(tableOf("| a | b |\n|---|---|\n| `x` | **y** |\n| 1 | 2 |"))).toBe("a\tb\nx\ty\n1\t2");
  });
});

describe("行内", () => {
  it("代码、加粗、摘要值各成片段；其余原样（星号、下划线、网址都不动）", () => {
    expect(inline("用 `rg -n` 找，**重点**在 a_b_c 与 2*3*4，见 https://example.test/x")).toEqual([
      { k: "text", v: "用 " }, { k: "code", v: "rg -n" }, { k: "text", v: " 找，" }, { k: "strong", v: "重点" }, { k: "text", v: "在 a_b_c 与 2*3*4，见 https://example.test/x" },
    ]);
  });

  it("摘要值：32/40/56/64 位十六进制，可带算法前缀，反引号里的也认；长度不对、纯数字、嵌在更长的词里都不认", () => {
    expect(hashOf(SHA)).toBe(SHA);
    expect(hashOf(`sha256:${SHA}`)).toBe(SHA);
    expect(hashOf(SHA.slice(0, 40))).toBe(SHA.slice(0, 40));
    expect(hashOf(SHA.slice(0, 39))).toBeNull();
    expect(hashOf("1".repeat(64))).toBeNull();
    expect(inline(`值是 ${SHA}。`).map((x) => x.k)).toEqual(["text", "hash", "text"]);
    expect(inline(`\`sha256:${SHA}\``)).toEqual([{ k: "hash", v: `sha256:${SHA}` }]);
    expect(inline(`x${SHA}y`).map((x) => x.k)).toEqual(["text"]);
    expect(inline(`${SHA}${SHA}`).map((x) => x.k)).toEqual(["text"]);
  });
});

describe("排版组件", () => {
  it("表格是带表头条的组件：行列数、可聚焦的滚动区、表头与行头的 scope；六列起算宽表", () => {
    const md = "| 编号 | 做法 | 价值 | 置信 | 难度 | 风险 |\n|---|---|---|---|---|---|\n| R-01 | 固定间隔 | 高 | 中 | 低 |  |";
    const { container } = render(<Prose text={md} />);
    const t = container.querySelector("[data-prose-table]")!;
    expect(t.getAttribute("data-wide")).toBe("true");
    expect(t.querySelector("figcaption")!.textContent).toContain("1 行 · 6 列");
    const region = t.querySelector('[role="region"]')!;
    expect(region.getAttribute("tabindex")).toBe("0");
    expect(region.getAttribute("aria-label")).toContain("编号、做法、价值");
    expect(t.querySelectorAll('thead th[scope="col"]')).toHaveLength(6);
    expect(t.querySelector('tbody th[scope="row"]')!.textContent).toBe("R-01");
    expect([...t.querySelectorAll(".pr-tag")].map((e) => e.className)).toEqual(["pr-tag pr-lv-hi", "pr-tag pr-lv-mid", "pr-tag pr-lv-lo"]);
    expect(t.querySelector(".pr-nil")!.getAttribute("aria-label")).toBe("空");       // 空格有说法，不是一片空白
    expect(render(<Prose text={"| a | b |\n|---|---|\n| 1 | 2 |"} />).container.querySelector("[data-prose-table]")!.getAttribute("data-wide")).toBe("false");
  });

  it("摘要值收成短的一截，点开看完整的；复制的是完整的值，成功后说“已复制”", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    const { container } = render(<Prose text={`对照值 sha256:${SHA} 已核对`} />);
    const chip = container.querySelector("[data-hash]")!;
    expect(chip.getAttribute("data-hash")).toBe(SHA);
    expect(chip.querySelector(".pr-hash-alg")!.textContent).toBe("sha256");
    const v = chip.querySelector<HTMLElement>(".pr-hash-v")!;
    const shown = () => chip.querySelector(".pr-hash-t")!.textContent;
    expect(shown()).toBe("3fa2c1d0…9e4b");
    expect(v.textContent).toBe("3fa2c1d0…9e4b（摘要值，点开看完整的）");     // 按钮的名字以看得见的值开头
    expect(v.getAttribute("aria-label")).toBeNull();
    expect(v.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(v);
    expect(v.getAttribute("aria-expanded")).toBe("true");
    expect(shown()).toBe(SHA);
    fireEvent.click(chip.querySelector('[data-action="copy"]')!);
    expect(writeText).toHaveBeenCalledWith(SHA);
    await waitFor(() => expect(chip.querySelector('[role="status"]')!.textContent).toBe("已复制"));
  });

  it("剪贴板不可用或被拒时说出来，不装作成功", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: undefined });
    const a = render(<Prose text={"```\nx\n```"} />);
    fireEvent.click(a.container.querySelector('[data-action="copy"]')!);
    expect(a.container.querySelector('[data-action="copy"]')!.getAttribute("data-copied")).toBe("fail");
    expect(a.container.querySelector('[role="status"]')!.textContent).toContain("复制不了");
    expect(a.container.querySelector('[data-action="copy"]')!.getAttribute("aria-label")).toBe("复制不了：复制这段代码");
    cleanup();
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: () => Promise.reject(new Error("denied")) } });
    const b = render(<Prose text={"```\nx\n```"} />);
    fireEvent.click(b.container.querySelector('[data-action="copy"]')!);
    await waitFor(() => expect(b.container.querySelector('[data-action="copy"]')!.getAttribute("data-copied")).toBe("fail"));
  });

  it("整表复制给出制表符分隔的文本", () => {
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    const { container } = render(<Prose text={"| a | b |\n|---|---|\n| 1 | 2 |"} />);
    fireEvent.click(container.querySelector('figcaption [data-action="copy"]')!);
    expect(writeText).toHaveBeenCalledWith("a\tb\n1\t2");
  });

  it("内容只当纯文本：不产出标记、不把网址变成链接；控制字符与双向控制符显出来", () => {
    const { container } = render(<Prose text={'<img src=x onerror=alert(1)> [点我](https://example.test) <script>1</script>\n\n| a |\n|---|\n| <b>粗</b>‮gnp.exe |'} />);
    expect(container.querySelectorAll("img, script, a, b")).toHaveLength(0);
    expect(container.textContent).toContain("<img src=x onerror=alert(1)>");
    expect(container.textContent).toContain("https://example.test");
    expect(container.querySelector("td, tbody th")!.textContent).toContain("\\u{202E}");
  });

  it("第一块是段落且后面还有内容时当作结论排大一号；只有一段时不放大；空答案有说法", () => {
    expect(render(<Prose text={"结论。\n\n细节。"} />).container.querySelectorAll(".pr-lead")).toHaveLength(1);
    expect(render(<Prose text={"只有一段。"} />).container.querySelectorAll(".pr-lead")).toHaveLength(0);
    expect(render(<Prose text={"# 标题在前\n\n段落"} />).container.querySelectorAll(".pr-lead")).toHaveLength(0);
    expect(render(<Prose text={"  \n"} />).container.textContent).toContain("答案是空的");
  });

  it("标题从三级排起（页面里答案已在二级标题之下）；有序列表带起始号；代码块可聚焦、可复制", () => {
    const { container } = render(<Prose text={"# 一\n## 二\n### 三\n\n3. 甲\n4. 乙\n\n```sh\nls -la\n```"} />);
    expect([...container.querySelectorAll(".pr-h")].map((h) => h.tagName)).toEqual(["H3", "H4", "H5"]);
    expect(container.querySelector("ol")!.getAttribute("start")).toBe("3");
    const pre = container.querySelector("[data-prose-code] pre")!;
    expect(pre.getAttribute("tabindex")).toBe("0");
    expect(pre.textContent).toBe("ls -la");
    expect(container.querySelector("[data-prose-code] .k-mono")!.textContent).toBe("sh");
  });
});
