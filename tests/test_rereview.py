import copy
import unittest

from pr_attention.evidence_bundle import build_evidence_bundle
from pr_attention.handoff import build_review_envelope
from pr_attention.integration_gate import build_integration_gate
from pr_attention.review_result import packet_sha256, validate_review_result
from pr_attention.rereview_packet import build_rereview_packet, rereview_packet_sha256
from pr_attention.rereview_result import build_rereview_result_template, validate_rereview_result

ACCEPTED = "b" * 40
FAILED_HEAD = "a" * 40
REPAIRED_HEAD = "c" * 40
OTHER_HEAD = "d" * 40


def snapshot():
    return {
        "schema_version": 2,
        "repository": "o/r",
        "pr_number": 7,
        "title": "test",
        "base_ref": "main",
        "head_ref": "feat/x",
        "head_sha": FAILED_HEAD,
        "final_head_sha": FAILED_HEAD,
        "generated_at": "2026-01-01T00:00:00Z",
        "scope": {"additions": 5, "deletions": 0, "changed_files": 2},
        "checks": {"state": "SUCCESS", "total": 1, "passed": ["test"], "pending": [], "failed": [], "unknown": []},
        "reviews": {"state": "NONE", "current_head_approvals": [], "current_head_changes_requested": [], "current_head_commented": [], "stale_review_count": 0, "dismissed_review_count": 0},
        "threads": {"total": 0, "unresolved_current": 0, "unresolved_outdated": 0, "resolved": 0, "unresolved_current_items": []},
        "merge": {"mergeable": True, "mergeable_state": "clean", "conflict": False},
        "delta": {
            "accepted_head_sha": ACCEPTED,
            "relation": "AHEAD",
            "acceptance_validity": "REUSABLE_FOR_UNCHANGED",
            "review_scope": "DELTA",
            "complete": True,
            "commits_ahead": 1,
            "commits_behind": 0,
            "additions": 5,
            "deletions": 0,
            "changed_files": 2,
            "files": [
                {"path": "a.py", "status": "modified", "additions": 3, "deletions": 0, "changes": 3, "previous_path": None},
                {"path": "b.py", "status": "modified", "additions": 2, "deletions": 0, "changes": 2, "previous_path": None},
            ],
            "reasons": [],
        },
        "attention": "READY",
        "next_action_class": "REVIEW_DELTA",
        "blockers": [],
        "pending_reasons": [],
        "facts_complete": True,
        "stale": False,
    }


def prior_packet(*, complete=True):
    return {
        "schema_version": 1,
        "repository": "o/r",
        "pr_number": 7,
        "accepted_head_sha": ACCEPTED,
        "head_sha": FAILED_HEAD,
        "final_head_sha": FAILED_HEAD,
        "relation": "AHEAD",
        "review_scope": "DELTA",
        "content_trust": "UNTRUSTED_REPOSITORY_CONTENT",
        "coverage": "COMPLETE" if complete else "PARTIAL",
        "complete": complete,
        "max_total_patch_bytes": 10000,
        "max_file_patch_bytes": 5000,
        "included_patch_bytes": 30,
        "files": [
            {"path": "a.py", "status": "modified", "additions": 3, "deletions": 0, "changes": 3, "previous_path": None, "patch": "@@\n-old\n+bad\n", "original_patch_bytes": 14, "included_patch_bytes": 14, "truncated": False, "omission_reason": None},
            {"path": "b.py", "status": "modified", "additions": 2, "deletions": 0, "changes": 2, "previous_path": None, "patch": "@@\n-old\n+ok\n", "original_patch_bytes": 13, "included_patch_bytes": 13, "truncated": False, "omission_reason": None},
        ],
        "reasons": [],
    }


def prior_result(pkt, *, reviewed_files=None):
    effective_reviewed = reviewed_files if reviewed_files is not None else ["a.py", "b.py"]
    findings = [
        {"id": "F1", "severity": "P1", "blocking": True, "title": "Broken invariant", "detail": "a.py violates the contract", "path": "a.py", "line": 10},
    ]
    if "b.py" in effective_reviewed:
        findings.append(
            {"id": "N1", "severity": "P3", "blocking": False, "title": "Nit", "detail": "non-blocking note", "path": "b.py", "line": 2}
        )
    return {
        "schema_version": 1,
        "repository": "o/r",
        "pr_number": 7,
        "accepted_head_sha": ACCEPTED,
        "head_sha": FAILED_HEAD,
        "packet_sha256": packet_sha256(pkt),
        "reviewer": {"name": "reviewer", "model": "test"},
        "verdict": "FAIL",
        "reviewed_files": effective_reviewed,
        "findings": findings,
        "notes": [],
    }


def fail_bundle(*, complete=True, reviewed_files=None):
    pkt = prior_packet(complete=complete)
    result = prior_result(pkt, reviewed_files=reviewed_files)
    validation = validate_review_result(pkt, result, live_head_sha=FAILED_HEAD).to_dict()
    env = build_review_envelope(pkt, reviewer_name="reviewer", reviewer_model="test")
    gate = build_integration_gate(snapshot(), validation).to_dict()
    return build_evidence_bundle(
        snapshot(),
        packet=pkt,
        envelope=env,
        review_result=result,
        validation=validation,
        integration_gate=gate,
    )


def compare_payload(*, status="ahead", patch=True):
    files = [
        {"filename": "a.py", "status": "modified", "additions": 2, "deletions": 1, "changes": 3, "patch": "@@\n-bad\n+fixed\n" if patch else None},
        {"filename": "new.py", "status": "added", "additions": 1, "deletions": 0, "changes": 1, "patch": "@@\n+helper\n" if patch else None},
    ]
    return {"status": status, "ahead_by": 1, "behind_by": 0, "files": files}


def rereview_packet():
    return build_rereview_packet(
        fail_bundle(),
        compare_payload(),
        current_head_sha=REPAIRED_HEAD,
        final_head_sha=REPAIRED_HEAD,
        max_total_patch_bytes=10000,
        max_file_patch_bytes=5000,
    )


def pass_result(pkt):
    return {
        "schema_version": 1,
        "repository": "o/r",
        "pr_number": 7,
        "previous_reviewed_head_sha": FAILED_HEAD,
        "head_sha": REPAIRED_HEAD,
        "rereview_packet_sha256": rereview_packet_sha256(pkt),
        "reviewer": {"name": "reviewer", "model": "test"},
        "verdict": "PASS",
        "reviewed_files": ["a.py", "new.py"],
        "rechecked_finding_ids": ["F1"],
        "resolved_finding_ids": ["F1"],
        "remaining_finding_ids": [],
        "global_invariants_rechecked": True,
        "findings": [],
        "notes": [],
    }


class RereviewPacketTests(unittest.TestCase):
    def test_complete_failed_review_becomes_incremental_checkpoint(self):
        pkt = rereview_packet()
        self.assertTrue(pkt["incremental_eligible"])
        self.assertTrue(pkt["complete"])
        self.assertEqual(pkt["coverage"], "COMPLETE")
        self.assertEqual(pkt["relation"], "AHEAD")
        self.assertEqual([item["id"] for item in pkt["prior_blocking_findings"]], ["F1"])
        self.assertEqual([item["path"] for item in pkt["finding_context_files"]], ["a.py"])
        self.assertEqual([item["path"] for item in pkt["repair_delta_files"]], ["a.py", "new.py"])
        self.assertEqual(pkt["scope_expansion_files"], ["new.py"])
        self.assertEqual(pkt["rereview_packet_sha256"], rereview_packet_sha256(pkt))

    def test_partial_prior_fail_is_not_reusable(self):
        with self.assertRaisesRegex(ValueError, "packet was incomplete"):
            build_rereview_packet(fail_bundle(complete=False), compare_payload(), current_head_sha=REPAIRED_HEAD)

    def test_fail_that_did_not_review_every_prior_file_is_not_reusable(self):
        with self.assertRaisesRegex(ValueError, "not every packet file was reviewed"):
            build_rereview_packet(fail_bundle(reviewed_files=["a.py"]), compare_payload(), current_head_sha=REPAIRED_HEAD)

    def test_diverged_head_requires_full_review(self):
        pkt = build_rereview_packet(fail_bundle(), compare_payload(status="diverged"), current_head_sha=REPAIRED_HEAD)
        self.assertFalse(pkt["incremental_eligible"])
        self.assertFalse(pkt["complete"])
        self.assertEqual(pkt["review_scope"], "FULL")
        self.assertEqual(pkt["coverage"], "NONE")

    def test_head_race_fails_closed(self):
        pkt = build_rereview_packet(
            fail_bundle(), compare_payload(), current_head_sha=REPAIRED_HEAD, final_head_sha=OTHER_HEAD
        )
        self.assertFalse(pkt["incremental_eligible"])
        self.assertEqual(pkt["coverage"], "UNKNOWN")

    def test_missing_patch_makes_packet_partial(self):
        pkt = build_rereview_packet(fail_bundle(), compare_payload(patch=False), current_head_sha=REPAIRED_HEAD)
        self.assertTrue(pkt["incremental_eligible"])
        self.assertFalse(pkt["complete"])
        self.assertIn(pkt["coverage"], {"PARTIAL", "NONE"})

    def test_budget_truncation_prevents_complete_packet(self):
        payload = compare_payload()
        payload["files"][0]["patch"] = "+" + ("x" * 1000)
        pkt = build_rereview_packet(
            fail_bundle(), payload, current_head_sha=REPAIRED_HEAD, max_total_patch_bytes=100, max_file_patch_bytes=100
        )
        self.assertFalse(pkt["complete"])
        self.assertEqual(pkt["coverage"], "PARTIAL")


class RereviewResultTests(unittest.TestCase):
    def test_template_is_bound_and_conservative(self):
        pkt = rereview_packet()
        template = build_rereview_result_template(pkt, reviewer_name="reviewer", reviewer_model="test")
        self.assertEqual(template["rereview_packet_sha256"], rereview_packet_sha256(pkt))
        self.assertEqual(template["verdict"], "NEEDS_HUMAN")
        self.assertEqual(template["remaining_finding_ids"], ["F1"])
        self.assertFalse(template["global_invariants_rechecked"])

    def test_pass_requires_all_delta_and_prior_findings(self):
        pkt = rereview_packet()
        validation = validate_rereview_result(pkt, pass_result(pkt), live_head_sha=REPAIRED_HEAD)
        self.assertTrue(validation.valid)
        self.assertEqual(validation.status, "VALID_PASS")
        self.assertEqual(validation.resolved_finding_ids, ["F1"])

    def test_pass_with_unresolved_prior_finding_is_invalid(self):
        pkt = rereview_packet()
        result = pass_result(pkt)
        result["resolved_finding_ids"] = []
        result["remaining_finding_ids"] = ["F1"]
        validation = validate_rereview_result(pkt, result, live_head_sha=REPAIRED_HEAD)
        self.assertEqual(validation.status, "INVALID")

    def test_pass_missing_delta_file_is_invalid(self):
        pkt = rereview_packet()
        result = pass_result(pkt)
        result["reviewed_files"] = ["a.py"]
        validation = validate_rereview_result(pkt, result, live_head_sha=REPAIRED_HEAD)
        self.assertEqual(validation.status, "INVALID")

    def test_pass_requires_global_invariant_recheck(self):
        pkt = rereview_packet()
        result = pass_result(pkt)
        result["global_invariants_rechecked"] = False
        validation = validate_rereview_result(pkt, result, live_head_sha=REPAIRED_HEAD)
        self.assertEqual(validation.status, "INVALID")

    def test_fail_can_keep_prior_finding_open(self):
        pkt = rereview_packet()
        result = pass_result(pkt)
        result["verdict"] = "FAIL"
        result["resolved_finding_ids"] = []
        result["remaining_finding_ids"] = ["F1"]
        validation = validate_rereview_result(pkt, result, live_head_sha=REPAIRED_HEAD)
        self.assertTrue(validation.valid)
        self.assertEqual(validation.status, "VALID_FAIL")

    def test_fail_can_close_prior_and_raise_new_blocker(self):
        pkt = rereview_packet()
        result = pass_result(pkt)
        result["verdict"] = "FAIL"
        result["findings"] = [
            {"id": "F2", "severity": "P2", "blocking": True, "title": "Regression", "detail": "repair introduces a new issue", "path": "new.py", "line": 1}
        ]
        validation = validate_rereview_result(pkt, result, live_head_sha=REPAIRED_HEAD)
        self.assertTrue(validation.valid)
        self.assertEqual(validation.status, "VALID_FAIL")

    def test_live_head_change_makes_result_stale(self):
        pkt = rereview_packet()
        validation = validate_rereview_result(pkt, pass_result(pkt), live_head_sha=OTHER_HEAD)
        self.assertFalse(validation.valid)
        self.assertEqual(validation.status, "STALE")

    def test_new_finding_cannot_reference_unprovided_evidence(self):
        pkt = rereview_packet()
        result = pass_result(pkt)
        result["verdict"] = "FAIL"
        result["findings"] = [
            {"id": "F2", "severity": "P2", "blocking": True, "title": "Unknown", "detail": "outside evidence", "path": "elsewhere.py", "line": 1}
        ]
        validation = validate_rereview_result(pkt, result, live_head_sha=REPAIRED_HEAD)
        self.assertEqual(validation.status, "INVALID")

    def test_tampered_packet_digest_is_invalid(self):
        pkt = rereview_packet()
        tampered = copy.deepcopy(pkt)
        tampered["repair_delta_files"][0]["patch"] = "+tampered\n"
        validation = validate_rereview_result(tampered, pass_result(pkt), live_head_sha=REPAIRED_HEAD)
        self.assertEqual(validation.status, "INVALID")

    def test_new_finding_cannot_reuse_prior_finding_id(self):
        pkt = rereview_packet()
        result = pass_result(pkt)
        result["verdict"] = "FAIL"
        result["findings"] = [
            {"id": "F1", "severity": "P2", "blocking": True, "title": "Collision", "detail": "duplicate id", "path": "a.py", "line": 1}
        ]
        validation = validate_rereview_result(pkt, result, live_head_sha=REPAIRED_HEAD)
        self.assertEqual(validation.status, "INVALID")


if __name__ == "__main__":
    unittest.main()
