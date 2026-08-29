import json
import os
import tempfile
import unittest
from unittest.mock import patch

from pr_attention.cli import main
from pr_attention.review_result import packet_sha256

BASE = "a" * 40
HEAD = "b" * 40


def packet():
    return {
        "schema_version": 1,
        "repository": "o/r",
        "pr_number": 3,
        "accepted_head_sha": BASE,
        "head_sha": HEAD,
        "final_head_sha": HEAD,
        "relation": "AHEAD",
        "review_scope": "DELTA",
        "content_trust": "UNTRUSTED_REPOSITORY_CONTENT",
        "coverage": "COMPLETE",
        "complete": True,
        "max_total_patch_bytes": 1000,
        "max_file_patch_bytes": 1000,
        "included_patch_bytes": 2,
        "files": [{"path": "a.py", "status": "modified", "patch": "+x"}],
    }


class HandoffCLITests(unittest.TestCase):
    def test_result_template_command_is_offline(self):
        p = packet()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            packet_path = os.path.join(tmp, "packet.json")
            output_path = os.path.join(tmp, "template.json")
            with open(packet_path, "w", encoding="utf-8") as handle:
                json.dump(p, handle)
            code = main([
                "review-result-template",
                packet_path,
                "--reviewer-name",
                "ChatGPT",
                "--reviewer-model",
                "test-model",
                "--output",
                output_path,
            ])
            self.assertEqual(code, 0)
            with open(output_path, encoding="utf-8") as handle:
                template = json.load(handle)
            self.assertEqual(template["packet_sha256"], packet_sha256(p))
            self.assertEqual(template["reviewer"], {"name": "ChatGPT", "model": "test-model"})
            self.assertEqual(template["reviewed_files"], [])

    def test_review_envelope_command_is_offline(self):
        p = packet()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            packet_path = os.path.join(tmp, "packet.json")
            output_path = os.path.join(tmp, "envelope.json")
            with open(packet_path, "w", encoding="utf-8") as handle:
                json.dump(p, handle)
            code = main([
                "review-envelope",
                packet_path,
                "--reviewer-name",
                "Claude",
                "--output",
                output_path,
            ])
            self.assertEqual(code, 0)
            with open(output_path, encoding="utf-8") as handle:
                envelope = json.load(handle)
            self.assertEqual(envelope["packet_sha256"], packet_sha256(p))
            self.assertEqual(envelope["packet"], p)
            self.assertEqual(envelope["review_result_template"]["reviewer"]["name"], "Claude")

    def test_prefill_reviewed_files_is_explicit(self):
        p = packet()
        with tempfile.TemporaryDirectory() as tmp:
            packet_path = os.path.join(tmp, "packet.json")
            output_path = os.path.join(tmp, "template.json")
            with open(packet_path, "w", encoding="utf-8") as handle:
                json.dump(p, handle)
            code = main([
                "review-result-template",
                packet_path,
                "--reviewer-name",
                "GLM",
                "--prefill-reviewed-files",
                "--output",
                output_path,
            ])
            self.assertEqual(code, 0)
            with open(output_path, encoding="utf-8") as handle:
                template = json.load(handle)
            self.assertEqual(template["reviewed_files"], ["a.py"])


if __name__ == "__main__":
    unittest.main()
