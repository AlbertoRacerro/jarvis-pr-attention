import copy
import unittest

from pr_attention.review_result import packet_sha256, validate_review_result

BASE = "a" * 40
HEAD = "b" * 40


def packet(*, coverage="COMPLETE", complete=True, final_head=HEAD):
    return {
        "schema_version": 1,
        "repository": "o/r",
        "pr_number": 7,
        "accepted_head_sha": BASE,
        "head_sha": HEAD,
        "final_head_sha": final_head,
        "generated_at": "2026-08-29T00:00:00+00:00",
        "relation": "AHEAD",
        "review_scope": "DELTA",
        "attention": "READY",
        "next_action_class": "REVIEW_DELTA",
        "content_trust": "UNTRUSTED_REPOSITORY_CONTENT",
        "coverage": coverage,
        "complete": complete,
        "max_total_patch_bytes": 1000,
        "max_file_patch_bytes": 500,
        "included_patch_bytes": 4,
        "files": [
            {"path": "a.py", "status": "modified", "patch": "+a"},
            {"path": "b.py", "status": "modified", "patch": "+b"},
        ],
        "reasons": [],
    }


def result(p, *, verdict="PASS", reviewed_files=None, findings=None):
    return {
        "schema_version": 1,
        "repository": p["repository"],
        "pr_number": p["pr_number"],
        "accepted_head_sha": p["accepted_head_sha"],
        "head_sha": p["head_sha"],
        "packet_sha256": packet_sha256(p),
        "reviewer": {"name": "test-reviewer", "model": "unit"},
        "verdict": verdict,
        "reviewed_files": list(reviewed_files if reviewed_files is not None else ["a.py", "b.py"]),
        "findings": list(findings or []),
        "notes": [],
    }


def blocking_finding():
    return {
        "id": "F1",
        "severity": "P1",
        "blocking": True,
        "title": "Broken invariant",
        "detail": "The changed code violates the contract.",
        "path": "a.py",
        "line": 1,
    }


class ReviewResultTests(unittest.TestCase):
    def test_digest_ignores_transient_packet_fields(self):
        first = packet()
        second = copy.deepcopy(first)
        second["generated_at"] = "later"
        second["attention"] = "PENDING"
        second["next_action_class"] = "WAIT_FOR_GATES"
        second["reasons"] = ["different transient state"]
        self.assertEqual(packet_sha256(first), packet_sha256(second))

    def test_digest_changes_when_patch_evidence_changes(self):
        first = packet()
        second = copy.deepcopy(first)
        second["files"][0]["patch"] = "+changed"
        self.assertNotEqual(packet_sha256(first), packet_sha256(second))

    def test_valid_pass(self):
        p = packet()
        validation = validate_review_result(p, result(p), live_head_sha=HEAD)
        self.assertTrue(validation.valid)
        self.assertEqual(validation.status, "VALID_PASS")

    def test_valid_fail_requires_blocker(self):
        p = packet()
        validation = validate_review_result(p, result(p, verdict="FAIL", findings=[blocking_finding()]))
        self.assertEqual(validation.status, "VALID_FAIL")
        self.assertTrue(validation.valid)

    def test_valid_needs_human_can_be_partial_review(self):
        p = packet()
        validation = validate_review_result(p, result(p, verdict="NEEDS_HUMAN", reviewed_files=["a.py"]))
        self.assertEqual(validation.status, "VALID_NEEDS_HUMAN")
        self.assertTrue(validation.valid)

    def test_wrong_digest_is_invalid(self):
        p = packet()
        r = result(p)
        r["packet_sha256"] = "sha256:" + "0" * 64
        validation = validate_review_result(p, r)
        self.assertEqual(validation.status, "INVALID")

    def test_live_head_move_is_stale(self):
        p = packet()
        validation = validate_review_result(p, result(p), live_head_sha="c" * 40)
        self.assertFalse(validation.valid)
        self.assertEqual(validation.status, "STALE")

    def test_pass_rejects_partial_packet(self):
        p = packet(coverage="PARTIAL", complete=False)
        validation = validate_review_result(p, result(p))
        self.assertEqual(validation.status, "INVALID")
        self.assertTrue(any("COMPLETE" in reason for reason in validation.reasons))

    def test_stale_packet_returns_stale_for_pass(self):
        p = packet(final_head="c" * 40)
        validation = validate_review_result(p, result(p))
        self.assertEqual(validation.status, "STALE")
        self.assertFalse(validation.valid)

    def test_stale_packet_returns_stale_for_fail(self):
        p = packet(final_head="c" * 40)
        validation = validate_review_result(p, result(p, verdict="FAIL", findings=[blocking_finding()]))
        self.assertEqual(validation.status, "STALE")
        self.assertFalse(validation.valid)

    def test_pass_requires_every_packet_file_reviewed(self):
        p = packet()
        validation = validate_review_result(p, result(p, reviewed_files=["a.py"]))
        self.assertEqual(validation.status, "INVALID")
        self.assertTrue(any("every packet file" in reason for reason in validation.reasons))

    def test_unknown_reviewed_file_is_invalid(self):
        p = packet()
        validation = validate_review_result(p, result(p, reviewed_files=["a.py", "b.py", "x.py"]))
        self.assertEqual(validation.status, "INVALID")

    def test_duplicate_reviewed_file_is_invalid(self):
        p = packet()
        validation = validate_review_result(p, result(p, reviewed_files=["a.py", "a.py"]))
        self.assertEqual(validation.status, "INVALID")

    def test_pass_cannot_contain_blocking_finding(self):
        p = packet()
        finding = {
            "id": "F1",
            "severity": "P3",
            "blocking": True,
            "title": "Block",
            "detail": "Still blocking.",
            "path": "a.py",
            "line": None,
        }
        validation = validate_review_result(p, result(p, findings=[finding]))
        self.assertEqual(validation.status, "INVALID")

    def test_fail_without_blocking_finding_is_invalid(self):
        p = packet()
        finding = {
            "id": "F1",
            "severity": "P3",
            "blocking": False,
            "title": "Nit",
            "detail": "Non-blocking.",
            "path": "a.py",
            "line": None,
        }
        validation = validate_review_result(p, result(p, verdict="FAIL", findings=[finding]))
        self.assertEqual(validation.status, "INVALID")

    def test_high_severity_cannot_be_declared_nonblocking(self):
        p = packet()
        finding = {
            "id": "F1",
            "severity": "P2",
            "blocking": False,
            "title": "Material issue",
            "detail": "Must be blocking at this severity.",
            "path": "a.py",
            "line": 2,
        }
        validation = validate_review_result(p, result(p, verdict="NEEDS_HUMAN", findings=[finding]))
        self.assertEqual(validation.status, "INVALID")
        self.assertTrue(any("must be blocking" in reason for reason in validation.reasons))

    def test_finding_path_must_be_in_packet(self):
        p = packet()
        finding = {
            "id": "F1",
            "severity": "P3",
            "blocking": False,
            "title": "Outside",
            "detail": "Invalid path.",
            "path": "x.py",
            "line": 1,
        }
        validation = validate_review_result(p, result(p, verdict="NEEDS_HUMAN", findings=[finding]))
        self.assertEqual(validation.status, "INVALID")

    def test_finding_path_must_be_declared_reviewed(self):
        p = packet()
        finding = {
            "id": "F1",
            "severity": "P3",
            "blocking": False,
            "title": "Observed",
            "detail": "Reviewer must declare this file reviewed.",
            "path": "b.py",
            "line": 1,
        }
        validation = validate_review_result(
            p,
            result(p, verdict="NEEDS_HUMAN", reviewed_files=["a.py"], findings=[finding]),
        )
        self.assertEqual(validation.status, "INVALID")

    def test_reviewer_name_is_required(self):
        p = packet()
        r = result(p)
        r["reviewer"] = {}
        validation = validate_review_result(p, r)
        self.assertEqual(validation.status, "INVALID")

    def test_boolean_packet_schema_is_not_integer_one(self):
        p = packet()
        p["schema_version"] = True
        r = result(p)
        validation = validate_review_result(p, r)
        self.assertEqual(validation.status, "INVALID")

    def test_boolean_result_schema_is_not_integer_one(self):
        p = packet()
        r = result(p)
        r["schema_version"] = True
        validation = validate_review_result(p, r)
        self.assertEqual(validation.status, "INVALID")

    def test_boolean_result_pr_number_does_not_alias_one(self):
        p = packet()
        p["pr_number"] = 1
        r = result(p)
        r["pr_number"] = True
        validation = validate_review_result(p, r)
        self.assertEqual(validation.status, "INVALID")


if __name__ == "__main__":
    unittest.main()
