import unittest

from pr_attention.normalize import normalize_delta


class DeltaTests(unittest.TestCase):
    def test_no_baseline_requires_full_review(self):
        d = normalize_delta(None, "b" * 40, None)
        self.assertEqual((d.relation, d.review_scope, d.acceptance_validity), ("ABSENT", "FULL", "ABSENT"))

    def test_same_head_reuses_acceptance(self):
        sha = "a" * 40
        d = normalize_delta(sha, sha, None)
        self.assertEqual((d.relation, d.review_scope, d.acceptance_validity), ("CURRENT", "NONE", "CURRENT"))

    def test_ancestor_limits_review_to_delta(self):
        d = normalize_delta(
            "a" * 40,
            "b" * 40,
            {
                "status": "ahead",
                "ahead_by": 2,
                "behind_by": 0,
                "files": [
                    {"filename": "src/a.py", "status": "modified", "additions": 5, "deletions": 2, "changes": 7},
                    {"filename": "src/b.py", "status": "added", "additions": 4, "deletions": 0, "changes": 4},
                ],
            },
        )
        self.assertEqual(d.relation, "AHEAD")
        self.assertEqual(d.review_scope, "DELTA")
        self.assertEqual(d.acceptance_validity, "REUSABLE_FOR_UNCHANGED")
        self.assertEqual(d.changed_files, 2)
        self.assertEqual((d.additions, d.deletions), (9, 2))

    def test_empty_content_delta_needs_no_new_semantic_review(self):
        d = normalize_delta("a" * 40, "b" * 40, {"status": "ahead", "ahead_by": 1, "behind_by": 0, "files": []})
        self.assertEqual(d.review_scope, "NONE")

    def test_large_delta_fails_closed_to_full_review(self):
        files = [{"filename": f"f{i}.py", "status": "modified"} for i in range(300)]
        d = normalize_delta("a" * 40, "b" * 40, {"status": "ahead", "ahead_by": 1, "behind_by": 0, "files": files})
        self.assertFalse(d.complete)
        self.assertEqual(d.review_scope, "FULL")

    def test_diverged_invalidates_prior_acceptance(self):
        d = normalize_delta("a" * 40, "b" * 40, {"status": "diverged", "ahead_by": 2, "behind_by": 1, "files": []})
        self.assertEqual((d.relation, d.acceptance_validity, d.review_scope), ("DIVERGED", "INVALID", "FULL"))

    def test_missing_compare_is_unknown(self):
        d = normalize_delta("a" * 40, "b" * 40, None)
        self.assertEqual((d.relation, d.review_scope, d.complete), ("UNKNOWN", "UNKNOWN", False))


if __name__ == "__main__":
    unittest.main()
