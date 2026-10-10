export type ErrorDisplayContext = "generation" | "gallery" | "download" | "account" | "update" | "auth" | "default";

type ErrorLike = {
  code?: unknown;
  status?: unknown;
  rawMessage?: unknown;
  requestId?: unknown;
  message?: unknown;
};

export function userFacingErrorMessage(error: unknown, context: ErrorDisplayContext = "default"): string {
  const code = errorCode(error);
  const raw = errorRawMessage(error);
  const upperRaw = raw.toUpperCase();
  const upperCode = code.toUpperCase();
  const sceneError = `${upperCode} ${upperRaw}`;

  if (sceneError.includes("DETAIL_SCENE_INPUT_INVALID")) {
    return "请检查场景内容，每项最多500字。";
  }
  if (sceneError.includes("DETAIL_BRAIN_REQUIRED")) {
    return "场景规划服务未启用，暂时无法按指定场景生成，请联系管理员。";
  }
  if (sceneError.includes("DETAIL_SCENE_SOURCE_INVALID")) {
    return "场景规划结果与输入不匹配，请重新生成。";
  }
  if (sceneError.includes("DETAIL_BRAIN_FAILED")) {
    return "场景规划失败，请稍后重试；已填写的场景不会替换为默认场景。";
  }
  if (/DETAIL_(PLAN|MODULE|USAGE)_/.test(sceneError)) {
    return "场景规划结果不完整或不符合要求，请重新生成。";
  }

  if (upperCode.includes("DESKTOP_API_PROXY_FAILED") || /SOCKET HANG UP|ECONNRESET|ECONNREFUSED|ETIMEDOUT|FAILED TO FETCH/.test(upperRaw)) {
    return context === "update" ? "更新失败，请检查网络后重试。" : "网络连接不稳定，请检查网络后重试。";
  }

  if (upperCode.includes("GENERATION_TIMEOUT") || upperRaw.includes("GENERATION_TIMEOUT")) {
    return "网络不佳，请检查网络后重试。";
  }

  if (upperCode.includes("OUTPUT_FILE_NOT_FOUND") || upperRaw.includes("OUTPUT_FILE_NOT_FOUND")) {
    return "图片文件不存在，可能是服务器历史记录指向的原图文件已被移动或删除。";
  }
  if (upperCode.includes("QUALITY_REVIEW_REQUIRED") || upperRaw.includes("QUALITY_REVIEW_REQUIRED")) {
    return "图片尚未通过质检，暂时不能下载。";
  }
  if (
    upperCode.includes("OUTPUT_QUALITY_FAILED") ||
    upperRaw.includes("OUTPUT_QUALITY_FAILED") ||
    upperRaw.includes("CERTIFICATE_CARD_TOO_LARGE") ||
    upperRaw.includes("CERTIFICATE_CARD_NOT_DETECTED")
  ) {
    return "图片未通过质检，请调整素材或重新生成。";
  }
  if (upperCode.includes("RESOURCE_ACCESS_DENIED") || upperRaw.includes("RESOURCE_ACCESS_DENIED")) {
    return "资源不存在或当前账号无权访问。";
  }
  if (upperCode.includes("INSUFFICIENT_BALANCE") || upperRaw.includes("INSUFFICIENT_BALANCE") || upperCode.includes("HTTP_402")) {
    return "积分不足，请充值后继续生成。";
  }
  if (upperCode.includes("AUTH_REQUIRED") || upperCode.includes("REFRESH_REQUIRED") || upperCode.includes("REFRESH_INVALID") || upperCode.includes("HTTP_401")) {
    return "登录状态已过期，请重新登录。";
  }
  if (upperCode.includes("INVALID_CREDENTIALS")) {
    return "账号或密码错误，请重新输入。";
  }
  if (
    upperCode.includes("PHONE_CODE_RATE_LIMITED") ||
    upperCode.includes("REGISTER_RATE_LIMITED") ||
    upperCode.includes("LOGIN_RATE_LIMITED") ||
    upperCode.includes("HTTP_429")
  ) {
    return "请求频繁，请稍后再试。";
  }
  if (upperCode.includes("HTTP_422")) {
    return "请检查必填项是否填写完整。";
  }
  if (upperCode.includes("BARCODE_NOT_CONFIRMED") || upperCode.includes("BARCODE_VALUE_INVALID")) {
    return "请先填写并确认条形码。";
  }
  if (upperCode.includes("PRODUCT_ORIGINAL_ASSET_REQUIRED")) {
    return "请先上传商品图片。";
  }
  if (upperCode.includes("PRODUCT_ID_REQUIRED")) {
    return "请先选择商品。";
  }
  if (upperCode.includes("UPLOAD_FILE_EMPTY")) {
    return "上传文件为空，请重新选择文件。";
  }
  if (upperCode.includes("UPLOAD_FILE_TOO_LARGE") || upperCode.includes("UPLOAD_IMAGE_PIXELS_TOO_LARGE")) {
    return "上传图片过大，请压缩后重试。";
  }
  if (upperCode.includes("UPLOAD_MIME_NOT_ALLOWED") || upperCode.includes("UPLOAD_IMAGE_DECODE_FAILED")) {
    return "图片格式不支持，请上传 PNG、JPEG 或 WebP 图片。";
  }

  if (upperCode.includes("IMAGE_PROVIDER_FAILED") || upperRaw.includes("IMAGE_PROVIDER_FAILED")) {
    if (upperRaw.includes("KELE_TIMEOUT")) {
      return "生成服务响应超时，请稍后重试。";
    }
    if (upperRaw.includes("KELE_HTTP_429") || upperRaw.includes("PROVIDER_BUSY") || upperRaw.includes("负载已饱和")) {
      return "当前生成服务繁忙，请稍后再试。";
    }
    return "图片生成失败，请稍后重试。";
  }

  if (upperCode.includes("ACTIVE_JOB_LIMIT_REACHED")) {
    return "当前账号正在生成图片，请稍后再试。";
  }
  if (upperCode.includes("GENERATION_QUEUE_FULL") || upperCode.includes("PROVIDER_BUSY")) {
    return "当前生成队列繁忙，请稍后再试。";
  }

  if (upperCode.startsWith("HTTP_5") || upperCode.includes("HTTP_500") || upperCode.includes("HTTP_502") || upperCode.includes("HTTP_503") || upperCode.includes("HTTP_504")) {
    return fallbackForContext(context);
  }

  return fallbackForContext(context);
}

function errorCode(error: unknown): string {
  if (isErrorLike(error) && typeof error.code === "string") {
    return error.code;
  }
  const raw = errorRawMessage(error);
  const match = raw.match(/^([A-Z0-9_]+)(?::|\b)/);
  return match?.[1] ?? "";
}

function errorRawMessage(error: unknown): string {
  if (isErrorLike(error) && typeof error.rawMessage === "string") {
    return error.rawMessage;
  }
  if (error instanceof Error) {
    return error.message;
  }
  if (typeof error === "string") {
    return error;
  }
  return "";
}

function isErrorLike(error: unknown): error is ErrorLike {
  return typeof error === "object" && error !== null;
}

function fallbackForContext(context: ErrorDisplayContext): string {
  switch (context) {
    case "generation":
      return "生成失败，请稍后重试。";
    case "gallery":
      return "图库加载失败，请刷新后重试。";
    case "download":
      return "下载失败，请稍后重试。";
    case "account":
      return "账户信息加载失败，请稍后重试。";
    case "update":
      return "更新失败，请稍后重试。";
    case "auth":
      return "认证失败，请稍后重试。";
    default:
      return "操作失败，请稍后重试。";
  }
}
