import unittest

from pr_attention.rereview_result import validate_rereview_result
from test_rereview import REPAIRED_HEAD, pass_result, rereview_packet


class RereviewContinuityTests(unittest.TestCase):
    def test_fail_cannot_drop_prior_blocker_from_tracking(self):
        packet = rereview_packet()
        result = pass_result(packet)
        result["verdict"] = "FAIL"
        result["rechecked_finding_ids"] = []
        result["resolved_finding_ids"] = []
        result["remaining_finding_ids"] = []
        result["findings"] = [
            {
                "id": "F2",
                "severity": "P2",
                "blocking": True,
                "title": "New blocker",
                "detail": "A new repair blocker exists.",
                "path": "new.py",
                "line": 1,
            }
        ]
        validation = validate_rereview_result(packet, result, live_head_sha=REPAIRED_HEAD)
        self.assertFalse(validation.valid)
        self.assertEqual(validation.status, "INVALID")
        self.assertTrue(any("every prior blocking finding" in reason for reason in validation.reasons))

    def test_boolean_packet_flags_cannot_alias_valid_state(self):
        packet = rereview_packet()
        packet["complete"] = 1
        packet["rereview_packet_sha256"] = __import__("pr_attention.rereview_packet", fromlist=["rereview_packet_sha256"]).rereview_packet_sha256(packet)
        result = pass_result(packet)
        validation = validate_rereview_result(packet, result, live_head_sha=REPAIRED_HEAD)
        self.assertFalse(validation.valid)
        self.assertEqual(validation.status, "INVALID")


if __name__ == "__main__":
    unittest.main()
