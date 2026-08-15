const EXPECTED_OUTPUT_COUNT = 5;
const RUNNING_PROGRESS_CEILING = 95;

type GenerationProgressInput = {
  outputCount?: number;
  workflowPercent?: number;
  loading?: boolean;
};

export function generationProgress(input: number | GenerationProgressInput = 0): number {
  if (typeof input === "number") {
    return progressFromOutputCount(input);
  }

  const outputProgress = progressFromOutputCount(input.outputCount ?? 0);
  if (!input.loading || outputProgress >= 100) {
    return outputProgress;
  }

  return Math.min(RUNNING_PROGRESS_CEILING, Math.max(outputProgress, clampPercent(input.workflowPercent ?? 0)));
}

export function nextLiveGenerationProgress(currentProgress: number, outputCount = 0): number {
  const floor = progressFromOutputCount(outputCount);
  const current = Math.max(clampPercent(currentProgress), floor);
  if (current >= RUNNING_PROGRESS_CEILING) {
    return RUNNING_PROGRESS_CEILING;
  }

  const increment = current < 60 ? 3 : current < 82 ? 2 : 1;
  return Math.min(RUNNING_PROGRESS_CEILING, current + increment);
}

function progressFromOutputCount(outputCount = 0): number {
  const clampedCount = Math.min(Math.max(outputCount, 0), EXPECTED_OUTPUT_COUNT);
  return Math.round((clampedCount / EXPECTED_OUTPUT_COUNT) * 100);
}

function clampPercent(value: number): number {
  return Math.min(Math.max(Math.round(value), 0), 100);
}
