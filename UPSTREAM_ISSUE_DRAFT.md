# Upstream issue draft (not posted)

> Target repo: `open-webui/pipelines` (or `open-webui/open-webui` under
> feature requests). One paragraph, concrete, no hype — paste as-is.

---

**Title: Pipeline filter for exporting conversations as `.curt` files**

Open WebUI already exports chats as NDJSON blobs of its internal chat objects,
but there is no portable, self-describing per-conversation format — the export
is only importable back into Open WebUI, and every field (timestamps in
seconds, the `history` message tree, `chat` payload nesting) is
implementation-specific. I wrote a filter pipeline
(`curt_export_pipeline.py`, ~230 lines, stdlib + optional `requests`) that
serializes each conversation on `outlet` to a [`.curt`](https://github.com/JordanNewell/dot_curt)
v1 file — an open, frozen single-file conversation format (JSON envelope with
a magic field, epoch-ms timestamps, strict whole-file validation, unknown
fields preserved on round-trip). Mapping is lossless for the current branch:
roles, model ids, and timestamps carry over; regenerate-variant branches are
summarized in a passthrough count field; attachments ride as passthrough
`files`. Files land in a configurable directory following the format's
`YYYY-MM-DD slug id-suffix.curt` bulk convention, and each write is validated
against the v1 rules before being kept. The pipeline's output has been
round-trip tested against the format's reference parser, and unit tests cover
the envelope, filename convention, and non-fatal handling of malformed turns.
Would the maintainers be open to a PR adding this under `examples/filters/`?
A native export option in the UI (Settings → Chats) could reuse the same
mapping later; the converter logic is also available standalone as the npm
package `curt-openwebui-export`.
