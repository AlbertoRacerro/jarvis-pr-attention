import json
import os
import tempfile
import unittest
from unittest.mock import patch

from pr_attention.cli import main
from pr_attention.review_result import packet_sha256


class CLITests(unittest.TestCase):
    def test_missing_token_is_bounded_error_for_snapshot(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(main(["snapshot", "o/r", "1"]), 40)

    def test_missing_token_is_bounded_error_for_packet(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(main(["review-packet", "o/r", "1", "--accepted-head", "a" * 40]), 70)

    def test_packet_digest_is_offline(self):
        packet = self._packet()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            packet_path = os.path.join(tmp, "packet.json")
            with open(packet_path, "w", encoding="utf-8") as handle:
                json.dump(packet, handle)
            self.assertEqual(main(["packet-digest", packet_path]), 0)

    def test_review_result_validation_is_offline_without_live_flag(self):
        packet = self._packet()
        result = {
            "schema_version": 1,
            "repository": packet["repository"],
            "pr_number": packet["pr_number"],
            "accepted_head_sha": packet["accepted_head_sha"],
            "head_sha": packet["head_sha"],
            "packet_sha256": packet_sha256(packet),
            "reviewer": {"name": "unit"},
            "verdict": "PASS",
            "reviewed_files": ["a.py"],
            "findings": [],
            "notes": [],
        }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            packet_path = os.path.join(tmp, "packet.json")
            result_path = os.path.join(tmp, "result.json")
            with open(packet_path, "w", encoding="utf-8") as handle:
                json.dump(packet, handle)
            with open(result_path, "w", encoding="utf-8") as handle:
                json.dump(result, handle)
            self.assertEqual(main(["validate-review-result", packet_path, result_path, "--no-validation-exit"]), 0)

    @staticmethod
    def _packet():
        return {
            "schema_version": 1,
            "repository": "o/r",
            "pr_number": 1,
            "accepted_head_sha": "a" * 40,
            "head_sha": "b" * 40,
            "final_head_sha": "b" * 40,
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


if __name__ == "__main__":
    unittest.main()
