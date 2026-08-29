import unittest

from pr_attention.normalize import normalize_checks, normalize_reviews, normalize_threads


class NormalizeTests(unittest.TestCase):
    def test_checks_success(self):
        s = normalize_checks([{"name": "test", "status": "completed", "conclusion": "success"}], [])
        self.assertEqual(s.state, "SUCCESS")

    def test_checks_pending(self):
        s = normalize_checks([{"name": "test", "status": "in_progress", "conclusion": None}], [])
        self.assertEqual(s.state, "PENDING")

    def test_checks_failure_dominates(self):
        s = normalize_checks([
            {"name": "ok", "status": "completed", "conclusion": "success"},
            {"name": "bad", "status": "completed", "conclusion": "failure"},
        ], [])
        self.assertEqual(s.state, "FAILURE")
        self.assertEqual(s.failed, ["bad"])

    def test_no_checks_is_unknown(self):
        self.assertEqual(normalize_checks([], []).state, "UNKNOWN")

    def test_status_context_failure(self):
        s = normalize_checks([], [{"context": "legacy", "state": "error"}])
        self.assertEqual(s.state, "FAILURE")

    def test_current_head_review_only(self):
        reviews = [
            {"user": {"login": "alice"}, "state": "APPROVED", "commit_id": "old"},
            {"user": {"login": "bob"}, "state": "APPROVED", "commit_id": "head"},
        ]
        s = normalize_reviews(reviews, "head")
        self.assertEqual(s.current_head_approvals, ["bob"])
        self.assertEqual(s.stale_review_count, 1)

    def test_changes_requested_current_head(self):
        s = normalize_reviews([{"user": {"login": "alice"}, "state": "CHANGES_REQUESTED", "commit_id": "head"}], "head")
        self.assertEqual(s.state, "CHANGES_REQUESTED")

    def test_dismissed_latest_review_invalidates_prior_approval(self):
        reviews = [
            {"user": {"login": "alice"}, "state": "APPROVED", "commit_id": "head"},
            {"user": {"login": "alice"}, "state": "DISMISSED", "commit_id": "head"},
        ]
        s = normalize_reviews(reviews, "head")
        self.assertEqual(s.state, "NONE")
        self.assertEqual(s.current_head_approvals, [])
        self.assertEqual(s.dismissed_review_count, 1)

    def test_threads_separate_current_outdated_resolved(self):
        nodes = [
            {"id": "1", "isResolved": False, "isOutdated": False, "path": "a.py", "comments": {"nodes": [{"author": {"login": "a"}, "body": "x"}]}},
            {"id": "2", "isResolved": False, "isOutdated": True, "path": "b.py", "comments": {"nodes": []}},
            {"id": "3", "isResolved": True, "isOutdated": False, "path": "c.py", "comments": {"nodes": []}},
        ]
        s = normalize_threads(nodes)
        self.assertEqual((s.unresolved_current, s.unresolved_outdated, s.resolved), (1, 1, 1))


if __name__ == "__main__":
    unittest.main()
