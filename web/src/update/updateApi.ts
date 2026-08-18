import { apiGet } from "../api/client";

export type UpdateCheckResponse = {
  has_update: boolean;
  current_version: string;
  latest_version: string;
  channel: string;
  platform: string;
  arch: string;
  force_update: boolean;
  release_notes: string[];
  download_url: string;
  sha256: string;
  file_size_bytes: number;
  published_at: string;
};

export type UpdateCheckRequest = {
  currentVersion: string;
  platform?: "windows";
  arch?: "x64" | "arm64";
  channel?: "stable" | "beta";
};

export async function checkForAppUpdate({
  currentVersion,
  platform = "windows",
  arch = "x64",
  channel = "stable",
}: UpdateCheckRequest): Promise<UpdateCheckResponse> {
  const params = new URLSearchParams({
    current_version: currentVersion,
    platform,
    arch,
    channel,
  });

  return apiGet<UpdateCheckResponse>(`/updates/check?${params.toString()}`);
}

export function updateDownloadHref(downloadUrl: string): string {
  const trimmed = downloadUrl.trim();
  if (trimmed.startsWith("http://") || trimmed.startsWith("https://") || trimmed.startsWith("/")) {
    return trimmed;
  }
  return `/${trimmed}`;
}
