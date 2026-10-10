import { describe, expect, it } from "vitest";
import { generationErrorMessage } from "./generationErrors";
import { userFacingErrorMessage } from "./userFacingErrors";

describe("generation error UX", () => {
  it.each([
    ["DETAIL_BRAIN_REQUIRED", "场景规划服务未启用，暂时无法按指定场景生成，请联系管理员。"],
    ["DETAIL_BRAIN_FAILED", "场景规划失败，请稍后重试；已填写的场景不会替换为默认场景。"],
    ["DETAIL_SCENE_SOURCE_INVALID", "场景规划结果与输入不匹配，请重新生成。"],
    ["DETAIL_SCENE_INPUT_INVALID", "请检查场景内容，每项最多500字。"],
  ])("explains scene errors even inside a provider failure (%s)", (code, expected) => {
    expect(generationErrorMessage(new Error(`IMAGE_PROVIDER_FAILED: PARTIAL_IMAGE_GENERATION_FAILED: detail: ${code}`))).toBe(expected);
  });

  it("hides Kele provider technical payloads from users", () => {
    const error = new Error(
      'IMAGE_PROVIDER_FAILED: KELE_HTTP_429: {"error":{"message":"当前分组上游负载已饱和，请稍后再试 (request id: req-123)","type":"new_api_error","code":"model_not_found"}}',
    );

    const message = generationErrorMessage(error);

    expect(message).toBe("当前生成服务繁忙，请稍后再试。");
    expect(message).not.toContain("KELE_HTTP");
    expect(message).not.toContain("req-123");
  });

  it("surfaces Kele timeouts as actionable retry guidance", () => {
    const message = generationErrorMessage(new Error("IMAGE_PROVIDER_FAILED: KELE_TIMEOUT: The read operation timed out"));

    expect(message).toContain("生成服务响应超时");
    expect(message).toContain("稍后重试");
  });

  it("surfaces frontend generation polling timeouts as network retry guidance", () => {
    const message = generationErrorMessage(new Error("GENERATION_TIMEOUT: Generation did not finish in time."));

    expect(message).toBe("网络不佳，请检查网络后重试。");
  });

  it("surfaces output quality failures instead of network retry guidance", () => {
    const message = generationErrorMessage(
      new Error("OUTPUT_QUALITY_FAILED: certificate: CERTIFICATE_CARD_TOO_LARGE_FOR_BULKY_PRODUCT"),
    );

    expect(message).toBe("图片未通过质检，请调整素材或重新生成。");
    expect(message).not.toContain("网络");
  });

  it("shows output file errors in readable Chinese even when the backend message is mojibake", () => {
    const message = generationErrorMessage(new Error("OUTPUT_FILE_NOT_FOUND: 杈撳嚭鏂囦欢涓嶅瓨鍦ㄣ€?"));

    expect(message).toBe("图片文件不存在，可能是服务器历史记录指向的原图文件已被移动或删除。");
  });

  it("hides desktop proxy socket errors from users", () => {
    const message = generationErrorMessage(
      new Error("DESKTOP_API_PROXY_FAILED: Could not reach Zhifeng API at http://124.174.70.182:8088: socket hang up"),
    );

    expect(message).toBe("网络连接不稳定，请检查网络后重试。");
    expect(message).not.toContain("socket");
    expect(message).not.toContain("DESKTOP_API_PROXY_FAILED");
  });

  it("uses context specific copy for update failures", () => {
    const message = userFacingErrorMessage(new Error("HTTP_500: Internal Server Error"), "update");

    expect(message).toBe("更新失败，请稍后重试。");
    expect(message).not.toContain("HTTP_500");
  });

  it("maps validation and required-field backend errors to readable Chinese", () => {
    expect(userFacingErrorMessage(new Error("HTTP_422: validation failed"), "generation")).toBe("请检查必填项是否填写完整。");
    expect(userFacingErrorMessage(new Error("BARCODE_NOT_CONFIRMED: missing barcode"), "generation")).toBe("请先填写并确认条形码。");
    expect(userFacingErrorMessage(new Error("PRODUCT_ORIGINAL_ASSET_REQUIRED: missing image"), "generation")).toBe("请先上传商品图片。");
  });

  it("maps common account errors to readable Chinese", () => {
    expect(userFacingErrorMessage(new Error("INVALID_CREDENTIALS: bad password"), "auth")).toBe("账号或密码错误，请重新输入。");
    expect(userFacingErrorMessage(new Error("PHONE_CODE_RATE_LIMITED: too often"), "auth")).toBe("请求频繁，请稍后再试。");
  });
});
