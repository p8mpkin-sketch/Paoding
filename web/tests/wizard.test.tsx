// 向导六页、文字与链接材料、本机草稿、初始提示、克隆、导入（工作台设计 §1 模块二）。
import { cleanup, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { submitDraft } from "../src/app/submit";
import { sha256Hex } from "../src/model/hash";
import { draftsFromCsv, guessMapping, parseCsv, parseJsonBatch } from "../src/model/importer";
import { buildOpen, draftFromTemplate, problemsOf, STEPS, textMaterial } from "../src/model/wizard";
import { Import } from "../src/pages/Import";
import { Wizard } from "../src/pages/Wizard";
import { renderWith, rig, until } from "./helpers";

beforeEach(() => localStorage.clear());
afterEach(cleanup);

const base = () => ({
  ...draftFromTemplate(null), judge: "exact_match", usd: "2", wall_s: "600",
  scope: [{ resource: "net", pattern: "h:1", actions: "connect", risk: "r0" as const }],
});

describe("模型", () => {
  it("六页，中间四页是 Origin、判据、授权、预算", () => {
    expect(STEPS).toHaveLength(6);
    expect(problemsOf(base())).toHaveLength(6);
  });
  it("文字材料按 UTF-8 存，链接按 text/uri-list 存；填了文字的必填槽不算缺", () => {
    const t = textMaterial({ slot: "x", required: false, name: null, hash: null, size: 0, media_type: "", kind: "text", text: "题面" })!;
    expect(new TextDecoder().decode(t.bytes)).toBe("题面");
    expect(t.media_type).toMatch(/^text\/plain/);
    const l = textMaterial({ slot: "x", required: false, name: null, hash: null, size: 0, media_type: "", kind: "link", text: " a.example/x " })!;
    expect(l.media_type).toBe("text/uri-list");
    expect(new TextDecoder().decode(l.bytes)).toBe("a.example/x\r\n");
    const d = { ...base(), id: "t", title: "t", statement: "s", materials: [{ slot: "题面", required: true, name: null, hash: null, size: 0, media_type: "", kind: "text" as const, text: "abc" }] };
    expect(problemsOf(d)[1]).toEqual([]);
    expect(problemsOf({ ...d, materials: [{ ...d.materials[0], text: " " }] })[1].join()).toMatch(/必填/);
  });
  it("JSON 题集：没写的字段沿用模板草稿；初始提示不进开题批次", () => {
    const out = parseJsonBatch(JSON.stringify([{ id: "a", title: "A", statement: "s", materials: [{ text: "题面" }], hint: "先看源码" }]), base());
    if (out instanceof Error) throw out;
    expect(out[0]).toMatchObject({ id: "a", judge: "exact_match", usd: "2", hint: "先看源码" });
    expect(out[0].materials[0]).toMatchObject({ slot: "题面", kind: "text", text: "题面", required: true });
    expect(JSON.stringify(buildOpen(out[0]))).not.toMatch(/先看源码|profile/);
    expect(parseJsonBatch("{", base())).toBeInstanceOf(Error);
    expect(parseJsonBatch('{"x":1}', base())).toBeInstanceOf(Error);
  });
  it("CSV：引号、逗号、换行；按表头猜映射；未映射的取模板", () => {
    const rows = parseCsv('﻿id,name,question,answer\r\nq1,"第一, 题","多行\n题面","秘密"\r\n\r\nq2,第二题,题面二,x\n');
    expect(rows).toEqual([["id", "name", "question", "answer"], ["q1", "第一, 题", "多行\n题面", "秘密"], ["q2", "第二题", "题面二", "x"]]);
    const m = guessMapping(rows[0]);
    expect(m).toEqual({ id: 0, title: 1, statement: -1, material: 2 });
    const ds = draftsFromCsv(rows, m, { ...base(), statement: "缺省目标" });
    expect(ds.map((d) => [d.id, d.title, d.statement, d.materials[0].text])).toEqual([["q1", "第一, 题", "缺省目标", "多行\n题面"], ["q2", "第二题", "缺省目标", "题面二"]]);
    expect(JSON.stringify(ds)).not.toMatch(/秘密/); // 答案列没映射就不进草稿
  });
});

describe("提交路径", () => {
  it("文字材料先存成 Blob（哈希本机核对），再开题；初始提示作为第一条 Hint", async () => {
    const r = rig();
    const d = { ...base(), id: "t-hint", title: "带提示", statement: "s", hint: "先看登录页", materials: [{ slot: "题面", required: true, name: null, hash: null, size: 0, media_type: "", kind: "text" as const, text: "题面正文" }] };
    const res = await submitDraft(r.api, d);
    expect(res.hintSeq).toBeGreaterThan(res.seq);
    const st = await r.api.status("t-hint");
    expect(st.hints.map((h) => h.text.value)).toEqual(["先看登录页"]);
    const art = await r.api.artifact(st.problem.origin.statement_ref);
    expect(art.hash).toBe(await sha256Hex(new TextEncoder().encode("题面正文")));
    expect(art.class).toBe("input");
  });
});

describe("向导页", () => {
  it("草稿存本机，刷新后恢复到同一页；“重新开始”清掉", async () => {
    const r = rig();
    const first = renderWith(r, <Wizard />).container;
    await waitFor(() => expect(first.querySelector("[data-wizard]")).not.toBeNull());
    fireEvent.change(first.querySelector('[data-field="title"]')!, { target: { value: "留着" } });
    fireEvent.click(first.querySelector('[data-step-tab="3"]')!);
    cleanup();
    const again = renderWith(r, <Wizard />).container;
    await waitFor(() => expect(again.querySelector("[data-restored]")).not.toBeNull());
    expect(again.querySelector("[data-wizard]")?.getAttribute("data-step-index")).toBe("3");
    fireEvent.click(again.querySelector('[data-step-tab="0"]')!);
    expect((again.querySelector('[data-field="title"]') as HTMLInputElement).value).toBe("留着");
    fireEvent.click(again.querySelector('[data-action="restart"]')!);
    expect((again.querySelector('[data-field="title"]') as HTMLInputElement).value).toBe("");
  });

  it("克隆：预填 scope、判据、预算与材料哈希，id 留空；提交体仍无画像", async () => {
    const r = rig();
    const pid = r.mock.demoPid;
    const src = await r.api.status(pid);
    const { container } = renderWith(r, <Wizard from={pid} />);
    await waitFor(() => expect(container.querySelector(`[data-cloned-from="${pid}"]`)).not.toBeNull());
    expect((container.querySelector('[data-field="id"]') as HTMLInputElement).value).toBe("");
    fireEvent.change(container.querySelector('[data-field="id"]')!, { target: { value: "clone-1" } });
    fireEvent.click(container.querySelector('[data-step-tab="3"]')!);
    const batch = JSON.parse(container.querySelector("[data-problem-json]")!.textContent!) as { ops: { op: string; body: Record<string, unknown> }[] };
    const open = batch.ops.at(-1)!.body as { scope: unknown; goal: { check: { judge_id: string } } };
    expect(open.scope).toEqual(src.problem.scope);
    expect(open.goal.check.judge_id).toBe(src.goal.predicate.judge_id);
    expect(JSON.stringify(batch)).not.toMatch(/profile/);
    const first = await r.api.artifact(src.problem.origin.statement_ref);
    expect(batch.ops[0].body).toMatchObject({ class: "input", hash: first.hash });
  });
});

describe("导入页", () => {
  it("JSON 题集逐题开出，缺项的标出来不提交", async () => {
    const r = rig();
    const { container } = renderWith(r, <Import />);
    await waitFor(() => expect(container.querySelector('[data-field="import-template"] option[value="service-practice"]')).not.toBeNull());
    const items = [
      { id: "imp-1", title: "一", statement: "s", materials: [{ text: "题面一" }], judge: "exact_match", scope: [{ resource: "net", pattern: "h:1", actions: ["connect"], risk: "r0" }], budget: { usd_milli: 2000, wall_s: 600 } },
      { id: "", title: "缺 id" },
    ];
    const file = new File([JSON.stringify(items)], "set.json", { type: "application/json" });
    fireEvent.change(container.querySelector('[data-field="import-file"]')!, { target: { files: [file] } });
    await waitFor(() => expect(container.querySelectorAll("[data-import-row]")).toHaveLength(2));
    expect(container.querySelector('[data-import-row="1"]')?.getAttribute("data-state")).toBe("invalid");
    fireEvent.click(container.querySelector('[data-action="import-all"]')!);
    const row = () => container.querySelector('[data-import-row="imp-1"]');
    await until(() => ["done", "failed"].includes(row()?.getAttribute("data-state") ?? ""), "第一题有结果");
    expect(row()?.textContent).toMatch(/已创建/);
    expect(r.mock.pids()).toContain("imp-1");
    expect(r.mock.pids()).not.toContain("");
  });

  it("YAML 如实说暂不支持", async () => {
    const r = rig();
    const { container } = renderWith(r, <Import />);
    await waitFor(() => expect(container.querySelector('[data-field="import-file"]')).not.toBeNull());
    fireEvent.change(container.querySelector('[data-field="import-file"]')!, { target: { files: [new File(["a: 1"], "s.yaml")] } });
    await waitFor(() => expect(container.querySelector("[data-import-error]")?.textContent).toMatch(/YAML 暂不支持/));
  });
});
