import type { UpdateCheckResponse } from "./updateApi";

export type UpdateInstallRequest = Pick<
  UpdateCheckResponse,
  "download_url" | "latest_version" | "sha256" | "file_size_bytes" | "platform" | "arch"
>;

export type UpdateInstallResult = {
  installer_path: string;
  launched: boolean;
};

export type ZhifengUpdateBridge = {
  getAppVersion: () => Promise<string>;
  install: (update: UpdateInstallRequest) => Promise<UpdateInstallResult>;
};

declare global {
  interface Window {
    zhifengUpdates?: ZhifengUpdateBridge;
  }
}
