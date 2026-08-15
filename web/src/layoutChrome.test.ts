import { describe, expect, it } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const css = readFileSync(resolve(__dirname, "App.css"), "utf8");
const appSource = readFileSync(resolve(__dirname, "App.tsx"), "utf8");

describe("layout chrome", () => {
  it("hides visible layout scrollbars across the workbench", () => {
    expect(css).toContain("scrollbar-width: none");
    expect(css).toContain("::-webkit-scrollbar");
    expect(css).toContain("display: none");
  });

  it("keeps the configuration rail scrollable without showing a scrollbar", () => {
    expect(css).toMatch(/\.config-rail\s*\{[^}]*overflow-y:\s*auto/s);
    expect(css).toMatch(/\.config-rail\s*\{[^}]*scrollbar-width:\s*none/s);
  });

  it("renders only the current topbar page navigation", () => {
    expect(appSource).toContain('<nav className="topbar-nav"');
    expect(appSource).toContain("首页");
    expect(appSource).toContain("图库");
    expect(appSource).not.toContain('href="#config">配置');
    expect(appSource).not.toContain('href="#pipeline">流程');
    expect(appSource).not.toContain('href="#outputs">输出');
  });
  it("loads gallery from the current account history instead of the active preview list", () => {
    expect(appSource).toContain('apiGet<ProjectOutputsResponse>("/gallery/outputs"');
    expect(appSource).toContain("galleryPreviews");
    expect(appSource).toContain("dataSource={galleryPreviews}");
  });
  it("adds an account page for balance and customer-service recharge", () => {
    expect(appSource).toContain('apiGet<AccountResponse>("/account/me"');
    expect(appSource).toContain('apiGet<AccountTransactionsResponse>("/account/transactions"');
    expect(appSource).toContain("3699");
    expect(appSource).toContain("wechat-service-qr.jpg");
    expect(css).toContain(".account-page");
    expect(css).toContain(".recharge-card");
    expect(existsSync(resolve(__dirname, "../public/wechat-service-qr.jpg"))).toBe(true);
  });
});
