import type { OpenWebUIChat, ExportFormat } from "./types.js";

/**
 * Parse an Open WebUI chat export payload.
 *
 * Two shapes occur in the wild:
 * - NDJSON: one ChatResponse JSON object per line — what GET /api/v1/chats/all
 *   streams (routers/chats.py generate_chat_export_ndjson) and what recent UI
 *   "Export chats" downloads produce.
 * - A JSON array of ChatResponse objects — older UI export files.
 */
export function parseExport(raw: string): {
  chats: OpenWebUIChat[];
  format: ExportFormat;
} {
  const text = raw.replace(/^﻿/, "").trim();
  if (text.startsWith("[")) {
    const parsed = JSON.parse(text);
    if (!Array.isArray(parsed)) {
      throw new Error("Export file is a JSON document but not an array");
    }
    return { chats: parsed as OpenWebUIChat[], format: "array" };
  }
  const chats: OpenWebUIChat[] = [];
  for (const [i, line] of text.split(/\r?\n/).entries()) {
    const trimmed = line.trim();
    if (trimmed.length === 0) continue;
    try {
      chats.push(JSON.parse(trimmed) as OpenWebUIChat);
    } catch (err) {
      throw new Error(
        `NDJSON parse error on line ${i + 1}: ${(err as Error).message}`
      );
    }
  }
  return { chats, format: "ndjson" };
}

export type FetchImpl = (url: string, init?: RequestInit) => Promise<Response>;

export interface ApiOptions {
  baseUrl: string;
  apiKey: string;
  fetchImpl?: FetchImpl;
}

/**
 * Fetch every chat for the authenticated user from
 * GET {base}/api/v1/chats/all (Bearer token auth, NDJSON stream).
 */
export async function fetchAllChats(options: ApiOptions): Promise<OpenWebUIChat[]> {
  const fetchImpl = options.fetchImpl ?? fetch;
  const base = options.baseUrl.replace(/\/+$/, "");
  const res = await fetchImpl(`${base}/api/v1/chats/all`, {
    headers: {
      Authorization: `Bearer ${options.apiKey}`,
      Accept: "application/x-ndjson",
    },
  });
  if (!res.ok) {
    throw new Error(`Open WebUI API returned ${res.status} ${res.statusText}`);
  }
  return parseExport(await res.text()).chats;
}
