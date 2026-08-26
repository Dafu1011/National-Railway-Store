import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClientError, apiPost } from "./client";
import { userFacingErrorMessage } from "../userFacingErrors";

describe("api client errors", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps non JSON response text for diagnostics without exposing it as user copy", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("Internal Server Error", { status: 500, statusText: "Internal Server Error" })),
    );

    await expect(apiPost("/projects/demo/generate")).rejects.toMatchObject({
      code: "HTTP_500",
      status: 500,
      rawMessage: "Internal Server Error",
    });
    await expect(apiPost("/projects/demo/generate")).rejects.toBeInstanceOf(ApiClientError);
  });

  it("maps structured API errors to safe user-facing text", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              code: "DESKTOP_API_PROXY_FAILED",
              message: "Could not reach Zhifeng API at http://124.174.70.182:8088: socket hang up",
              details: {},
              request_id: "desktop-proxy",
            }),
            { status: 502, statusText: "Bad Gateway" },
          ),
      ),
    );

    let captured: unknown;
    try {
      await apiPost("/projects/demo/generate");
    } catch (error) {
      captured = error;
    }

    expect(captured).toBeInstanceOf(ApiClientError);
    expect(userFacingErrorMessage(captured, "generation")).toBe("网络连接不稳定，请检查网络后重试。");
    expect(userFacingErrorMessage(captured, "generation")).not.toContain("socket");
  });
});
