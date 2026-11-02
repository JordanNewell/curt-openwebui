"""Outlet behavior: writes/updates .curt files from Function outlet bodies,
including the modern chat.history tree when the body embeds a chat payload."""

import asyncio
import json
import os

import pytest

import curt_export_function as cef

from pipelines.tests.test_convert_chat import PLAIN_HISTORY, BLOCK_HISTORY


@pytest.fixture()
def filt(tmp_path):
    f = cef.Filter()
    f.valves.EXPORT_DIR = str(tmp_path)
    return f


def read_curt(output_dir):
    files = [f for f in os.listdir(output_dir) if f.endswith(".curt")]
    assert len(files) == 1
    with open(os.path.join(output_dir, files[0]), encoding="utf-8") as f:
        return json.load(f)


def test_outlet_writes_valid_curt_from_turn_body(filt):
    body = {
        "chat_id": "synthetic-chat-0001",
        "model": "llama3.1:8b",
        "messages": [
            {"role": "user", "content": "Hello fixture world."},
            {"role": "assistant", "content": "Greetings from the fixture reply.",
             "model": "llama3.1:8b"},
        ],
    }
    returned = asyncio.run(filt.outlet(dict(body)))
    assert returned == body  # body passes through untouched

    envelope = read_curt(filt.valves.EXPORT_DIR)
    assert envelope["curt"] == "curtis-conversation"
    assert envelope["version"] == 1
    assert envelope["generator"] == "curt-openwebui-function/0.1.0"
    conv = envelope["conversation"]
    assert cef.is_valid_conversation(conv)
    assert conv["id"] == "synthetic-chat-0001"
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]
    assert conv["messages"][1]["model"] == "llama3.1:8b"
    assert conv["provider"] == "Open WebUI"


def test_outlet_prefers_history_tree_over_turn_body(filt):
    """When the body embeds a chat payload with a history tree, the Function
    exports the UI-visible parent chain, not the raw turn-body message list."""
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
    asyncio.run(filt.outlet(body))
    envelope = read_curt(filt.valves.EXPORT_DIR)
    conv = envelope["conversation"]
    assert [m["id"] for m in conv["messages"]] == ["m1", "m2", "m3"]
    assert conv["messages"][1]["model"] == "llama3.1:8b"


def test_outlet_tree_with_variants_and_block_content(filt):
    body = {
        "chat_id": "block-chat-0001",
        "chat": {
            "title": "Fixture: block chat",
            "models": ["mistral-small"],
            "history": BLOCK_HISTORY,
        },
        "messages": [],
    }
    asyncio.run(filt.outlet(body))
    envelope = read_curt(filt.valves.EXPORT_DIR)
    conv = envelope["conversation"]
    assert cef.is_valid_conversation(conv)
    assert [m["id"] for m in conv["messages"]] == ["blk-1", "blk-2", "blk-3"]
    assert conv["messages"][2]["content"] == (
        "Here is what I found:\n\n- repo-a\n- repo-b\n- repo-c"
    )
    assert conv["messages"][2]["openwebuiContent"][0]["text"] == "Here is what I found:"


def test_outlet_tree_counts_dropped_variants(filt):
    body = {
        "chat_id": "variant-chat-0001",
        "chat": {
            "title": "Fixture: variants",
            "history": {
                "currentId": "b2",
                "messages": {
                    "b1": {"id": "b1", "parentId": None, "childrenIds": ["b2", "b2x"],
                           "role": "user", "content": "q", "timestamp": 1761800000},
                    "b2": {"id": "b2", "parentId": "b1", "childrenIds": [], "role": "assistant",
                           "content": "kept", "timestamp": 1761800010},
                    "b2x": {"id": "b2x", "parentId": "b1", "childrenIds": [], "role": "assistant",
                            "content": "variant", "timestamp": 1761800015},
                },
            },
        },
        "messages": [],
    }
    asyncio.run(filt.outlet(body))
    envelope = read_curt(filt.valves.EXPORT_DIR)
    assert [m["id"] for m in envelope["conversation"]["messages"]] == ["b1", "b2"]
    assert envelope["conversation"]["openwebuiSkippedBranches"] == 1


def test_second_turn_updates_same_file(filt):
    body = {
        "chat_id": "synthetic-chat-0001",
        "model": "llama3.1:8b",
        "messages": [
            {"role": "user", "content": "Hello fixture world."},
            {"role": "assistant", "content": "Greetings from the fixture reply.",
             "model": "llama3.1:8b"},
        ],
    }
    asyncio.run(filt.outlet(dict(body)))
    body["messages"] = body["messages"] + [{"role": "user", "content": "Follow-up question."}]
    asyncio.run(filt.outlet(body))
    envelope = read_curt(filt.valves.EXPORT_DIR)
    assert len(envelope["conversation"]["messages"]) == 3


def test_valve_off_means_no_files(filt):
    filt.valves.EXPORT_ON_OUTLET = False
    asyncio.run(filt.outlet({"chat_id": "x", "messages": [{"role": "user", "content": "hi"}]}))
    assert os.listdir(filt.valves.EXPORT_DIR) == []


def test_block_array_content_in_turn_body(filt):
    body = {
        "chat_id": "blocks-turn-0001",
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "What is up?"}]},
            {"role": "assistant", "content": "fine"},
        ],
    }
    asyncio.run(filt.outlet(body))
    envelope = read_curt(filt.valves.EXPORT_DIR)
    conv = envelope["conversation"]
    assert [m["content"] for m in conv["messages"]] == ["What is up?", "fine"]
    assert conv["messages"][0]["openwebuiContent"] == [{"type": "text", "text": "What is up?"}]


def test_error_stub_and_unknown_roles_dropped_in_turn_body(filt):
    body = {
        "chat_id": "filter-turn-0001",
        "messages": [
            {"role": "oracle", "content": "not a curt role"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "boom", "error": True},
        ],
    }
    asyncio.run(filt.outlet(body))
    envelope = read_curt(filt.valves.EXPORT_DIR)
    assert [m["role"] for m in envelope["conversation"]["messages"]] == ["user"]


def test_outlet_without_messages_writes_nothing(filt):
    result = filt._export({"chat_id": "empty-1"})
    assert result is None
    assert os.listdir(filt.valves.EXPORT_DIR) == []


def test_export_failure_never_breaks_the_turn(filt):
    """Export errors are swallowed: outlet always returns the body intact."""
    filt.valves.EXPORT_DIR = "Z:\\definitely-not-a-real-dir\\curt"
    body = {"chat_id": "boom-1", "messages": [{"role": "user", "content": "hi"}]}
    returned = asyncio.run(filt.outlet(body))
    assert returned == body


def test_missing_chat_id_synthesizes_one(filt):
    body = {"messages": [{"role": "user", "content": "hi"}]}
    asyncio.run(filt.outlet(body))
    envelope = read_curt(filt.valves.EXPORT_DIR)
    conv = envelope["conversation"]
    assert conv["id"].startswith("openwebui_")
    assert conv["title"] == "Untitled chat"
