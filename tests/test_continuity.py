import copy
import unittest

from pr_attention.continuity import (
    CONTENT_TRUST,
    THREAD_TRUST,
    build_lineage_rereview_packet,
    build_lineage_result_template,
    checkpoint_sha256,
    failed_checkpoint_from_evidence_bundle,
    failed_checkpoint_from_rereview_bundle,
    lineage_packet_sha256,
    validate_lineage_result,
)
from pr_attention.evidence_bundle import build_evidence_bundle
from pr_attention.handoff import build_review_envelope
from pr_attention.integration_gate import build_integration_gate
from pr_attention.review_result import packet_sha256, validate_review_result
from pr_attention.rereview_evidence_bundle import build_rereview_evidence_bundle
from pr_attention.rereview_gate import build_rereview_integration_gate
from pr_attention.rereview_handoff import build_rereview_envelope
from pr_attention.rereview_packet import build_rereview_packet, rereview_packet_sha256
from pr_attention.rereview_result import validate_rereview_result

ACCEPTED = "b" * 40
H1 = "a" * 40
H2 = "c" * 40
H3 = "d" * 40


def snapshot(head, *, accepted=ACCEPTED, attention="READY"):
    delta = {
        "accepted_head_sha": accepted,
        "relation": "AHEAD",
        "acceptance_validity": "REUSABLE_FOR_UNCHANGED",
        "review_scope": "DELTA",
        "complete": True,
        "commits_ahead": 1,
        "commits_behind": 0,
        "additions": 3,
        "deletions": 0,
        "changed_files": 1,
        "files": [{"path": "a.py", "status": "modified", "additions": 3, "deletions": 0, "changes": 3, "previous_path": None}],
        "reasons": [],
    }
    if accepted is None:
        delta = {
            "accepted_head_sha": None,
            "relation": "ABSENT",
            "acceptance_validity": "ABSENT",
            "review_scope": "FULL",
            "complete": True,
            "commits_ahead": None,
            "commits_behind": None,
            "additions": 0,
            "deletions": 0,
            "changed_files": 0,
            "files": [],
            "reasons": ["no accepted semantic head supplied"],
        }
    return {
        "schema_version": 2,
        "repository": "o/r",
        "pr_number": 7,
        "title": "test",
        "base_ref": "main",
        "head_ref": "feat/x",
        "head_sha": head,
        "final_head_sha": head,
        "generated_at": "2026-01-01T00:00:00Z",
        "scope": {"additions": 3, "deletions": 0, "changed_files": 1},
        "checks": {"state": "SUCCESS", "total": 1, "passed": ["test"], "pending": [], "failed": [], "unknown": []},
        "reviews": {"state": "NONE", "current_head_approvals": [], "current_head_changes_requested": [], "current_head_commented": [], "stale_review_count": 0, "dismissed_review_count": 0},
        "threads": {"total": 0, "unresolved_current": 0, "unresolved_outdated": 0, "resolved": 0, "unresolved_current_items": []},
        "merge": {"mergeable": True, "mergeable_state": "clean", "conflict": False},
        "delta": delta,
        "attention": attention,
        "next_action_class": "REVIEW_DELTA" if accepted is not None else "FULL_REVIEW",
        "blockers": [],
        "pending_reasons": [],
        "facts_complete": True,
        "stale": False,
    }


def review_packet_h1():
    return {
        "schema_version": 1,
        "repository": "o/r",
        "pr_number": 7,
        "accepted_head_sha": ACCEPTED,
        "head_sha": H1,
        "final_head_sha": H1,
        "relation": "AHEAD",
        "review_scope": "DELTA",
        "content_trust": CONTENT_TRUST,
        "coverage": "COMPLETE",
        "complete": True,
        "max_total_patch_bytes": 10000,
        "max_file_patch_bytes": 5000,
        "included_patch_bytes": 14,
        "files": [
            {"path": "a.py", "status": "modified", "additions": 3, "deletions": 0, "changes": 3, "previous_path": None, "patch": "@@\n-old\n+bad\n", "original_patch_bytes": 14, "included_patch_bytes": 14, "truncated": False, "omission_reason": None}
        ],
        "reasons": [],
    }


def source_fail_bundle():
    packet = review_packet_h1()
    result = {
        "schema_version": 1,
        "repository": "o/r",
        "pr_number": 7,
        "accepted_head_sha": ACCEPTED,
        "head_sha": H1,
        "packet_sha256": packet_sha256(packet),
        "reviewer": {"name": "reviewer", "model": "test"},
        "verdict": "FAIL",
        "reviewed_files": ["a.py"],
        "findings": [
            {"id": "F1", "severity": "P1", "blocking": True, "title": "Broken invariant", "detail": "a.py violates the contract", "path": "a.py", "line": 10}
        ],
        "notes": [],
    }
    validation = validate_review_result(packet, result, live_head_sha=H1).to_dict()
    envelope = build_review_envelope(packet, reviewer_name="reviewer", reviewer_model="test")
    gate = build_integration_gate(snapshot(H1), validation).to_dict()
    return build_evidence_bundle(snapshot(H1), packet=packet, envelope=envelope, review_result=result, validation=validation, integration_gate=gate)


def compare_h1_h2():
    return {
        "status": "ahead",
        "ahead_by": 1,
        "behind_by": 0,
        "files": [
            {"filename": "a.py", "status": "modified", "additions": 2, "deletions": 1, "changes": 3, "patch": "@@\n-bad\n+fixed\n"},
            {"filename": "new.py", "status": "added", "additions": 1, "deletions": 0, "changes": 1, "patch": "@@\n+helper\n"},
        ],
    }


def rereview_fail_bundle_h2():
    packet = build_rereview_packet(
        source_fail_bundle(), compare_h1_h2(), current_head_sha=H2, final_head_sha=H2,
        max_total_patch_bytes=10000, max_file_patch_bytes=5000,
    )
    result = {
        "schema_version": 1,
        "repository": "o/r",
        "pr_number": 7,
        "previous_reviewed_head_sha": H1,
        "head_sha": H2,
        "rereview_packet_sha256": rereview_packet_sha256(packet),
        "reviewer": {"name": "reviewer", "model": "test"},
        "verdict": "FAIL",
        "reviewed_files": ["a.py", "new.py"],
        "rechecked_finding_ids": ["F1"],
        "resolved_finding_ids": ["F1"],
        "remaining_finding_ids": [],
        "global_invariants_rechecked": True,
        "findings": [
            {"id": "F2", "severity": "P1", "blocking": True, "title": "New blocker", "detail": "new.py breaks the invariant", "path": "new.py", "line": 1}
        ],
        "notes": [],
    }
    validation = validate_rereview_result(packet, result, live_head_sha=H2).to_dict()
    current = snapshot(H2, accepted=None)
    envelope = build_rereview_envelope(packet, reviewer_name="reviewer", reviewer_model="test")
    gate = build_rereview_integration_gate(current, validation).to_dict()
    return build_rereview_evidence_bundle(
        current, source_fail_bundle(), packet,
        envelope=envelope, rereview_result=result, validation=validation, integration_gate=gate,
    )


def compare_h2_h3():
    return {
        "status": "ahead",
        "ahead_by": 1,
        "behind_by": 0,
        "files": [
            {"filename": "new.py", "status": "modified", "additions": 1, "deletions": 1, "changes": 2, "patch": "@@\n-helper\n+safe_helper\n"}
        ],
    }


def unresolved_thread(thread_id="T1", *, path="new.py", body="review thread finding", resolved=False, outdated=False):
    return {
        "id": thread_id,
        "isResolved": resolved,
        "isOutdated": outdated,
        "path": path,
        "comments": {"nodes": [{"author": {"login": "reviewer"}, "body": body}]},
    }


class ContinuityCheckpointTests(unittest.TestCase):
    def test_bootstraps_from_full_failed_bundle(self):
        checkpoint = failed_checkpoint_from_evidence_bundle(source_fail_bundle())
        self.assertEqual(checkpoint["generation"], 1)
        self.assertEqual(checkpoint["accepted_semantic_baseline_sha"], ACCEPTED)
        self.assertEqual(checkpoint["failed_reviewed_checkpoint_sha"], H1)
        self.assertEqual([item["id"] for item in checkpoint["unresolved_findings"]], ["F1"])
        self.assertEqual(checkpoint["checkpoint_sha256"], checkpoint_sha256(checkpoint))

    def test_bootstraps_second_generation_from_existing_rereview_fail(self):
        checkpoint = failed_checkpoint_from_rereview_bundle(rereview_fail_bundle_h2())
        self.assertEqual(checkpoint["generation"], 2)
        self.assertEqual(checkpoint["accepted_semantic_baseline_sha"], ACCEPTED)
        self.assertEqual(checkpoint["failed_reviewed_checkpoint_sha"], H2)
        self.assertEqual([item["id"] for item in checkpoint["unresolved_findings"]], ["F2"])
        self.assertEqual(checkpoint["unresolved_findings"][0]["origin_head_sha"], H2)


class ThreadContinuityTests(unittest.TestCase):
    def test_only_pertinent_unresolved_current_threads_are_bound(self):
        checkpoint = failed_checkpoint_from_rereview_bundle(rereview_fail_bundle_h2())
        threads = [
            unresolved_thread("T1"),
            unresolved_thread("T2", resolved=True),
            unresolved_thread("T3", outdated=True),
            unresolved_thread("T4", path="unrelated.py"),
        ]
        packet = build_lineage_rereview_packet(checkpoint, compare_h2_h3(), threads, current_head_sha=H3)
        self.assertTrue(packet["complete"])
        self.assertEqual(packet["thread_coverage"], "COMPLETE")
        self.assertEqual([item["id"] for item in packet["review_threads"]], ["T1"])
        self.assertEqual(packet["review_threads"][0]["content_trust"], THREAD_TRUST)
        self.assertEqual(packet["lineage_packet_sha256"], lineage_packet_sha256(packet))

    def test_thread_truncation_blocks_pass(self):
        checkpoint = failed_checkpoint_from_rereview_bundle(rereview_fail_bundle_h2())
        packet = build_lineage_rereview_packet(
            checkpoint, compare_h2_h3(), [unresolved_thread(body="x" * 100)],
            current_head_sha=H3, max_thread_bytes=10, max_total_thread_bytes=10,
        )
        self.assertFalse(packet["complete"])
        result = build_lineage_result_template(packet, reviewer_name="reviewer")
        result.update({
            "verdict": "PASS",
            "reviewed_files": ["new.py"],
            "considered_thread_ids": ["T1"],
            "rechecked_finding_ids": ["F2"],
            "resolved_finding_ids": ["F2"],
            "remaining_finding_ids": [],
            "global_invariants_rechecked": True,
        })
        validation = validate_lineage_result(packet, result, live_head_sha=H3)
        self.assertFalse(validation["valid"])
        self.assertEqual(validation["status"], "INVALID")


class MultiGenerationTests(unittest.TestCase):
    def test_h1_fail_h2_fail_h3_pass_without_full_review(self):
        checkpoint_h2 = failed_checkpoint_from_rereview_bundle(rereview_fail_bundle_h2())
        packet_h3 = build_lineage_rereview_packet(
            checkpoint_h2, compare_h2_h3(), [unresolved_thread()], current_head_sha=H3
        )
        self.assertEqual(packet_h3["generation"], 3)
        self.assertEqual(packet_h3["accepted_semantic_baseline_sha"], ACCEPTED)
        self.assertEqual(packet_h3["previous_failed_checkpoint_sha"], H2)
        self.assertEqual(packet_h3["review_scope"], "REREVIEW_DELTA_PLUS_LINEAGE")

        result = build_lineage_result_template(packet_h3, reviewer_name="reviewer", reviewer_model="test")
        result.update({
            "verdict": "PASS",
            "reviewed_files": ["new.py"],
            "considered_thread_ids": ["T1"],
            "rechecked_finding_ids": ["F2"],
            "resolved_finding_ids": ["F2"],
            "remaining_finding_ids": [],
            "global_invariants_rechecked": True,
        })
        validation = validate_lineage_result(packet_h3, result, live_head_sha=H3)
        self.assertTrue(validation["valid"], validation["reasons"])
        self.assertEqual(validation["status"], "VALID_PASS")
        self.assertIsNone(validation["next_failed_checkpoint"])

    def test_fail_emits_next_checkpoint_and_preserves_finding_origin(self):
        checkpoint_h1 = failed_checkpoint_from_evidence_bundle(source_fail_bundle())
        packet_h2 = build_lineage_rereview_packet(
            checkpoint_h1, compare_h1_h2(), [unresolved_thread("T1", path="a.py")], current_head_sha=H2
        )
        result = build_lineage_result_template(packet_h2, reviewer_name="reviewer")
        result.update({
            "verdict": "FAIL",
            "reviewed_files": ["a.py", "new.py"],
            "considered_thread_ids": ["T1"],
            "rechecked_finding_ids": ["F1"],
            "resolved_finding_ids": [],
            "remaining_finding_ids": ["F1"],
            "global_invariants_rechecked": True,
        })
        validation = validate_lineage_result(packet_h2, result, live_head_sha=H2)
        self.assertTrue(validation["valid"], validation["reasons"])
        self.assertEqual(validation["status"], "VALID_FAIL")
        next_checkpoint = validation["next_failed_checkpoint"]
        self.assertEqual(next_checkpoint["generation"], 2)
        self.assertEqual(next_checkpoint["accepted_semantic_baseline_sha"], ACCEPTED)
        self.assertEqual(next_checkpoint["failed_reviewed_checkpoint_sha"], H2)
        self.assertEqual(next_checkpoint["unresolved_findings"][0]["origin_head_sha"], H1)
        self.assertEqual(next_checkpoint["unresolved_findings"][0]["last_seen_head_sha"], H2)

    def test_divergence_fails_closed_to_full_review(self):
        checkpoint = failed_checkpoint_from_evidence_bundle(source_fail_bundle())
        packet = build_lineage_rereview_packet(
            checkpoint, {"status": "diverged", "files": []}, [], current_head_sha=H2
        )
        self.assertFalse(packet["incremental_eligible"])
        self.assertEqual(packet["review_scope"], "FULL")
        self.assertFalse(packet["complete"])

    def test_unavailable_thread_truth_blocks_pass(self):
        checkpoint = failed_checkpoint_from_evidence_bundle(source_fail_bundle())
        packet = build_lineage_rereview_packet(checkpoint, compare_h1_h2(), None, current_head_sha=H2)
        self.assertFalse(packet["complete"])
        self.assertEqual(packet["thread_coverage"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
