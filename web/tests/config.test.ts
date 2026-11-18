// 人的令牌只在本标签页、带到期时间（裁决 005-6，P2-2）。
import { beforeEach, describe, expect, it } from "vitest";
import { loadConfig, loadToken, saveToken, TOKEN_TTL_MS } from "../src/app/config";

describe("人的令牌", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
  });

  it("存进 sessionStorage，不进 localStorage，带到期时间", () => {
    const t = saveToken("tok", 1000);
    expect(t).toEqual({ token: "tok", expires_at: 1000 + TOKEN_TTL_MS });
    expect(localStorage.getItem("paoding.human_token")).toBeNull();
    expect(JSON.parse(sessionStorage.getItem("paoding.human_token")!)).toEqual(t);
    expect(loadToken(1001)).toEqual(t);
    saveToken("tok");
    expect(loadConfig().token).toBe("tok");
  });

  it("到期即失效，并从存储里删掉", () => {
    saveToken("tok", 0, 10);
    expect(loadToken(9)?.token).toBe("tok");
    expect(loadToken(10)).toBeNull();
    expect(sessionStorage.getItem("paoding.human_token")).toBeNull();
  });

  it("旧版本放在 localStorage 的令牌不再沿用，读一次就清掉", () => {
    localStorage.setItem("paoding.human_token", "old");
    expect(loadToken()).toBeNull();
    expect(localStorage.getItem("paoding.human_token")).toBeNull();
  });

  it("坏数据与清除", () => {
    sessionStorage.setItem("paoding.human_token", "{oops");
    expect(loadToken()).toBeNull();
    saveToken("tok");
    expect(saveToken(null)).toBeNull();
    expect(loadToken()).toBeNull();
  });
});
