const { spawn } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");
const https = require("node:https");
const os = require("node:os");
const path = require("node:path");
const { Readable, Transform } = require("node:stream");
const { pipeline } = require("node:stream/promises");

const DEFAULT_API_BASE_URL = "http://124.174.70.182:8088";
const LOCAL_API_CANDIDATES = [DEFAULT_API_BASE_URL];
const API_READY_PATH = "/api/v1/health/ready";

const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".gif": "image/gif",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
};

function resolveWindowIconPath() {
  const candidates = [
    path.join(__dirname, "..", "dist", "brand", "zf-logo.ico"),
    path.join(__dirname, "..", "public", "brand", "zf-logo.ico"),
  ];
  return candidates.find((candidate) => fs.existsSync(candidate));
}

function normalizeApiBaseUrl(rawValue = process.env.ZHIFENG_API_BASE_URL) {
  const value = rawValue && rawValue.trim() ? rawValue : DEFAULT_API_BASE_URL;
  return new URL(value).origin;
}

function getCandidateApiBaseUrls(rawValue = process.env.ZHIFENG_API_BASE_URL, candidateBaseUrls = LOCAL_API_CANDIDATES) {
  const values = rawValue && rawValue.trim() ? [rawValue] : candidateBaseUrls;
  const seen = new Set();

  return values.reduce((urls, value) => {
    const normalized = normalizeApiBaseUrl(value);
    if (!seen.has(normalized)) {
      seen.add(normalized);
      urls.push(normalized);
    }
    return urls;
  }, []);
}

async function resolveApiBaseUrl({
  rawValue = process.env.ZHIFENG_API_BASE_URL,
  candidateBaseUrls = LOCAL_API_CANDIDATES,
  fetchImpl = globalThis.fetch,
  timeoutMs = 1200,
} = {}) {
  const candidates = getCandidateApiBaseUrls(rawValue, candidateBaseUrls);

  for (const candidate of candidates) {
    if (await isZhifengApiReady(candidate, { fetchImpl, timeoutMs })) {
      return candidate;
    }
  }

  return candidates[0] || normalizeApiBaseUrl(rawValue);
}

async function isZhifengApiReady(apiBaseUrl, { fetchImpl, timeoutMs }) {
  if (typeof fetchImpl !== "function") {
    return false;
  }

  const controller = typeof AbortController === "function" ? new AbortController() : null;
  const timeout = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;

  try {
    const response = await fetchImpl(new URL(API_READY_PATH, apiBaseUrl).toString(), {
      method: "GET",
      signal: controller ? controller.signal : undefined,
    });
    return Boolean(response && response.ok);
  } catch {
    return false;
  } finally {
    if (timeout) {
      clearTimeout(timeout);
    }
  }
}

function buildProxyTarget(requestUrl, apiBaseUrl = process.env.ZHIFENG_API_BASE_URL) {
  const incomingUrl = new URL(requestUrl, "http://renderer.local");
  return new URL(`${incomingUrl.pathname}${incomingUrl.search}`, normalizeApiBaseUrl(apiBaseUrl)).toString();
}

function createRendererServer({ distDir, apiBaseUrl = process.env.ZHIFENG_API_BASE_URL, host = "127.0.0.1", port = 0 }) {
  const resolvedDist = path.resolve(distDir);
  const server = http.createServer((request, response) => {
    if (!request.url) {
      response.writeHead(400);
      response.end("Bad request");
      return;
    }

    if (request.url.startsWith("/api/v1/") || request.url === "/api/v1") {
      proxyApiRequest(request, response, apiBaseUrl);
      return;
    }

    serveStaticFile(request, response, resolvedDist);
  });

  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, host, () => {
      server.off("error", reject);
      const address = server.address();
      const selectedPort = typeof address === "object" && address ? address.port : port;
      resolve({
        url: `http://${host}:${selectedPort}`,
        close: () =>
          new Promise((closeResolve, closeReject) => {
            server.close((error) => (error ? closeReject(error) : closeResolve()));
          }),
      });
    });
  });
}

function proxyApiRequest(request, response, apiBaseUrl) {
  const targetUrl = new URL(buildProxyTarget(request.url, apiBaseUrl));
  const transport = targetUrl.protocol === "https:" ? https : http;
  const headers = { ...request.headers, host: targetUrl.host };

  const proxyRequest = transport.request(
    {
      protocol: targetUrl.protocol,
      hostname: targetUrl.hostname,
      port: targetUrl.port,
      path: `${targetUrl.pathname}${targetUrl.search}`,
      method: request.method,
      headers,
    },
    (proxyResponse) => {
      response.writeHead(proxyResponse.statusCode || 502, proxyResponse.headers);
      proxyResponse.pipe(response);
    },
  );

  proxyRequest.on("error", (error) => {
    response.writeHead(502, { "content-type": "application/json; charset=utf-8" });
    response.end(
      JSON.stringify({
        code: "DESKTOP_API_PROXY_FAILED",
        message: `Could not reach Zhifeng API at ${normalizeApiBaseUrl(apiBaseUrl)}: ${error.message}`,
        details: {},
        request_id: "desktop-proxy",
      }),
    );
  });

  request.pipe(proxyRequest);
}

function serveStaticFile(request, response, distDir) {
  if (request.method !== "GET" && request.method !== "HEAD") {
    response.writeHead(405, { allow: "GET, HEAD" });
    response.end("Method not allowed");
    return;
  }

  const candidatePath = resolveStaticCandidate(request.url || "/", distDir);

  const filePath = fs.existsSync(candidatePath) && fs.statSync(candidatePath).isFile()
    ? candidatePath
    : path.join(distDir, "index.html");
  const extension = path.extname(filePath).toLowerCase();
  response.writeHead(200, { "content-type": contentTypes[extension] || "application/octet-stream" });

  if (request.method === "HEAD") {
    response.end();
    return;
  }

  fs.createReadStream(filePath).pipe(response);
}

function resolveStaticCandidate(requestUrl, distDir) {
  try {
    const url = new URL(requestUrl, "http://renderer.local");
    const pathname = decodeURIComponent(url.pathname);
    const relativePath = pathname === "/" ? "index.html" : pathname.replace(/^[/\\]+/, "");
    const candidatePath = path.resolve(distDir, relativePath);
    const relativeToDist = path.relative(distDir, candidatePath);

    if (relativeToDist.startsWith("..") || path.isAbsolute(relativeToDist)) {
      return path.join(distDir, "index.html");
    }
    return candidatePath;
  } catch {
    return path.join(distDir, "index.html");
  }
}

async function startElectronApp() {
  const { BrowserWindow, app, ipcMain, shell } = require("electron");
  let rendererServer = null;

  registerUpdateIpc({ app, ipcMain });

  async function createMainWindow() {
    const windowOptions = {
      width: 1440,
      height: 940,
      minWidth: 1160,
      minHeight: 720,
      autoHideMenuBar: true,
      backgroundColor: "#eceeed",
      title: "Zhifeng Image",
      webPreferences: {
        contextIsolation: true,
        nodeIntegration: false,
        preload: path.join(__dirname, "preload.cjs"),
        sandbox: true,
      },
    };
    const windowIconPath = resolveWindowIconPath();
    if (windowIconPath) {
      windowOptions.icon = windowIconPath;
    }
    const window = new BrowserWindow(windowOptions);
    window.setMenu(null);
    window.setMenuBarVisibility(false);

    window.webContents.setWindowOpenHandler(({ url }) => {
      if (isSafeExternalUrl(url)) {
        shell.openExternal(url);
      }
      return { action: "deny" };
    });

    if (!app.isPackaged) {
      await window.loadURL(process.env.ELECTRON_RENDERER_URL || "http://127.0.0.1:5173");
      window.webContents.openDevTools({ mode: "detach" });
      return;
    }

    const distDir = path.join(__dirname, "..", "dist");
    const apiBaseUrl = await resolveApiBaseUrl();
    rendererServer = await createRendererServer({ distDir, apiBaseUrl });
    await window.loadURL(rendererServer.url);
  }

  await app.whenReady();
  await createMainWindow();

  app.on("activate", async () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      await createMainWindow();
    }
  });

  app.on("window-all-closed", async () => {
    if (rendererServer) {
      await rendererServer.close();
      rendererServer = null;
    }
    if (process.platform !== "darwin") {
      app.quit();
    }
  });
}

if (require.main === module) {
  startElectronApp().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}

module.exports = {
  buildUpdateDownloadUrl,
  buildProxyTarget,
  createRendererServer,
  downloadUpdateInstaller,
  isSafeExternalUrl,
  launchInstaller,
  normalizeApiBaseUrl,
  resolveWindowIconPath,
  resolveApiBaseUrl,
  resolveStaticCandidate,
  sha256File,
};

function isSafeExternalUrl(rawUrl) {
  try {
    const url = new URL(rawUrl);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

function registerUpdateIpc({ app, ipcMain }) {
  ipcMain.handle("updates:get-app-version", () => app.getVersion());
  ipcMain.handle("updates:install", async (event, update) => {
    const installerPath = await downloadUpdateInstaller(update, {
      appModule: app,
      onProgress: (progress) => event.sender.send("updates:download-progress", progress),
    });
    launchInstaller(installerPath);
    app.quit();
    return { installer_path: installerPath, launched: true };
  });
}

function buildUpdateDownloadUrl(downloadUrl, apiBaseUrl = process.env.ZHIFENG_API_BASE_URL) {
  const apiOrigin = normalizeApiBaseUrl(apiBaseUrl);
  const targetUrl = new URL(downloadUrl, apiOrigin);
  const apiUrl = new URL(apiOrigin);

  if (targetUrl.protocol !== "http:" && targetUrl.protocol !== "https:") {
    throw new Error("Update download URL must use http or https.");
  }
  if (targetUrl.origin !== apiUrl.origin) {
    throw new Error("Update download URL must stay on the configured API origin.");
  }

  return targetUrl.toString();
}

async function downloadUpdateInstaller(
  update,
  {
    apiBaseUrl = process.env.ZHIFENG_API_BASE_URL,
    appModule,
    fetchImpl = globalThis.fetch,
    onProgress,
  } = {},
) {
  const payload = normalizeUpdatePayload(update);
  if (typeof fetchImpl !== "function") {
    throw new Error("Update downloads require fetch support in the Electron main process.");
  }
  const downloadUrl = buildUpdateDownloadUrl(payload.download_url, apiBaseUrl);
  const response = await fetchImpl(downloadUrl);
  if (!response || !response.ok) {
    throw new Error(`Update download failed with HTTP ${response ? response.status : "unknown"}.`);
  }

  const updatesDir = resolveUpdatesDirectory(appModule);
  fs.mkdirSync(updatesDir, { recursive: true });
  const installerPath = path.join(updatesDir, installerFileName(payload));
  const contentLength = Number(response.headers && typeof response.headers.get === "function" ? response.headers.get("content-length") : 0);
  const totalBytes = payload.file_size_bytes > 0 ? payload.file_size_bytes : contentLength;

  try {
    await writeResponseBodyToFile(response, installerPath, { totalBytes, onProgress });
    assertDownloadedFileSize(installerPath, payload.file_size_bytes);
    assertDownloadedFileSha256(installerPath, payload.sha256);
    return installerPath;
  } catch (error) {
    fs.rmSync(installerPath, { force: true });
    throw error;
  }
}

function normalizeUpdatePayload(update) {
  if (!update || typeof update !== "object") {
    throw new Error("Update payload is required.");
  }
  if (typeof update.download_url !== "string" || !update.download_url.trim()) {
    throw new Error("Update download URL is required.");
  }
  if (typeof update.latest_version !== "string" || !update.latest_version.trim()) {
    throw new Error("Update latest version is required.");
  }

  return {
    download_url: update.download_url.trim(),
    latest_version: update.latest_version.trim(),
    sha256: typeof update.sha256 === "string" ? update.sha256.trim() : "",
    file_size_bytes: Number(update.file_size_bytes || 0),
    platform: typeof update.platform === "string" ? update.platform.trim() : "windows",
    arch: typeof update.arch === "string" ? update.arch.trim() : "x64",
  };
}

function resolveUpdatesDirectory(appModule) {
  if (appModule && typeof appModule.getPath === "function") {
    return path.join(appModule.getPath("userData"), "updates");
  }
  return path.join(os.tmpdir(), "zhifeng-image-updates");
}

async function writeResponseBodyToFile(response, filePath, { totalBytes = 0, onProgress } = {}) {
  emitDownloadProgress(onProgress, 0, totalBytes);
  if (!response.body) {
    const buffer = Buffer.from(await response.arrayBuffer());
    fs.writeFileSync(filePath, buffer);
    emitDownloadProgress(onProgress, buffer.length, totalBytes || buffer.length);
    return;
  }

  const readable = typeof response.body.pipe === "function" ? response.body : Readable.fromWeb(response.body);
  let receivedBytes = 0;
  const progressStream = new Transform({
    transform(chunk, _encoding, callback) {
      receivedBytes += chunk.length;
      emitDownloadProgress(onProgress, receivedBytes, totalBytes);
      callback(null, chunk);
    },
  });
  await pipeline(readable, progressStream, fs.createWriteStream(filePath));
  emitDownloadProgress(onProgress, receivedBytes, totalBytes || receivedBytes);
}

function emitDownloadProgress(onProgress, receivedBytes, totalBytes) {
  if (typeof onProgress !== "function") {
    return;
  }
  const safeReceived = Math.max(0, Number(receivedBytes) || 0);
  const safeTotal = Math.max(0, Number(totalBytes) || 0);
  const percent = safeTotal > 0 ? Math.min(100, Math.round((safeReceived / safeTotal) * 100)) : safeReceived > 0 ? 100 : 0;
  onProgress({
    percent,
    received_bytes: safeReceived,
    total_bytes: safeTotal,
  });
}

function assertDownloadedFileSize(filePath, expectedSize) {
  if (!Number.isFinite(expectedSize) || expectedSize <= 0) {
    return;
  }
  const actualSize = fs.statSync(filePath).size;
  if (actualSize !== expectedSize) {
    throw new Error(`Update installer size mismatch: expected ${expectedSize}, received ${actualSize}.`);
  }
}

function assertDownloadedFileSha256(filePath, expectedSha256) {
  if (!expectedSha256) {
    return;
  }
  const actualSha256 = sha256File(filePath);
  if (actualSha256.toLowerCase() !== expectedSha256.toLowerCase()) {
    throw new Error("Update installer checksum mismatch.");
  }
}

function sha256File(filePath) {
  const hash = crypto.createHash("sha256");
  hash.update(fs.readFileSync(filePath));
  return hash.digest("hex");
}

function installerFileName(update) {
  const version = sanitizeFileNamePart(update.latest_version);
  const arch = sanitizeFileNamePart(update.arch || "x64");
  return `zhifeng-image-${version}-${arch}.exe`;
}

function sanitizeFileNamePart(value) {
  return String(value || "release").replace(/[^a-zA-Z0-9._-]/g, "-");
}

function launchInstaller(installerPath, spawnImpl = spawn) {
  const child = spawnImpl(installerPath, [], {
    detached: true,
    stdio: "ignore",
  });
  if (child && typeof child.unref === "function") {
    child.unref();
  }
}
