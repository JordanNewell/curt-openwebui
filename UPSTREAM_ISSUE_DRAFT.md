<!-- Title (form auto-prefixes "feat: " — do not add your own): portable per-conversation export (working Filter Function as reference) -->

### Problem

Open WebUI's native export (NDJSON) handles instance migration and backup well, but the export payload is the internal chat object, so there is no *spec'd* interop path outside Open WebUI: every external tool has to reverse-engineer the internals (the `history` message tree keyed by `parentId`, epoch-seconds timestamps, `chat` payload nesting, block-array content) and hope they don't change shape between versions. I'm trying to get conversations into portable, tool-agnostic formats, but every consumer has to re-derive what the UI already knows.

### Desired Behavior

A portable per-conversation export that preserves what the UI actually renders — the visible branch (`history.currentId` parent-chain walk), roles, model ids, timestamps, attachments — in an open, self-describing single-file format. Today the only export path is `generate_chat_export_ndjson` in `backend/open_webui/routers/chats.py`, so this could slot in beside it. With the Functions system this requires no core changes: I've built and verified a Filter Function that does exactly this on `outlet`, and I'm sharing it as a working reference.

**What the Function does** (`curt_export_function.py`, single file — its only import beyond the stdlib is `pydantic`, which ships with Open WebUI itself; installs via the admin Functions importer): serializes the conversation to a [`.curt`](https://github.com/JordanNewell/dot_curt) file — a small open single-file conversation format (JSON envelope, epoch-ms timestamps, strict whole-file validation, unknown fields preserved on round-trip). Regenerate variants are counted in a passthrough field; attachments ride as passthrough `files`. Files follow the format's `YYYY-MM-DD slug id-suffix.curt` bulk naming and are validated before being kept. Export failures never break the chat turn.

### Why This Matters

- **Users** get conversations in a format not locked to Open WebUI — not locked to re-import into the same instance
- **The Functions ecosystem** gains a reference implementation demonstrating outlet-time per-conversation export, including the less-documented parts (`__user__` injection, `chat_id` in the outlet body, `error === true` hidden-message semantics)
- **The format spec** ([dotcurt.org](https://dotcurt.org)) is defined independently of any product

### Examples

Source repo: https://github.com/JordanNewell/curt-openwebui — the Function is `functions/curt_export_function.py`, install steps in `functions/INSTALL.md`.

Verification (all runnable from the repo):

- 79 tests (vitest 32, pytest 47) across three implementations — standalone CLI, Pipelines filter, Functions port — sharing fixtures and deep-compared on every run, so mappings can't drift
- Mapping verified field-by-field against `open-webui/main` source (`chats.py`, `Messages.svelte`, `ResponseMessage.svelte`); Function conventions verified against `utils/filter.py` and `utils/middleware.py` (`__user__` injection, `chat_id` in the outlet body)
- Smoke-tested end-to-end on a live Open WebUI instance running the `main` Docker image (late Oct 2026)

Two shapes this could take, happy either way: (a) the Function lives as a community contribution — if there's a preferred channel for sharing those (docs tutorial? community library?), I'll adapt it to that format; (b) if portable export is interesting as a native option someday (Settings → Chats), the mapping logic is standalone and could seed that without redesign. Per the contributing guidance I am not opening a PR for this — sharing the code as reference here.

### Alternatives or Workarounds

The workaround in active use is the reference Function itself — conversations export to `.curt` per-chat, today, with no core changes. Alternatives considered:

- **Status quo (NDJSON + per-tool converters):** works, but every consumer reimplements the internals independently and re-verifies against each release — our own mapping had to be checked field-by-field against `main` source, and that cost recurs for every tool and every version bump.
- **Markdown/PDF export:** human-readable, but structure is lost — turns, attribution, and metadata can't round-trip back into anything tool-readable.
- **Browser-extension capture:** works client-side but is per-user setup and misses server-side context (model ids, usage) unless separately reconstructed.
