import copy
import json
import unittest

from pr_attention.compact import build_attention_digest, build_repair_packet
from pr_attention.evidence_bundle import build_evidence_bundle
from pr_attention.handoff import build_review_envelope
from pr_attention.integration_gate import build_integration_gate
from pr_attention.review_result import packet_sha256, validate_review_result

HEAD = "a" * 40
BASE = "b" * 40


def snapshot(*, attention="READY", blockers=None, failed=None, threads=None):
    blockers = blockers or []
    failed = failed or []
    thread_items = threads or []
    return {
        "schema_version": 2,
        "repository": "o/r",
        "pr_number": 9,
        "title": "compact",
        "base_ref": "main",
        "head_ref": "feat/x",
        "head_sha": HEAD,
        "final_head_sha": HEAD,
        "generated_at": "2026-01-01T00:00:00Z",
        "scope": {"additions": 4, "deletions": 1, "changed_files": 1},
        "checks": {"state": "FAILURE" if failed else "SUCCESS", "total": max(1, len(failed)), "passed": [] if failed else ["unit"], "pending": [], "failed": failed, "unknown": []},
        "reviews": {"state": "NONE", "current_head_approvals": [], "current_head_changes_requested": [], "current_head_commented": [], "stale_review_count": 2, "dismissed_review_count": 0},
        "threads": {"total": len(thread_items), "unresolved_current": len(thread_items), "unresolved_outdated": 1, "resolved": 3, "unresolved_current_items": thread_items},
        "merge": {"mergeable": True, "mergeable_state": "clean", "conflict": False},
        "delta": {"accepted_head_sha": BASE, "relation": "AHEAD", "acceptance_validity": "REUSABLE_FOR_UNCHANGED", "review_scope": "DELTA", "complete": True, "commits_ahead": 1, "commits_behind": 0, "additions": 4, "deletions": 1, "changed_files": 1, "files": [{"path": "a.py", "status": "modified", "additions": 4, "deletions": 1, "changes": 5, "previous_path": None}], "reasons": []},
        "attention": attention,
        "next_action_class": "REPAIR" if attention == "BLOCKED" else "REVIEW_DELTA",
        "blockers": blockers,
        "pending_reasons": [],
        "facts_complete": True,
        "stale": False,
    }


def packet():
    return {
        "schema_version": 1,
        "repository": "o/r",
        "pr_number": 9,
        "accepted_head_sha": BASE,
        "head_sha": HEAD,
        "final_head_sha": HEAD,
        "generated_at": "now",
        "relation": "AHEAD",
        "review_scope": "DELTA",
        "attention": "READY",
        "next_action_class": "REVIEW_DELTA",
        "content_trust": "UNTRUSTED_REPOSITORY_CONTENT",
        "coverage": "COMPLETE",
        "complete": True,
        "max_total_patch_bytes": 1000,
        "max_file_patch_bytes": 1000,
        "included_patch_bytes": 20,
        "files": [{"path": "a.py", "status": "modified", "additions": 4, "deletions": 1, "changes": 5, "previous_path": None, "patch": "+secret patch body\n", "original_patch_bytes": 20, "included_patch_bytes": 20, "truncated": False, "omission_reason": None}],
        "reasons": [],
    }


def result(pkt, *, verdict="PASS", detail=""):
    findings = []
    if verdict == "FAIL":
        findings = [{"id": "F1", "severity": "P1", "blocking": True, "title": "Broken invariant", "detail": detail or "Must be repaired", "path": "a.py", "line": 4}]
    return {"schema_version": 1, "repository": "o/r", "pr_number": 9, "accepted_head_sha": BASE, "head_sha": HEAD, "packet_sha256": packet_sha256(pkt), "reviewer": {"name": "tester"}, "verdict": verdict, "reviewed_files": ["a.py"], "findings": findings, "notes": []}


def full_bundle(snap, *, verdict="PASS", detail=""):
    pkt = packet()
    review = result(pkt, verdict=verdict, detail=detail)
    validation = validate_review_result(pkt, review, live_head_sha=HEAD).to_dict()
    gate = build_integration_gate(snap, validation).to_dict()
    return build_evidence_bundle(snap, packet=pkt, envelope=build_review_envelope(pkt, reviewer_name="tester"), review_result=review, validation=validation, integration_gate=gate)


class CompactAttentionTests(unittest.TestCase):
    def test_digest_contains_no_patch_body(self):
        digest = build_attention_digest(full_bundle(snapshot()))
        rendered = json.dumps(digest, sort_keys=True)
        self.assertNotIn("secret patch body", rendered)
        self.assertNotIn('"patch"', rendered)
        self.assertEqual(digest["delta"]["files"][0]["path"], "a.py")

    def test_digest_binds_source_bundle_and_ready_action(self):
        bundle = full_bundle(snapshot())
        digest = build_attention_digest(bundle)
        self.assertEqual(digest["source_bundle_sha256"], bundle["bundle_sha256"])
        self.assertEqual(digest["next_exact_action_class"], "VERIFY_EXACT_HEAD_AND_MERGE")
        self.assertTrue(digest["attention_digest_sha256"].startswith("sha256:"))

    def test_digest_preserves_stale_review_count(self):
        digest = build_attention_digest(full_bundle(snapshot()))
        self.assertEqual(digest["github"]["reviews"]["stale_review_count"], 2)

    def test_digest_bounds_thread_items_and_details(self):
        items = [{"thread_id": f"T{i}", "path": "a.py", "author": "u", "body": "x" * 200} for i in range(4)]
        snap = snapshot(attention="BLOCKED", blockers=["4 unresolved current review thread(s)"], threads=items)
        digest = build_attention_digest(full_bundle(snap), max_items=2, max_detail_chars=80)
        self.assertEqual(len(digest["github"]["threads"]["current_items"]), 2)
        self.assertEqual(digest["bounds"]["omitted"]["threads"], 2)
        self.assertTrue(digest["bounds"]["detail_truncated"])

    def test_digest_rejects_tampered_bundle(self):
        bundle = full_bundle(snapshot())
        bundle["head_sha"] = "c" * 40
        with self.assertRaisesRegex(ValueError, "evidence bundle is invalid"):
            build_attention_digest(bundle)

    def test_semantic_fail_yields_repair_packet(self):
        bundle = full_bundle(snapshot(), verdict="FAIL", detail="repair this invariant")
        repair = build_repair_packet(bundle)
        self.assertEqual(repair["repair_sources"], ["SEMANTIC_REVIEW"])
        self.assertEqual(repair["blocking_findings"][0]["id"], "F1")
        self.assertEqual(repair["head_sha"], HEAD)
        self.assertTrue(repair["repair_packet_sha256"].startswith("sha256:"))

    def test_github_blocker_yields_live_state_repair_source(self):
        threads = [{"thread_id": "T1", "path": "a.py", "author": "reviewer", "body": "fix this"}]
        snap = snapshot(attention="BLOCKED", blockers=["CI has failing checks", "1 unresolved current review thread(s)"], failed=["unit"], threads=threads)
        repair = build_repair_packet(full_bundle(snap))
        self.assertEqual(repair["repair_sources"], ["GITHUB_LIVE_STATE"])
        self.assertEqual(repair["failed_checks"], ["unit"])
        self.assertEqual(repair["unresolved_current_threads"][0]["thread_id"], "T1")

    def test_repair_packet_can_be_mixed(self):
        threads = [{"thread_id": "T1", "path": "a.py", "author": "reviewer", "body": "fix this"}]
        snap = snapshot(attention="BLOCKED", blockers=["1 unresolved current review thread(s)"], threads=threads)
        repair = build_repair_packet(full_bundle(snap, verdict="FAIL"))
        self.assertEqual(repair["repair_sources"], ["SEMANTIC_REVIEW", "GITHUB_LIVE_STATE"])

    def test_repair_packet_bounds_finding_detail(self):
        bundle = full_bundle(snapshot(), verdict="FAIL", detail="y" * 500)
        repair = build_repair_packet(bundle, max_detail_chars=80)
        self.assertLessEqual(len(repair["blocking_findings"][0]["detail"]), 80)
        self.assertTrue(repair["bounds"]["detail_truncated"])

    def test_ready_bundle_cannot_emit_repair_packet(self):
        with self.assertRaisesRegex(ValueError, "gate status REPAIR"):
            build_repair_packet(full_bundle(snapshot()))

    def test_tampered_bundle_cannot_emit_repair_packet(self):
        bundle = full_bundle(snapshot(), verdict="FAIL")
        bad = copy.deepcopy(bundle)
        bad["evidence"]["review_result"]["findings"][0]["detail"] = "tampered"
        with self.assertRaisesRegex(ValueError, "evidence bundle is invalid"):
            build_repair_packet(bad)

    def test_invalid_bounds_fail_closed(self):
        bundle = full_bundle(snapshot())
        with self.assertRaisesRegex(ValueError, "bounds"):
            build_attention_digest(bundle, max_items=0)
        with self.assertRaisesRegex(ValueError, "bounds"):
            build_attention_digest(bundle, max_detail_chars=10)


if __name__ == "__main__":
    unittest.main()
