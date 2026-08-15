import { describe, expect, it } from "vitest";
import { generationErrorMessage } from "./generationErrors";

describe("generation error UX", () => {
  it("surfaces Kele provider failures as human readable errors", () => {
    const error = new Error(
      'IMAGE_PROVIDER_FAILED: KELE_HTTP_429: {"error":{"message":"当前分组上游负载已饱和，请稍后再试 (request id: req-123)","type":"new_api_error","code":"model_not_found"}}',
    );

    const message = generationErrorMessage(error);

    expect(message).toContain("可乐生图失败");
    expect(message).toContain("当前分组上游负载已饱和");
    expect(message).toContain("req-123");
  });

  it("surfaces Kele timeouts as actionable retry guidance", () => {
    const message = generationErrorMessage(new Error("IMAGE_PROVIDER_FAILED: KELE_TIMEOUT: The read operation timed out"));

    expect(message).toContain("可乐请求超时");
    expect(message).toContain("稍后重试");
  });
});
