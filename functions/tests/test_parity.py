"""Function/pipeline parity (drift guard).

Runs the same fixtures through the Function's outlet path and the pipeline's
_export path and asserts IDENTICAL conversation payloads. The Function is a
standalone mirror of the pipeline mapping (Functions are installed as a single
.py with no repo-relative imports), so this test is what keeps the two from
drifting. See scripts/parity-check.md.
"""

import asyncio
import json
import os
import time
import uuid

import pytest

import curt_export_function as cef
import curt_export_pipeline as cep

from pipelines.tests.test_convert_chat import PLAIN_HISTORY, BLOCK_HISTORY


@pytest.fixture()
def dirs(tmp_path):
    fn = cef.Filter()
    fn.valves.EXPORT_DIR = str(tmp_path / "fn")
    pl = cep.Pipeline()
    pl.valves.OPENWEBUI_BASE_URL = ""
    pl.valves.OPENWEBUI_API_KEY = ""
    pl.valves.OUTPUT_DIR = str(tmp_path / "pl")
    return fn, pl


def _fixed_clock():
    return 1761800000.123


@pytest.fixture()
def frozen_time(monkeypatch):
    monkeypatch.setattr(time, "time", _fixed_clock)
    # Both paths synthesize a chat_id via uuid4 when the body carries none;
    # pin it so the two synthesized ids are comparable.
    fixed_uuid = uuid.UUID("12345678123456781234567812345678")
    monkeypatch.setattr(cef.uuid, "uuid4", lambda: fixed_uuid)
    monkeypatch.setattr(cep.uuid, "uuid4", lambda: fixed_uuid)


def _export(fn, pl, body, frozen_time):
    """Run one body through both export paths; return both conversations."""
    fn_path = asyncio.run(fn.outlet(dict(body)))
    pl_path = asyncio.run(pl.outlet(dict(body)))
    assert fn_path is not None and pl_path is not None

    def read(directory):
        files = [f for f in os.listdir(directory) if f.endswith(".curt")]
        assert len(files) == 1, files
        with open(os.path.join(directory, files[0]), encoding="utf-8") as f:
            return json.load(f)

    fn_env = read(fn.valves.EXPORT_DIR)
    pl_env = read(pl.valves.OUTPUT_DIR)
    assert fn_env["curt"] == pl_env["curt"]
    assert fn_env["version"] == pl_env["version"]
    return fn_env["conversation"], pl_env["conversation"]


def test_parity_turn_body(dirs, frozen_time):
    fn, pl = dirs
    body = {
        "chat_id": "synthetic-chat-0001",
        "model": "llama3.1:8b",
        "messages": [
            {"role": "user", "content": "Hello fixture world."},
            {"role": "assistant", "content": "Greetings from the fixture reply.",
             "model": "llama3.1:8b"},
        ],
    }
    fn_conv, pl_conv = _export(fn, pl, body, frozen_time)
    assert fn_conv == pl_conv


def test_parity_history_tree(dirs, frozen_time):
    fn, pl = dirs
    body = {
        "chat_id": "tree-chat-0001",
        "model": "llama3.1:8b",
        "chat": {
            "title": "Fixture: tree chat",
            "models": ["llama3.1:8b"],
            "history": PLAIN_HISTORY,
        },
        "messages": [{"role": "user", "content": "stale turn body"}],
    }
    fn_conv, pl_conv = _export(fn, pl, body, frozen_time)
    assert fn_conv == pl_conv


def test_parity_blocks_and_variants(dirs, frozen_time):
    fn, pl = dirs
    body = {
        "chat_id": "block-chat-0001",
        "chat": {
            "title": "Fixture: block chat",
            "models": ["mistral-small"],
            "history": BLOCK_HISTORY,
        },
        "messages": [],
    }
    fn_conv, pl_conv = _export(fn, pl, body, frozen_time)
    assert fn_conv == pl_conv


def test_parity_no_chat_id_synthesized_identically(dirs, frozen_time):
    fn, pl = dirs
    body = {"messages": [{"role": "user", "content": "hi"}]}
    fn_conv, pl_conv = _export(fn, pl, body, frozen_time)
    assert fn_conv == pl_conv
    assert fn_conv["id"].startswith("openwebui_")
