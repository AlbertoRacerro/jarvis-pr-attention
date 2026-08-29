import unittest

import pr_attention
from pr_attention.continuity import CONTENT_TRUST, THREAD_TRUST
from pr_attention.rereview_gate import build_rereview_integration_gate

ACCEPTED = "b" * 40
H1 = "a" * 40
H2 = "c" * 40


def checkpoint():
    payload = {
        "schema_version": 1,
        "kind": "PR_ATTENTION_FAILED_REVIEW_CHECKPOINT",
        "repository": "o/r",
        "pr_number": 7,
        "accepted_semantic_baseline_sha": ACCEPTED,
        "failed_reviewed_checkpoint_sha": H1,
        "generation": 1,
        "source_kind": "semantic_review_fail",
        "source_sha256": "sha256:" + ("1" * 64),
        "prior_checkpoint_sha256": None,
        "unresolved_findings": [
            {
                "id": "F1",
                "severity": "P1",
                "blocking": True,
                "title": "blocker",
                "detail": "must remain continuous",
                "path": "a.py",
                "line": 1,
                "origin_head_sha": H1,
                "last_seen_head_sha": H1,
            }
        ],
        "finding_context_files": [
            {
                "path": "a.py",
                "status": "modified",
                "additions": 1,
                "deletions": 1,
                "changes": 2,
                "previous_path": None,
                "patch": "@@\n-old\n+bad\n",
                "original_patch_bytes": 13,
                "included_patch_bytes": 13,
                "truncated": False,
                "omission_reason": None,
            }
        ],
        "global_invariants_recheck_required": True,
    }
    payload["checkpoint_sha256"] = pr_attention.checkpoint_sha256(payload)
    return payload


def lineage_packet():
    compare = {
        "status": "ahead",
        "files": [
            {"filename": "a.py", "status": "modified", "additions": 1, "deletions": 1, "changes": 2, "patch": "@@\n-bad\n+fixed\n"},
            {"filename": "b.py", "status": "added", "additions": 1, "deletions": 0, "changes": 1, "patch": "@@\n+new\n"},
        ],
    }
    return pr_attention.build_lineage_rereview_packet(
        checkpoint(), compare, [], current_head_sha=H2, final_head_sha=H2
    )


def fail_result(packet):
    result = pr_attention.build_lineage_result_template(packet, reviewer_name="reviewer")
    result.update(
        verdict="FAIL",
        reviewed_files=["a.py", "b.py"],
        considered_thread_ids=[],
        rechecked_finding_ids=["F1"],
        resolved_finding_ids=[],
        remaining_finding_ids=["F1"],
        global_invariants_rechecked=True,
    )
    return result


class PublicContinuityGuardTests(unittest.TestCase):
    def test_valid_fail_cannot_advance_when_repair_delta_was_only_partly_reviewed(self):
        packet = lineage_packet()
        result = fail_result(packet)
        result["reviewed_files"] = ["a.py"]
        validation = pr_attention.validate_lineage_result(packet, result, live_head_sha=H2)
        self.assertFalse(validation["valid"])
        self.assertEqual(validation["status"], "INVALID")
        self.assertIsNone(validation["next_failed_checkpoint"])
        self.assertTrue(any("every repair-delta file" in reason for reason in validation["reasons"]))

    def test_valid_fail_advances_only_after_complete_delta_review(self):
        packet = lineage_packet()
        self.assertEqual(packet["coverage"], "COMPLETE")
        self.assertEqual(packet["thread_coverage"], "COMPLETE")
        self.assertTrue(packet["complete"])
        validation = pr_attention.validate_lineage_result(packet, fail_result(packet), live_head_sha=H2)
        self.assertTrue(validation["valid"], validation["reasons"])
        self.assertEqual(validation["status"], "VALID_FAIL")
        self.assertEqual(validation["next_failed_checkpoint"]["failed_reviewed_checkpoint_sha"], H2)
        self.assertEqual(validation["kind"], "PR_ATTENTION_REREVIEW_VALIDATION")
        self.assertEqual(validation["previous_reviewed_head_sha"], H1)
        self.assertEqual(validation["rereview_packet_sha256"], packet["lineage_packet_sha256"])

    def test_v11_validation_is_consumed_by_existing_advisory_gate(self):
        packet = lineage_packet()
        validation = pr_attention.validate_lineage_result(packet, fail_result(packet), live_head_sha=H2)
        snapshot = {
            "schema_version": 2,
            "repository": "o/r",
            "pr_number": 7,
            "head_sha": H2,
            "final_head_sha": H2,
            "attention": "READY",
            "facts_complete": True,
            "stale": False,
        }
        gate = build_rereview_integration_gate(snapshot, validation)
        self.assertEqual(gate.status, "REPAIR")
        self.assertFalse(gate.merge_ready)

    def test_legacy_rereview_partial_packet_is_not_reusable(self):
        fake = {
            "kind": "PR_ATTENTION_REREVIEW_EVIDENCE_BUNDLE",
            "evidence": {
                "rereview_packet": {
                    "incremental_eligible": True,
                    "coverage": "PARTIAL",
                    "complete": False,
                    "repair_delta_files": [{"path": "a.py"}],
                },
                "rereview_result": {"reviewed_files": ["a.py"]},
            },
        }
        with self.assertRaisesRegex(ValueError, "not a complete reusable checkpoint"):
            pr_attention.failed_checkpoint_from_rereview_bundle(fake)

    def test_legacy_rereview_must_have_reviewed_entire_delta(self):
        fake = {
            "kind": "PR_ATTENTION_REREVIEW_EVIDENCE_BUNDLE",
            "evidence": {
                "rereview_packet": {
                    "incremental_eligible": True,
                    "coverage": "COMPLETE",
                    "complete": True,
                    "repair_delta_files": [{"path": "a.py"}, {"path": "b.py"}],
                },
                "rereview_result": {"reviewed_files": ["a.py"]},
            },
        }
        with self.assertRaisesRegex(ValueError, "every repair-delta file"):
            pr_attention.failed_checkpoint_from_rereview_bundle(fake)

    def test_public_constants_keep_untrusted_content_boundary(self):
        self.assertEqual(CONTENT_TRUST, "UNTRUSTED_REPOSITORY_CONTENT")
        self.assertEqual(THREAD_TRUST, "UNTRUSTED_GITHUB_REVIEW_CONTENT")


if __name__ == "__main__":
    unittest.main()
