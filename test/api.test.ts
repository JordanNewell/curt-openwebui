import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { fetchAllChats } from "../src/source.js";

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

test("fetchAllChats hits /api/v1/chats/all with bearer auth and parses NDJSON", async () => {
  const { impl, calls } = fakeFetch(ndjson);
  const chats = await fetchAllChats({
    baseUrl: "http://openwebui.example:8080/",
    apiKey: "sk-fixture-token",
    fetchImpl: impl,
  });

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "http://openwebui.example:8080/api/v1/chats/all");
  assert.equal(
    (calls[0].init?.headers as Record<string, string>).Authorization,
    "Bearer sk-fixture-token"
  );
  assert.equal(chats.length, 4);
  assert.equal(chats[0].title, "Fixture: modern tree chat");
});

test("fetchAllChats throws on non-2xx responses", async () => {
  const { impl } = fakeFetch('{"detail":"Not authenticated"}', 401);
  await assert.rejects(
    () =>
      fetchAllChats({
        baseUrl: "http://openwebui.example:8080",
        apiKey: "bad",
        fetchImpl: impl,
      }),
    /401/
  );
});
