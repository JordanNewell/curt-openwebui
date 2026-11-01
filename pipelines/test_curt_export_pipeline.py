"""Unit tests for the .curt export pipeline. No network: the API-enrichment
path is exercised only through its None-returning fallback."""

import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import curt_export_pipeline as cep


def make_pipeline(output_dir: str):
    p = cep.Pipeline()
    p.valves.OPENWEBUI_BASE_URL = ""
    p.valves.OPENWEBUI_API_KEY = ""
    p.valves.OUTPUT_DIR = output_dir
    return p


SYNTHETIC_BODY = {
    "chat_id": "synthetic-chat-0001",
    "model": "llama3.1:8b",
    "messages": [
        {"role": "user", "content": "Hello fixture world."},
        {"role": "assistant", "content": "Greetings from the fixture reply.", "model": "llama3.1:8b"},
    ],
}


class TestCurtHelpers(unittest.TestCase):
    def test_filename_convention(self):
        name = cep.curt_filename(
            {"id": "chat_abc12345", "title": "My Test Chat!", "createdAt": 1735689600000}
        )
        self.assertEqual(name, "2025-01-01 my-test-chat abc12345.curt")

    def test_filename_survives_bad_timestamps(self):
        name = cep.curt_filename({"id": "plainid", "title": "x", "createdAt": 10**30})
        self.assertTrue(name.startswith("1970-01-01 "))

    def test_validation_rejects_missing_fields(self):
        ok = {
            "id": "a", "title": "", "createdAt": 1, "updatedAt": 2,
            "messages": [{"id": "m", "role": "user", "content": "hi", "timestamp": 3}],
        }
        self.assertTrue(cep.is_valid_conversation(ok))
        for mutation in (
            {"id": None},
            {"createdAt": None},
            {"messages": [{"id": "m", "role": "oracle", "content": "x", "timestamp": 1}]},
            {"messages": [{"id": "m", "role": "user", "content": 5, "timestamp": 1}]},
        ):
            bad = dict(ok)
            bad.update(mutation)
            self.assertFalse(cep.is_valid_conversation(bad), mutation)

    def test_serializer_envelope(self):
        conv = {"id": "a", "title": "t", "createdAt": 1, "updatedAt": 1, "messages": []}
        body = cep.serialize_curt(conv, "gen/1")
        envelope = json.loads(body)
        self.assertEqual(envelope["curt"], "curtis-conversation")
        self.assertEqual(envelope["version"], 1)
        self.assertEqual(envelope["generator"], "gen/1")
        self.assertIn("\n\t\"", body)  # tab-indented


class TestPipelineOutlet(unittest.TestCase):
    def test_outlet_writes_valid_curt(self):
        with tempfile.TemporaryDirectory() as outdir:
            p = make_pipeline(outdir)
            returned = asyncio.run(p.outlet(dict(SYNTHETIC_BODY)))
            self.assertEqual(returned, SYNTHETIC_BODY)  # body passes through untouched

            files = [f for f in os.listdir(outdir) if f.endswith(".curt")]
            self.assertEqual(len(files), 1)
            envelope = json.loads(open(os.path.join(outdir, files[0]), encoding="utf-8").read())
            self.assertEqual(envelope["curt"], "curtis-conversation")
            conv = envelope["conversation"]
            self.assertEqual(conv["id"], "synthetic-chat-0001")
            self.assertEqual([m["role"] for m in conv["messages"]], ["user", "assistant"])
            self.assertEqual(conv["messages"][1]["model"], "llama3.1:8b")
            self.assertEqual(conv["provider"], "Open WebUI")

    def test_second_turn_updates_same_file(self):
        with tempfile.TemporaryDirectory() as outdir:
            p = make_pipeline(outdir)
            asyncio.run(p.outlet(dict(SYNTHETIC_BODY)))
            body = dict(SYNTHETIC_BODY)
            body["messages"] = SYNTHETIC_BODY["messages"] + [
                {"role": "user", "content": "Follow-up question."}
            ]
            asyncio.run(p.outlet(body))
            files = [f for f in os.listdir(outdir) if f.endswith(".curt")]
            self.assertEqual(len(files), 1)
            envelope = json.loads(open(os.path.join(outdir, files[0]), encoding="utf-8").read())
            self.assertEqual(len(envelope["conversation"]["messages"]), 3)

    def test_valve_off_means_no_files(self):
        with tempfile.TemporaryDirectory() as outdir:
            p = make_pipeline(outdir)
            p.valves.EXPORT_ON_OUTLET = False
            asyncio.run(p.outlet(dict(SYNTHETIC_BODY)))
            self.assertEqual(os.listdir(outdir), [])

    def test_non_string_content_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as outdir:
            p = make_pipeline(outdir)
            body = dict(SYNTHETIC_BODY)
            body["messages"] = [
                {"role": "user", "content": ["block", "list"]},
                {"role": "assistant", "content": "fine"},
            ]
            asyncio.run(p.outlet(body))
            files = [f for f in os.listdir(outdir) if f.endswith(".curt")]
            self.assertEqual(len(files), 1)
            envelope = json.loads(open(os.path.join(outdir, files[0]), encoding="utf-8").read())
            self.assertEqual(len(envelope["conversation"]["messages"]), 1)


if __name__ == "__main__":
    unittest.main()
