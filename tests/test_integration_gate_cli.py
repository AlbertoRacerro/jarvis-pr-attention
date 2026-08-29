import json
import os
import tempfile
import unittest
from unittest.mock import patch

from pr_attention.cli import main

HEAD = "a" * 40
DIGEST = "sha256:" + "b" * 64


def snapshot(attention="READY"):
    return {
        "schema_version": 2,
        "repository": "o/r",
        "pr_number": 1,
        "head_sha": HEAD,
        "final_head_sha": HEAD,
        "attention": attention,
        "facts_complete": True,
        "stale": False,
    }


def validation(live_head=HEAD):
    return {
        "schema_version": 1,
        "valid": True,
        "status": "VALID_PASS",
        "repository": "o/r",
        "pr_number": 1,
        "head_sha": HEAD,
        "packet_sha256": DIGEST,
        "verdict": "PASS",
        "live_head_sha": live_head,
        "reasons": [],
    }


class IntegrationGateCLITests(unittest.TestCase):
    def _write(self, path, payload):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def test_ready_gate_command_is_offline(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            snapshot_path = os.path.join(tmp, "snapshot.json")
            validation_path = os.path.join(tmp, "validation.json")
            output_path = os.path.join(tmp, "gate.json")
            self._write(snapshot_path, snapshot())
            self._write(validation_path, validation())
            code = main(["integration-gate", snapshot_path, validation_path, "--output", output_path])
            self.assertEqual(code, 0)
            with open(output_path, encoding="utf-8") as handle:
                gate = json.load(handle)
            self.assertEqual(gate["status"], "READY_TO_MERGE")
            self.assertTrue(gate["merge_ready"])

    def test_pending_gate_has_nonzero_policy_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot_path = os.path.join(tmp, "snapshot.json")
            validation_path = os.path.join(tmp, "validation.json")
            self._write(snapshot_path, snapshot("PENDING"))
            self._write(validation_path, validation())
            self.assertEqual(main(["integration-gate", snapshot_path, validation_path]), 90)

    def test_no_gate_exit_allows_orchestrator_to_read_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot_path = os.path.join(tmp, "snapshot.json")
            validation_path = os.path.join(tmp, "validation.json")
            self._write(snapshot_path, snapshot("BLOCKED"))
            self._write(validation_path, validation())
            self.assertEqual(main(["integration-gate", snapshot_path, validation_path, "--no-gate-exit"]), 0)

    def test_offline_review_pass_requires_live_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot_path = os.path.join(tmp, "snapshot.json")
            validation_path = os.path.join(tmp, "validation.json")
            output_path = os.path.join(tmp, "gate.json")
            self._write(snapshot_path, snapshot())
            self._write(validation_path, validation(None))
            code = main([
                "integration-gate",
                snapshot_path,
                validation_path,
                "--output",
                output_path,
                "--no-gate-exit",
            ])
            self.assertEqual(code, 0)
            with open(output_path, encoding="utf-8") as handle:
                gate = json.load(handle)
            self.assertEqual(gate["status"], "VERIFY_LIVE")
            self.assertFalse(gate["merge_ready"])


if __name__ == "__main__":
    unittest.main()
