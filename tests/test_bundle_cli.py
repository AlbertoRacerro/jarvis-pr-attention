import json
import os
import tempfile
import unittest

from pr_attention.bundle_cli import main

HEAD = "a" * 40


def snapshot():
    return {
        "schema_version": 2,
        "repository": "o/r",
        "pr_number": 2,
        "title": "x",
        "base_ref": "main",
        "head_ref": "feat/x",
        "head_sha": HEAD,
        "final_head_sha": HEAD,
        "generated_at": "now",
        "scope": {},
        "checks": {},
        "reviews": {},
        "threads": {},
        "merge": {},
        "delta": {"accepted_head_sha": None, "relation": "ABSENT", "review_scope": "FULL", "changed_files": 0, "files": []},
        "attention": "READY",
        "next_action_class": "FULL_REVIEW",
        "blockers": [],
        "pending_reasons": [],
        "facts_complete": True,
        "stale": False,
    }


class BundleCliTests(unittest.TestCase):
    def test_build_then_verify_snapshot_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            snap = os.path.join(directory, "snapshot.json")
            bundle = os.path.join(directory, "bundle.json")
            verify = os.path.join(directory, "verify.json")
            with open(snap, "w", encoding="utf-8") as handle:
                json.dump(snapshot(), handle)
            self.assertEqual(main(["build", snap, "--output", bundle]), 0)
            self.assertEqual(main(["verify", bundle, "--output", verify]), 0)
            with open(verify, encoding="utf-8") as handle:
                result = json.load(handle)
            self.assertTrue(result["valid"])
            self.assertEqual(result["phase"], "SNAPSHOT_ONLY")

    def test_invalid_bundle_returns_97(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "bundle.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"schema_version": 1}, handle)
            self.assertEqual(main(["verify", path]), 97)


if __name__ == "__main__":
    unittest.main()
