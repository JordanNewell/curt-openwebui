/**
 * Types for Open WebUI chat objects, verified against the open-webui source:
 *
 * - backend/open_webui/models/chats.py  (ChatModel / ChatResponse)
 * - backend/open_webui/routers/chats.py (GET /api/v1/chats/all -> NDJSON of ChatResponse)
 * - backend/open_webui/models/chat_messages.py (message fields)
 * - src/lib/utils/index.ts createMessagesList (history tree walk)
 * - src/lib/components/chat/Chat.svelte (message.timestamp = Math.floor(Date.now()/1000))
 */

/** A single message inside `chat.chat.history.messages` or `chat.chat.messages`. */
export interface OpenWebUIMessage {
  id: string;
  parentId?: string | null;
  childrenIds?: string[];
  role: string; // "user" | "assistant" | "system" | "tool"
  content: string | unknown[] | null;
  /** Epoch seconds (Chat.svelte: Math.floor(Date.now() / 1000)). */
  timestamp?: number;
  /** Legacy assistant-message model id. */
  model?: string;
  /** Newer chat_message table model id. */
  model_id?: string;
  done?: boolean;
  error?: unknown;
  files?: unknown[];
  sources?: unknown[];
  usage?: unknown;
  annotations?: unknown;
  [key: string]: unknown;
}

/** The free-form JSON stored in the `chat` column. */
export interface OpenWebUIChatBody {
  id?: string;
  title?: string;
  models?: string[];
  /** Legacy flat message list (older exports). */
  messages?: OpenWebUIMessage[];
  /** Modern tree-shaped history. */
  history?: {
    currentId?: string;
    messages?: Record<string, OpenWebUIMessage>;
  };
  files?: unknown;
  [key: string]: unknown;
}

/** ChatResponse — what GET /api/v1/chats/all streams and what the UI export file contains. */
export interface OpenWebUIChat {
  id: string;
  user_id?: string;
  title: string;
  chat: OpenWebUIChatBody;
  /** Epoch seconds. */
  created_at: number;
  /** Epoch seconds. */
  updated_at: number;
  share_id?: string | null;
  archived?: boolean;
  pinned?: boolean | null;
  meta?: Record<string, unknown>;
  variables?: Record<string, unknown>;
  folder_id?: string | null;
  summary?: string | null;
  current_message_id?: string | null;
  [key: string]: unknown;
}

export type ExportFormat = "ndjson" | "array";

export interface ExportStats {
  chats: number;
  messages: number;
  /** Messages dropped because their role is outside the .curt v1 role set. */
  skippedRoles: number;
  /**
   * Messages the UI hides: legacy error stubs whose `error` field is the
   * boolean true (the error string is stored in content and ResponseMessage
   * renders it only when error !== true).
   */
  skippedHidden: number;
  /** Branches of the message tree not exported (only the current branch is kept). */
  skippedBranches: number;
}
