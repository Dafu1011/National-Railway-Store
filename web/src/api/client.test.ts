import { afterEach, describe, expect, it, vi } from "vitest";
import { apiPost } from "./client";

describe("api client errors", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("falls back to response text when an error response is not JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("Internal Server Error", { status: 500, statusText: "Internal Server Error" })),
    );

    await expect(apiPost("/projects/demo/generate")).rejects.toThrow("HTTP_500: Internal Server Error");
  });
});
