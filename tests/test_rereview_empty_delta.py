import unittest

from pr_attention.rereview_packet import build_rereview_packet
from test_rereview import REPAIRED_HEAD, fail_bundle


class EmptyRepairDeltaTests(unittest.TestCase):
    def test_ahead_without_file_changes_is_not_incrementally_eligible(self):
        packet = build_rereview_packet(
            fail_bundle(),
            {"status": "ahead", "ahead_by": 1, "behind_by": 0, "files": []},
            current_head_sha=REPAIRED_HEAD,
            final_head_sha=REPAIRED_HEAD,
        )
        self.assertFalse(packet["incremental_eligible"])
        self.assertFalse(packet["complete"])
        self.assertEqual(packet["coverage"], "NONE")
        self.assertEqual(packet["relation"], "AHEAD")
        self.assertIn("no file-content repair delta", packet["reasons"][0])


if __name__ == "__main__":
    unittest.main()
