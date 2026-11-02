"""Filename convention, serializer envelope, and v1 validation rules —
mirrored from pipelines/tests/test_helpers.py against the Function module."""

import json

import curt_export_function as cef


def test_filename_convention():
    name = cef.curt_filename(
        {"id": "chat_abc12345", "title": "My Test Chat!", "createdAt": 1735689600000}
    )
    assert name == "2025-01-01 my-test-chat abc12345.curt"


def test_filename_survives_bad_timestamps():
    name = cef.curt_filename({"id": "plainid", "title": "x", "createdAt": 10**30})
    assert name.startswith("1970-01-01 ")


def test_serializer_envelope():
    conv = {"id": "a", "title": "t", "createdAt": 1, "updatedAt": 1, "messages": []}
    body = cef.serialize_curt(conv, "gen/1")
    envelope = json.loads(body)
    assert envelope["curt"] == "curtis-conversation"
    assert envelope["version"] == 1
    assert envelope["generator"] == "gen/1"
    assert '\n\t"' in body  # tab-indented


def test_validation_rejects_missing_fields():
    ok = {
        "id": "a",
        "title": "",
        "createdAt": 1,
        "updatedAt": 2,
        "messages": [{"id": "m", "role": "user", "content": "hi", "timestamp": 3}],
    }
    assert cef.is_valid_conversation(ok)
    for mutation in (
        {"id": None},
        {"createdAt": None},
        {"messages": [{"id": "m", "role": "oracle", "content": "x", "timestamp": 1}]},
        {"messages": [{"id": "m", "role": "user", "content": 5, "timestamp": 1}]},
    ):
        bad = dict(ok)
        bad.update(mutation)
        assert not cef.is_valid_conversation(bad), mutation


def test_seconds_to_ms_mirrors_ts_math_round():
    assert cef._seconds_to_ms(1761800000) == 1761800000000
    assert cef._seconds_to_ms(1761800000.4) == 1761800000400
    assert cef._seconds_to_ms(1761800000.5) == 1761800000500
    assert cef._seconds_to_ms(0) == 0
    assert cef._seconds_to_ms(None) == 0
    assert cef._seconds_to_ms(True) == 0  # bools are not timestamps
    assert cef._seconds_to_ms(float("nan")) == 0
