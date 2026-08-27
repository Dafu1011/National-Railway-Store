const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const projectRoot = path.resolve(__dirname, "..");
const portableAppDir = path.join(projectRoot, "desktop-portable", "huizhizuo");
const portableInstallerDir = path.join(projectRoot, "desktop-installer");
const portableInstallerCurrentDir = path.join(projectRoot, "desktop-installer-single");
const portableDisplayExeName = "绘智作.exe";

function main() {
  if (process.argv.includes("--prepare-only")) {
    preparePortableApp();
    return;
  }

  runElectronBuilder(["--win", "--dir", "--config.directories.output=desktop-release"], { allowFailure: true });
  preparePortableApp();
  fs.rmSync(portableInstallerCurrentDir, { recursive: true, force: true });
  runElectronBuilder([
    "--prepackaged",
    portableAppDir,
    "--win",
    "portable",
    `--config.directories.output=${path.relative(projectRoot, portableInstallerCurrentDir)}`,
  ]);
  mirrorCurrentInstallerToStableDirectory();
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

function preparePortableApp() {
  const runtimeDir = findRuntimeDir();
  ensureInside(runtimeDir, projectRoot);
  ensureInside(portableAppDir, projectRoot);

  fs.rmSync(portableAppDir, { recursive: true, force: true });
  fs.mkdirSync(portableAppDir, { recursive: true });
  copyDirectoryContents(runtimeDir, portableAppDir);

  const appDir = path.join(portableAppDir, "resources", "app");
  fs.rmSync(appDir, { recursive: true, force: true });
  fs.mkdirSync(appDir, { recursive: true });
  fs.cpSync(path.join(projectRoot, "dist"), path.join(appDir, "dist"), { recursive: true });
  fs.cpSync(path.join(projectRoot, "electron"), path.join(appDir, "electron"), { recursive: true });
  fs.copyFileSync(path.join(projectRoot, "package.json"), path.join(appDir, "package.json"));
  fs.writeFileSync(path.join(portableAppDir, "main.cjs"), portableMainShimContents(), "utf8");

  assertPreparedApp(appDir);

  const electronExe = path.join(portableAppDir, "electron.exe");
  if (!fs.existsSync(electronExe)) {
    throw new Error(`Electron runtime is missing ${electronExe}`);
  }
  const portableDisplayExe = path.join(portableAppDir, portableDisplayExeName);
  const portableIconSourceExe = path.join(portableAppDir, "huizhizuo-icon-source.exe");
  fs.copyFileSync(electronExe, portableIconSourceExe);
  applyPortableExeIcon(portableIconSourceExe);
  fs.copyFileSync(portableIconSourceExe, portableDisplayExe);
  fs.rmSync(portableIconSourceExe, { force: true });
  console.log(`Prepared portable app: ${portableAppDir}`);
}

function findRuntimeDir() {
  const candidates = [
    path.join(projectRoot, "desktop-release", "win-unpacked"),
    path.join(projectRoot, "desktop-release", "win-unpacked.tmp"),
    path.join(projectRoot, "release", "win-unpacked"),
    path.join(projectRoot, "release", "win-unpacked.tmp"),
  ];
  const runtimeDir = candidates.find((candidate) => fs.existsSync(path.join(candidate, "electron.exe")));
  if (!runtimeDir) {
    throw new Error(
      [
        "Electron runtime was not found.",
        "Run `pnpm run build` and then `pnpm exec electron-builder --win --dir --config.directories.output=desktop-release` first.",
        "If that command fails with EPERM after extraction, this script can still use `desktop-release/win-unpacked.tmp`.",
      ].join(" "),
    );
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

function ensureInside(childPath, parentPath) {
  const child = path.resolve(childPath);
  const parent = path.resolve(parentPath);
  const relativePath = path.relative(parent, child);
  if (relativePath.startsWith("..") || path.isAbsolute(relativePath)) {
    throw new Error(`Refusing to write outside project root: ${child}`);
  }
}

function assertPreparedApp(appDir) {
  const requiredFiles = [
    path.join(appDir, "package.json"),
    path.join(appDir, "dist", "index.html"),
    path.join(appDir, "electron", "main.cjs"),
  ];
  for (const requiredFile of requiredFiles) {
    if (!fs.existsSync(requiredFile)) {
      throw new Error(`Prepared portable app is missing ${requiredFile}`);
    }
  }
}

function portableMainShimContents() {
  return 'require("./resources/app/electron/main.cjs");\n';
}

function portableIconPath() {
  return path.join(projectRoot, "public", "brand", "hz-logo.ico");
}

function rceditIconArgs(exePath) {
  return [exePath, "--set-icon", portableIconPath()];
}

function applyPortableExeIcon(exePath) {
  if (process.platform !== "win32") {
    return;
  }

  const iconPath = portableIconPath();
  if (!fs.existsSync(iconPath)) {
    throw new Error(`Portable app icon is missing ${iconPath}`);
  }

  const rceditPath = findRceditExe();
  if (!rceditPath) {
    throw new Error("rcedit.exe was not found; cannot stamp the portable app icon.");
  }

  const result = spawnSync(rceditPath, rceditIconArgs(exePath), {
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

function mirrorCurrentInstallerToStableDirectory() {
  try {
    fs.rmSync(portableInstallerDir, { recursive: true, force: true });
    fs.mkdirSync(portableInstallerDir, { recursive: true });
    copyDirectoryContents(portableInstallerCurrentDir, portableInstallerDir);
  } catch (error) {
    console.warn(
      [
        `Portable installer was created in ${portableInstallerCurrentDir}.`,
        `Could not mirror it to ${portableInstallerDir}: ${error.message}`,
        "Close any running old installer executable and copy from desktop-installer-single if you need the stable folder.",
      ].join(" "),
    );
  }
}

if (require.main === module) {
  main();
}

module.exports = {
  portableIconPath,
  portableMainShimContents,
  rceditIconArgs,
};
