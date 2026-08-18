import type { UpdateCheckResponse } from "./updateApi";

export const UPDATE_DISMISSED_VERSION_KEY = "zhifeng.update.dismissedVersion";

export type UpdateNoticeStorage = {
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
};

export function shouldOpenUpdateModal(update: UpdateCheckResponse | null, dismissedLatestVersion: string): boolean {
  if (!update?.has_update) {
    return false;
  }
  if (update.force_update) {
    return true;
  }
  return update.latest_version !== dismissedLatestVersion;
}

export function hasUpdateNotice(update: UpdateCheckResponse | null): boolean {
  return Boolean(update?.has_update);
}

export function readDismissedUpdateVersion(storage: UpdateNoticeStorage): string {
  try {
    return storage.getItem(UPDATE_DISMISSED_VERSION_KEY) || "";
  } catch {
    return "";
  }
}

export function rememberDismissedUpdateVersion(storage: UpdateNoticeStorage, latestVersion: string): void {
  try {
    storage.setItem(UPDATE_DISMISSED_VERSION_KEY, latestVersion);
  } catch {
    // A blocked storage write should not prevent the user from closing an optional update prompt.
  }
}
