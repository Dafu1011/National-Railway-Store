const fs = require("node:fs");
const http = require("node:http");
const https = require("node:https");
const path = require("node:path");

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
  const { BrowserWindow, app, shell } = require("electron");
  let rendererServer = null;

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
  buildProxyTarget,
  createRendererServer,
  isSafeExternalUrl,
  normalizeApiBaseUrl,
  resolveWindowIconPath,
  resolveApiBaseUrl,
  resolveStaticCandidate,
};

function isSafeExternalUrl(rawUrl) {
  try {
    const url = new URL(rawUrl);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}
