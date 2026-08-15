export type OutputResponse = {
  id: string;
  output_type: string;
  width: number;
  height: number;
  quality_status: string;
};

export type PreviewImage = OutputResponse & {
  url: string;
};

export async function createOutputPreviews(
  outputs: OutputResponse[],
  download: (output: OutputResponse) => Promise<Blob>,
  createUrl: (blob: Blob) => string,
  options: { preserveOrder?: boolean; ignoreDownloadErrors?: boolean } = {},
): Promise<PreviewImage[]> {
  const previewResults = await Promise.allSettled(
    outputs.map(async (output) => {
      const blob = await download(output);
      return { ...output, url: createUrl(blob) };
    }),
  );
  const failedResult = previewResults.find((result) => result.status === "rejected");
  if (failedResult && !options.ignoreDownloadErrors) {
    throw failedResult.reason;
  }
  const previewImages = previewResults.flatMap((result) => (result.status === "fulfilled" ? [result.value] : []));
  return options.preserveOrder ? previewImages : sortOutputs(previewImages);
}

export function sortOutputs(outputs: PreviewImage[]): PreviewImage[] {
  const order = ["main", "certificate", "package", "detail", "scene"];
  return [...outputs].sort((left, right) => outputRank(left.output_type, order) - outputRank(right.output_type, order));
}

function outputRank(outputType: string, order: string[]): number {
  const index = order.indexOf(outputType);
  return index === -1 ? 999 : index;
}
