import { describe, expect, it } from "vitest";
import { pageForAuthState } from "./navigation";

describe("pageForAuthState", () => {
  it("sends unauthenticated users to the login page before generation", () => {
    expect(pageForAuthState("", "/generate")).toBe("/login");
  });

  it("sends authenticated users away from login to the generation page", () => {
    expect(pageForAuthState("token", "/login")).toBe("/generate");
  });
});
