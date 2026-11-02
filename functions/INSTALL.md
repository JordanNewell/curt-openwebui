# Installing the .curt Export Filter (Function)

`functions/curt_export_function.py` is an Open WebUI **Filter Function** — the
official successor to the deprecated open-webui/pipelines format. Install steps
below are verbatim from the official Functions documentation
(<https://docs.openwebui.com/features/extensibility/plugin/> — "Installing
Functions").

> ⚠️ **Critical Security Warning** (from the official docs): Functions execute
> arbitrary Python code on your server. Function creation is restricted to
> administrators only. Only install from trusted sources and review code before
> importing.

Prerequisite: the Functions admin page is hidden when
[`ENABLE_FUNCTIONS`](https://docs.openwebui.com/reference/env-configuration#enable_functions)
is set to `False`.

## From a URL

(from the official docs, "Installing Functions > From a URL")

1. Go to **Admin Panel > Functions**.
2. Click **Import from URL** and paste a link to the Python file.
   - GitHub URLs are automatically converted to raw file URLs.
3. Review and save.

Point it at the raw file, e.g.:

```
https://raw.githubusercontent.com/JordanNewell/curt-openwebui/main/functions/curt_export_function.py
```

## Create Manually

(from the official docs, "Installing Functions > Create Manually")

1. Go to **Admin Panel > Functions**.
2. Click **Create**.
3. Enter an ID (alphanumeric and underscores only), name, and description.
4. Write your Python code in the editor (paste the full contents of
   `functions/curt_export_function.py`).
5. Click **Save**. The function type is auto-detected from your code.

## Community Library

The official docs also document installing from the
[Community Function Library](https://openwebui.com/search) (browse → **Get** →
enter your instance URL → **Import to Open WebUI** → review → **Save**). This
filter is not published there; use one of the two methods above.

## After install

1. Review the code (it runs as privileged Python on your server), then keep the
   function **Active** (green toggle).
2. Attach it per-model in **Model Settings → Filters**, or flip **Global** in
   the function's ⋮ menu to run it on every model.
3. Configure the Valves in **Admin Panel > Functions > ⚙️**:
   - `EXPORT_DIR` — directory `.curt` files are written to (default
     `./curt-exports`, relative to the Open WebUI working directory).
   - `EXPORT_ON_OUTLET` — write/update the `.curt` file after each assistant
     reply (default `true`).

No extra pip packages are required: the Function is stdlib-only (pydantic ships
with Open WebUI). An export failure never breaks the chat turn — the error is
logged and the conversation continues.
