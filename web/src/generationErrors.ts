export function generationErrorMessage(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error || "");
  if (!raw) {
    return "生成失败，请查看后端日志。";
  }

  if (raw.includes("OUTPUT_FILE_NOT_FOUND")) {
    return "图片文件不存在，可能是服务器历史记录指向的原图文件已被移动或删除。";
  }
  if (raw.includes("QUALITY_REVIEW_REQUIRED")) {
    return "图片尚未通过质检，暂时不能下载。";
  }
  if (raw.includes("RESOURCE_ACCESS_DENIED")) {
    return "资源不存在或当前账号无权访问。";
  }

  if (raw.includes("IMAGE_PROVIDER_FAILED")) {
    if (raw.includes("KELE_TIMEOUT")) {
      return "可乐请求超时：上游生图耗时过长，请稍后重试。";
    }
    const providerMessage = extractProviderMessage(raw);
    if (providerMessage) {
      return `可乐生图失败：${providerMessage}`;
    }
    if (raw.includes("KELE_HTTP_429")) {
      return "可乐生图失败：上游负载已饱和，请稍后再试。";
    }
    return `可乐生图失败：${raw}`;
  }

  return raw;
}

function extractProviderMessage(raw: string): string | null {
  const match = raw.match(/"message"\s*:\s*"([^"]+)"/);
  return match?.[1] ?? null;
}
