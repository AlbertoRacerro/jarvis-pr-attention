import copy
import unittest

from pr_attention.rereview_packet import rereview_packet_sha256
from pr_attention.rereview_result import validate_rereview_result
from test_rereview_bundle import REPAIRED_HEAD, pass_result, rereview_packet


def redigest(packet):
    packet["rereview_packet_sha256"] = rereview_packet_sha256(packet)
    return packet


def result_for(packet):
    result = pass_result(packet)
    result["rereview_packet_sha256"] = packet["rereview_packet_sha256"]
    return result


class RereviewPacketContractV11Tests(unittest.TestCase):
    def assert_invalid_after_redigest(self, mutate):
        packet = copy.deepcopy(rereview_packet())
        mutate(packet)
        redigest(packet)
        validation = validate_rereview_result(packet, result_for(packet), live_head_sha=REPAIRED_HEAD)
        self.assertFalse(validation.valid)
        self.assertEqual(validation.status, "INVALID")
        return validation

    def test_accepted_semantic_baseline_cannot_be_rewritten_with_a_fresh_digest(self):
        validation = self.assert_invalid_after_redigest(
            lambda packet: packet.__setitem__("accepted_semantic_baseline_sha", "e" * 40)
        )
        self.assertTrue(any("accepted semantic baseline" in reason for reason in validation.reasons))

    def test_lineage_generation_must_be_bounded_integer(self):
        validation = self.assert_invalid_after_redigest(
            lambda packet: packet.__setitem__("lineage_generation", "2")
        )
        self.assertTrue(any("lineage_generation" in reason for reason in validation.reasons))

    def test_failed_checkpoint_must_equal_previous_reviewed_head(self):
        validation = self.assert_invalid_after_redigest(
            lambda packet: packet.__setitem__("failed_reviewed_checkpoint_sha", "f" * 40)
        )
        self.assertTrue(any("failed reviewed checkpoint" in reason for reason in validation.reasons))

    def test_thread_byte_accounting_cannot_be_forged_with_a_fresh_digest(self):
        def mutate(packet):
            packet["review_threads"] = [
                {
                    "id": "T1",
                    "path": "a.py",
                    "author": "alice",
                    "body": "x",
                    "original_body_bytes": 1,
                    "included_body_bytes": 1,
                    "truncated": False,
                    "content_trust": "UNTRUSTED_REPOSITORY_CONTENT",
                }
            ]
            packet["included_thread_bytes"] = 0

        validation = self.assert_invalid_after_redigest(mutate)
        self.assertTrue(any("included_thread_bytes" in reason for reason in validation.reasons))

    def test_rereview_source_requires_latest_checkpoint_binding(self):
        def mutate(packet):
            packet["source_checkpoint_kind"] = "REREVIEW_FAIL"
            packet["latest_rereview_checkpoint_sha"] = "f" * 40

        validation = self.assert_invalid_after_redigest(mutate)
        self.assertTrue(any("latest_rereview_checkpoint_sha" in reason for reason in validation.reasons))


if __name__ == "__main__":
    unittest.main()
