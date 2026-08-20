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
    expect(appSource).toContain('apiGet<ProjectOutputsResponse>(galleryOutputsPath');
    expect(appSource).toContain("galleryPreviews");
    expect(appSource).toContain("dataSource={galleryPreviews}");
    expect(appSource).toContain("if (galleryLoaded) {");
    expect(appSource).toContain("createGalleryPreviews(galleryOutputs.items)");
    expect(appSource).toContain("GalleryPreviewImage");
    expect(appSource).toContain("loadPreviousGalleryPage");
    expect(appSource).toContain("loadNextGalleryPage");
    expect(appSource).toContain("上一页");
    expect(appSource).toContain("下一页");
    expect(appSource).not.toContain("鍔犺浇鏇村");
    expect(appSource).toContain("next_cursor");
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

  it("waits longer for generation and does not mark frontend polling timeouts as failed jobs", () => {
    expect(appSource).toContain("20 * 60 * 1000");
    expect(appSource).toContain("const generationTimedOut = isGenerationTimeoutError(error);");
    expect(appSource).toContain("if (!generationTimedOut && activeProject)");
    expect(appSource).not.toContain("const deadline = Date.now() + 10 * 60 * 1000;");
  });

  it("shows update installer download progress in the update modal", () => {
    const updateModalSource = readFileSync(resolve(__dirname, "update/UpdateModal.tsx"), "utf8");
    const bridgeSource = readFileSync(resolve(__dirname, "update/electronBridge.ts"), "utf8");
    const preloadSource = readFileSync(resolve(__dirname, "../electron/preload.cjs"), "utf8");

    expect(updateModalSource).toContain("downloadProgress");
    expect(updateModalSource).toContain("<Progress");
    expect(updateModalSource).toContain("正在下载安装包");
    expect(css).toContain(".update-download-progress");
    expect(appSource).toContain("setUpdateDownloadProgress");
    expect(appSource).toContain("onDownloadProgress");
    expect(bridgeSource).toContain("onDownloadProgress");
    expect(preloadSource).toContain("updates:download-progress");
  });

  it("shows reference-image upload entries and the renamed form labels", () => {
    expect(appSource).toContain('label="合格证参考图"');
    expect(appSource).toContain('label="包装箱参考图"');
    expect(appSource).toContain('label="规格型号"');
    expect(appSource).toContain('label="生产厂家"');
    expect(appSource).not.toContain('label="分类"');
    expect(appSource).not.toContain('label="材质"');
    expect(appSource).not.toContain('label="颜色"');
    expect(appSource).not.toContain('label="详情文案"');
  });
});
