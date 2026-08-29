import unittest

from pr_attention.evidence_bundle import build_evidence_bundle
from pr_attention.handoff import build_review_envelope
from pr_attention.integration_gate import build_integration_gate
from pr_attention.metrics import measure_compaction
from pr_attention.review_result import packet_sha256, validate_review_result

HEAD = "a" * 40
BASE = "b" * 40


def snapshot(attention="READY", blockers=None):
    return {
        "schema_version": 2, "repository": "o/r", "pr_number": 11, "title": "metrics",
        "base_ref": "main", "head_ref": "feat/x", "head_sha": HEAD, "final_head_sha": HEAD,
        "generated_at": "now", "scope": {"additions": 1, "deletions": 0, "changed_files": 1},
        "checks": {"state": "SUCCESS", "total": 1, "passed": ["unit"], "pending": [], "failed": [], "unknown": []},
        "reviews": {"state": "NONE", "current_head_approvals": [], "current_head_changes_requested": [], "current_head_commented": [], "stale_review_count": 3, "dismissed_review_count": 0},
        "threads": {"total": 0, "unresolved_current": 0, "unresolved_outdated": 0, "resolved": 0, "unresolved_current_items": []},
        "merge": {"mergeable": True, "mergeable_state": "clean", "conflict": False},
        "delta": {"accepted_head_sha": BASE, "relation": "AHEAD", "acceptance_validity": "REUSABLE_FOR_UNCHANGED", "review_scope": "DELTA", "complete": True, "commits_ahead": 1, "commits_behind": 0, "additions": 1, "deletions": 0, "changed_files": 1, "files": [{"path": "a.py", "status": "modified", "additions": 1, "deletions": 0, "changes": 1, "previous_path": None}], "reasons": []},
        "attention": attention, "next_action_class": "REPAIR" if attention == "BLOCKED" else "REVIEW_DELTA",
        "blockers": blockers or [], "pending_reasons": [], "facts_complete": True, "stale": False,
    }


def packet():
    patch = "+" + ("x" * 8000)
    return {
        "schema_version": 1, "repository": "o/r", "pr_number": 11, "accepted_head_sha": BASE,
        "head_sha": HEAD, "final_head_sha": HEAD, "generated_at": "now", "relation": "AHEAD", "review_scope": "DELTA",
        "attention": "READY", "next_action_class": "REVIEW_DELTA", "content_trust": "UNTRUSTED_REPOSITORY_CONTENT",
        "coverage": "COMPLETE", "complete": True, "max_total_patch_bytes": 10000, "max_file_patch_bytes": 10000,
        "included_patch_bytes": len(patch.encode()),
        "files": [{"path": "a.py", "status": "modified", "additions": 1, "deletions": 0, "changes": 1, "previous_path": None, "patch": patch, "original_patch_bytes": len(patch.encode()), "included_patch_bytes": len(patch.encode()), "truncated": False, "omission_reason": None}],
        "reasons": [],
    }


def bundle(verdict="PASS", snap=None):
    snap = snap or snapshot()
    pkt = packet()
    findings = [] if verdict == "PASS" else [{"id": "F1", "severity": "P1", "blocking": True, "title": "broken", "detail": "repair", "path": "a.py", "line": 1}]
    result = {"schema_version": 1, "repository": "o/r", "pr_number": 11, "accepted_head_sha": BASE, "head_sha": HEAD, "packet_sha256": packet_sha256(pkt), "reviewer": {"name": "tester"}, "verdict": verdict, "reviewed_files": ["a.py"], "findings": findings, "notes": []}
    validation = validate_review_result(pkt, result, live_head_sha=HEAD).to_dict()
    gate = build_integration_gate(snap, validation).to_dict()
    return build_evidence_bundle(snap, packet=pkt, envelope=build_review_envelope(pkt, reviewer_name="tester"), review_result=result, validation=validation, integration_gate=gate)


class MetricsTests(unittest.TestCase):
    def test_patch_heavy_bundle_compacts_materially(self):
        metrics = measure_compaction(bundle())
        sizes = metrics["canonical_json_bytes"]
        self.assertGreater(sizes["evidence_bundle"], sizes["compact_digest"])
        self.assertGreater(sizes["bytes_avoided_by_first_read"], 0)
        self.assertGreater(sizes["included_patch_evidence"], 7000)
        self.assertGreater(metrics["canonical_json_bytes"]["first_read_reduction_basis_points"], 0)

    def test_metrics_do_not_claim_token_savings(self):
        metrics = measure_compaction(bundle())
        self.assertIsNone(metrics["measurement_boundary"]["token_estimate"])
        self.assertIn("consumer", metrics["measurement_boundary"]["note"])

    def test_metrics_are_deterministic(self):
        source = bundle()
        self.assertEqual(measure_compaction(source), measure_compaction(source))
        self.assertTrue(measure_compaction(source)["metrics_sha256"].startswith("sha256:"))

    def test_repair_metrics_include_repair_packet_size(self):
        metrics = measure_compaction(bundle(verdict="FAIL"))
        self.assertIsNotNone(metrics["canonical_json_bytes"]["repair_packet"])
        self.assertTrue(metrics["repair_packet_sha256"].startswith("sha256:"))

    def test_invalid_bundle_fails_closed(self):
        source = bundle()
        source["head_sha"] = "c" * 40
        with self.assertRaisesRegex(ValueError, "evidence bundle is invalid"):
            measure_compaction(source)


if __name__ == "__main__":
    unittest.main()
