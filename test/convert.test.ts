import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { isCurtConversation, parseCurt, serializeCurt } from "curt-format";
import { convertChat, flattenMessages } from "../src/convert.js";
import { parseExport } from "../src/source.js";
import type { OpenWebUIChat } from "../src/types.js";

const here = dirname(fileURLToPath(import.meta.url));
const fixturePath = join(here, "fixtures", "chat-export.ndjson");
const legacyArrayPath = join(here, "fixtures", "chat-export-legacy-array.json");

function loadFixtures(): OpenWebUIChat[] {
  return parseExport(readFileSync(fixturePath, "utf8")).chats;
}

test("parseExport handles NDJSON and array formats", () => {
  const nd = parseExport(readFileSync(fixturePath, "utf8"));
  assert.equal(nd.format, "ndjson");
  assert.equal(nd.chats.length, 4);

  const arr = parseExport(readFileSync(legacyArrayPath, "utf8"));
  assert.equal(arr.format, "array");
  assert.equal(arr.chats.length, 1);
});

test("parseExport rejects malformed NDJSON with a line number", () => {
  assert.throws(() => parseExport('{"id":"x"}\nnot-json\n'), /line 2/);
});

test("modern tree chat: exports current branch, skips regenerate variants", () => {
  const chats = loadFixtures();
  const { conversation, stats } = convertChat(chats[0], "1.0.0");

  assert.equal(conversation.id, "fc2e91a0-1111-4aaa-8bbb-000000000001");
  assert.equal(conversation.title, "Fixture: modern tree chat");
  assert.equal(conversation.provider, "Open WebUI");
  assert.equal(conversation.model, "llama3.1:8b");
  assert.deepEqual(
    conversation.messages.map((m) => m.id),
    ["msg-a1", "msg-a2", "msg-a3"]
  );
  assert.equal(stats.skippedBranches, 1);
  assert.ok(conversation.openwebuiSkippedBranches === 1);
});

test("timestamps are converted from epoch seconds to epoch milliseconds", () => {
  const chats = loadFixtures();
  const { conversation } = convertChat(chats[0], "1.0.0");
  assert.equal(conversation.createdAt, 1761800000000);
  assert.equal(conversation.updatedAt, 1761800030000);
  assert.equal(conversation.messages[0].timestamp, 1761800000000);
  assert.equal(conversation.messages[1].timestamp, 1761800010000);
});

test("assistant messages carry the model id", () => {
  const chats = loadFixtures();
  const { conversation } = convertChat(chats[0], "1.0.0");
  assert.equal(conversation.messages[1].model, "llama3.1:8b");
  // user message must not get a model field
  assert.equal(conversation.messages[0].model, undefined);
});

test("legacy flat chat and model_id variant convert correctly", () => {
  const chats = loadFixtures();

  const legacy = convertChat(chats[1], "1.0.0");
  assert.deepEqual(
    legacy.conversation.messages.map((m) => m.role),
    ["system", "user", "assistant"]
  );
  assert.equal(legacy.conversation.model, "gpt-4o-mini");
  assert.equal(legacy.conversation.folder_id, "folder-77");

  const blocks = convertChat(chats[2], "1.0.0");
  const assistant = blocks.conversation.messages[2];
  assert.equal(assistant.model, "mistral-small");
  assert.match(assistant.content as string, /Here is what I found:/);
  assert.match(assistant.content as string, /repo-c/);
  // structured original content preserved as passthrough
  assert.ok(Array.isArray(assistant.openwebuiContent));
});

test("tool role survives; unknown roles are skipped and counted", () => {
  const chats = loadFixtures();
  const { conversation, stats } = convertChat(chats[2], "1.0.0");
  assert.equal(conversation.messages[1].role, "tool");

  const weird: OpenWebUIChat = {
    ...chats[0],
    chat: {
      ...chats[0].chat,
      messages: [],
      history: {
        currentId: "w2",
        messages: {
          w1: { id: "w1", parentId: null, childrenIds: ["w2"], role: "oracle", content: "?" },
          w2: { id: "w2", parentId: "w1", childrenIds: [], role: "user", content: "hi" },
        },
      },
    },
  };
  const r = convertChat(weird, "1.0.0");
  assert.equal(r.stats.skippedRoles, 1);
  assert.deepEqual(
    r.conversation.messages.map((m) => m.role),
    ["user"]
  );
});

test("every fixture conversion round-trips through parseCurt", () => {
  for (const chat of loadFixtures()) {
    const { conversation } = convertChat(chat, "1.0.0");
    if (conversation.messages.length === 0) continue;
    const body = serializeCurt(conversation, "curt-openwebui-export@1.0.0");
    const parsed = parseCurt(body);
    assert.ok(parsed !== null, `parseCurt rejected chat ${chat.id}`);
    assert.ok(isCurtConversation(parsed));
    assert.equal(parsed.id, chat.id);
    assert.deepEqual(parsed.messages.map((m) => m.id), conversation.messages.map((m) => m.id));
  }
});

test("empty chat produces zero messages and is reported as empty", () => {
  const chats = loadFixtures();
  const { conversation } = convertChat(chats[3], "1.0.0");
  assert.equal(conversation.messages.length, 0);
});

test("flattenMessages falls back to deepest leaf when currentId is missing", () => {
  const chats = loadFixtures();
  const chat: OpenWebUIChat = {
    ...chats[0],
    chat: {
      ...chats[0].chat,
      history: {
        currentId: undefined,
        messages: (chats[0].chat.history?.messages ?? {}) as Record<string, never>,
      },
    },
  };
  // Deepest leaf is msg-a3 via walk; chain from leaf upward is the same branch.
  const list = flattenMessages(chat, {
    chats: 0,
    messages: 0,
    skippedRoles: 0,
    skippedBranches: 0,
  });
  assert.deepEqual(list.map((m) => m.id), ["msg-a1", "msg-a2", "msg-a3"]);
});
