import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { fetchAllChats, parseExport } from "../src/source.js";

const here = dirname(fileURLToPath(import.meta.url));
const ndjson = readFileSync(join(here, "fixtures", "chat-export.ndjson"), "utf8");

function fakeFetch(body: string, status = 200) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const impl = (async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return new Response(body, { status });
  }) as unknown as typeof fetch;
  return { impl, calls };
}

describe("fetchAllChats", () => {
  it("hits /api/v1/chats/all with bearer auth and parses the NDJSON stream", async () => {
    const { impl, calls } = fakeFetch(ndjson);
    const chats = await fetchAllChats({
      baseUrl: "http://openwebui.example:8080/",
      apiKey: "sk-fixture-token",
      fetchImpl: impl,
    });

    expect(calls.length).toBe(1);
    expect(calls[0].url).toBe("http://openwebui.example:8080/api/v1/chats/all");
    expect(
      (calls[0].init?.headers as Record<string, string>).Authorization
    ).toBe("Bearer sk-fixture-token");
    expect(chats.length).toBe(4);
    expect(chats[0].title).toBe("Fixture: modern tree chat");
  });

  it("strips trailing slashes from the base URL", async () => {
    const { impl, calls } = fakeFetch(ndjson);
    await fetchAllChats({ baseUrl: "http://x.example///", apiKey: "k", fetchImpl: impl });
    expect(calls[0].url).toBe("http://x.example/api/v1/chats/all");
  });

  it("throws on non-2xx responses", async () => {
    const { impl } = fakeFetch('{"detail":"Not authenticated"}', 401);
    await expect(
      fetchAllChats({
        baseUrl: "http://openwebui.example:8080",
        apiKey: "bad",
        fetchImpl: impl,
      })
    ).rejects.toThrow(/401/);
  });
});

describe("parseExport (NDJSON reader used by the API path)", () => {
  it("returns chats in stream order, one JSON object per line", () => {
    const chats = parseExport(ndjson).chats;
    expect(chats.map((c) => c.id)).toEqual([
      "fc2e91a0-1111-4aaa-8bbb-000000000001",
      "fc2e91a0-2222-4aaa-8bbb-000000000002",
      "fc2e91a0-3333-4aaa-8bbb-000000000003",
      "fc2e91a0-4444-4aaa-8bbb-000000000004",
    ]);
  });

  it("tolerates batch boundaries: blank lines, CRLF, missing final newline", () => {
    const raw = '{"id":"a"}\r\n\r\n{"id":"b"}\r\n{"id":"c"}';
    const { chats, format } = parseExport(raw);
    expect(format).toBe("ndjson");
    expect(chats.map((c) => c.id)).toEqual(["a", "b", "c"]);
  });

  it("reports the failing line number on malformed input", () => {
    const lines = [
      JSON.stringify({ id: "ok-1" }),
      "",
      "not-json",
      JSON.stringify({ id: "never-reached" }),
    ];
    expect(() => parseExport(lines.join("\n"))).toThrow(/line 3/);
  });
});
