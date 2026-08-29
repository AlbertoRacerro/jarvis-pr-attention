import copy
import unittest

from pr_attention.cycle import run_cycle


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


def ordinary_fail_result(template):
    result = copy.deepcopy(template)
    result["verdict"] = "FAIL"
    result["findings"] = [
        {
            "id": "F1",
            "severity": "P1",
            "blocking": True,
            "title": "first blocker",
            "detail": "repair this before semantic acceptance",
            "path": None,
            "line": None,
        }
    ]
    return result


def continuity_result(template, *, verdict, resolved, remaining, findings):
    result = copy.deepcopy(template)
    result["verdict"] = verdict
    result["reviewed_files"] = ["src/a.py"]
    result["considered_thread_ids"] = []
    prior = [*resolved, *remaining]
    result["rechecked_finding_ids"] = prior
    result["resolved_finding_ids"] = resolved
    result["remaining_finding_ids"] = remaining
    result["global_invariants_rechecked"] = True
    result["findings"] = findings
    result["notes"] = []
    return result


class CycleTests(unittest.TestCase):
    def test_no_baseline_is_full_review_without_inventing_authority(self):
        result = run_cycle(FakeClient(H1), "o/r", 1)
        self.assertEqual(result["review_mode"], "FULL")
        self.assertEqual(result["next_action"], "FULL_REVIEW")
        self.assertFalse(result["merge_candidate"])
        self.assertIsNone(result["review_packet"])

    def test_h1_fail_h2_fail_h3_pass_continuity(self):
        h1_handoff = run_cycle(FakeClient(H1), "o/r", 1, accepted_head_sha=H1, reviewer_name="reviewer")
        h1_fail = ordinary_fail_result(h1_handoff["review_result_template"])
        h1 = run_cycle(
            FakeClient(H1),
            "o/r",
            1,
            accepted_head_sha=H1,
            review_result=h1_fail,
            reviewer_name="reviewer",
        )
        self.assertEqual(h1["gate_status"], "REPAIR")
        self.assertEqual(h1["checkpoint"]["generation"], 1)

        h2_handoff = run_cycle(
            FakeClient(H2),
            "o/r",
            1,
            previous_failed_source=h1["checkpoint"],
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
            reviewer_name="reviewer",
        )
        self.assertEqual(h2["gate_status"], "REPAIR")
        self.assertEqual(h2["checkpoint"]["generation"], 2)
        self.assertEqual([item["id"] for item in h2["checkpoint"]["unresolved_findings"]], ["F2"])

        h3_handoff = run_cycle(
            FakeClient(H3),
            "o/r",
            1,
            previous_failed_source=h2["checkpoint"],
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
            reviewer_name="reviewer",
        )
        self.assertEqual(h3["gate_status"], "READY_TO_MERGE")
        self.assertEqual(h3["next_action"], "MERGE_CANDIDATE")
        self.assertTrue(h3["merge_candidate"])
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


if __name__ == "__main__":
    unittest.main()
