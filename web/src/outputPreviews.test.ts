import { describe, expect, it } from "vitest";
import {
  createGalleryPreviews,
  createOutputPreviews,
  outputOriginalDownloadPath,
  outputPreviewDownloadPath,
  type OutputResponse,
} from "./outputPreviews";

describe("output previews", () => {
  it("downloads and sorts partial generation outputs in business order", async () => {
    const outputs: OutputResponse[] = [
      { id: "package-id", output_type: "package", width: 800, height: 800, quality_status: "passed" },
      { id: "main-id", output_type: "main", width: 800, height: 800, quality_status: "passed" },
      { id: "certificate-id", output_type: "certificate", width: 800, height: 800, quality_status: "passed" },
    ];
    const downloaded: string[] = [];

    const previews = await createOutputPreviews(
      outputs,
      async (output) => {
        downloaded.push(output.id);
        return new Blob([output.id], { type: "image/png" });
      },
      (blob) => `blob://${blob.size}`,
    );

    expect(downloaded).toEqual(["package-id", "main-id", "certificate-id"]);
    expect(previews.map((preview) => preview.output_type)).toEqual(["main", "certificate", "package"]);
    expect(previews.every((preview) => preview.url.startsWith("blob://"))).toBe(true);
  });

  it("can preserve API order for account gallery history", async () => {
    const outputs: OutputResponse[] = [
      { id: "latest-scene-id", output_type: "scene", width: 800, height: 800, quality_status: "passed" },
      { id: "older-main-id", output_type: "main", width: 800, height: 800, quality_status: "passed" },
    ];

    const previews = await createOutputPreviews(
      outputs,
      async (output) => new Blob([output.id], { type: "image/png" }),
      (blob) => `blob://${blob.size}`,
      { preserveOrder: true },
    );

    expect(previews.map((preview) => preview.id)).toEqual(["latest-scene-id", "older-main-id"]);
  });

  it("can ignore missing gallery files and keep loading the remaining history", async () => {
    const outputs: OutputResponse[] = [
      { id: "missing-output-id", output_type: "scene", width: 800, height: 800, quality_status: "passed" },
      { id: "available-output-id", output_type: "main", width: 800, height: 800, quality_status: "passed" },
    ];

    const previews = await createOutputPreviews(
      outputs,
      async (output) => {
        if (output.id === "missing-output-id") {
          throw new Error("OUTPUT_FILE_NOT_FOUND: 输出文件不存在。");
        }
        return new Blob([output.id], { type: "image/png" });
      },
      (blob) => `blob://${blob.size}`,
      { preserveOrder: true, ignoreDownloadErrors: true },
    );

    expect(previews.map((preview) => preview.id)).toEqual(["available-output-id"]);
  });

  it("uses gallery thumbnails for previews when the API provides them", () => {
    const output: OutputResponse = {
      id: "thumb-output-id",
      output_type: "detail",
      width: 800,
      height: 2400,
      quality_status: "passed",
      thumbnail_url: "/api/v1/outputs/thumb-output-id/thumbnail",
    };

    expect(outputPreviewDownloadPath(output)).toBe("/outputs/thumb-output-id/thumbnail");
  });

  it("uses API-provided original download paths without duplicating the API prefix", () => {
    const output: OutputResponse = {
      id: "download-output-id",
      output_type: "main",
      width: 800,
      height: 800,
      quality_status: "passed",
      download_url: "/api/v1/outputs/download-output-id/download",
    };

    expect(outputOriginalDownloadPath(output)).toBe("/outputs/download-output-id/download");
  });

  it("creates gallery previews from thumbnail urls without downloading blobs first", () => {
    const outputs: OutputResponse[] = [
      {
        id: "latest-scene-id",
        output_type: "scene",
        width: 800,
        height: 800,
        quality_status: "passed",
        thumbnail_url: "/api/v1/outputs/latest-scene-id/thumbnail",
      },
      {
        id: "older-main-id",
        output_type: "main",
        width: 800,
        height: 800,
        quality_status: "passed",
        download_url: "/api/v1/outputs/older-main-id/download",
      },
    ];

    const previews = createGalleryPreviews(outputs);

    expect(previews.map((preview) => preview.id)).toEqual(["latest-scene-id", "older-main-id"]);
    expect(previews.map((preview) => preview.url)).toEqual([
      "/api/v1/outputs/latest-scene-id/thumbnail",
      "/api/v1/outputs/older-main-id/download",
    ]);
  });
});
