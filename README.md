# curt-openwebui

Export [Open WebUI](https://github.com/open-webui/open-webui) chats to
[`.curt`](https://github.com/JordanNewell/dot_curt) v1 single-file conversation
files. Two artifacts:

1. **`curt-openwebui-export`** — standalone TypeScript/Node CLI. Reads a chat
   export file or fetches from the Open WebUI REST API; writes one validated
   `.curt` per chat.
2. **`pipelines/curt_export_pipeline.py`** — a community
   [open-webui/pipelines](https://github.com/open-webui/pipelines) filter that
   writes/updates a `.curt` file as each conversation happens.

## Schema verification

All field names were verified against the open-webui `main` source (not guessed):

| Fact | Source file (open-webui/open-webui @ main) |
|---|---|
| `ChatResponse`: `id`, `user_id`, `title`, `chat: dict`, `created_at`/`updated_at` (epoch **seconds**), `share_id`, `archived`, `pinned`, `meta`, `variables`, `folder_id`, `summary`, `current_message_id` | `backend/open_webui/models/chats.py` |
| `GET /api/v1/chats/all` streams **NDJSON** (one `ChatResponse` per line), batch size 100 | `backend/open_webui/routers/chats.py` → `generate_chat_export_ndjson` |
| `chat.chat.history.messages` is a `Record<id, message>` tree linked by `parentId`; the visible conversation is the parent chain ending at `history.currentId` | `src/lib/utils/index.ts` → `createMessagesList` |
| Legacy chats keep a flat array at `chat.chat.messages` | `backend/open_webui/models/chats.py` (dual-write path) |
| Message fields: `id`, `parentId`, `childrenIds`, `role`, `content`, `timestamp` (epoch **seconds**, `Math.floor(Date.now()/1000)`), `model` / `model_id`, `done`, `error`, `files`, `sources`, `usage`, `annotations`; newer rows may store `content` as a **list of typed blocks** | `src/lib/components/chat/Chat.svelte`, `src/lib/components/chat/Messages/ResponseMessage.svelte`, `backend/open_webui/models/chat_messages.py` |

## Mapping → .curt v1

| Open WebUI | .curt | Notes |
|---|---|---|
| `id` | `conversation.id` | verbatim |
| `title` | `conversation.title` | fallback `""` |
| `created_at` / `updated_at` (s) | `createdAt` / `updatedAt` (ms) | ×1000 |
| current `history` branch or `messages[]` | `messages[]` | UI-visible branch only |
| `message.timestamp` (s) | `message.timestamp` (ms) | ×1000; falls back to chat `updatedAt` when missing |
| `message.model` / `model_id` | `message.model` | assistant messages only |
| `chat.models` | `conversation.model` | joined; `provider` = `"Open WebUI"` |
| `files`, `sources`, `usage`, `annotations`, `error` | same-named passthrough fields | .curt readers ignore unknowns and preserve them on round-trip |
| block-array `content` | `content` (text blocks joined) + `openwebuiContent` passthrough | original structured payload kept verbatim |
| `folder_id`, `share_id`, `summary` | conversation passthrough fields | |
| roles outside `user/assistant/system/tool` | dropped | counted in the export summary |

### Known losses

- **Message-tree branches**: Open WebUI stores regenerate/variant siblings;
  only the currently displayed branch is exported. The count of dropped
  sibling messages is recorded as `openwebuiSkippedBranches` (conversation
  passthrough) and in the CLI summary.
- **Files/images**: attachment metadata survives as passthrough `files`, but
  .curt v1 has no inline-binary story beyond data URIs inside `content`.
- **Chat UI state**: pinned/archived/tags/folder membership beyond
  `folder_id` is not exported.

## CLI usage

```sh
npm i
npm run build

# from a UI export file (Settings > Chats > Export) — NDJSON or JSON array
node dist/src/cli.js chat-export.ndjson -o ./curt-out

# or straight from the API
OPENWEBUI_BASE_URL=https://openwebui.example \
OPENWEBUI_API_KEY=sk-... \
node dist/src/cli.js -o ./curt-out
```

Every file is validated with the reference `parseCurt` before it is written;
an invalid conversation is reported and skipped, never half-written. Output
names follow the Curtis bulk convention (`YYYY-MM-DD slug suffix.curt`, via
`curtFilename`).

## Pipeline

Copy `pipelines/curt_export_pipeline.py` into your pipelines `filters/`
directory (requirements: `requests`, which is only used for the optional
title/`created_at` enrichment call — the filter degrades gracefully without
it). Valves: `OPENWEBUI_BASE_URL`, `OPENWEBUI_API_KEY`, `OUTPUT_DIR`,
`EXPORT_ON_OUTLET`. The serializer and v1 validation are implemented
stdlib-only inside the file; its output round-trips through the reference
`parseCurt` (see `pipelines/test_curt_export_pipeline.py` and the cross-check
below).

```sh
python -m unittest discover -s pipelines   # 8 tests
npm test                                   # 15 tests, includes CLI end-to-end
```

## License

MIT
