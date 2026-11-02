import type {
  CurtConversation,
  CurtMessage,
} from "curt-format";
import type {
  ExportStats,
  OpenWebUIChat,
  OpenWebUIMessage,
} from "./types.js";

const CURT_ROLES = new Set(["user", "assistant", "system", "tool"]);

export const GENERATOR = "curt-openwebui-export";

/**
 * Flatten an Open WebUI chat body into a linear message list, mirroring the
 * order the UI shows:
 *
 * 1. Modern chats keep messages in `chat.history.messages` as a tree keyed by
 *    id, linked with `parentId`; the visible conversation is the parent chain
 *    ending at `history.currentId` (see createMessagesList in the open-webui
 *    frontend). Other branches (regenerate variants) are not exported.
 * 2. Legacy chats keep a flat array in `chat.messages`.
 */
export function flattenMessages(
  chat: OpenWebUIChat,
  stats: ExportStats
): OpenWebUIMessage[] {
  const history = chat.chat?.history;
  const historyMap = history?.messages;
  if (
    historyMap &&
    typeof historyMap === "object" &&
    Object.keys(historyMap).length > 0
  ) {
    const byId = historyMap as Record<string, OpenWebUIMessage>;
    let cursor = history.currentId ?? chat.current_message_id ?? null;

    // Fall back to the deepest leaf if the chat has no current pointer.
    if (!cursor || !byId[cursor]) {
      const leaves = Object.values(byId).filter(
        (m) => !(m.childrenIds && m.childrenIds.length > 0)
      );
      if (leaves.length === 0) return [];
      cursor = leaves[leaves.length - 1].id;
    }

    const chain: OpenWebUIMessage[] = [];
    const seen = new Set<string>();
    while (cursor && byId[cursor] && !seen.has(cursor)) {
      seen.add(cursor);
      chain.push(byId[cursor]);
      cursor = byId[cursor].parentId ?? null;
    }
    chain.reverse();

    // Count regenerate-variant branches that will not appear in the export.
    const exported = new Set(chain.map((m) => m.id));
    for (const m of Object.values(byId)) {
      if (!exported.has(m.id)) stats.skippedBranches++;
    }
    return chain;
  }

  if (Array.isArray(chat.chat?.messages)) {
    return chat.chat.messages;
  }
  return [];
}

/** .curt content must be a string; Open WebUI content may be a block array. */
function contentToText(message: OpenWebUIMessage): {
  text: string;
  structured: boolean;
} {
  const content = message.content;
  if (typeof content === "string") return { text: content, structured: false };
  if (content == null) return { text: "", structured: false };
  if (Array.isArray(content)) {
    // Newer chat_message table can store content as a list of typed blocks
    // ({type: "text", text: ...}); join the text blocks and keep the original
    // structured payload as a passthrough field.
    const text = content
      .map(
        (block) =>
          typeof block === "object" &&
          block !== null &&
          typeof (block as { text?: unknown }).text === "string"
            ? (block as { text: string }).text
            : ""
      )
      .filter((t) => t.length > 0)
      .join("\n\n");
    return { text, structured: true };
  }
  return { text: String(content), structured: false };
}

/**
 * Convert one Open WebUI chat into a .curt v1 conversation.
 *
 * Mapping:
 * - id/title          -> conversation id/title
 * - created_at/updated_at (epoch SECONDS) -> createdAt/updatedAt (epoch MS)
 * - current message branch -> messages[]
 * - message.timestamp (epoch SECONDS) -> timestamp (epoch MS)
 * - message.model | model_id -> message.model
 * - chat.models       -> conversation.model (first entry) + provider "Open WebUI"
 *
 * Open WebUI fields with no .curt v1 counterpart (files, sources, usage,
 * annotations, the sibling branches of the message tree, folder/archive
 * state) are either attached as passthrough fields or dropped — see README.
 */
export function convertChat(
  chat: OpenWebUIChat,
  generatorVersion: string
): { conversation: CurtConversation; stats: ExportStats } {
  const stats: ExportStats = {
    chats: 1,
    messages: 0,
    skippedRoles: 0,
    skippedHidden: 0,
    skippedBranches: 0,
  };

  const secondsToMs = (s: unknown): number =>
    typeof s === "number" && Number.isFinite(s) ? Math.round(s * 1000) : 0;

  const createdAt = secondsToMs(chat.created_at);
  const updatedAt = secondsToMs(chat.updated_at);
  const fallbackTs = updatedAt || createdAt;

  const messages: CurtMessage[] = [];
  for (const m of flattenMessages(chat, stats)) {
    if (typeof m?.role !== "string" || !CURT_ROLES.has(m.role)) {
      stats.skippedRoles++;
      continue;
    }
    if (m.error === true) {
      // Legacy error stub: the UI never renders the content of a message
      // whose error field is the boolean true (ResponseMessage.svelte renders
      // content only when error !== true; the error string is stored in
      // content). Skip so the export matches what the UI shows.
      stats.skippedHidden++;
      continue;
    }
    const { text, structured } = contentToText(m);
    const curt: CurtMessage = {
      id: String(m.id),
      role: m.role as CurtMessage["role"],
      content: text,
      timestamp: secondsToMs(m.timestamp) || fallbackTs,
    };
    const model = m.model ?? m.model_id;
    if (typeof model === "string" && model.length > 0 && m.role === "assistant") {
      curt.model = model;
    }
    // Passthrough: Open WebUI fields .curt readers may still want. The .curt
    // spec allows unknown fields on messages and preserves them round-trip.
    if (structured) curt.openwebuiContent = m.content;
    if (Array.isArray(m.files) && m.files.length > 0) curt.files = m.files;
    if (Array.isArray(m.sources) && m.sources.length > 0) curt.sources = m.sources;
    if (m.error != null) curt.error = m.error;
    if (m.usage != null) curt.usage = m.usage;
    if (m.annotations != null) curt.annotations = m.annotations;
    messages.push(curt);
  }
  stats.messages = messages.length;

  const models =
    Array.isArray(chat.chat?.models) && chat.chat.models.length > 0
      ? chat.chat.models.filter((m) => typeof m === "string")
      : [];

  const conversation: CurtConversation = {
    id: chat.id,
    title: typeof chat.title === "string" ? chat.title : "",
    createdAt,
    updatedAt,
    messages,
    provider: "Open WebUI",
  };
  if (models.length > 0) conversation.model = models.join(", ");

  // Chat-level passthrough (unknown fields are allowed on the conversation).
  if (chat.folder_id) conversation.folder_id = chat.folder_id;
  if (chat.share_id) conversation.share_id = chat.share_id;
  if (chat.summary) conversation.summary = chat.summary;
  if (stats.skippedBranches > 0) {
    conversation.openwebuiSkippedBranches = stats.skippedBranches;
  }

  return { conversation, stats };
}
