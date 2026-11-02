"""
title: .curt Export Filter
author: JordanNewell
author_url: https://github.com/JordanNewell
git_url: https://github.com/open-webui/pipelines/blob/main/examples/filters/curt_export_pipeline.py
description: Exports each conversation to a portable .curt v1 file  as it happens.
required_open_webui_version: 0.4.0
requirements: requests
version: 0.2.0
licence: MIT
"""

import json
import math
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

from pydantic import BaseModel, Field
try:
    import requests
except ImportError:
    requests = None

from logging import getLogger
logger = getLogger(__name__)

CURT_MAGIC = "curtis-conversation"
CURT_VERSION = 1
CURT_ROLES = ("user", "assistant", "system", "tool")
GENERATOR = "curt-openwebui-pipeline"


def _seconds_to_ms(value) -> int:
    """Epoch seconds (or float seconds) -> epoch ms, mirroring the CLI's
    secondsToMs (Math.round(value * 1000), 0 for non-numbers)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            if math.isfinite(value):
                return int(math.floor(value * 1000 + 0.5))
        except (OverflowError, ValueError):
            return 0
    return 0


def _content_to_text(content) -> Tuple[str, bool]:
    """.curt content must be a string; Open WebUI content may be a block array.

    Mirrors the CLI's contentToText: join text blocks with a blank line and
    flag the original payload as structured so it is kept as passthrough.
    """
    if isinstance(content, str):
        return content, False
    if content is None:
        return "", False
    if isinstance(content, list):
        parts = []
        for block in content:
            if (
                isinstance(block, dict)
                and isinstance(block.get("text"), str)
                and len(block["text"]) > 0
            ):
                parts.append(block["text"])
        return "\n\n".join(parts), True
    return str(content), False


def _flatten_visible(chat_body: Any, chat: Any, stats: dict) -> List[dict]:
    """Walk the parent chain ending at history.currentId — the exact branch the
    Open WebUI UI renders (Messages.svelte buildMessages). Identical rule to the
    CLI's flattenMessages in src/convert.ts so the two never drift:

    1. Modern chats keep messages in `chat.history.messages` as a tree keyed by
       id, linked with parentId; the visible conversation is the parent chain
       ending at `history.currentId` (falling back to the chat's
       current_message_id, then to the deepest leaf). Other branches
       (regenerate variants) are not exported — each skipped entry is counted
       in stats["skippedBranches"] and surfaced as the
       openwebuiSkippedBranches passthrough field.
    2. Legacy chats keep a flat array in `chat.messages`.
    """
    history = chat_body.get("history")
    history_map = history.get("messages") if isinstance(history, dict) else None
    if isinstance(history, dict) and isinstance(history_map, dict) and len(history_map) > 0:
        cursor = history.get("currentId") or chat.get("current_message_id")

        # Fall back to the deepest leaf if the chat has no current pointer.
        if not cursor or cursor not in history_map:
            leaves = [
                m
                for m in history_map.values()
                if not (
                    isinstance(m, dict)
                    and isinstance(m.get("childrenIds"), list)
                    and len(m["childrenIds"]) > 0
                )
            ]
            if not leaves:
                return []
            last = leaves[-1]
            cursor = last.get("id") if isinstance(last, dict) else None

        chain: List[dict] = []
        seen = set()
        while (
            cursor
            and isinstance(history_map.get(cursor), dict)
            and cursor not in seen
        ):
            seen.add(cursor)
            chain.append(history_map[cursor])
            cursor = history_map[cursor].get("parentId")
        chain.reverse()

        # Count regenerate-variant branches that will not appear in the export.
        exported = {m.get("id") for m in chain}
        stats["skippedBranches"] = sum(
            1
            for m in history_map.values()
            if isinstance(m, dict) and m.get("id") not in exported
        )
        return chain

    if isinstance(chat_body.get("messages"), list):
        return chat_body["messages"]
    return []


def convert_chat(chat: Any) -> Tuple[dict, dict]:
    """Convert one Open WebUI chat (ChatResponse shape) into a .curt v1
    conversation, using the exact same rules as the CLI's convertChat in
    src/convert.ts. Returns (conversation, stats); see scripts/parity-check.md
    for the drift-guard that pins this equivalence.

    Mapping:
    - id/title          -> conversation id/title
    - created_at/updated_at (epoch SECONDS) -> createdAt/updatedAt (epoch MS)
    - current message branch -> messages[]
    - message.timestamp (epoch SECONDS) -> timestamp (epoch MS)
    - message.model | model_id -> message.model (assistant only)
    - chat.models       -> conversation.model (joined) + provider "Open WebUI"

    Open WebUI fields with no .curt v1 counterpart (files, sources, usage,
    annotations, the sibling branches of the message tree, folder/archive
    state) are attached as passthrough fields or dropped — see README.
    """
    if not isinstance(chat, dict):
        chat = {}
    chat_body = chat.get("chat")
    if not isinstance(chat_body, dict):
        chat_body = {}

    stats = {
        "chats": 1,
        "messages": 0,
        "skippedRoles": 0,
        "skippedHidden": 0,
        "skippedBranches": 0,
    }

    created_at = _seconds_to_ms(chat.get("created_at"))
    updated_at = _seconds_to_ms(chat.get("updated_at"))
    fallback_ts = updated_at or created_at

    messages: List[dict] = []
    for m in _flatten_visible(chat_body, chat, stats):
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        if role not in CURT_ROLES:
            stats["skippedRoles"] += 1
            continue
        if m.get("error") is True:
            # Legacy error stub: the UI never renders the content of a message
            # whose error field is the boolean true (ResponseMessage.svelte
            # renders content only when error !== true; the error string is
            # stored in content). Skip so the export matches what the UI shows.
            stats["skippedHidden"] += 1
            continue
        text, structured = _content_to_text(m.get("content"))
        curt = {
            "id": str(m.get("id")),
            "role": role,
            "content": text,
            "timestamp": _seconds_to_ms(m.get("timestamp")) or fallback_ts,
        }
        model = m.get("model") or m.get("model_id")
        if isinstance(model, str) and len(model) > 0 and role == "assistant":
            curt["model"] = model
        # Passthrough: Open WebUI fields .curt readers may still want. The
        # .curt spec allows unknown fields on messages and preserves them
        # round-trip.
        if structured:
            curt["openwebuiContent"] = m.get("content")
        files = m.get("files")
        sources = m.get("sources")
        if isinstance(files, list) and len(files) > 0:
            curt["files"] = files
        if isinstance(sources, list) and len(sources) > 0:
            curt["sources"] = sources
        if m.get("error") is not None:
            curt["error"] = m.get("error")
        if m.get("usage") is not None:
            curt["usage"] = m.get("usage")
        if m.get("annotations") is not None:
            curt["annotations"] = m.get("annotations")
        messages.append(curt)
    stats["messages"] = len(messages)

    conversation = {
        "id": chat.get("id"),
        "title": chat.get("title") if isinstance(chat.get("title"), str) else "",
        "createdAt": created_at,
        "updatedAt": updated_at,
        "messages": messages,
        "provider": "Open WebUI",
    }
    models_raw = chat_body.get("models")
    models = (
        [m for m in models_raw if isinstance(m, str)]
        if isinstance(models_raw, list)
        else []
    )
    if models:
        conversation["model"] = ", ".join(models)

    # Chat-level passthrough (unknown fields are allowed on the conversation).
    for key in ("folder_id", "share_id", "summary"):
        if chat.get(key):
            conversation[key] = chat[key]
    if stats["skippedBranches"] > 0:
        conversation["openwebuiSkippedBranches"] = stats["skippedBranches"]

    return conversation, stats


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return slug[:50] or "untitled"


def curt_filename(conversation: dict) -> str:
    """Curtis bulk convention: '<YYYY-MM-DD> <slug> <suffix>.curt'."""
    created = conversation.get("createdAt") or 0
    try:
        date = datetime.fromtimestamp(created / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        date = "1970-01-01"
    chat_id = conversation.get("id") or "untitled"
    suffix = chat_id.rsplit("_", 1)[-1] if "_" in chat_id else chat_id[-8:]
    return f"{date} {_slugify(conversation.get('title', ''))} {suffix}.curt"


def serialize_curt(conversation: dict, generator: str) -> str:
    """Serialize a conversation as a .curt v1 file body (tab-indented JSON)."""
    envelope = {
        "curt": CURT_MAGIC,
        "version": CURT_VERSION,
        "generator": generator,
        "conversation": conversation,
    }
    return json.dumps(envelope, indent="\t", ensure_ascii=False)


def is_valid_conversation(conversation: Any) -> bool:
    """Mirror of the .curt v1 validation rules (validation is whole-file)."""
    if not isinstance(conversation, dict):
        return False
    if not isinstance(conversation.get("id"), str) or not isinstance(conversation.get("title"), str):
        return False
    for key in ("createdAt", "updatedAt"):
        if not isinstance(conversation.get(key), (int, float)):
            return False
    messages = conversation.get("messages")
    if not isinstance(messages, list):
        return False
    for message in messages:
        if not isinstance(message, dict):
            return False
        if not isinstance(message.get("id"), str):
            return False
        if message.get("role") not in CURT_ROLES:
            return False
        if not isinstance(message.get("content"), str):
            return False
        if not isinstance(message.get("timestamp"), (int, float)):
            return False
    return True


class Pipeline:
    class Valves(BaseModel):
        OPENWEBUI_BASE_URL: str = Field(
            default="", description="Open WebUI base URL, used to fetch chat titles when not present in the body."
        )
        OPENWEBUI_API_KEY: str = Field(
            default="", description="Open WebUI API key (Settings > Account > API keys)."
        )
        OUTPUT_DIR: str = Field(
            default="./curt-exports", description="Directory .curt files are written to."
        )
        EXPORT_ON_OUTLET: bool = Field(
            default=True, description="Write/update the .curt file after each assistant reply."
        )

    def __init__(self):
        self.type = "filter"
        self.name = ".curt Export Filter"
        self.valves = self.Valves(
            **{
                "OPENWEBUI_BASE_URL": os.getenv("OPENWEBUI_BASE_URL", ""),
                "OPENWEBUI_API_KEY": os.getenv("OPENWEBUI_API_KEY", ""),
                "OUTPUT_DIR": os.getenv("CURT_OUTPUT_DIR", "./curt-exports"),
                "EXPORT_ON_OUTLET": os.getenv("CURT_EXPORT_ON_OUTLET", "true").lower() == "true",
            }
        )

    async def on_startup(self):
        logger.debug(f"on_startup:{self.name}")

    async def on_shutdown(self):
        logger.debug(f"on_shutdown:{self.name}")

    async def inlet(self, body: dict, user: Optional[dict] = None) -> dict:  # noqa: ARG002 - framework signature
        del user
        return body

    async def outlet(self, body: dict, user: Optional[dict] = None) -> dict:
        if not self.valves.EXPORT_ON_OUTLET:
            return body

        try:
            self._export(body, user)
        except Exception:
            # An export failure must never break the chat turn.
            logger.exception("curt export failed")
        return body

    def _export(self, body: dict, user: Optional[dict] = None) -> Optional[str]:
        chat_id = body.get("chat_id") or f"openwebui_{uuid.uuid4().hex[:12]}"
        now_ms = int(time.time() * 1000)
        now_s = now_ms / 1000.0
        meta: dict = self._fetch_chat_meta(chat_id) or {}
        chat_body = body.get("chat")
        if not isinstance(chat_body, dict):
            chat_body = {}

        # Reuse the CLI's exact mapping rules: shape the outlet body as a
        # ChatResponse record and run it through convert_chat (see
        # scripts/parity-check.md for the drift-guard test).
        chat_record = {
            "id": chat_id,
            "title": (
                meta.get("title")
                or chat_body.get("title")
                or body.get("chat_title")
                or "Untitled chat"
            ),
            "chat": chat_body,
            "created_at": meta.get("created_at"),
            "updated_at": now_s,
        }
        conversation, stats = convert_chat(chat_record)

        if not conversation["createdAt"]:
            conversation["createdAt"] = now_ms
        if not conversation.get("model"):
            meta_models = meta.get("models") or (
                [body["model"]] if body.get("model") else []
            )
            if meta_models:
                conversation["model"] = ", ".join(str(m) for m in meta_models)

        # Bodies that carry no chat payload (enrichment off, chat not yet
        # persisted): map the raw turn-body message list with the same
        # per-message rules so nothing silently degrades.
        if not conversation["messages"] and isinstance(body.get("messages"), list):
            conversation["messages"] = self._map_turn_messages(body, now_ms)
            stats["messages"] = len(conversation["messages"])

        if not conversation["messages"]:
            return None
        if not is_valid_conversation(conversation):
            logger.warning("curt export: conversation failed v1 validation, skipping chat %s", chat_id)
            return None

        os.makedirs(self.valves.OUTPUT_DIR, exist_ok=True)
        path = os.path.join(self.valves.OUTPUT_DIR, curt_filename(conversation))
        with open(path, "w", encoding="utf-8") as f:
            f.write(serialize_curt(conversation, f"{GENERATOR}/0.2.0"))
        logger.debug(
            "curt export: wrote %s (%d messages, %d skipped branch(es), %d hidden)",
            path,
            stats["messages"],
            stats["skippedBranches"],
            stats["skippedHidden"],
        )
        return path

    def _map_turn_messages(self, body: dict, now_ms: int) -> List[dict]:
        """Map the raw pipeline turn-body message list to .curt messages.

        Same per-message rules as convert_chat (roles, error===true stubs,
        block-array content); ids are synthesized for turn bodies that carry
        none, and missing timestamps fall back to the current time so the v1
        validation rules (numbers required) always hold.
        """
        mapped: List[dict] = []
        for i, message in enumerate(body.get("messages") or []):
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            if role not in CURT_ROLES:
                continue
            if message.get("error") is True:
                continue
            text, structured = _content_to_text(message.get("content"))
            curt = {
                "id": str(message.get("id") or f"{body.get('chat_id', 'msg')}_{i}"),
                "role": role,
                "content": text,
                "timestamp": _seconds_to_ms(message.get("timestamp")) or now_ms,
            }
            model = message.get("model") or body.get("model")
            if isinstance(model, str) and len(model) > 0 and role == "assistant":
                curt["model"] = model
            if structured:
                curt["openwebuiContent"] = message.get("content")
            files = message.get("files")
            sources = message.get("sources")
            if isinstance(files, list) and len(files) > 0:
                curt["files"] = files
            if isinstance(sources, list) and len(sources) > 0:
                curt["sources"] = sources
            if message.get("error") is not None:
                curt["error"] = message.get("error")
            if message.get("usage") is not None:
                curt["usage"] = message.get("usage")
            if message.get("annotations") is not None:
                curt["annotations"] = message.get("annotations")
            mapped.append(curt)
        return mapped

    def _fetch_chat_meta(self, chat_id: str) -> Optional[dict]:
        """Best-effort GET /api/v1/chats/{id} for title/created_at; returns None on any failure."""
        base = (self.valves.OPENWEBUI_BASE_URL or "").rstrip("/")
        key = self.valves.OPENWEBUI_API_KEY or ""
        if not base or not key or requests is None:
            return None
        try:
            res = requests.get(
                f"{base}/api/v1/chats/{chat_id}",
                headers={"Authorization": f"Bearer {key}"},
                timeout=5,
            )
            if res.status_code != 200:
                return None
            chat = res.json()
            return {
                "title": chat.get("title"),
                "created_at": chat.get("created_at"),
                "models": (chat.get("chat") or {}).get("models"),
            }
        except Exception:
            return None
