/**
 * Runs both Python test suites (`python -m pytest functions/tests pipelines/tests`).
 * Exits 0 with a message if no Python interpreter is available so the JS
 * suite alone still passes `npm test`.
 */
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..");

function findPython() {
  for (const cmd of ["python", "python3"]) {
    const probe = spawnSync(cmd, ["-c", "import sys; sys.exit(0)"], {
      cwd: repoRoot,
      encoding: "utf8",
    });
    if (probe.status === 0) return cmd;
  }
  return null;
}

const python = findPython();
if (!python) {
  console.error(
    "[curt-openwebui] Python not found — skipping the Python test suites " +
      "(functions/tests, pipelines/tests). Install Python 3.10+ to run the full test matrix."
  );
  process.exit(0);
}

const res = spawnSync(
  python,
  ["-m", "pytest", "functions/tests", "pipelines/tests", "-q"],
  {
    cwd: repoRoot,
    stdio: "inherit",
  }
);
process.exit(res.status ?? 1);
