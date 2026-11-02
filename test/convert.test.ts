import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { isCurtConversation, parseCurt, serializeCurt } from "curt-format";
import { convertChat, flattenMessages } from "../src/convert.js";
import { parseExport } from "../src/source.js";
import type { ExportStats, OpenWebUIChat, OpenWebUIMessage } from "../src/types.js";

const here = dirname(fileURLToPath(import.meta.url));
const fixturePath = join(here, "fixtures", "chat-export.ndjson");
const legacyArrayPath = join(here, "fixtures", "chat-export-legacy-array.json");

function loadFixtures(): OpenWebUIChat[] {
  return parseExport(readFileSync(fixturePath, "utf8")).chats;
}

const zeroStats = (): ExportStats => ({
  chats: 0,
  messages: 0,
  skippedRoles: 0,
  skippedHidden: 0,
  skippedBranches: 0,
});

/** Build a ChatResponse whose visible branch is the given message list. */
function treeChat(
  messages: OpenWebUIMessage[],
  currentId?: string,
  overrides: Partial<OpenWebUIChat> = {}
): OpenWebUIChat {
  const byId: Record<string, OpenWebUIMessage> = {};
  for (const m of messages) byId[m.id] = m;
  return {
    id: "tree-chat",
    title: "Tree fixture",
    chat: {
      id: "tree-chat",
      models: ["llama3.1:8b"],
      messages: [],
      history: { currentId, messages: byId },
    },
    created_at: 1761800000,
    updated_at: 1761800030,
    ...overrides,
  };
}

describe("parseExport", () => {
  it("handles NDJSON and array formats", () => {
    const nd = parseExport(readFileSync(fixturePath, "utf8"));
    expect(nd.format).toBe("ndjson");
    expect(nd.chats.length).toBe(4);

    const arr = parseExport(readFileSync(legacyArrayPath, "utf8"));
    expect(arr.format).toBe("array");
    expect(arr.chats.length).toBe(1);
  });

  it("parses NDJSON line by line, including boundary cases", () => {
    // blank lines between records, CRLF endings, no trailing newline
    const raw = '{"id":"a"}\r\n\r\n{"id":"b"}\r\n\n{"id":"c"}';
    const { chats, format } = parseExport(raw);
    expect(format).toBe("ndjson");
    expect(chats.map((c) => c.id)).toEqual(["a", "b", "c"]);
  });

  it("strips a leading BOM", () => {
    const { chats } = parseExport("﻿{\"id\":\"a\"}\n");
    expect(chats.map((c) => c.id)).toEqual(["a"]);
  });

  it("parses large NDJSON streams (many lines) without dropping records", () => {
    const lines = Array.from(
      { length: 250 },
      (_, i) => JSON.stringify({ id: `chat-${i}` })
    );
    const { chats } = parseExport(lines.join("\n"));
    expect(chats.length).toBe(250);
    expect(chats[249].id).toBe("chat-249");
  });

  it("rejects malformed NDJSON with a line number", () => {
    expect(() => parseExport('{"id":"x"}\nnot-json\n')).toThrow(/line 2/);
  });

  it("treats a bare JSON object as a single NDJSON record", () => {
    const { chats, format } = parseExport('{"id":"x"}');
    expect(format).toBe("ndjson");
    expect(chats.map((c) => c.id)).toEqual(["x"]);
  });
});

describe("flattenMessages (history-tree walk)", () => {
  it("exports the current parent chain, skipping regenerate variants", () => {
    const chat = treeChat(
      [
        { id: "m1", parentId: null, childrenIds: ["m2", "m2b"], role: "user", content: "q" },
        { id: "m2", parentId: "m1", childrenIds: ["m3"], role: "assistant", content: "a" },
        { id: "m2b", parentId: "m1", childrenIds: [], role: "assistant", content: "variant" },
        { id: "m3", parentId: "m2", childrenIds: [], role: "user", content: "follow-up" },
      ],
      "m3"
    );
    const stats = zeroStats();
    const list = flattenMessages(chat, stats);
    expect(list.map((m) => m.id)).toEqual(["m1", "m2", "m3"]);
    expect(stats.skippedBranches).toBe(1);
  });

  it("walks a branchy tree with multiple siblings and generations", () => {
    const chat = treeChat(
      [
        { id: "r", parentId: null, childrenIds: ["a", "b"], role: "user", content: "root" },
        { id: "a", parentId: "r", childrenIds: ["a1"], role: "assistant", content: "a" },
        { id: "b", parentId: "r", childrenIds: [], role: "assistant", content: "b" },
        { id: "a1", parentId: "a", childrenIds: ["a2"], role: "user", content: "a1" },
        { id: "a2", parentId: "a1", childrenIds: [], role: "assistant", content: "a2" },
      ],
      "a2"
    );
    const stats = zeroStats();
    const list = flattenMessages(chat, stats);
    expect(list.map((m) => m.id)).toEqual(["r", "a", "a1", "a2"]);
    expect(stats.skippedBranches).toBe(1); // only "b" is off the current chain
  });

  it("guards against cycles in a corrupted parent chain", () => {
    const chat = treeChat(
      [
        { id: "c1", parentId: "c2", childrenIds: ["c2"], role: "user", content: "x" },
        { id: "c2", parentId: "c1", childrenIds: ["c1"], role: "assistant", content: "y" },
      ],
      "c2"
    );
    const list = flattenMessages(chat, zeroStats());
    // terminates; both nodes visited once
    expect(list.map((m) => m.id).sort()).toEqual(["c1", "c2"]);
  });

  it("falls back to the deepest leaf when currentId is missing", () => {
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
    const list = flattenMessages(chat, zeroStats());
    expect(list.map((m) => m.id)).toEqual(["msg-a1", "msg-a2", "msg-a3"]);
  });

  it("returns the legacy flat messages[] array when history is empty", () => {
    const chat: OpenWebUIChat = {
      id: "flat",
      title: "Legacy",
      chat: {
        id: "flat",
        messages: [
          { id: "l1", role: "user", content: "hello" },
          { id: "l2", role: "assistant", content: "hi" },
        ],
        history: { currentId: "l2", messages: {} },
      },
      created_at: 1755100000,
      updated_at: 1755100006,
    };
    const stats = zeroStats();
    expect(flattenMessages(chat, stats).map((m) => m.id)).toEqual(["l1", "l2"]);
    expect(stats.skippedBranches).toBe(0);
  });
});

describe("convertChat", () => {
  it("modern tree chat: exports current branch, skips regenerate variants", () => {
    const chats = loadFixtures();
    const { conversation, stats } = convertChat(chats[0], "1.0.0");

    expect(conversation.id).toBe("fc2e91a0-1111-4aaa-8bbb-000000000001");
    expect(conversation.title).toBe("Fixture: modern tree chat");
    expect(conversation.provider).toBe("Open WebUI");
    expect(conversation.model).toBe("llama3.1:8b");
    expect(conversation.messages.map((m) => m.id)).toEqual(["msg-a1", "msg-a2", "msg-a3"]);
    expect(stats.skippedBranches).toBe(1);
    expect(conversation.openwebuiSkippedBranches).toBe(1);
  });

  it("timestamps are converted from epoch seconds to epoch milliseconds", () => {
    const chats = loadFixtures();
    const { conversation } = convertChat(chats[0], "1.0.0");
    expect(conversation.createdAt).toBe(1761800000000);
    expect(conversation.updatedAt).toBe(1761800030000);
    expect(conversation.messages[0].timestamp).toBe(1761800000000);
    expect(conversation.messages[1].timestamp).toBe(1761800010000);
  });

  it("message timestamps fall back to chat updatedAt when missing", () => {
    const chats = loadFixtures();
    const { conversation } = convertChat(chats[1], "1.0.0");
    // leg-1 (system) carries no timestamp in the fixture
    expect(conversation.messages[0].timestamp).toBe(1755100006000);
  });

  it("assistant messages carry the model id", () => {
    const chats = loadFixtures();
    const { conversation } = convertChat(chats[0], "1.0.0");
    expect(conversation.messages[1].model).toBe("llama3.1:8b");
    // user message must not get a model field
    expect(conversation.messages[0].model).toBeUndefined();
  });

  it("legacy flat chat and model_id variant convert correctly", () => {
    const chats = loadFixtures();

    const legacy = convertChat(chats[1], "1.0.0");
    expect(legacy.conversation.messages.map((m) => m.role)).toEqual([
      "system",
      "user",
      "assistant",
    ]);
    expect(legacy.conversation.model).toBe("gpt-4o-mini");
    expect(legacy.conversation.folder_id).toBe("folder-77");

    const blocks = convertChat(chats[2], "1.0.0");
    const assistant = blocks.conversation.messages[2];
    expect(assistant.model).toBe("mistral-small");
    expect(assistant.content as string).toMatch(/Here is what I found:/);
    expect(assistant.content as string).toMatch(/repo-c/);
    // structured original content preserved as passthrough
    expect(Array.isArray(assistant.openwebuiContent)).toBe(true);
  });

  it("joins block-array text blocks with a blank line", () => {
    const chat = treeChat([
      {
        id: "b1",
        parentId: null,
        childrenIds: [],
        role: "assistant",
        content: [
          { type: "text", text: "Part one." },
          { type: "text", text: "Part two." },
        ],
        timestamp: 1761800010,
      },
    ]);
    const { conversation } = convertChat(chat, "1.0.0");
    expect(conversation.messages[0].content).toBe("Part one.\n\nPart two.");
    expect(conversation.messages[0].openwebuiContent).toEqual([
      { type: "text", text: "Part one." },
      { type: "text", text: "Part two." },
    ]);
  });

  it("tool role survives; files, sources, usage, annotations pass through", () => {
    const chats = loadFixtures();
    const { conversation } = convertChat(chats[0], "1.0.0");
    expect(conversation.messages[1].files).toEqual([
      { type: "citation", source: { name: "everett-fixture.txt" } },
    ]);
    expect(conversation.messages[1].usage).toEqual({
      prompt_tokens: 12,
      completion_tokens: 9,
    });

    const toolChat = convertChat(chats[2], "1.0.0");
    expect(toolChat.conversation.messages[1].role).toBe("tool");
  });

  it("drops error === true stubs the UI hides, keeps error objects", () => {
    const hidden = convertChat(
      treeChat([
        { id: "e1", parentId: null, childrenIds: ["e2"], role: "user", content: "hi" },
        {
          id: "e2",
          parentId: "e1",
          childrenIds: [],
          role: "assistant",
          content: "model overloaded, try again",
          error: true,
        },
      ]),
      "1.0.0"
    );
    expect(hidden.conversation.messages.map((m) => m.id)).toEqual(["e1"]);
    expect(hidden.stats.skippedHidden).toBe(1);

    const kept = convertChat(
      treeChat([
        { id: "f1", parentId: null, childrenIds: ["f2"], role: "user", content: "hi" },
        {
          id: "f2",
          parentId: "f1",
          childrenIds: [],
          role: "assistant",
          content: "partial answer",
          error: { content: "stream aborted" },
        },
      ]),
      "1.0.0"
    );
    expect(kept.conversation.messages.length).toBe(2);
    expect(kept.conversation.messages[1].error).toEqual({ content: "stream aborted" });
    expect(kept.stats.skippedHidden).toBe(0);
  });

  it("unknown roles are skipped and counted", () => {
    const chats = loadFixtures();
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
    expect(r.stats.skippedRoles).toBe(1);
    expect(r.conversation.messages.map((m) => m.role)).toEqual(["user"]);
  });

  it("empty chat produces zero messages", () => {
    const chats = loadFixtures();
    const { conversation } = convertChat(chats[3], "1.0.0");
    expect(conversation.messages.length).toBe(0);
  });
});

describe("round-trip", () => {
  it("every fixture conversion round-trips through parseCurt", () => {
    for (const chat of loadFixtures()) {
      const { conversation } = convertChat(chat, "1.0.0");
      if (conversation.messages.length === 0) continue;
      const body = serializeCurt(conversation, "curt-openwebui-export@1.0.0");
      const parsed = parseCurt(body);
      expect(parsed).not.toBeNull();
      expect(isCurtConversation(parsed)).toBe(true);
      expect(parsed!.id).toBe(chat.id);
      expect(parsed!.messages.map((m) => m.id)).toEqual(conversation.messages.map((m) => m.id));
    }
  });
});
