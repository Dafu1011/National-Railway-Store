export function generationErrorMessage(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error || "");
  if (!raw) {
    return "生成失败，请查看后端日志。";
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
