import { describe, expect, it } from "vitest";
import {
  UPDATE_DISMISSED_VERSION_KEY,
  hasUpdateNotice,
  readDismissedUpdateVersion,
  rememberDismissedUpdateVersion,
  shouldOpenUpdateModal,
} from "./updateState";
import type { UpdateCheckResponse } from "./updateApi";

describe("updateState", () => {
  const update: UpdateCheckResponse = {
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
  };

  it("opens the modal for a new update that has not been dismissed", () => {
    expect(shouldOpenUpdateModal(update, "")).toBe(true);
  });

  it("keeps a dismissed optional update as a blue-dot notice instead of reopening automatically", () => {
    expect(shouldOpenUpdateModal(update, "2.0.10")).toBe(false);
    expect(hasUpdateNotice(update)).toBe(true);
  });

  it("always opens the modal for a forced update", () => {
    expect(shouldOpenUpdateModal({ ...update, force_update: true }, "2.0.10")).toBe(true);
  });

  it("persists the dismissed latest version", () => {
    const storage = new Map<string, string>();
    const localStorageLike = {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
    };

    rememberDismissedUpdateVersion(localStorageLike, "2.0.10");

    expect(storage.get(UPDATE_DISMISSED_VERSION_KEY)).toBe("2.0.10");
    expect(readDismissedUpdateVersion(localStorageLike)).toBe("2.0.10");
  });
});
