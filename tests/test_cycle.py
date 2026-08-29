import copy
import tempfile
import unittest
from pathlib import Path

from pr_attention.cycle import run_cycle
from pr_attention.cycle_cli import _prepare_output_dir, _write_json


BASE = "0" * 40
H1 = "a" * 40
H2 = "b" * 40
H3 = "c" * 40


class FakeClient:
    def __init__(self, head):
        self.head = head

    def pull_request(self, repo, number):
        return {
            "title": "cycle",
            "draft": False,
            "head": {"sha": self.head, "ref": "feature"},
            "base": {"ref": "main"},
            "mergeable": True,
            "mergeable_state": "clean",
            "additions": 2,
            "deletions": 1,
            "changed_files": 1,
        }

    def check_runs(self, repo, sha):
        return [{"name": "test", "status": "completed", "conclusion": "success", "app": {"id": 1}}]

    def status_contexts(self, repo, sha):
        return []

    def reviews(self, repo, number):
        return []

    def review_threads(self, repo, number):
        return []

    def branch(self, repo, branch):
        return {
            "protected": True,
            "protection": {
                "required_status_checks": {
                    "enforcement_level": "non_admins",
                    "contexts": ["test"],
                    "checks": [],
                }
            },
        }

    def branch_rules(self, repo, branch):
        return []

    def review_policy(self, repo, number):
        return {"isDraft": False, "reviewDecision": None}

    def compare(self, repo, base, head):
        return {
            "status": "ahead",
            "ahead_by": 1,
            "behind_by": 0,
            "files": [
                {
                    "filename": "src/a.py",
                    "status": "modified",
                    "additions": 2,
                    "deletions": 1,
                    "changes": 3,
                    "patch": "@@ -1 +1 @@\n-old\n+new\n",
                }
            ],
        }


class MovingHeadClient(FakeClient):
    def __init__(self):
        super().__init__(H1)
        self.calls = 0

    def pull_request(self, repo, number):
        self.calls += 1
        self.head = H1 if self.calls == 1 else H2
        return super().pull_request(repo, number)


def ordinary_fail_result(template):
    result = copy.deepcopy(template)
    result["verdict"] = "FAIL"
    result["reviewed_files"] = ["src/a.py"]
    result["findings"] = [
        {
            "id": "F1",
            "severity": "P1",
            "blocking": True,
            "title": "first blocker",
            "detail": "repair this before semantic acceptance",
            "path": "src/a.py",
            "line": 1,
        }
    ]
    return result


def ordinary_pass_result(template):
    result = copy.deepcopy(template)
    result["verdict"] = "PASS"
    result["reviewed_files"] = ["src/a.py"]
    result["findings"] = []
    result["notes"] = []
    return result


def continuity_result(template, *, verdict, resolved, remaining, findings):
    result = copy.deepcopy(template)
    result["verdict"] = verdict
    result["reviewed_files"] = ["src/a.py"]
    result["considered_thread_ids"] = []
    result["rechecked_finding_ids"] = [*resolved, *remaining]
    result["resolved_finding_ids"] = resolved
    result["remaining_finding_ids"] = remaining
    result["global_invariants_rechecked"] = True
    result["findings"] = findings
    result["notes"] = []
    return result


class CycleSafetyTests(unittest.TestCase):
    def test_no_baseline_is_full_review_without_inventing_authority(self):
        result = run_cycle(FakeClient(H1), "o/r", 1, expected_head_sha=H1)
        self.assertEqual(result["review_mode"], "FULL")
        self.assertEqual(result["next_action"], "FULL_REVIEW")
        self.assertFalse(result["merge_candidate"])
        self.assertIsNone(result["review_packet"])
        self.assertEqual(result["safety"]["baseline_authority"], "NONE")

    def test_naked_accepted_head_cannot_reduce_review_scope(self):
        result = run_cycle(
            FakeClient(H1),
            "o/r",
            1,
            accepted_head_sha=BASE,
            expected_head_sha=H1,
        )
        self.assertEqual(result["review_mode"], "FULL")
        self.assertEqual(result["next_action"], "FULL_REVIEW")
        self.assertFalse(result["merge_candidate"])
        self.assertIsNone(result["review_packet"])
        self.assertEqual(result["safety"]["status"], "BLOCKED")
        self.assertEqual(result["safety"]["baseline_authority"], "UNCONFIRMED_CLAIM")

    def test_confirmed_baseline_requires_traceable_source(self):
        with self.assertRaises(ValueError):
            run_cycle(
                FakeClient(H1),
                "o/r",
                1,
                accepted_head_sha=BASE,
                accepted_head_authority_confirmed=True,
            )

    def test_confirmed_baseline_can_generate_delta_handoff(self):
        result = run_cycle(
            FakeClient(H1),
            "o/r",
            1,
            accepted_head_sha=BASE,
            accepted_head_authority_confirmed=True,
            accepted_head_source="github-review:123",
            expected_head_sha=H1,
            reviewer_name="reviewer",
        )
        self.assertEqual(result["review_mode"], "DELTA")
        self.assertEqual(result["next_action"], "REVIEW_DELTA")
        self.assertFalse(result["merge_candidate"])
        self.assertIsNotNone(result["review_packet"])
        self.assertIsNotNone(result["review_envelope"])
        self.assertEqual(result["safety"]["status"], "SAFE_TO_REVIEW")

    def test_current_confirmed_baseline_never_shortcuts_to_merge_candidate(self):
        result = run_cycle(
            FakeClient(H1),
            "o/r",
            1,
            accepted_head_sha=H1,
            accepted_head_authority_confirmed=True,
            accepted_head_source="governance:accepted-head",
            expected_head_sha=H1,
        )
        self.assertEqual(result["review_mode"], "NONE")
        self.assertEqual(result["next_action"], "VERIFY_MERGE_GOVERNANCE")
        self.assertFalse(result["merge_candidate"])
        self.assertIsNone(result["review_packet"])
        self.assertEqual(result["gate_status"], "NOT_RUN")

    def test_merge_candidate_requires_current_live_bound_pass(self):
        handoff = run_cycle(
            FakeClient(H1),
            "o/r",
            1,
            accepted_head_sha=BASE,
            accepted_head_authority_confirmed=True,
            accepted_head_source="github-review:baseline",
            expected_head_sha=H1,
            reviewer_name="reviewer",
        )
        passed = ordinary_pass_result(handoff["review_result_template"])
        result = run_cycle(
            FakeClient(H1),
            "o/r",
            1,
            accepted_head_sha=BASE,
            accepted_head_authority_confirmed=True,
            accepted_head_source="github-review:baseline",
            expected_head_sha=H1,
            review_result=passed,
            review_result_source="review-service:result-1",
            reviewer_name="reviewer",
        )
        self.assertEqual(result["semantic_status"], "VALID_PASS")
        self.assertTrue(result["live_review_bound"])
        self.assertEqual(result["gate_status"], "READY_TO_MERGE")
        self.assertTrue(result["merge_candidate"])
        self.assertEqual(result["safety"]["status"], "SAFE_TO_MERGE_ADVISORY")

    def test_tampered_result_never_emits_merge_signal(self):
        handoff = run_cycle(
            FakeClient(H1),
            "o/r",
            1,
            accepted_head_sha=BASE,
            accepted_head_authority_confirmed=True,
            accepted_head_source="github-review:baseline",
            reviewer_name="reviewer",
        )
        passed = ordinary_pass_result(handoff["review_result_template"])
        passed["packet_sha256"] = "sha256:" + ("f" * 64)
        result = run_cycle(
            FakeClient(H1),
            "o/r",
            1,
            accepted_head_sha=BASE,
            accepted_head_authority_confirmed=True,
            accepted_head_source="github-review:baseline",
            review_result=passed,
            review_result_source="review-service:tampered",
            reviewer_name="reviewer",
        )
        self.assertEqual(result["semantic_status"], "INVALID")
        self.assertFalse(result["live_review_bound"])
        self.assertFalse(result["merge_candidate"])
        self.assertEqual(result["safety"]["status"], "BLOCKED")

    def test_review_result_requires_result_source_and_confirmed_baseline(self):
        handoff = run_cycle(
            FakeClient(H1),
            "o/r",
            1,
            accepted_head_sha=BASE,
            accepted_head_authority_confirmed=True,
            accepted_head_source="github-review:baseline",
            reviewer_name="reviewer",
        )
        passed = ordinary_pass_result(handoff["review_result_template"])
        with self.assertRaises(ValueError):
            run_cycle(
                FakeClient(H1),
                "o/r",
                1,
                accepted_head_sha=BASE,
                accepted_head_authority_confirmed=True,
                accepted_head_source="github-review:baseline",
                review_result=passed,
                reviewer_name="reviewer",
            )
        with self.assertRaises(ValueError):
            run_cycle(
                FakeClient(H1),
                "o/r",
                1,
                accepted_head_sha=BASE,
                review_result=passed,
                review_result_source="review-service:result",
                reviewer_name="reviewer",
            )

    def test_expected_head_mismatch_fails_before_handoff(self):
        with self.assertRaises(ValueError):
            run_cycle(FakeClient(H1), "o/r", 1, expected_head_sha=H2)

    def test_head_move_during_snapshot_returns_no_evidence_for_merge(self):
        result = run_cycle(MovingHeadClient(), "o/r", 1)
        self.assertEqual(result["attention"], "STALE")
        self.assertEqual(result["next_action"], "REFRESH_SNAPSHOT")
        self.assertFalse(result["merge_candidate"])
        self.assertIsNone(result["review_packet"])
        self.assertEqual(result["safety"]["status"], "BLOCKED")

    def test_invalid_repository_and_zero_budget_fail_closed(self):
        with self.assertRaises(ValueError):
            run_cycle(FakeClient(H1), "not-a-repository", 1)
        with self.assertRaises(ValueError):
            run_cycle(
                FakeClient(H1),
                "o/r",
                1,
                accepted_head_sha=BASE,
                accepted_head_authority_confirmed=True,
                accepted_head_source="github-review:baseline",
                max_total_patch_bytes=0,
            )

    def test_h1_fail_h2_fail_h3_pass_continuity(self):
        h1_handoff = run_cycle(
            FakeClient(H1),
            "o/r",
            1,
            accepted_head_sha=BASE,
            accepted_head_authority_confirmed=True,
            accepted_head_source="github-review:baseline",
            expected_head_sha=H1,
            reviewer_name="reviewer",
        )
        h1_fail = ordinary_fail_result(h1_handoff["review_result_template"])
        h1 = run_cycle(
            FakeClient(H1),
            "o/r",
            1,
            accepted_head_sha=BASE,
            accepted_head_authority_confirmed=True,
            accepted_head_source="github-review:baseline",
            expected_head_sha=H1,
            review_result=h1_fail,
            review_result_source="review-service:h1",
            reviewer_name="reviewer",
        )
        self.assertEqual(h1["gate_status"], "REPAIR")
        self.assertEqual(h1["checkpoint"]["generation"], 1)
        self.assertFalse(h1["merge_candidate"])

        h2_handoff = run_cycle(
            FakeClient(H2),
            "o/r",
            1,
            previous_failed_source=h1["checkpoint"],
            expected_head_sha=H2,
            reviewer_name="reviewer",
        )
        self.assertEqual(h2_handoff["review_mode"], "CONTINUITY")
        self.assertEqual(h2_handoff["next_action"], "REREVIEW_DELTA")
        h2_fail = continuity_result(
            h2_handoff["review_result_template"],
            verdict="FAIL",
            resolved=["F1"],
            remaining=[],
            findings=[
                {
                    "id": "F2",
                    "severity": "P1",
                    "blocking": True,
                    "title": "second blocker",
                    "detail": "new blocker found while checking the repair delta",
                    "path": "src/a.py",
                    "line": 1,
                }
            ],
        )
        h2 = run_cycle(
            FakeClient(H2),
            "o/r",
            1,
            previous_failed_source=h1["checkpoint"],
            continuity_result=h2_fail,
            continuity_result_source="review-service:h2",
            expected_head_sha=H2,
            reviewer_name="reviewer",
        )
        self.assertEqual(h2["gate_status"], "REPAIR")
        self.assertEqual(h2["checkpoint"]["generation"], 2)
        self.assertEqual([item["id"] for item in h2["checkpoint"]["unresolved_findings"]], ["F2"])
        self.assertFalse(h2["merge_candidate"])

        h3_handoff = run_cycle(
            FakeClient(H3),
            "o/r",
            1,
            previous_failed_source=h2["checkpoint"],
            expected_head_sha=H3,
            reviewer_name="reviewer",
        )
        h3_pass = continuity_result(
            h3_handoff["review_result_template"],
            verdict="PASS",
            resolved=["F2"],
            remaining=[],
            findings=[],
        )
        h3 = run_cycle(
            FakeClient(H3),
            "o/r",
            1,
            previous_failed_source=h2["checkpoint"],
            continuity_result=h3_pass,
            continuity_result_source="review-service:h3",
            expected_head_sha=H3,
            reviewer_name="reviewer",
        )
        self.assertEqual(h3["gate_status"], "READY_TO_MERGE")
        self.assertEqual(h3["next_action"], "MERGE_CANDIDATE")
        self.assertTrue(h3["merge_candidate"])
        self.assertTrue(h3["live_review_bound"])
        self.assertIsNone(h3["checkpoint"])

    def test_ambiguous_authority_inputs_fail_closed(self):
        with self.assertRaises(ValueError):
            run_cycle(
                FakeClient(H1),
                "o/r",
                1,
                accepted_head_sha=H1,
                previous_failed_source={"kind": "anything"},
            )


class CycleArtifactSafetyTests(unittest.TestCase):
    def test_nonempty_output_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cycle"
            path.mkdir()
            (path / "old.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                _prepare_output_dir(path)

    def test_empty_output_directory_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cycle"
            path.mkdir()
            self.assertEqual(_prepare_output_dir(path), path)

    def test_artifacts_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.json"
            _write_json(path, {"first": True})
            with self.assertRaises(ValueError):
                _write_json(path, {"second": True})


if __name__ == "__main__":
    unittest.main()
