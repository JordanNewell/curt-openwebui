import test from "node:test";
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { readdir, readFile, mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { parseCurt } from "curt-format";

const here = dirname(fileURLToPath(import.meta.url));
const cli = join(here, "..", "src", "cli.js");
const fixture = join(here, "fixtures", "chat-export.ndjson");

function run(args: string[], env: NodeJS.ProcessEnv): Promise<{ code: number; stdout: string; stderr: string }> {
  return new Promise((resolve, reject) => {
    execFile(
      process.execPath,
      [cli, ...args],
      { env: { ...process.env, ...env } },
      (err, stdout, stderr) => {
        const code = (err as (NodeJS.ErrnoException & { code?: number }) | null)?.code ?? 0;
        if (err && typeof code !== "number") return reject(err);
        resolve({ code: code ?? 0, stdout, stderr });
      }
    );
  });
}

test("CLI converts the NDJSON fixture into validated .curt files", async () => {
  const outDir = await mkdtemp(join(tmpdir(), "curt-owui-"));
  const { code, stderr } = await run([fixture, "-o", outDir], {});

  assert.equal(code, 0, stderr);
  // 3 of 4 chats have messages; the empty one is skipped
  const files = (await readdir(outDir)).filter((f) => f.endsWith(".curt"));
  assert.equal(files.length, 3);

  let totalMessages = 0;
  for (const f of files) {
    const body = await readFile(join(outDir, f), "utf8");
    const parsed = parseCurt(body);
    assert.ok(parsed !== null, `${f} failed parseCurt validation`);
    assert.equal(parsed.provider, "Open WebUI");
    assert.match(body, /"generator": "curt-openwebui-export@/);
    totalMessages += parsed.messages.length;
  }
  // 3 + 3 + 3 across the three non-empty chats
  assert.equal(totalMessages, 9);
  assert.match(stderr, /1 empty chat\(s\) skipped/);
  assert.match(stderr, /1 regenerate-variant message\(s\)/);
});

test("CLI errors when neither input nor API env vars are present", async () => {
  const { code, stderr } = await run([], {
    OPENWEBUI_BASE_URL: "",
    OPENWEBUI_API_KEY: "",
  });
  assert.equal(code, 1);
  assert.match(stderr, /OPENWEBUI_BASE_URL/);
});

test("CLI help exits 0", async () => {
  const { code } = await run(["--help"], {});
  assert.equal(code, 0);
});
