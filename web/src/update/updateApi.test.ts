import { afterEach, describe, expect, it, vi } from "vitest";
import { checkForAppUpdate, updateDownloadHref } from "./updateApi";

describe("checkForAppUpdate", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("calls the existing updates check endpoint with the desktop defaults", async () => {
    let requestedUrl = "";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        requestedUrl = input.toString();
        return new Response(
          JSON.stringify({
            has_update: true,
            current_version: "0.1.0",
            latest_version: "2.0.10",
            channel: "stable",
            platform: "windows",
            arch: "x64",
            force_update: false,
            release_notes: ["修复更新检测"],
            download_url: "/api/v1/updates/releases/release-2-0-10/download",
            sha256: "abc123",
            file_size_bytes: 128,
            published_at: "2026-08-18T00:00:00",
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }),
    );

    const update = await checkForAppUpdate({ currentVersion: "0.1.0" });

    expect(requestedUrl).toBe(
      "/api/v1/updates/check?current_version=0.1.0&platform=windows&arch=x64&channel=stable",
    );
    expect(update.latest_version).toBe("2.0.10");
    expect(update.release_notes).toEqual(["修复更新检测"]);
  });
});

describe("updateDownloadHref", () => {
  it("keeps backend-provided update download paths usable in the renderer", () => {
    expect(updateDownloadHref("/api/v1/updates/releases/release-2-0-10/download")).toBe(
      "/api/v1/updates/releases/release-2-0-10/download",
    );
  });
});
