// 模型页（前端重新设计 v5 第二期）：档案表、测试连接、测通才能存、默认分配即改即存、在用的档案删不掉、只读模式。
import { cleanup, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ModelsPage, probeSig } from "../src/pages/Models";
import { renderWith, rig } from "./helpers";

afterEach(cleanup);

const $ = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel);
const field = (k: string) => $<HTMLInputElement>(`[data-model-sheet] [data-field="model.${k}"]`)!;
const type = (k: string, v: string) => fireEvent.change(field(k), { target: { value: v } });
const btn = (a: string) => $<HTMLButtonElement>(`[data-action="${a}"]`)!;

async function page(token?: string | null) {
  const r = token === undefined ? rig() : rig(token);
  const out = renderWith(r, <ModelsPage />);
  await waitFor(() => expect($('[data-profile="default"]')).not.toBeNull());
  return { r, ...out };
}

describe("模型页", () => {
  it("测试结果的签名只看地址、ID、密钥槽与格式（缺省即 anthropic）", () => {
    const p = { endpoint: " https://a.test ", model: "m", key_slot: "default" };
    expect(probeSig(p)).toBe(probeSig({ ...p, endpoint: "https://a.test" }));
    expect(probeSig(p)).not.toBe(probeSig({ ...p, model: "n" }));
    expect(probeSig(p)).toBe(probeSig({ ...p, format: "anthropic" }));
    expect(probeSig(p)).not.toBe(probeSig({ ...p, format: "openai" }));
  });

  it("OpenAI 兼容：选了格式要写地址；按这个格式测；存进设置带 format，表里写 OpenAI 兼容", async () => {
    const { r } = await page();
    fireEvent.click(btn("add-model"));
    await waitFor(() => expect($("[data-model-sheet]")).not.toBeNull());
    type("name", "兼容"); type("model", "model-a");
    fireEvent.click($('[data-field="model.format"] [data-format="openai"]')!);
    expect($('[data-field="model.format"] [data-format="openai"]')!.getAttribute("aria-checked")).toBe("true");
    expect($("[data-model-sheet] .md-issues")!.textContent).toContain("OpenAI 格式要写接口地址");
    expect(btn("probe-model").disabled).toBe(true);
    type("endpoint", "https://compat.test/v1");
    fireEvent.click(btn("probe-model"));
    await waitFor(() => expect(btn("save-model").disabled).toBe(false));
    const call = r.fetch.calls.filter((c) => c.url === "/v1/models/test").at(-1)!;
    expect(JSON.parse(String(call.body)).profile.format).toBe("openai");
    fireEvent.click(btn("save-model"));
    await waitFor(() => expect($('[data-profile="兼容"] [data-format]')?.getAttribute("data-format")).toBe("openai"));
    expect($('[data-profile="兼容"]')!.textContent).toContain("OpenAI 兼容");
    const s = (await r.api.settings()).settings;
    expect(s.models.profiles.at(-1)).toMatchObject({ name: "兼容", format: "openai" });
    expect(s.models.profiles[0]).not.toHaveProperty("format"); // 旧档案不写 format，摘要不变
  });

  it("一张表列出全部档案；测试一行，连接一栏变“正常”并给延迟", async () => {
    const { r } = await page();
    expect([...document.querySelectorAll("[data-profile]")].map((x) => x.getAttribute("data-profile"))).toEqual(["default", "light"]);
    expect($('[data-profile="default"]')!.textContent).toContain("main-1");
    expect($('[data-profile="default"] [data-probe]')!.getAttribute("data-probe")).toBe("none");
    fireEvent.click($('[data-profile="light"] [data-action="test-model"]')!);
    await waitFor(() => expect($('[data-profile="light"] [data-probe]')!.getAttribute("data-probe")).toBe("ok"));
    expect($('[data-profile="light"] [data-probe]')!.textContent).toMatch(/正常\d+ ms/);
    const calls = r.fetch.calls.filter((c) => c.url === "/v1/models/test");
    expect(calls).toHaveLength(1);
    expect(JSON.parse(String(calls[0].body))).toEqual({ profile: { endpoint: "", model: "light-1", key_slot: "default", format: "anthropic" } });
  });

  it("添加：没测通不能存；测通后改了模型 ID 要重测；存了表里多一行", async () => {
    const { r } = await page();
    fireEvent.click(btn("add-model"));
    await waitFor(() => expect($("[data-model-sheet]")).not.toBeNull());
    type("name", "备用"); type("model", "bad-1");
    expect(btn("save-model").disabled).toBe(true);
    fireEvent.click(btn("probe-model"));
    await waitFor(() => expect($("[data-probe-result]")?.getAttribute("data-probe-result")).toBe("not_found"));
    expect(btn("save-model").disabled).toBe(true);
    type("model", "spare-1");
    fireEvent.click(btn("probe-model"));
    await waitFor(() => expect($("[data-probe-result]")?.getAttribute("data-probe-result")).toBe("ok"));
    expect(btn("save-model").disabled).toBe(false);
    type("model", "spare-2"); // 改了就不算测过
    expect(btn("save-model").disabled).toBe(true);
    fireEvent.click(btn("probe-model"));
    await waitFor(() => expect(btn("save-model").disabled).toBe(false));
    fireEvent.click(btn("save-model"));
    await waitFor(() => expect($("[data-model-sheet]")).toBeNull());
    await waitFor(() => expect($('[data-profile="备用"]')).not.toBeNull());
    const s = (await r.api.settings()).settings;
    expect(s.models.profiles.at(-1)).toMatchObject({ name: "备用", model: "spare-2", tier: "mid", key_slot: "default" });
  });

  it("抽屉里填的密钥先存进槽再测；页面上不留它", async () => {
    const { r } = await page();
    fireEvent.click(btn("add-model"));
    await waitFor(() => expect($("[data-model-sheet]")).not.toBeNull());
    const secret = "sk-test-canary-models-77aa";
    type("name", "新槽"); type("model", "x-1"); type("key_slot", "spare");
    fireEvent.click(btn("probe-model"));
    await waitFor(() => expect($("[data-probe-result]")?.getAttribute("data-probe-result")).toBe("key_not_set"));
    type("key", secret);
    fireEvent.click(btn("probe-model"));
    await waitFor(() => expect($("[data-probe-result]")?.getAttribute("data-probe-result")).toBe("ok"));
    expect(field("key").value).toBe("");
    expect(document.body.innerHTML).not.toContain(secret);
    expect(r.fetch.calls.filter((c) => c.body?.includes(secret)).map((c) => [c.method, c.url])).toEqual([["PUT", "/v1/keys/spare"]]);
  });

  it("默认分配即改即存；被分配着的档案删不掉，改走后能删", async () => {
    const { r } = await page();
    fireEvent.click($('[data-profile="default"] [data-action="edit-model"]')!);
    await waitFor(() => expect($("[data-model-sheet]")).not.toBeNull());
    expect(btn("delete-model").disabled).toBe(true);
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    await waitFor(() => expect($("[data-model-sheet]")).toBeNull());
    for (const role of ["draft", "bootstrap", "reason", "explore", "verify"]) {
      fireEvent.change($(`[data-field="route.${role}"]`)!, { target: { value: "light" } });
      await waitFor(async () => expect((await r.api.settings()).settings.models.routes[role as "draft"]).toBe("light"));
    }
    await waitFor(() => expect($('[data-profile="default"] .md-used')!.textContent).toBe("—"));
    fireEvent.click($('[data-profile="default"] [data-action="edit-model"]')!);
    await waitFor(() => expect(btn("delete-model").disabled).toBe(false));
    fireEvent.click(btn("delete-model"));
    await waitFor(() => expect($('[data-profile="default"]')).toBeNull());
    expect((await r.api.settings()).settings.models.profiles.map((p) => p.name)).toEqual(["light"]);
  });

  it("没有人的令牌：只读，不能测、不能加、分配框锁住", async () => {
    await page(null);
    expect(btn("add-model").disabled).toBe(true);
    expect(btn("test-all").disabled).toBe(true);
    expect($<HTMLSelectElement>('[data-field="route.draft"]')!.disabled).toBe(true);
    expect(document.body.textContent).toContain("只读");
  });
});
