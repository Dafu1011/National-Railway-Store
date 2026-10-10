const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const projectRoot = path.resolve(__dirname, "..");
const releaseDir = path.join(projectRoot, "desktop-release");
const prepackagedAppDir = path.join(projectRoot, "desktop-prepackaged", "huizhizuo");
const productExeName = "绘智作.exe";

function main() {
  cleanRuntimeStagingDirs();
  runElectronBuilder(["--win", "--dir", "--config.directories.output=desktop-release"], { allowFailure: true });
  preparePrepackagedApp();
  runElectronBuilder([
    "--prepackaged",
    prepackagedAppDir,
    "--win",
    "nsis",
    "--config.directories.output=desktop-release",
  ]);
}

function runElectronBuilder(args, { allowFailure = false } = {}) {
  const builderCli = require.resolve("electron-builder/cli.js");
  const result = spawnSync(process.execPath, [builderCli, ...args], {
    cwd: projectRoot,
    env: process.env,
    stdio: "inherit",
  });

  if (result.status !== 0 && !allowFailure) {
    process.exit(result.status || 1);
  }

  return result.status === 0;
}

function cleanRuntimeStagingDirs() {
  removeInsideProject(path.join(releaseDir, "win-unpacked"));
  removeInsideProject(path.join(releaseDir, "win-unpacked.tmp"));
  removeInsideProject(path.join(releaseDir, "builder-effective-config.yaml"));
}

function preparePrepackagedApp() {
  const runtimeDir = findRuntimeDir();
  ensureInside(runtimeDir, projectRoot);
  ensureInside(prepackagedAppDir, projectRoot);

  removeInsideProject(prepackagedAppDir);
  fs.mkdirSync(prepackagedAppDir, { recursive: true });
  copyDirectoryContents(runtimeDir, prepackagedAppDir);

  const appDir = path.join(prepackagedAppDir, "resources", "app");
  removeInsideProject(appDir);
  removeInsideProject(path.join(prepackagedAppDir, "resources", "app.asar"));
  fs.mkdirSync(appDir, { recursive: true });
  fs.cpSync(path.join(projectRoot, "dist"), path.join(appDir, "dist"), { recursive: true });
  fs.cpSync(path.join(projectRoot, "electron"), path.join(appDir, "electron"), { recursive: true });
  fs.copyFileSync(path.join(projectRoot, "package.json"), path.join(appDir, "package.json"));

  const electronExe = path.join(prepackagedAppDir, "electron.exe");
  const productExe = path.join(prepackagedAppDir, productExeName);
  if (!fs.existsSync(electronExe) && !fs.existsSync(productExe)) {
    throw new Error(`Electron runtime is missing ${electronExe}`);
  }
  const iconSourceExe = path.join(prepackagedAppDir, "huizhizuo-icon-source.exe");
  if (fs.existsSync(electronExe)) {
    fs.copyFileSync(electronExe, iconSourceExe);
    applyExeIcon(iconSourceExe);
    fs.copyFileSync(iconSourceExe, productExe);
    fs.rmSync(electronExe, { force: true });
  } else {
    fs.copyFileSync(productExe, iconSourceExe);
    applyExeIcon(iconSourceExe);
    fs.copyFileSync(iconSourceExe, productExe);
  }
  fs.rmSync(iconSourceExe, { force: true });
  assertPrepackagedApp(appDir, productExe);
  console.log(`Prepared NSIS app: ${prepackagedAppDir}`);
}

function findRuntimeDir() {
  const candidates = [
    path.join(releaseDir, "win-unpacked"),
    path.join(releaseDir, "win-unpacked.tmp"),
  ];
  const runtimeDir = candidates.find((candidate) =>
    fs.existsSync(path.join(candidate, "electron.exe")) || fs.existsSync(path.join(candidate, productExeName)),
  );
  if (!runtimeDir) {
    throw new Error("Electron runtime was not found after electron-builder --dir.");
  }
  return runtimeDir;
}

function copyDirectoryContents(sourceDir, targetDir) {
  for (const entry of fs.readdirSync(sourceDir, { withFileTypes: true })) {
    const sourcePath = path.join(sourceDir, entry.name);
    const targetPath = path.join(targetDir, entry.name);
    fs.cpSync(sourcePath, targetPath, { recursive: true });
  }
}

function applyExeIcon(exePath) {
  if (process.platform !== "win32") {
    return;
  }

  const iconPath = path.join(projectRoot, "public", "brand", "hz-logo.ico");
  if (!fs.existsSync(iconPath)) {
    throw new Error(`App icon is missing ${iconPath}`);
  }

  const rceditPath = findRceditExe();
  if (!rceditPath) {
    throw new Error("rcedit.exe was not found; cannot stamp the packaged app icon.");
  }

  const result = spawnSync(rceditPath, [exePath, "--set-icon", iconPath], {
    cwd: projectRoot,
    stdio: "inherit",
  });
  if (result.status !== 0) {
    throw new Error(`rcedit.exe failed while stamping ${exePath}`);
  }
}

function findRceditExe() {
  const directCandidates = [
    path.join(projectRoot, "node_modules", "rcedit", "bin", "rcedit.exe"),
    path.join(projectRoot, "node_modules", "electron-winstaller", "vendor", "rcedit.exe"),
  ];
  for (const candidate of directCandidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }

  const pnpmStore = path.join(projectRoot, "node_modules", ".pnpm");
  if (!fs.existsSync(pnpmStore)) {
    return null;
  }

  const pending = [pnpmStore];
  while (pending.length > 0) {
    const current = pending.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const entryPath = path.join(current, entry.name);
      if (entry.isFile() && entry.name.toLowerCase() === "rcedit.exe") {
        return entryPath;
      }
      if (entry.isDirectory()) {
        pending.push(entryPath);
      }
    }
  }
  return null;
}

function assertPrepackagedApp(appDir, productExe) {
  const requiredFiles = [
    productExe,
    path.join(appDir, "package.json"),
    path.join(appDir, "dist", "index.html"),
    path.join(appDir, "electron", "main.cjs"),
  ];
  for (const requiredFile of requiredFiles) {
    if (!fs.existsSync(requiredFile)) {
      throw new Error(`Prepared NSIS app is missing ${requiredFile}`);
    }
  }
}

function removeInsideProject(targetPath) {
  ensureInside(targetPath, projectRoot);
  fs.rmSync(targetPath, { recursive: true, force: true });
}

function ensureInside(childPath, parentPath) {
  const child = path.resolve(childPath);
  const parent = path.resolve(parentPath);
  const relativePath = path.relative(parent, child);
  if (relativePath.startsWith("..") || path.isAbsolute(relativePath)) {
    throw new Error(`Refusing to write outside project root: ${child}`);
  }
}

if (require.main === module) {
  main();
}

module.exports = {
  prepackagedAppDir,
  productExeName,
};

