const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");

const packageJson = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "package.json"), "utf8"));

test("Windows NSIS installer supports user-selected install paths with elevation when needed", () => {
  const { productExeName } = require("./build-nsis.cjs");

  assert.match(packageJson.scripts["electron:dist"], /node electron\/build-nsis\.cjs/);
  assert.equal(packageJson.version, "2.0.23");
  assert.equal(productExeName, "绘智作.exe");
  assert.equal(packageJson.build.win.requestedExecutionLevel, "asInvoker");
  assert.equal(packageJson.build.nsis.oneClick, false);
  assert.equal(packageJson.build.nsis.allowToChangeInstallationDirectory, true);
  assert.equal(packageJson.build.nsis.perMachine, false);
  assert.equal(packageJson.build.nsis.allowElevation, true);
  assert.equal(packageJson.build.nsis.selectPerMachineByDefault, false);
});

