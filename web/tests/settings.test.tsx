// 设置页（宪章 03 §2、§4、§5、§7；L1 第一期）：三道硬顶次序、密钥只发一次且读不回来、409 重读、只读模式。
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { Settings } from "../src/api/settings-types";
import { capIssues, changedKeys, fromMinInput, fromUsdInput, rulerFraction, settingsIssues } from "../src/model/settings";
import { SettingsPage } from "../src/pages/Settings";
import { renderWith, rig } from "./helpers";

afterEach(cleanup);

const CAPS = { global_usd_milli: 500_000, open_usd_milli: 20_000, open_wall_s: 14_400, practice_usd_milli: 500, practice_wall_s: 1_800 };
const S = (): Settings => ({
  caps: { ...CAPS },
  risk: [],
  models: { profiles: [{ name: "default", endpoint: "", model: "", family: "", tier: "strong", key_slot: "default" }], routes: { draft: "default", bootstrap: "default", reason: "default", explore: "default", verify: "default" } },
});

describe("设置的纯函数", () => {
  it("三道顶的次序：练习 ≤ 单任务 ≤ 全局", () => {
    expect(capIssues(CAPS)).toEqual([]);
    expect(capIssues({ ...CAPS, open_usd_milli: 600_000 })).toEqual(["单任务硬顶超过全局硬顶"]);
    expect(capIssues({ ...CAPS, practice_usd_milli: 30_000 })).toEqual(["练习上限超过单任务硬顶"]);
    expect(capIssues({ ...CAPS, practice_wall_s: 20_000 })).toEqual(["练习墙钟上限超过单任务墙钟硬顶"]);
    expect(capIssues({ ...CAPS, open_wall_s: 0 })[0]).toMatch(/正数/);
  });
  it("档案与路由：不重名、路由指向存在的档案、槽名合法", () => {
    const s = S();
    expect(settingsIssues(s)).toEqual([]);
    s.models.routes.draft = "nope";
    s.models.profiles.push({ ...s.models.profiles[0], key_slot: "Bad Slot" });
    const out = settingsIssues(s).join("|");
    expect(out).toMatch(/重名/);
    expect(out).toMatch(/起草 指向的档案不存在/);
    expect(out).toMatch(/密钥槽名/);
  });
  it("单位换算与刻度尺", () => {
    expect(fromUsdInput("20")).toBe(20_000);
    expect(fromUsdInput("0.5")).toBe(500);
    expect(fromUsdInput("-1")).toBeNull();
    expect(fromUsdInput("")).toBeNull();
    expect(fromMinInput("30")).toBe(1_800);
    expect(rulerFraction(500, 500_000)).toBeLessThan(rulerFraction(20_000, 500_000));
    expect(rulerFraction(20_000, 500_000)).toBeLessThan(rulerFraction(500_000, 500_000));
    expect(rulerFraction(500_000, 500_000)).toBeLessThan(1);
  });
  it("改了哪些键", () => {
    const a = S(), b = S();
    b.caps.open_usd_milli = 1;
    b.models.routes.verify = "x";
    expect(changedKeys(a, b)).toEqual(["caps.open_usd_milli", "models.routes.verify"]);
  });
});

describe("设置页", () => {
  it("密钥一节常显“重启后失效”；只显示指纹；设置后输入框清空，密钥不进任何存储与读请求", async () => {
    const r = rig();
    const { container } = renderWith(r, <SettingsPage />);
    await screen.findByText("密钥重启后失效，可用环境变量持久注入");
    await waitFor(() => expect(container.querySelector('[data-key-slot="default"][data-key-set="true"]')).not.toBeNull());
    expect(container.querySelector("[data-fingerprint]")!.textContent).toMatch(/…/);
    fireEvent.click(container.querySelector('[data-action="clear-key"]')!);
    const input = await waitFor(() => { const el = container.querySelector<HTMLInputElement>('[data-key-slot="default"] input[type="password"]'); expect(el).not.toBeNull(); return el!; });
    const secret = "sk-test-canary-9f8e7d6c5b4a";
    fireEvent.change(input, { target: { value: secret } });
    fireEvent.click(container.querySelector('[data-action="set-key"]')!);
    await waitFor(() => expect(container.querySelector('[data-key-slot="default"][data-key-set="true"]')).not.toBeNull());
    expect(container.innerHTML).not.toContain(secret);
    const puts = r.fetch.calls.filter((c) => c.body?.includes(secret));
    expect(puts.map((c) => [c.method, c.url])).toEqual([["PUT", "/v1/keys/default"]]); // 只出现在这一次请求里
    expect(JSON.stringify({ ...localStorage })).not.toContain(secret);
    expect(JSON.stringify({ ...sessionStorage })).not.toContain(secret);
    expect(container.querySelector("[data-fingerprint]")!.textContent).toMatch(/…6c5b4a$|…5b4a$/);
  });

  it("改硬顶：次序不对时不能保存；改对后一次 PUT，带读时的摘要，变更记录多一行", async () => {
    const r = rig();
    const { container } = renderWith(r, <SettingsPage />);
    const open = await waitFor(() => { const el = container.querySelector<HTMLInputElement>('[data-field="open_usd_milli"]'); expect(el).not.toBeNull(); return el!; });
    const before = (await r.api.settings()).digest;
    const save = () => container.querySelector<HTMLButtonElement>('[data-action="save-settings"]')!;
    expect(save().disabled).toBe(true); // 没改
    fireEvent.change(open, { target: { value: "900" } });
    await screen.findByText("单任务硬顶超过全局硬顶");
    expect(save().disabled).toBe(true);
    fireEvent.change(open, { target: { value: "30" } });
    await waitFor(() => expect(save().disabled).toBe(false));
    fireEvent.click(save());
    await waitFor(() => expect(container.querySelector(".settings")!.getAttribute("data-settings-version")).toBe("2"));
    const put = r.fetch.calls.find((c) => c.method === "PUT" && c.url === "/v1/settings")!;
    expect(JSON.parse(put.body!)).toMatchObject({ base_digest: before, settings: { caps: { open_usd_milli: 30_000 } } });
    await waitFor(() => expect(container.querySelectorAll("[data-settings-log] tbody tr")).toHaveLength(2));
  });

  it("别处先改了：409 提示重读，不覆盖别人的改动", async () => {
    const r = rig();
    const { container } = renderWith(r, <SettingsPage />);
    const open = await waitFor(() => { const el = container.querySelector<HTMLInputElement>('[data-field="open_usd_milli"]'); expect(el).not.toBeNull(); return el!; });
    const d = await r.api.settings();
    await r.api.putSettings(d.digest, { ...d.settings, caps: { ...d.settings.caps, open_usd_milli: 10_000 } }); // 另一处的保存
    fireEvent.change(open, { target: { value: "30" } });
    fireEvent.click(container.querySelector('[data-action="save-settings"]')!);
    await screen.findByText(/设置在你读过之后被别处改过/);
    expect((await r.api.settings()).settings.caps.open_usd_milli).toBe(10_000);
    fireEvent.click(container.querySelector('[data-action="reload-settings"]')!);
    await waitFor(() => expect(container.querySelector<HTMLInputElement>('[data-field="open_usd_milli"]')!.value).toBe("10"));
  });

  it("没有令牌：只读，不请求密钥槽", async () => {
    const r = rig(null);
    const { container } = renderWith(r, <SettingsPage />);
    await screen.findByText(/填了人的令牌.*才能看和改密钥/);
    expect(container.querySelector<HTMLInputElement>('[data-field="open_usd_milli"]')!.disabled).toBe(true);
    expect(r.fetch.calls.some((c) => c.url.startsWith("/v1/keys"))).toBe(false);
    expect(screen.getByText("密钥重启后失效，可用环境变量持久注入")).toBeTruthy();
  });

  it("风险表最后一行永远是“其它 · 任意 · r2”，不能删", async () => {
    const r = rig();
    const { container } = renderWith(r, <SettingsPage />);
    const fb = await waitFor(() => { const el = container.querySelector("[data-risk-fallback]"); expect(el).not.toBeNull(); return el!; });
    expect(fb.textContent).toContain("r2");
    expect(fb.querySelector("button")).toBeNull();
  });
});
