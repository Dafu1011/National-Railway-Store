export type RecoverableGenerationJob = {
  id: string;
  status: string;
  error_code?: string | null;
  error_message?: string | null;
  outputs: unknown[];
};

export type ActiveGenerationJobsResponse<TJob extends RecoverableGenerationJob = RecoverableGenerationJob> = {
  items: TJob[];
};

type WaitForGenerationOptions<TJob extends RecoverableGenerationJob> = {
  jobId: string;
  fetchJob: (jobId: string) => Promise<TJob>;
  onProgress: (job: TJob) => void;
  timeoutMs?: number;
  delayMs?: number;
};

const DEFAULT_GENERATION_TIMEOUT_MS = 20 * 60 * 1000;
const DEFAULT_GENERATION_POLL_MS = 1200;

export async function waitForGenerationCompletion<TJob extends RecoverableGenerationJob>({
  jobId,
  fetchJob,
  onProgress,
  timeoutMs = DEFAULT_GENERATION_TIMEOUT_MS,
  delayMs = DEFAULT_GENERATION_POLL_MS,
}: WaitForGenerationOptions<TJob>): Promise<TJob> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await delay(delayMs);
    let job: TJob;
    try {
      job = await fetchJob(jobId);
    } catch (error) {
      if (isTransientGenerationConnectionError(error)) {
        continue;
      }
      throw error;
    }
    onProgress(job);
    if (job.status === "completed") {
      return job;
    }
    if (job.status === "failed") {
      throw new Error(`${job.error_code || "IMAGE_PROVIDER_FAILED"}: ${job.error_message || "Generation failed"}`);
    }
  }
  throw new Error("GENERATION_TIMEOUT: Generation did not finish in time.");
}

export function isRecoverableActiveGenerationError(error: unknown): boolean {
  return errorText(error).includes("ACTIVE_JOB_LIMIT_REACHED") || isTransientGenerationConnectionError(error);
}

export function isTransientGenerationConnectionError(error: unknown): boolean {
  const text = errorText(error);
  return /DESKTOP_API_PROXY_FAILED|SOCKET HANG UP|ECONNRESET|ECONNREFUSED|ETIMEDOUT|FAILED TO FETCH|NETWORKERROR/.test(text);
}

function errorText(error: unknown): string {
  if (isErrorLike(error)) {
    return `${typeof error.code === "string" ? error.code : ""} ${
      typeof error.rawMessage === "string" ? error.rawMessage : ""
    } ${typeof error.message === "string" ? error.message : ""}`.toUpperCase();
  }
  if (error instanceof Error) {
    return error.message.toUpperCase();
  }
  if (typeof error === "string") {
    return error.toUpperCase();
  }
  return "";
}

function isErrorLike(error: unknown): error is { code?: unknown; rawMessage?: unknown; message?: unknown } {
  return typeof error === "object" && error !== null;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => globalThis.setTimeout(resolve, ms));
}
