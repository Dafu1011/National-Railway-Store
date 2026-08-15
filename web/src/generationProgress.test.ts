import { describe, expect, it } from "vitest";
import { generationProgress, nextLiveGenerationProgress } from "./generationProgress";

describe("generationProgress", () => {
  it("starts at zero before any generated output exists", () => {
    expect(generationProgress()).toBe(0);
  });

  it("uses the actual generated output count", () => {
    expect(generationProgress(1)).toBe(20);
    expect(generationProgress(3)).toBe(60);
    expect(generationProgress(5)).toBe(100);
  });

  it("clamps impossible output counts into the visible range", () => {
    expect(generationProgress(-1)).toBe(0);
    expect(generationProgress(9)).toBe(100);
  });

  it("uses live workflow progress while a generation request is running", () => {
    expect(generationProgress({ outputCount: 0, workflowPercent: 36, loading: true })).toBe(36);
    expect(generationProgress({ outputCount: 2, workflowPercent: 10, loading: true })).toBe(40);
    expect(generationProgress({ outputCount: 0, workflowPercent: 99, loading: true })).toBe(95);
  });

  it("falls back to the actual output count when generation is not running", () => {
    expect(generationProgress({ outputCount: 2, workflowPercent: 95, loading: false })).toBe(40);
    expect(generationProgress({ outputCount: 5, workflowPercent: 70, loading: false })).toBe(100);
  });

  it("advances the visible running progress without claiming completion early", () => {
    expect(nextLiveGenerationProgress(62, 0)).toBeGreaterThan(62);
    expect(nextLiveGenerationProgress(94, 0)).toBe(95);
    expect(nextLiveGenerationProgress(95, 0)).toBe(95);
    expect(nextLiveGenerationProgress(12, 3)).toBeGreaterThanOrEqual(60);
  });
});
