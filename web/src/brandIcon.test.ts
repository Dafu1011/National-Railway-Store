import { describe, expect, it } from "vitest";
import { existsSync, readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";

const webRoot = resolve(__dirname, "..");

describe("brand icon assets", () => {
  it("ships the extracted ZF mark for app chrome and Windows icons", () => {
    const requiredAssets = [
      "public/brand/zf-logo.png",
      "public/brand/zf-logo-icon.png",
      "public/brand/zf-logo.ico",
    ];

    for (const asset of requiredAssets) {
      const assetPath = resolve(webRoot, asset);
      expect(existsSync(assetPath), asset).toBe(true);
      expect(statSync(assetPath).size, asset).toBeGreaterThan(1024);
    }
  });

  it("uses the ZF mark in browser, renderer, Electron window, and packaged exe config", () => {
    const indexHtml = readFileSync(resolve(webRoot, "index.html"), "utf8");
    const appSource = readFileSync(resolve(__dirname, "App.tsx"), "utf8");
    const mainSource = readFileSync(resolve(webRoot, "electron", "main.cjs"), "utf8");
    const packageJson = JSON.parse(readFileSync(resolve(webRoot, "package.json"), "utf8"));

    expect(indexHtml).toContain('href="/brand/zf-logo.ico"');
    expect(appSource).toContain('src="/brand/zf-logo.png"');
    expect(mainSource).toContain("resolveWindowIconPath");
    expect(packageJson.build.win.icon).toBe("public/brand/zf-logo.ico");
  });
});
