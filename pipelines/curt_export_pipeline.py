"""
title: .curt Export Filter
author: JordanNewell
author_url: https://github.com/JordanNewell
git_url: https://github.com/open-webui/pipelines/blob/main/examples/filters/curt_export_pipeline.py
description: Exports each conversation to a portable .curt v1 file  as it happens.
required_open_webui_version: 0.4.0
requirements: requests
version: 0.1.0
licence: MIT
"""

import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import List, Optional

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


def _to_ms(value) -> int:
    """Normalize epoch seconds/floats to integer epoch milliseconds."""
    if isinstance(value, (int, float)) and value > 0:
        return int(value * 1000)
    return 0


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


def is_valid_conversation(conversation: dict) -> bool:
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

    async def inlet(self, body: dict, user: Optional[dict] = None) -> dict:
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

    def _export(self, body: dict, user: Optional[dict]) -> Optional[str]:
        chat_id = body.get("chat_id") or f"openwebui_{uuid.uuid4().hex[:12]}"
        messages = self._map_messages(body)
        if not messages:
            return None

        now_ms = int(time.time() * 1000)
        meta = self._fetch_chat_meta(chat_id) or {}
        chat_body = body.get("chat") if isinstance(body.get("chat"), dict) else {}

        title = (
            meta.get("title")
            or chat_body.get("title")
            or body.get("chat_title")
            or "Untitled chat"
        )
        models = (
            meta.get("models")
            or chat_body.get("models")
            or ([body.get("model")] if body.get("model") else [])
        )

        conversation = {
            "id": chat_id,
            "title": title,
            "createdAt": _to_ms(meta.get("created_at")) or now_ms,
            "updatedAt": now_ms,
            "messages": messages,
            "provider": "Open WebUI",
        }
        if models:
            conversation["model"] = ", ".join(str(m) for m in models)
        if not is_valid_conversation(conversation):
            logger.warning("curt export: conversation failed v1 validation, skipping chat %s", chat_id)
            return None

        os.makedirs(self.valves.OUTPUT_DIR, exist_ok=True)
        path = os.path.join(self.valves.OUTPUT_DIR, curt_filename(conversation))
        with open(path, "w", encoding="utf-8") as f:
            f.write(serialize_curt(conversation, f"{GENERATOR}/0.1.0"))
        logger.debug("curt export: wrote %s (%d messages)", path, len(messages))
        return path

    def _map_messages(self, body: dict) -> List[dict]:
        """Map the pipeline message list to .curt messages.

        Pipeline bodies carry epoch-second timestamps on some fields and none
        on others; missing timestamps fall back to the current time so the
        v1 validation rules (numbers required) always hold.
        """
        mapped = []
        now_ms = int(time.time() * 1000)
        for i, message in enumerate(body.get("messages") or []):
            role = message.get("role")
            content = message.get("content")
            if role not in CURT_ROLES or not isinstance(content, str):
                continue
            curt = {
                "id": str(message.get("id") or f"{body.get('chat_id', 'msg')}_{i}"),
                "role": role,
                "content": content,
                "timestamp": _to_ms(message.get("timestamp")) or now_ms,
            }
            if role == "assistant":
                model = message.get("model") or body.get("model")
                if model:
                    curt["model"] = model
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
