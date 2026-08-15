import { describe, expect, it } from "vitest";
import { authErrorMessage, restoreAuthFromRefresh } from "./authFlow";

describe("authFlow", () => {
  it("maps backend registration code failures to actionable messages", () => {
    expect(authErrorMessage(new Error("EMAIL_CODE_INVALID: invalid"))).toContain("验证码");
    expect(authErrorMessage(new Error("EMAIL_DOMAIN_UNSUPPORTED: unsupported"))).toContain("邮箱");
  });

  it("maps invalid login credentials to a short message", () => {
    expect(authErrorMessage(new Error("INVALID_CREDENTIALS: bad password"))).toContain("密码");
  });

  it("restores auth from refresh when the refresh cookie is still valid", async () => {
    const auth = {
      access_token: "new-access-token",
      user: { id: "user-1", email: "alice@qq.com" },
    };

    await expect(restoreAuthFromRefresh(() => Promise.resolve(auth))).resolves.toEqual(auth);
  });

  it("returns null when startup refresh fails", async () => {
    await expect(restoreAuthFromRefresh(() => Promise.reject(new Error("REFRESH_INVALID")))).resolves.toBeNull();
  });

  it("maps password reset failures to actionable messages", () => {
    expect(authErrorMessage(new Error("PASSWORD_RESET_IN_PROGRESS: busy"))).toContain("重置");
  });
});
