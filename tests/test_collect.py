import unittest

import pr_attention
from pr_attention.cli import collect_snapshot


HEAD = "b" * 40
ACCEPTED = "a" * 40


class FakeClient:
    def __init__(self, final_head=HEAD, compare_status="ahead"):
        self.final_head = final_head
        self.compare_status = compare_status
        self.pr_calls = 0

    def pull_request(self, repo, number):
        self.pr_calls += 1
        sha = HEAD if self.pr_calls == 1 else self.final_head
        return {
            "title": "test",
            "head": {"sha": sha, "ref": "feature"},
            "base": {"ref": "main"},
            "mergeable": True,
            "mergeable_state": "clean",
            "additions": 5,
            "deletions": 1,
            "changed_files": 1,
        }

    def check_runs(self, repo, sha):
        return [{"name": "test", "status": "completed", "conclusion": "success"}]

    def status_contexts(self, repo, sha):
        return []

    def reviews(self, repo, number):
        return []

    def review_threads(self, repo, number):
        return []

    def compare(self, repo, base, head):
        return {
            "status": self.compare_status,
            "ahead_by": 1,
            "behind_by": 0,
            "files": [{"filename": "src/a.py", "status": "modified", "additions": 5, "deletions": 1, "changes": 6}],
        }


class CollectTests(unittest.TestCase):
    def test_public_collect_snapshot_export_is_preserved(self):
        self.assertIs(pr_attention.collect_snapshot, collect_snapshot)

    def test_schema_v2_and_delta_review(self):
        s = collect_snapshot(FakeClient(), "o/r", 1, accepted_head_sha=ACCEPTED)
        self.assertEqual(s.schema_version, 2)
        self.assertEqual(s.attention, "READY")
        self.assertEqual(s.delta.review_scope, "DELTA")
        self.assertEqual(s.next_action_class, "REVIEW_DELTA")

    def test_current_accepted_head_is_merge_candidate(self):
        s = collect_snapshot(FakeClient(), "o/r", 1, accepted_head_sha=HEAD)
        self.assertEqual(s.next_action_class, "MERGE_CANDIDATE")

    def test_head_move_forces_refresh(self):
        s = collect_snapshot(FakeClient(final_head="c" * 40), "o/r", 1, accepted_head_sha=ACCEPTED)
        self.assertEqual(s.attention, "STALE")
        self.assertEqual(s.next_action_class, "REFRESH_SNAPSHOT")

    def test_invalid_accepted_sha_fails_before_network(self):
        with self.assertRaises(ValueError):
            collect_snapshot(FakeClient(), "o/r", 1, accepted_head_sha="short")


if __name__ == "__main__":
    unittest.main()
