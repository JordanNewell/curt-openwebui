import { describe, expect, it } from "vitest";
import { execFile } from "node:child_process";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { parseCurt } from "curt-format";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, "..");
const cli = join(repoRoot, "dist", "src", "cli.js");
const fixture = join(here, "fixtures", "chat-export.ndjson");

const cliBuilt = existsSync(cli);

function run(
  args: string[],
  env: NodeJS.ProcessEnv
): Promise<{ code: number; stdout: string; stderr: string }> {
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

describe("CLI output writing", () => {
  it.skipIf(!cliBuilt)(
    "converts the NDJSON fixture into validated .curt files",
    async () => {
      const outDir = mkdtempSync(join(tmpdir(), "curt-owui-"));
      const { code, stderr } = await run([fixture, "-o", outDir], {});

      expect(code).toBe(0);
      // 3 of 4 chats have messages; the empty one is skipped
      const files = readdirSync(outDir).filter((f) => f.endsWith(".curt"));
      expect(files.length).toBe(3);

      let totalMessages = 0;
      for (const f of files) {
        const body = readFileSync(join(outDir, f), "utf8");
        const parsed = parseCurt(body);
        expect(parsed).not.toBeNull();
        expect(parsed!.provider).toBe("Open WebUI");
        expect(body).toMatch(/"generator": "curt-openwebui-export@/);
        totalMessages += parsed!.messages.length;
      }
      // 3 + 3 + 3 across the three non-empty chats
      expect(totalMessages).toBe(9);
      expect(stderr).toMatch(/1 empty chat\(s\) skipped/);
      expect(stderr).toMatch(/1 regenerate-variant message\(s\)/);
    }
  );

  it.skipIf(!cliBuilt)(
    "errors when neither input nor API env vars are present",
    async () => {
      const { code, stderr } = await run([], {
        OPENWEBUI_BASE_URL: "",
        OPENWEBUI_API_KEY: "",
      });
      expect(code).toBe(1);
      expect(stderr).toMatch(/OPENWEBUI_BASE_URL/);
    }
  );

  it.skipIf(!cliBuilt)("help exits 0", async () => {
    const { code } = await run(["--help"], {});
    expect(code).toBe(0);
  });
});
