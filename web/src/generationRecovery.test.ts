import { describe, expect, it } from "vitest";
import {
  isRecoverableActiveGenerationError,
  waitForGenerationCompletion,
  type RecoverableGenerationJob,
} from "./generationRecovery";

describe("generation recovery", () => {
  it("keeps polling the same job after a transient network failure", async () => {
    const seen: RecoverableGenerationJob[] = [];
    let calls = 0;

    const completed = await waitForGenerationCompletion<RecoverableGenerationJob>({
      jobId: "job-1",
      delayMs: 0,
      timeoutMs: 1000,
      fetchJob: async () => {
        calls += 1;
        if (calls === 1) {
          throw new TypeError("Failed to fetch");
        }
        return { id: "job-1", status: "completed", outputs: [] };
      },
      onProgress: (job) => seen.push(job),
    });

    expect(completed.status).toBe("completed");
    expect(calls).toBe(2);
    expect(seen).toEqual([{ id: "job-1", status: "completed", outputs: [] }]);
  });

  it("treats active-job limit errors as recoverable generation interruptions", () => {
    expect(isRecoverableActiveGenerationError(new Error("ACTIVE_JOB_LIMIT_REACHED: Generation active job limit reached."))).toBe(true);
    expect(isRecoverableActiveGenerationError(new Error("IMAGE_PROVIDER_FAILED: provider rejected the prompt"))).toBe(false);
  });
});
