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

  it("surfaces frontend generation polling timeouts as network retry guidance", () => {
    const message = generationErrorMessage(new Error("GENERATION_TIMEOUT: Generation did not finish in time."));

    expect(message).toBe("网络不佳，请检查网络后重试。");
  });

  it("shows output file errors in readable Chinese even when the backend message is mojibake", () => {
    const message = generationErrorMessage(new Error("OUTPUT_FILE_NOT_FOUND: 杈撳嚭鏂囦欢涓嶅瓨鍦ㄣ€?"));

    expect(message).toBe("图片文件不存在，可能是服务器历史记录指向的原图文件已被移动或删除。");
  });
});
