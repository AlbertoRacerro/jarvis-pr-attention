import copy
import unittest

from pr_attention.integration_gate import MERGE_SAFETY_NOTICE, build_integration_gate

HEAD = "a" * 40
DIGEST = "sha256:" + "b" * 64


def snapshot(*, attention="READY", stale=False, facts_complete=True, final_head=HEAD):
    return {
        "schema_version": 2,
        "repository": "o/r",
        "pr_number": 4,
        "head_sha": HEAD,
        "final_head_sha": final_head,
        "attention": attention,
        "facts_complete": facts_complete,
        "stale": stale,
    }


def validation(*, status="VALID_PASS", valid=True, live_head=HEAD, head=HEAD):
    return {
        "schema_version": 1,
        "valid": valid,
        "status": status,
        "repository": "o/r",
        "pr_number": 4,
        "head_sha": head,
        "packet_sha256": DIGEST,
        "verdict": "PASS" if status == "VALID_PASS" else None,
        "live_head_sha": live_head,
        "reasons": [],
    }


class IntegrationGateTests(unittest.TestCase):
    def test_ready_requires_live_pass_and_ready_github_state(self):
        gate = build_integration_gate(snapshot(), validation())
        self.assertEqual(gate.status, "READY_TO_MERGE")
        self.assertTrue(gate.merge_ready)
        self.assertTrue(gate.live_review_bound)
        self.assertEqual(gate.safety_notice, MERGE_SAFETY_NOTICE)

    def test_pending_github_gates_wait_after_semantic_pass(self):
        gate = build_integration_gate(snapshot(attention="PENDING"), validation())
        self.assertEqual(gate.status, "WAIT_FOR_GATES")
        self.assertFalse(gate.merge_ready)

    def test_blocked_github_state_repairs_after_semantic_pass(self):
        gate = build_integration_gate(snapshot(attention="BLOCKED"), validation())
        self.assertEqual(gate.status, "REPAIR")

    def test_semantic_fail_repairs_even_if_github_ready(self):
        gate = build_integration_gate(snapshot(), validation(status="VALID_FAIL", valid=True))
        self.assertEqual(gate.status, "REPAIR")

    def test_needs_human_is_preserved(self):
        gate = build_integration_gate(snapshot(), validation(status="VALID_NEEDS_HUMAN", valid=True))
        self.assertEqual(gate.status, "NEEDS_HUMAN")

    def test_invalid_semantic_result_requires_review(self):
        gate = build_integration_gate(snapshot(), validation(status="INVALID", valid=False, live_head=None))
        self.assertEqual(gate.status, "REVIEW_REQUIRED")

    def test_offline_pass_requires_live_verification(self):
        gate = build_integration_gate(snapshot(), validation(live_head=None))
        self.assertEqual(gate.status, "VERIFY_LIVE")
        self.assertFalse(gate.merge_ready)

    def test_live_head_move_is_stale(self):
        gate = build_integration_gate(snapshot(), validation(live_head="c" * 40))
        self.assertEqual(gate.status, "STALE")

    def test_snapshot_head_move_is_stale(self):
        gate = build_integration_gate(snapshot(final_head="c" * 40), validation())
        self.assertEqual(gate.status, "STALE")

    def test_reviewed_head_mismatch_is_stale(self):
        gate = build_integration_gate(snapshot(), validation(head="c" * 40, live_head="c" * 40))
        self.assertEqual(gate.status, "STALE")

    def test_unknown_github_state_remains_unknown(self):
        gate = build_integration_gate(snapshot(attention="UNKNOWN"), validation())
        self.assertEqual(gate.status, "UNKNOWN")

    def test_incomplete_github_facts_cannot_merge(self):
        gate = build_integration_gate(snapshot(facts_complete=False), validation())
        self.assertEqual(gate.status, "UNKNOWN")
        self.assertFalse(gate.merge_ready)

    def test_invalid_binding_is_unknown(self):
        bad = validation()
        bad["repository"] = "other/repo"
        gate = build_integration_gate(snapshot(), bad)
        self.assertEqual(gate.status, "UNKNOWN")

    def test_boolean_schema_is_rejected(self):
        snap = snapshot()
        snap["schema_version"] = True
        gate = build_integration_gate(snap, validation())
        self.assertEqual(gate.status, "UNKNOWN")

    def test_boolean_pr_number_does_not_alias_integer(self):
        review = validation()
        review["pr_number"] = True
        gate = build_integration_gate(snapshot(), review)
        self.assertEqual(gate.status, "UNKNOWN")

    def test_input_objects_are_not_mutated(self):
        snap = snapshot()
        review = validation()
        snap_before = copy.deepcopy(snap)
        review_before = copy.deepcopy(review)
        build_integration_gate(snap, review)
        self.assertEqual(snap, snap_before)
        self.assertEqual(review, review_before)


if __name__ == "__main__":
    unittest.main()
