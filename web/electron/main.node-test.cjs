const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { test } = require("node:test");

const { buildProxyTarget, normalizeApiBaseUrl, resolveApiBaseUrl } = require("./main.cjs");

test("normalizeApiBaseUrl defaults to the local FastAPI backend", () => {
  assert.equal(normalizeApiBaseUrl(), "http://127.0.0.1:8000");
});

test("normalizeApiBaseUrl removes trailing slashes and ignores paths", () => {
  assert.equal(normalizeApiBaseUrl("http://localhost:9000/api/v1/"), "http://localhost:9000");
});

test("buildProxyTarget keeps API path and query on the configured backend origin", () => {
  assert.equal(
    buildProxyTarget("/api/v1/projects/abc/outputs?limit=5", "http://api.local:8000/"),
    "http://api.local:8000/api/v1/projects/abc/outputs?limit=5",
  );
});

test("resolveApiBaseUrl selects the local backend that exposes the Zhifeng ready endpoint", async () => {
  const calls = [];
  const selected = await resolveApiBaseUrl({
    rawValue: "",
    candidateBaseUrls: ["http://127.0.0.1:8000", "http://127.0.0.1:8010"],
    fetchImpl: async (url) => {
      calls.push(url.toString());
      return { ok: url.toString() === "http://127.0.0.1:8010/api/v1/health/ready" };
    },
  });

  assert.equal(selected, "http://127.0.0.1:8010");
  assert.deepEqual(calls, [
    "http://127.0.0.1:8000/api/v1/health/ready",
    "http://127.0.0.1:8010/api/v1/health/ready",
  ]);
});

test("isSafeExternalUrl only allows http and https schemes", () => {
  const { isSafeExternalUrl } = require("./main.cjs");
  assert.equal(isSafeExternalUrl("https://example.com/help"), true);
  assert.equal(isSafeExternalUrl("http://example.com/help"), true);
  assert.equal(isSafeExternalUrl("file:///C:/Windows/System32/calc.exe"), false);
  assert.equal(isSafeExternalUrl("javascript:alert(1)"), false);
});

test("renderer server falls back to index for malformed URL escapes", async () => {
  const { createRendererServer } = require("./main.cjs");
  const fixture = createRendererFixture();
  const server = await createRendererServer({ distDir: fixture.distDir });
  try {
    const response = await fetch(`${server.url}/%E0%A4%A`);
    assert.equal(response.status, 200);
    assert.equal(await response.text(), "INDEX_OK");
  } finally {
    await server.close();
    fs.rmSync(fixture.rootDir, { recursive: true, force: true });
  }
});

test("renderer server does not serve sibling files through encoded traversal", async () => {
  const { createRendererServer } = require("./main.cjs");
  const fixture = createRendererFixture();
  fs.writeFileSync(path.join(fixture.rootDir, "dist-secret.txt"), "SECRET");
  const server = await createRendererServer({ distDir: fixture.distDir });
  try {
    const response = await fetch(`${server.url}/..%2Fdist-secret.txt`);
    assert.equal(response.status, 200);
    assert.equal(await response.text(), "INDEX_OK");
  } finally {
    await server.close();
    fs.rmSync(fixture.rootDir, { recursive: true, force: true });
  }
});

function createRendererFixture() {
  const rootDir = fs.mkdtempSync(path.join(os.tmpdir(), "zhifeng-renderer-"));
  const distDir = path.join(rootDir, "dist");
  fs.mkdirSync(distDir);
  fs.writeFileSync(path.join(distDir, "index.html"), "INDEX_OK");
  return { distDir, rootDir };
}
