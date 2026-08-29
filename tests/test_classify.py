import unittest

from pr_attention.classify import classify_attention
from pr_attention.models import CheckSummary, MergeSummary, ReviewSummary, ThreadSummary


def base(**overrides):
    data = dict(
        initial_head_sha="h",
        final_head_sha="h",
        checks=CheckSummary(state="SUCCESS", total=1, passed=["test"]),
        reviews=ReviewSummary(state="NONE"),
        threads=ThreadSummary(),
        merge=MergeSummary(mergeable=True, mergeable_state="clean", conflict=False),
        facts_complete=True,
    )
    data.update(overrides)
    return classify_attention(**data)


class ClassificationTests(unittest.TestCase):
    def test_ready(self):
        self.assertEqual(base()[0], "READY")

    def test_failed_ci_blocks(self):
        state, blockers, _ = base(checks=CheckSummary(state="FAILURE", total=1, failed=["test"]))
        self.assertEqual(state, "BLOCKED")
        self.assertTrue(blockers)

    def test_pending_ci_waits(self):
        self.assertEqual(base(checks=CheckSummary(state="PENDING", total=1, pending=["test"]))[0], "PENDING")

    def test_unresolved_thread_blocks(self):
        self.assertEqual(base(threads=ThreadSummary(total=1, unresolved_current=1))[0], "BLOCKED")

    def test_conflict_blocks(self):
        self.assertEqual(base(merge=MergeSummary(mergeable=False, mergeable_state="dirty", conflict=True))[0], "BLOCKED")

    def test_head_change_is_stale(self):
        self.assertEqual(base(final_head_sha="new")[0], "STALE")

    def test_incomplete_facts_unknown(self):
        self.assertEqual(base(facts_complete=False)[0], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
