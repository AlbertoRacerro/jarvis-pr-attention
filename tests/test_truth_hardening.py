import unittest

from pr_attention.classify import classify_attention
from pr_attention.models import (
    CheckSummary,
    MergeSummary,
    NativeReviewPolicySummary,
    RequiredCheckSummary,
    ReviewSummary,
    ThreadSummary,
)
from pr_attention.truth import normalize_native_review_policy, normalize_required_checks


def branch(required=None):
    return {
        "protected": bool(required),
        "protection": {
            "required_status_checks": {
                "enforcement_level": "non_admins" if required else "off",
                "contexts": list(required or []),
                "checks": [],
            }
        },
    }


class RequiredCheckTruthTests(unittest.TestCase):
    def test_known_policy_with_no_required_checks(self):
        result = normalize_required_checks(branch(), [], [], [])
        self.assertTrue(result.known)
        self.assertEqual(result.state, "NONE")

    def test_classic_required_check_passes(self):
        result = normalize_required_checks(
            branch(["ci"]),
            [],
            [{"name": "ci", "status": "completed", "conclusion": "success"}],
            [],
        )
        self.assertEqual(result.state, "SUCCESS")
        self.assertEqual(result.passed, ["ci"])

    def test_missing_required_check_is_pending(self):
        result = normalize_required_checks(branch(["ci"]), [], [], [])
        self.assertEqual(result.state, "PENDING")
        self.assertEqual(result.missing, ["ci"])

    def test_required_failure_dominates(self):
        result = normalize_required_checks(
            branch(["ci"]),
            [],
            [{"name": "ci", "status": "completed", "conclusion": "failure"}],
            [],
        )
        self.assertEqual(result.state, "FAILURE")

    def test_ruleset_integration_id_requires_matching_app(self):
        rules = [{
            "id": 9,
            "type": "required_status_checks",
            "parameters": {"required_status_checks": [{"context": "ci", "integration_id": 42}]},
        }]
        wrong = normalize_required_checks(
            branch(), rules,
            [{"name": "ci", "status": "completed", "conclusion": "success", "app": {"id": 7}}],
            [{"context": "ci", "state": "success"}],
        )
        self.assertEqual(wrong.state, "PENDING")
        self.assertEqual(wrong.missing, ["ci@app:42"])
        right = normalize_required_checks(
            branch(), rules,
            [{"name": "ci", "status": "completed", "conclusion": "success", "app": {"id": 42}}],
            [],
        )
        self.assertEqual(right.state, "SUCCESS")

    def test_missing_policy_evidence_is_unknown(self):
        result = normalize_required_checks(None, [], [], [])
        self.assertFalse(result.known)
        self.assertEqual(result.state, "UNKNOWN")


class NativeReviewTruthTests(unittest.TestCase):
    def test_native_policy_is_separate_fact(self):
        result = normalize_native_review_policy(
            {"isDraft": False, "reviewDecision": "APPROVED"}, rest_draft=False
        )
        self.assertTrue(result.known)
        self.assertFalse(result.draft)
        self.assertEqual(result.review_decision, "APPROVED")
        self.assertTrue(any("not Jarvis semantic acceptance" in item for item in result.reasons))

    def test_draft_disagreement_fails_closed(self):
        result = normalize_native_review_policy(
            {"isDraft": True, "reviewDecision": None}, rest_draft=False
        )
        self.assertFalse(result.known)
        self.assertEqual(result.review_decision, "UNKNOWN")

    def test_unknown_decision_fails_closed(self):
        result = normalize_native_review_policy(
            {"isDraft": False, "reviewDecision": "MAGIC"}, rest_draft=False
        )
        self.assertFalse(result.known)


class PolicyClassificationTests(unittest.TestCase):
    def _base(self, *, required=None, native=None):
        checks = CheckSummary(
            state="SUCCESS",
            total=1,
            passed=["ci"],
            required=required or RequiredCheckSummary(known=True, state="NONE"),
        )
        reviews = ReviewSummary(
            state="NONE",
            native_policy=native or NativeReviewPolicySummary(
                known=True, draft=False, review_decision="NONE"
            ),
        )
        return classify_attention(
            initial_head_sha="h",
            final_head_sha="h",
            checks=checks,
            reviews=reviews,
            threads=ThreadSummary(),
            merge=MergeSummary(mergeable=True, mergeable_state="clean", conflict=False),
            facts_complete=True,
        )

    def test_required_failure_blocks(self):
        state, blockers, _ = self._base(required=RequiredCheckSummary(known=True, state="FAILURE", failed=["ci"]))
        self.assertEqual(state, "BLOCKED")
        self.assertTrue(any("required GitHub checks" in item for item in blockers))

    def test_required_pending_waits(self):
        state, _, pending = self._base(required=RequiredCheckSummary(known=True, state="PENDING", missing=["ci"]))
        self.assertEqual(state, "PENDING")
        self.assertTrue(pending)

    def test_required_unknown_is_unknown(self):
        state, _, _ = self._base(required=RequiredCheckSummary(known=True, state="UNKNOWN", unknown=["ci"]))
        self.assertEqual(state, "UNKNOWN")

    def test_draft_blocks(self):
        state, blockers, _ = self._base(native=NativeReviewPolicySummary(known=True, draft=True, review_decision="NONE"))
        self.assertEqual(state, "BLOCKED")
        self.assertIn("pull request is draft", blockers)

    def test_native_review_required_waits(self):
        state, _, pending = self._base(native=NativeReviewPolicySummary(known=True, draft=False, review_decision="REVIEW_REQUIRED"))
        self.assertEqual(state, "PENDING")
        self.assertTrue(any("native review policy" in item for item in pending))

    def test_native_approval_is_not_extra_semantic_authority(self):
        state, blockers, pending = self._base(native=NativeReviewPolicySummary(known=True, draft=False, review_decision="APPROVED"))
        self.assertEqual(state, "READY")
        self.assertEqual(blockers, [])
        self.assertEqual(pending, [])


if __name__ == "__main__":
    unittest.main()
