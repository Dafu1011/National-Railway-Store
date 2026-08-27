import { describe, expect, it } from "vitest";
import { existsSync, readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";

const webRoot = resolve(__dirname, "..");

describe("brand icon assets", () => {
  it("ships the extracted Huizhizuo mark for app chrome and Windows icons", () => {
    const requiredAssets = [
      "public/brand/hz-logo.png",
      "public/brand/hz-logo-icon.png",
      "public/brand/hz-logo.ico",
    ];

    for (const asset of requiredAssets) {
      const assetPath = resolve(webRoot, asset);
      expect(existsSync(assetPath), asset).toBe(true);
      expect(statSync(assetPath).size, asset).toBeGreaterThan(1024);
    }
  });

  it("uses the Huizhizuo mark and name in browser, renderer, Electron window, and packaged exe config", () => {
    const indexHtml = readFileSync(resolve(webRoot, "index.html"), "utf8");
    const appSource = readFileSync(resolve(__dirname, "App.tsx"), "utf8");
    const mainSource = readFileSync(resolve(webRoot, "electron", "main.cjs"), "utf8");
    const packageJson = JSON.parse(readFileSync(resolve(webRoot, "package.json"), "utf8"));

    expect(indexHtml).toContain("<title>绘智作</title>");
    expect(indexHtml).toContain('href="/brand/hz-logo.ico"');
    expect(appSource).toContain('src="/brand/hz-logo.png"');
    expect(appSource).toContain("<strong>绘智作</strong>");
    expect(appSource).toContain("绘智作登录");
    expect(mainSource).toContain("resolveWindowIconPath");
    expect(mainSource).toContain('title: "绘智作"');
    expect(packageJson.build.productName).toBe("绘智作");
    expect(packageJson.build.win.icon).toBe("public/brand/hz-logo.ico");
    expect(indexHtml).not.toContain("智枫生图");
    expect(appSource).not.toContain("智枫生图");
    expect(mainSource).not.toContain("Zhifeng Image");
  });
});
