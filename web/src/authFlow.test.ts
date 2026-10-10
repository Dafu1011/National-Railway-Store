import { describe, expect, it } from "vitest";
import { authErrorMessage, loginRequestBody, restoreAuthFromRefresh } from "./authFlow";

describe("authFlow", () => {
  it("maps backend registration code failures to actionable messages", () => {
    expect(authErrorMessage(new Error("EMAIL_CODE_INVALID: invalid"))).toContain("验证码");
    expect(authErrorMessage(new Error("EMAIL_DOMAIN_UNSUPPORTED: unsupported"))).toContain("邮箱");
    expect(authErrorMessage(new Error("PHONE_CODE_INVALID: invalid"))).toContain("验证码");
    expect(authErrorMessage(new Error("INVITATION_CODE_INVALID: invalid"))).toContain("邀请码");
    expect(authErrorMessage(new Error("USERNAME_ALREADY_REGISTERED: duplicate"))).toContain("用户名");
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

  it("maps sms provider failures separately from missing sms configuration", () => {
    expect(authErrorMessage(new Error("SMS_PROVIDER_FAILED: provider rejected request"))).toContain("短信服务发送失败");
    expect(authErrorMessage(new Error("SMS_NOT_CONFIGURED: missing config"))).toContain("尚未配置");
  });

  it("maps tencent phone daily sms limits to a readable retry message", () => {
    expect(
      authErrorMessage(
        new Error(
          "SMS_PROVIDER_FAILED: SMS_TENCENT_FAILED:LimitExceeded.PhoneNumberDailyLimit:the number of sms messages sent from a single mobile number every day exceeds the upper limit",
        ),
      ),
    ).toBe("请求频率过高，请稍后再试");
  });

  it("maps auth rate limits to a readable retry message", () => {
    expect(authErrorMessage(new Error("PHONE_CODE_RATE_LIMITED: too often"))).toBe("请求频繁，请稍后再试");
    expect(authErrorMessage(new Error("LOGIN_RATE_LIMITED: too often"))).toBe("请求频繁，请稍后再试");
  });

  it("builds login payloads for either phone or username login", () => {
    expect(loginRequestBody("13800138000", "StrongPass123")).toEqual({
      phone: "13800138000",
      password: "StrongPass123",
    });
    expect(loginRequestBody("hua", "StrongPass123")).toEqual({
      username: "hua",
      password: "StrongPass123",
    });
  });
});
