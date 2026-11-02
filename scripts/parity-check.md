# CLI / pipeline parity check (drift guard)

The two implementations in this repo — the TypeScript CLI (`src/convert.ts`)
and the Python pipeline (`pipelines/curt_export_pipeline.py`) — must never
produce different `.curt` message sequences from the same Open WebUI chat
payload. This note defines the shared rule and the tests that pin it.

## The shared rule (one algorithm, two implementations)

Both sides implement the exact same mapping. The pipeline's `convert_chat` is
a line-by-line mirror of the CLI's `convertChat`; neither may change without
the other, and the parity test fails if they drift.

1. **Visible branch selection** — modern chats store messages in
   `chat.history.messages` as a parent-linked tree; the visible conversation
   is the parent chain ending at `history.currentId` (falling back to the
   chat's `current_message_id`, then to the deepest leaf). This is what the
   Open WebUI UI renders (`Messages.svelte` → `buildMessages`, verified
   against upstream `main`). Legacy chats fall back to the flat
   `chat.messages` array. Every tree entry not on the chain counts into
   `skippedBranches`, surfaced as the `openwebuiSkippedBranches` conversation
   passthrough.
2. **Hidden messages** — a message whose `error` field is the boolean `true`
   is a legacy error stub: the error string is stored in `content` and
   ResponseMessage.svelte renders content only when `error !== true`, so the
   UI shows only an error bubble. Both implementations skip these and count
   them (`skippedHidden`). Error *objects* (`error: {content}`) render
   alongside content upstream and are kept, with `error` as a passthrough
   field.
3. **Roles** — only `user` / `assistant` / `system` / `tool` map to .curt v1;
   anything else is dropped and counted (`skippedRoles`). Tool and other
   intermediate steps rendered by the UI (tool messages, status-history is
   inside the assistant message, not separate rows) are kept.
4. **Content** — string content maps verbatim; block-array content has its
   `{type: "text", text: ...}` blocks joined with a blank line, and the
   original structured payload is preserved as the `openwebuiContent`
   passthrough.
5. **Timestamps** — epoch seconds to milliseconds (`Math.round(v * 1000)`
   semantics); message timestamps falling back to the chat's `updatedAt` (CLI)
   / outlet time (pipeline), then the v1 rules (number required) always hold.
6. **Model** — `message.model` or `message.model_id`, assistant messages only.
7. **Passthroughs** — `files`, `sources`, `usage`, `annotations`, `error`
   (non-true) ride along on messages; `folder_id`, `share_id`, `summary`,
   `openwebuiSkippedBranches` on the conversation.

## Where it's pinned

- **`test/parity.test.ts`** (vitest): feeds `test/fixtures/chat-export.ndjson`
  through both implementations — `convertChat` in-process, `convert_chat` via
  a `python -c` subprocess — and deep-compares the full conversation and the
  counters for every chat. Fails the JS suite on any divergence. Skips
  cleanly when Python is unavailable.
- **`pipelines/tests/`** (pytest): the pipeline side of the same fixtures plus
  synthetic payloads (plain, legacy flat, block-array, regenerate variants,
  files/sources passthrough, hidden error stubs), asserting every outlet
  output validates against the pipeline's own `is_valid_conversation` v1
  mirror.

Run both with `npm test` (the pytest leg degrades to a message when Python is
absent).

## Change protocol

Changing any of the seven rules above requires touching both
`src/convert.ts` and `pipelines/curt_export_pipeline.py` in the same commit
and updating the fixture expectations on both sides. If the parity test is
red, the mapping has drifted — fix the implementations, not the test.
