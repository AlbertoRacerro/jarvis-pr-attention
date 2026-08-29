import unittest

from pr_attention.classify import classify_next_action
from pr_attention.models import DeltaSummary


def delta(scope="NONE"):
    return DeltaSummary(
        accepted_head_sha="a" * 40,
        relation="CURRENT" if scope == "NONE" else "AHEAD",
        acceptance_validity="CURRENT" if scope == "NONE" else "REUSABLE_FOR_UNCHANGED",
        review_scope=scope,
        complete=scope != "UNKNOWN",
    )


class NextActionTests(unittest.TestCase):
    def test_stale_refreshes(self):
        self.assertEqual(classify_next_action("STALE", delta()), "REFRESH_SNAPSHOT")

    def test_unknown_investigates(self):
        self.assertEqual(classify_next_action("UNKNOWN", delta()), "INVESTIGATE_UNKNOWN")

    def test_blocked_repairs(self):
        self.assertEqual(classify_next_action("BLOCKED", delta("DELTA")), "REPAIR")

    def test_pending_waits(self):
        self.assertEqual(classify_next_action("PENDING", delta("DELTA")), "WAIT_FOR_GATES")

    def test_ready_current_is_merge_candidate(self):
        self.assertEqual(classify_next_action("READY", delta("NONE")), "MERGE_CANDIDATE")

    def test_ready_delta_reviews_delta(self):
        self.assertEqual(classify_next_action("READY", delta("DELTA")), "REVIEW_DELTA")

    def test_ready_without_reusable_acceptance_full_reviews(self):
        self.assertEqual(classify_next_action("READY", delta("FULL")), "FULL_REVIEW")

    def test_ready_unknown_delta_investigates(self):
        self.assertEqual(classify_next_action("READY", delta("UNKNOWN")), "INVESTIGATE_UNKNOWN")


if __name__ == "__main__":
    unittest.main()
