import unittest

from pr_attention.rereview_packet import build_rereview_packet
from test_rereview_bundle import REPAIRED_HEAD, source_fail_bundle


COMPARE = {
    "status": "ahead",
    "files": [{"filename": "a.py", "status": "modified", "patch": "@@\n-bad\n+fixed\n"}],
}


class DirectRereviewThreadInputV11Tests(unittest.TestCase):
    def test_missing_thread_state_truth_is_rejected(self):
        with self.assertRaises(ValueError):
            build_rereview_packet(
                source_fail_bundle(),
                COMPARE,
                current_head_sha=REPAIRED_HEAD,
                review_threads_payload=[
                    {
                        "id": "T1",
                        "path": "a.py",
                        "comments": {"nodes": [{"author": {"login": "alice"}, "body": "blocker"}]},
                    }
                ],
            )

    def test_unbounded_raw_comment_list_is_rejected_at_direct_builder_boundary(self):
        with self.assertRaises(ValueError):
            build_rereview_packet(
                source_fail_bundle(),
                COMPARE,
                current_head_sha=REPAIRED_HEAD,
                review_threads_payload=[
                    {
                        "id": "T1",
                        "path": "a.py",
                        "isResolved": False,
                        "isOutdated": False,
                        "comments": {
                            "nodes": [
                                {"author": {"login": "alice"}, "body": "one"},
                                {"author": {"login": "bob"}, "body": "two"},
                            ]
                        },
                    }
                ],
            )


if __name__ == "__main__":
    unittest.main()
