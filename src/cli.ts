#!/usr/bin/env node
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { parseCurt, serializeCurt, curtFilename } from "curt-format";
import { convertChat, GENERATOR } from "./convert.js";
import { fetchAllChats, parseExport } from "./source.js";

interface Args {
  input?: string;
  outDir: string;
  help: boolean;
}

function usage(): string {
  return `curt-openwebui-export — convert Open WebUI chats to .curt files

Usage:
  curt-openwebui-export <chat-export.json|chat-export.ndjson> [-o OUTDIR]
  OPENWEBUI_BASE_URL=https://... OPENWEBUI_API_KEY=... curt-openwebui-export [-o OUTDIR]

Options:
  -o, --outdir <dir>   Output directory (default: ./curt-export)
  -h, --help           Show this help

Reads a chat export file (Settings > Chats > Export, or GET /api/v1/chats/all
NDJSON), or fetches all chats from the API when OPENWEBUI_BASE_URL and
OPENWEBUI_API_KEY are set and no input file is given. Writes one .curt v1
file per chat, validated with parseCurt before writing.`;
}

function parseArgs(argv: string[]): Args {
  const args: Args = { outDir: "curt-export", help: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "-h" || a === "--help") args.help = true;
    else if (a === "-o" || a === "--outdir") args.outDir = argv[++i] ?? args.outDir;
    else if (!a.startsWith("-")) args.input = a;
  }
  return args;
}

async function main(): Promise<number> {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log(usage());
    return 0;
  }

  let raw: string;
  if (args.input) {
    raw = await readFile(resolve(args.input), "utf8");
  } else {
    const baseUrl = process.env.OPENWEBUI_BASE_URL;
    const apiKey = process.env.OPENWEBUI_API_KEY;
    if (!baseUrl || !apiKey) {
      console.error(
        "No input file given and OPENWEBUI_BASE_URL / OPENWEBUI_API_KEY are not set."
      );
      console.error(usage());
      return 1;
    }
    console.error(`Fetching chats from ${baseUrl} ...`);
    const chats = await fetchAllChats({ baseUrl, apiKey });
    raw = chats.map((c) => JSON.stringify(c)).join("\n");
  }

  const { chats, format } = parseExport(raw);
  console.error(`Parsed ${chats.length} chat(s) from ${format} export.`);

  await mkdir(args.outDir, { recursive: true });

  const version = process.env.npm_package_version ?? "1.0.0";
  const generator = `${GENERATOR}@${version}`;
  let written = 0;
  let empty = 0;
  const totals = { messages: 0, skippedRoles: 0, skippedBranches: 0 };

  for (const chat of chats) {
    const { conversation, stats } = convertChat(chat, version);
    totals.messages += stats.messages;
    totals.skippedRoles += stats.skippedRoles;
    totals.skippedBranches += stats.skippedBranches;

    if (conversation.messages.length === 0) {
      empty++;
      continue;
    }

    // Validate with the reference parser before writing anything to disk.
    const body = serializeCurt(conversation, generator);
    const check = parseCurt(body);
    if (check === null) {
      console.error(`VALIDATION FAILED for chat ${chat.id} — skipped.`);
      continue;
    }
    const path = resolve(args.outDir, curtFilename(conversation));
    await mkdir(dirname(path), { recursive: true });
    await writeFile(path, body, "utf8");
    written++;
    console.error(`wrote ${path} (${stats.messages} messages)`);
  }

  console.error(
    `Done: ${written} .curt file(s), ${totals.messages} messages. ` +
      `${empty} empty chat(s) skipped` +
      (totals.skippedRoles ? `, ${totals.skippedRoles} message(s) with unsupported roles dropped` : "") +
      (totals.skippedBranches ? `, ${totals.skippedBranches} regenerate-variant message(s) on non-current branches dropped` : "") +
      "."
  );
  return 0;
}

main().then(
  (code) => process.exit(code),
  (err) => {
    console.error(`error: ${err instanceof Error ? err.message : err}`);
    process.exit(1);
  }
);
