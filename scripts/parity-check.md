# CLI / pipeline / Function parity check (drift guard)

The three implementations in this repo — the TypeScript CLI (`src/convert.ts`),
the Python pipeline (`pipelines/curt_export_pipeline.py`), and the Python
Function (`functions/curt_export_function.py`) — must never produce different
`.curt` message sequences from the same Open WebUI chat payload. This note
defines the shared rule and the tests that pin it.

> **Pipelines is deprecated — use Functions.** The community
> [open-webui/pipelines](https://github.com/open-webui/pipelines) repo is in
> maintenance mode; the official successor is
> [Filter Functions](https://docs.openwebui.com/features/extensibility/plugin/functions/filter/)
> (Admin Panel > Functions). `functions/curt_export_function.py` is that port;
> the pipeline file is kept for existing deployments.

## Why the Function mirrors instead of importing

Open WebUI Functions are installed as a single standalone `.py` file
(admin pastes code or imports a URL), executed inside the Open WebUI process
with no access to this repo. So `functions/curt_export_function.py` cannot
`import curt_export_pipeline` at runtime — the mapping functions
(`convert_chat`, `is_valid_conversation`, `curt_filename`, `serialize_curt`,
and their helpers) are **duplicated line-for-line** in the Function file, and
the parity tests below are the enforcement that the copies never diverge.
(Preference order was import-first; packaging makes that impossible here.)

## The shared rule (one algorithm, three implementations)

All three sides implement the exact same mapping. The pipeline's
`convert_chat` and the Function's `convert_chat` are line-by-line mirrors of
the CLI's `convertChat`; none may change without the others, and the parity
tests fail if they drift.

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
   UI shows only an error bubble. All implementations skip these and count
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
   semantics); message timestamps falling back to the chat's `updatedAt`
   (CLI) / outlet time (pipeline and Function), then the v1 rules (number
   required) always hold.
6. **Model** — `message.model` or `message.model_id`, assistant messages only.
7. **Passthroughs** — `files`, `sources`, `usage`, `annotations`, `error`
   (non-true) ride along on messages; `folder_id`, `share_id`, `summary`,
   `openwebuiSkippedBranches` on the conversation.

## Function-specific deltas (intentional, not drift)

- No `requests` dependency: the pipeline's optional
  `GET /api/v1/chats/{id}` title/`created_at` enrichment call is dropped.
  Functions receive `chat_id` at the outlet body's top level (verified in
  upstream `backend/open_webui/utils/middleware.py`, `outlet_data`), and
  title/id/models are synthesized from the body exactly like the pipeline's
  no-metadata fallback path.
- The user-parameter keyword is `__user__` (Function convention), not the
  pipelines-era `user` — verified upstream: `get_filter_params` in
  `backend/open_webui/utils/filter.py` injects `extra_params` (including
  `__user__ = user.model_dump()`, set in `middleware.py`) only into handler
  signatures that declare the parameter, and applies user valves to
  `params['__user__']`.
- Valves renamed to `EXPORT_DIR` / `EXPORT_ON_OUTLET` (Function Valves are
  edited in Admin Panel > Functions > ⚙️).
- Envelope `generator` string is `curt-openwebui-function/0.1.0` (the
  pipeline writes `curt-openwebui-pipeline/0.2.0`). Conversation payloads are
  identical — only the envelope generator string differs.

## Where it's pinned

- **`test/parity.test.ts`** (vitest): feeds `test/fixtures/chat-export.ndjson`
  through CLI (`convertChat`, in-process) and pipeline (`convert_chat` via a
  `python -c` subprocess) and deep-compares the full conversation and the
  counters for every chat. Fails the JS suite on any divergence. Skips
  cleanly when Python is unavailable.
- **`functions/tests/test_parity.py`** (pytest): runs the same fixtures
  through the Function's outlet path and the pipeline's `_export` path with a
  frozen clock (and pinned uuid4), asserting identical conversation payloads.
- **`functions/tests/`** (pytest): Function-side fixture coverage mirroring
  `pipelines/tests/` (plain, legacy flat, block-array, regenerate variants,
  files/sources passthrough, hidden error stubs), asserting every outlet
  output validates against the Function's own `is_valid_conversation` v1
  mirror.
- **`pipelines/tests/`** (pytest): the pipeline side of the same fixtures.

Run everything with `npm test` (the pytest leg degrades to a message when
Python is absent).

## Change protocol

Changing any of the seven rules above requires touching `src/convert.ts`,
`pipelines/curt_export_pipeline.py`, AND `functions/curt_export_function.py`
in the same commit and updating the fixture expectations on all three sides.
If any parity test is red, the mapping has drifted — fix the
implementations, not the test.
