import copy
import unittest

from pr_attention.evidence_bundle import build_evidence_bundle, verify_evidence_bundle
from pr_attention.handoff import build_review_envelope
from pr_attention.review_result import packet_sha256

HEAD = "a" * 40
BASE = "b" * 40


def snapshot():
    return {
        "schema_version": 2,
        "repository": "o/r",
        "pr_number": 7,
        "title": "test",
        "base_ref": "main",
        "head_ref": "feat/x",
        "head_sha": HEAD,
        "final_head_sha": HEAD,
        "generated_at": "2026-01-01T00:00:00Z",
        "scope": {"additions": 2, "deletions": 0, "changed_files": 1},
        "checks": {"state": "PASS"},
        "reviews": {},
        "threads": {},
        "merge": {"mergeable": True},
        "delta": {"accepted_head_sha": BASE, "relation": "AHEAD", "review_scope": "DELTA", "changed_files": 1, "files": ["a.py"]},
        "attention": "READY",
        "next_action_class": "REVIEW_DELTA",
        "blockers": [],
        "pending_reasons": [],
        "facts_complete": True,
        "stale": False,
    }


def packet():
    return {
        "schema_version": 1,
        "repository": "o/r",
        "pr_number": 7,
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
        "included_patch_bytes": 12,
        "files": [{"path": "a.py", "status": "modified", "patch": "+print('x')\n"}],
    }


def validation(pkt):
    return {
        "schema_version": 1,
        "valid": True,
        "status": "VALID_PASS",
        "repository": "o/r",
        "pr_number": 7,
        "head_sha": HEAD,
        "packet_sha256": packet_sha256(pkt),
        "verdict": "PASS",
        "live_head_sha": HEAD,
        "reasons": [],
    }


def gate(pkt):
    return {
        "schema_version": 1,
        "status": "READY_TO_MERGE",
        "merge_ready": True,
        "repository": "o/r",
        "pr_number": 7,
        "head_sha": HEAD,
        "packet_sha256": packet_sha256(pkt),
        "attention": "READY",
        "semantic_review_status": "VALID_PASS",
        "live_review_bound": True,
        "reasons": [],
        "safety_notice": "advisory",
    }


class EvidenceBundleTests(unittest.TestCase):
    def test_snapshot_only_bundle_is_valid(self):
        bundle = build_evidence_bundle(snapshot())
        self.assertEqual(bundle["phase"], "SNAPSHOT_ONLY")
        self.assertEqual(bundle["semantic_review_status"], "NOT_RUN")
        self.assertTrue(verify_evidence_bundle(bundle).valid)

    def test_full_bundle_is_integration_evaluated(self):
        pkt = packet()
        env = build_review_envelope(pkt, reviewer_name="tester")
        bundle = build_evidence_bundle(snapshot(), packet=pkt, envelope=env, validation=validation(pkt), integration_gate=gate(pkt))
        self.assertEqual(bundle["phase"], "INTEGRATION_EVALUATED")
        self.assertTrue(bundle["merge_ready"])
        self.assertEqual(bundle["component_digests"]["packet_sha256"], packet_sha256(pkt))
        self.assertTrue(verify_evidence_bundle(bundle).valid)

    def test_bundle_stores_control_plane_without_duplicate_packet(self):
        pkt = packet()
        env = build_review_envelope(pkt, reviewer_name="tester")
        bundle = build_evidence_bundle(snapshot(), packet=pkt, envelope=env)
        self.assertEqual(bundle["phase"], "REVIEW_HANDOFF_READY")
        self.assertEqual(bundle["evidence"]["review_packet"], pkt)
        self.assertEqual(bundle["evidence"]["review_control_plane"], env["control_plane"])
        self.assertNotIn("untrusted_evidence", bundle["evidence"]["review_control_plane"])

    def test_snapshot_generation_time_does_not_change_bundle_identity(self):
        first = snapshot()
        second = snapshot()
        second["generated_at"] = "2026-01-01T00:05:00Z"
        one = build_evidence_bundle(first)
        two = build_evidence_bundle(second)
        self.assertEqual(one["bundle_sha256"], two["bundle_sha256"])
        one["evidence"]["snapshot"]["generated_at"] = "later"
        self.assertTrue(verify_evidence_bundle(one).valid)

    def test_patch_tampering_invalidates_bundle(self):
        pkt = packet()
        bundle = build_evidence_bundle(snapshot(), packet=pkt)
        tampered = copy.deepcopy(bundle)
        tampered["evidence"]["review_packet"]["files"][0]["patch"] = "+malicious\n"
        self.assertFalse(verify_evidence_bundle(tampered).valid)

    def test_top_level_tampering_invalidates_bundle(self):
        bundle = build_evidence_bundle(snapshot())
        bundle["attention"] = "BLOCKED"
        self.assertFalse(verify_evidence_bundle(bundle).valid)

    def test_mismatched_packet_head_is_rejected(self):
        pkt = packet()
        pkt["head_sha"] = "c" * 40
        with self.assertRaisesRegex(ValueError, "head_sha"):
            build_evidence_bundle(snapshot(), packet=pkt)

    def test_mismatched_envelope_is_rejected(self):
        pkt = packet()
        env = build_review_envelope(pkt, reviewer_name="tester")
        env["packet_sha256"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "envelope"):
            build_evidence_bundle(snapshot(), packet=pkt, envelope=env)

    def test_gate_without_validation_is_rejected(self):
        pkt = packet()
        with self.assertRaisesRegex(ValueError, "requires review validation"):
            build_evidence_bundle(snapshot(), packet=pkt, integration_gate=gate(pkt))

    def test_inconsistent_merge_ready_is_rejected(self):
        pkt = packet()
        bad_gate = gate(pkt)
        bad_gate["merge_ready"] = False
        with self.assertRaisesRegex(ValueError, "merge_ready"):
            build_evidence_bundle(snapshot(), packet=pkt, validation=validation(pkt), integration_gate=bad_gate)

    def test_invalid_validation_status_is_rejected(self):
        pkt = packet()
        bad = validation(pkt)
        bad["status"] = "TRUST_ME"
        with self.assertRaisesRegex(ValueError, "status/valid"):
            build_evidence_bundle(snapshot(), packet=pkt, validation=bad)

    def test_valid_pass_requires_pass_verdict(self):
        pkt = packet()
        bad = validation(pkt)
        bad["verdict"] = "FAIL"
        with self.assertRaisesRegex(ValueError, "verdict"):
            build_evidence_bundle(snapshot(), packet=pkt, validation=bad)

    def test_unknown_gate_status_is_rejected(self):
        pkt = packet()
        bad = gate(pkt)
        bad["status"] = "MAGIC"
        bad["merge_ready"] = False
        with self.assertRaisesRegex(ValueError, "state fields"):
            build_evidence_bundle(snapshot(), packet=pkt, validation=validation(pkt), integration_gate=bad)

    def test_invalid_snapshot_attention_is_rejected(self):
        snap = snapshot()
        snap["attention"] = "MAYBE"
        with self.assertRaisesRegex(ValueError, "attention"):
            build_evidence_bundle(snap)

    def test_boolean_pr_number_does_not_alias_integer(self):
        snap = snapshot()
        snap["pr_number"] = True
        with self.assertRaisesRegex(ValueError, "repository/pr_number"):
            build_evidence_bundle(snap)

    def test_packet_boolean_pr_number_does_not_alias_pr_one(self):
        snap = snapshot()
        pkt = packet()
        snap["pr_number"] = 1
        pkt["pr_number"] = True
        with self.assertRaisesRegex(ValueError, "repository/pr_number"):
            build_evidence_bundle(snap, packet=pkt)

    def test_validation_boolean_pr_number_does_not_alias_pr_one(self):
        snap = snapshot()
        pkt = packet()
        snap["pr_number"] = 1
        pkt["pr_number"] = 1
        review = validation(pkt)
        review["pr_number"] = True
        with self.assertRaisesRegex(ValueError, "binding"):
            build_evidence_bundle(snap, packet=pkt, validation=review)


if __name__ == "__main__":
    unittest.main()
