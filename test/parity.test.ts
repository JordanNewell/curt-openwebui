/**
 * Drift-guard (see scripts/parity-check.md): the TypeScript CLI and the
 * Python pipeline must produce IDENTICAL .curt conversations from the same
 * chat payload. This test feeds test/fixtures/chat-export.ndjson through both
 * implementations and deep-compares the results. Skipped with a clear
 * message when Python is not available.
 */
import { describe, expect, it } from "vitest";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { convertChat } from "../src/convert.js";
import { parseExport } from "../src/source.js";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, "..");
const fixture = join(here, "fixtures", "chat-export.ndjson");

/** Find a runnable python interpreter, or null. */
function findPython(): string | null {
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

describe("CLI/pipeline parity", () => {
  it.skipIf(python === null)(
    "pipeline convert_chat matches the CLI conversation for every fixture chat",
    () => {
      const probe = spawnSync(
        python!,
        [
          "-c",
          [
            "import json, sys",
            "sys.path.insert(0, 'pipelines')",
            "import curt_export_pipeline as cep",
            "out = []",
            "for line in open(sys.argv[1], encoding='utf-8'):",
            "    line = line.strip()",
            "    if not line:",
            "        continue",
            "    conv, stats = cep.convert_chat(json.loads(line))",
            "    out.append({'conversation': conv, 'stats': stats})",
            "print(json.dumps(out))",
          ].join("\n"),
          fixture,
        ],
        { cwd: repoRoot, encoding: "utf8" }
      );
      expect(probe.status).toBe(0);

      const pyResults: {
        conversation: ReturnType<typeof convertChat>["conversation"];
        stats: { skippedBranches: number; skippedHidden: number; skippedRoles: number };
      }[] = JSON.parse(probe.stdout);

      const chats = parseExport(readFileSync(fixture, "utf8")).chats;
      expect(chats.length).toBe(pyResults.length);

      for (let i = 0; i < chats.length; i++) {
        const { conversation, stats } = convertChat(chats[i], "1.0.0");
        const py = pyResults[i];

        // Identical message sequences: ids, roles, content, models,
        // passthrough fields and timestamps — the whole mapped message.
        expect(py.conversation.messages).toEqual(conversation.messages);

        // Identical conversation envelope, including the variant count
        // passthrough the README mapping table defines.
        expect(py.conversation).toEqual(conversation);

        // Identical counters.
        expect(py.stats.skippedBranches).toBe(stats.skippedBranches);
        expect(py.stats.skippedRoles).toBe(stats.skippedRoles);
        expect(py.stats.skippedHidden).toBe(stats.skippedHidden);
      }
    }
  );
});
