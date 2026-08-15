const assert = require("node:assert/strict");
const fs = require("node:fs");
const Module = require("node:module");
const path = require("node:path");
const { test } = require("node:test");

test("portable main shim loads the packaged Electron app entry", () => {
  const { portableMainShimContents } = loadBuildPortableModuleForTest();
  assert.equal(
    portableMainShimContents(),
    'require("./resources/app/electron/main.cjs");\n',
  );
});

test("portable main shim does not bake local absolute paths into the exe", () => {
  const { portableMainShimContents } = loadBuildPortableModuleForTest();
  assert.equal(portableMainShimContents().includes("D:\\"), false);
  assert.equal(portableMainShimContents().includes("C:\\"), false);
});

test("portable app executable uses the ZF icon resource", () => {
  const { portableIconPath, rceditIconArgs } = loadBuildPortableModuleForTest();
  const projectRoot = path.resolve(__dirname, "..");
  const iconPath = path.join(projectRoot, "public", "brand", "zf-logo.ico");

  assert.equal(portableIconPath(), iconPath);
  assert.deepEqual(rceditIconArgs("app.exe"), ["app.exe", "--set-icon", iconPath]);
});

function loadBuildPortableModuleForTest() {
  const filename = path.join(__dirname, "build-portable.cjs");
  const source = fs.readFileSync(filename, "utf8").replace(/\nmain\(\);\s*$/, "\n");
  const mod = new Module(filename, module);
  mod.filename = filename;
  mod.paths = Module._nodeModulePaths(path.dirname(filename));
  mod._compile(source, filename);
  return mod.exports;
}
