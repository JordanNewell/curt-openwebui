"""convert_chat mapping tests: the ChatResponse -> .curt v1 conversation path
shared with the CLI (see scripts/parity-check.md). Fixture payloads cover
plain, legacy flat, block-array, and regenerate-variant chats; every mapped
conversation is checked against the pipeline's own v1 validator."""

import json
import os

import curt_export_pipeline as cep

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE_NDJSON = os.path.join(REPO_ROOT, "test", "fixtures", "chat-export.ndjson")


def load_repo_fixtures():
    chats = []
    with open(FIXTURE_NDJSON, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chats.append(json.loads(line))
    return chats


def make_chat(body, **overrides):
    chat = {
        "id": "chat-1",
        "title": "Fixture chat",
        "chat": body,
        "created_at": 1761800000,
        "updated_at": 1761800030,
    }
    chat.update(overrides)
    return chat


# --- fixture chat payloads ---------------------------------------------------

PLAIN_HISTORY = {
    "currentId": "m3",
    "messages": {
        "m1": {"id": "m1", "parentId": None, "childrenIds": ["m2"], "role": "user",
               "content": "Hello fixture world.", "timestamp": 1761800000},
        "m2": {"id": "m2", "parentId": "m1", "childrenIds": ["m3"], "role": "assistant",
               "content": "Greetings from the fixture reply.", "model": "llama3.1:8b",
               "timestamp": 1761800010, "usage": {"completion_tokens": 9}},
        "m3": {"id": "m3", "parentId": "m2", "childrenIds": [], "role": "user",
               "content": "Thanks!", "timestamp": 1761800020},
    },
}

LEGACY_FLAT_BODY = {
    "models": ["gpt-4o-mini"],
    "messages": [
        {"id": "leg-1", "role": "system", "content": "You are a helpful assistant."},
        {"id": "leg-2", "role": "user", "content": "Say hello in French.", "timestamp": 1755100000},
        {"id": "leg-3", "role": "assistant", "content": "Bonjour !", "model": "gpt-4o-mini",
         "timestamp": 1755100005},
    ],
    "history": {"currentId": "leg-3", "messages": {}},
}

BLOCK_HISTORY = {
    "currentId": "blk-3",
    "messages": {
        "blk-1": {"id": "blk-1", "parentId": None, "childrenIds": ["blk-2"], "role": "user",
                  "content": "Search for the repo.", "timestamp": 1760000000},
        "blk-2": {"id": "blk-2", "parentId": "blk-1", "childrenIds": ["blk-3"], "role": "tool",
                  "content": '[{"name":"result","value":"found 3 repos"}]',
                  "timestamp": 1760000005},
        "blk-3": {"id": "blk-3", "parentId": "blk-2", "childrenIds": [], "role": "assistant",
                  "content": [
                      {"type": "text", "text": "Here is what I found:"},
                      {"type": "text", "text": "- repo-a\n- repo-b\n- repo-c"},
                  ],
                  "model_id": "mistral-small", "done": True, "error": None,
                  "timestamp": 1760000010, "sources": [{"source": {"name": "README.md"}}]},
    },
}

VARIANT_HISTORY = {
    "currentId": "v3",
    "messages": {
        "v1": {"id": "v1", "parentId": None, "childrenIds": ["v2", "v2b"], "role": "user",
               "content": "Question one.", "timestamp": 1761800000},
        "v2": {"id": "v2", "parentId": "v1", "childrenIds": ["v3"], "role": "assistant",
               "content": "Kept branch answer.", "model": "llama3.1:8b", "timestamp": 1761800010},
        "v2b": {"id": "v2b", "parentId": "v1", "childrenIds": ["v3b"], "role": "assistant",
                "content": "Regenerate variant, dropped.", "model": "llama3.1:8b",
                "timestamp": 1761800015},
        "v3": {"id": "v3", "parentId": "v2", "childrenIds": [], "role": "user",
               "content": "Follow-up.", "timestamp": 1761800020},
        "v3b": {"id": "v3b", "parentId": "v2b", "childrenIds": [], "role": "assistant",
                "content": "Orphan descendant of the dropped branch.", "model": "llama3.1:8b",
                "timestamp": 1761800025},
    },
}


# --- plain history -----------------------------------------------------------

def test_plain_history_maps_current_branch():
    conversation, stats = cep.convert_chat(make_chat({"models": ["llama3.1:8b"], "history": PLAIN_HISTORY}))
    assert cep.is_valid_conversation(conversation)
    assert [m["id"] for m in conversation["messages"]] == ["m1", "m2", "m3"]
    assert [m["role"] for m in conversation["messages"]] == ["user", "assistant", "user"]
    assert conversation["messages"][1]["model"] == "llama3.1:8b"
    assert stats["skippedBranches"] == 0
    assert "openwebuiSkippedBranches" not in conversation


def test_timestamps_seconds_to_ms_and_fallback():
    conversation, _ = cep.convert_chat(make_chat({"models": ["llama3.1:8b"], "history": PLAIN_HISTORY}))
    assert conversation["createdAt"] == 1761800000000
    assert conversation["updatedAt"] == 1761800030000
    assert conversation["messages"][0]["timestamp"] == 1761800000000
    # legacy flat messages without a timestamp fall back to chat updatedAt
    conversation, _ = cep.convert_chat(make_chat(LEGACY_FLAT_BODY, updated_at=1755100006))
    assert conversation["messages"][0]["timestamp"] == 1755100006000


# --- legacy flat -------------------------------------------------------------

def test_legacy_flat_messages_used_when_history_empty():
    conversation, stats = cep.convert_chat(make_chat(LEGACY_FLAT_BODY))
    assert cep.is_valid_conversation(conversation)
    assert [m["id"] for m in conversation["messages"]] == ["leg-1", "leg-2", "leg-3"]
    assert conversation["model"] == "gpt-4o-mini"
    assert stats["skippedBranches"] == 0


def test_legacy_flat_chat_from_repo_fixture():
    legacy = next(c for c in load_repo_fixtures() if c["id"].endswith("0002"))
    conversation, _ = cep.convert_chat(legacy)
    assert cep.is_valid_conversation(conversation)
    assert [m["role"] for m in conversation["messages"]] == ["system", "user", "assistant"]
    assert conversation["folder_id"] == "folder-77"


# --- block-array content -----------------------------------------------------

def test_block_array_content_joined_and_preserved():
    conversation, _ = cep.convert_chat(make_chat({"models": ["mistral-small"], "history": BLOCK_HISTORY}))
    assert cep.is_valid_conversation(conversation)
    assistant = conversation["messages"][2]
    assert assistant["role"] == "assistant"
    assert assistant["content"] == "Here is what I found:\n\n- repo-a\n- repo-b\n- repo-c"
    assert assistant["openwebuiContent"] == BLOCK_HISTORY["messages"]["blk-3"]["content"]
    assert assistant["model"] == "mistral-small"  # model_id variant
    assert assistant["sources"] == [{"source": {"name": "README.md"}}]
    assert conversation["messages"][1]["role"] == "tool"  # tool/intermediate steps kept


# --- regenerate variants -----------------------------------------------------

def test_regenerate_variants_skipped_and_counted():
    conversation, stats = cep.convert_chat(make_chat({"models": ["llama3.1:8b"], "history": VARIANT_HISTORY}))
    assert cep.is_valid_conversation(conversation)
    assert [m["id"] for m in conversation["messages"]] == ["v1", "v2", "v3"]
    assert stats["skippedBranches"] == 2  # v2b and its orphan descendant v3b
    assert conversation["openwebuiSkippedBranches"] == 2


def test_variant_count_on_repo_fixture():
    tree = next(c for c in load_repo_fixtures() if c["id"].endswith("0001"))
    conversation, stats = cep.convert_chat(tree)
    assert [m["id"] for m in conversation["messages"]] == ["msg-a1", "msg-a2", "msg-a3"]
    assert stats["skippedBranches"] == 1
    assert conversation["openwebuiSkippedBranches"] == 1


# --- hidden / non-rendered messages ------------------------------------------

def test_legacy_error_stub_is_hidden():
    body = {
        "currentId": "e2",
        "messages": {
            "e1": {"id": "e1", "parentId": None, "childrenIds": ["e2"], "role": "user",
                   "content": "hi", "timestamp": 1761800000},
            "e2": {"id": "e2", "parentId": "e1", "childrenIds": [], "role": "assistant",
                   "content": "model overloaded, try again", "error": True,
                   "timestamp": 1761800010},
        },
    }
    conversation, stats = cep.convert_chat(make_chat({"history": body}))
    assert [m["id"] for m in conversation["messages"]] == ["e1"]
    assert stats["skippedHidden"] == 1


def test_error_object_is_kept_as_passthrough():
    body = {
        "currentId": "f2",
        "messages": {
            "f1": {"id": "f1", "parentId": None, "childrenIds": ["f2"], "role": "user",
                   "content": "hi", "timestamp": 1761800000},
            "f2": {"id": "f2", "parentId": "f1", "childrenIds": [], "role": "assistant",
                   "content": "partial answer", "error": {"content": "stream aborted"},
                   "timestamp": 1761800010},
        },
    }
    conversation, _ = cep.convert_chat(make_chat({"history": body}))
    assert len(conversation["messages"]) == 2
    assert conversation["messages"][1]["error"] == {"content": "stream aborted"}


def test_unknown_roles_dropped_and_counted():
    body = {
        "currentId": "u2",
        "messages": {
            "u1": {"id": "u1", "parentId": None, "childrenIds": ["u2"], "role": "oracle",
                   "content": "?", "timestamp": 1761800000},
            "u2": {"id": "u2", "parentId": "u1", "childrenIds": [], "role": "user",
                   "content": "hi", "timestamp": 1761800010},
        },
    }
    conversation, stats = cep.convert_chat(make_chat({"history": body}))
    assert [m["id"] for m in conversation["messages"]] == ["u2"]
    assert stats["skippedRoles"] == 1


# --- files/sources passthrough -----------------------------------------------

def test_files_and_usage_passthrough():
    body = {
        "currentId": "p2",
        "messages": {
            "p1": {"id": "p1", "parentId": None, "childrenIds": ["p2"], "role": "user",
                   "content": "What is in this file?", "timestamp": 1761800000,
                   "files": [{"type": "file", "name": "notes.txt"}]},
            "p2": {"id": "p2", "parentId": "p1", "childrenIds": [], "role": "assistant",
                   "content": "It contains notes.", "model": "llama3.1:8b",
                   "timestamp": 1761800010, "usage": {"prompt_tokens": 8},
                   "annotations": {"rating": 1}},
        },
    }
    conversation, _ = cep.convert_chat(make_chat({"history": body}))
    assert conversation["messages"][0]["files"] == [{"type": "file", "name": "notes.txt"}]
    assert conversation["messages"][1]["usage"] == {"prompt_tokens": 8}
    assert conversation["messages"][1]["annotations"] == {"rating": 1}


# --- conversation envelope ----------------------------------------------------

def test_conversation_passthroughs_and_provider():
    chat = make_chat(
        PLAIN_HISTORY,
        folder_id="folder-9",
        share_id="share-abc",
        summary="A chat",
    )
    conversation, _ = cep.convert_chat(chat)
    assert conversation["provider"] == "Open WebUI"
    assert conversation["folder_id"] == "folder-9"
    assert conversation["share_id"] == "share-abc"
    assert conversation["summary"] == "A chat"


def test_empty_chat_maps_to_zero_messages():
    conversation, stats = cep.convert_chat(
        make_chat({"models": ["llama3.1:8b"], "messages": [],
                   "history": {"currentId": None, "messages": {}}})
    )
    assert conversation["messages"] == []
    assert stats["messages"] == 0
