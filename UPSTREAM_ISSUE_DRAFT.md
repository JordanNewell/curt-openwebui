# Upstream issue draft (not posted)

> Target: `open-webui/pipelines` → Issues. Posts under JordanNewell.
> Framing: contribution-first, complementary-not-critical, verifiable-only.
> Never criticize the native export; the pipelines framework is the hero.

---

**Title: Filter: per-conversation portable export (`.curt` single-file format) — follows `examples/filters` conventions**

The pipelines framework makes it straightforward to add capabilities to
conversations without touching core — this is a filter in that mold.

Open WebUI's native export (NDJSON) handles instance migration and backup
well. The one thing it doesn't cover is interop outside Open WebUI: the
payload is the internal chat object, so other tools can't consume it without
reimplementing the internals. A portable per-conversation format closes that
gap, and it can be added entirely from a filter — no core changes.

**What the filter does** (`curt_export_pipeline.py`, ~500 lines, stdlib +
optional `requests`): on `outlet`, serializes the conversation to a
[`.curt`](https://github.com/JordanNewell/dot_curt) file — a small open
single-file conversation format (JSON envelope, epoch-ms timestamps, strict
whole-file validation, unknown fields preserved on round-trip). Mapping is
lossless for the rendered branch: roles, model ids, timestamps; regenerate
variants are counted in a passthrough field; attachments ride as passthrough
`files`. Writes follow the format's `YYYY-MM-DD slug id-suffix.curt` bulk
naming, and each file is validated before being kept.

**Verification** (all runnable from the repo):

- Round-trip against the format's reference parser — green
- vitest + pytest suites: 32 + 27 tests (plain, legacy-flat, block-array,
  regenerate-variant chats, NDJSON edge cases)
- Parity test: pipeline and CLI outputs are deep-compared on a shared fixture,
  so the two mappings can't drift
- Schema mapping verified field-by-field against `open-webui/main` source
  (`chats.py`, `Messages.svelte`, `ResponseMessage.svelte`) — cited in-repo

Source: https://github.com/JordanNewell/curt-openwebui
(pipeline: `pipelines/curt_export_pipeline.py`)

If this fits the project's direction, I'm glad to contribute it as a PR under
`examples/filters/` — happy to hear preferences on shape (standalone example
file vs. docs-listed external project). Either way, thanks for the pipelines
framework; it's what makes this possible without a fork.
