import unittest

import pr_attention
from pr_attention.models import (
    CheckSummary,
    DeltaSummary,
    MergeSummary,
    ReviewSummary,
    ScopeSummary,
    Snapshot,
    ThreadSummary,
)
from pr_attention.packet import CONTENT_TRUST, build_review_packet, collect_review_packet

BASE = "a" * 40
HEAD = "b" * 40


def snapshot(scope="DELTA", *, complete=True, relation="AHEAD"):
    return Snapshot(
        schema_version=2,
        repository="o/r",
        pr_number=1,
        title="x",
        base_ref="main",
        head_ref="feature",
        head_sha=HEAD,
        final_head_sha=HEAD,
        generated_at="now",
        scope=ScopeSummary(1, 0, 1),
        checks=CheckSummary(state="SUCCESS", total=1, passed=["test"]),
        reviews=ReviewSummary(state="NONE"),
        threads=ThreadSummary(),
        merge=MergeSummary(True, "clean", False),
        delta=DeltaSummary(
            accepted_head_sha=BASE,
            relation=relation,
            acceptance_validity="REUSABLE_FOR_UNCHANGED" if relation == "AHEAD" else "CURRENT",
            review_scope=scope,
            complete=complete,
        ),
        attention="READY",
        next_action_class="REVIEW_DELTA" if scope == "DELTA" else ("MERGE_CANDIDATE" if scope == "NONE" else "FULL_REVIEW"),
        blockers=[],
        pending_reasons=[],
        facts_complete=True,
        stale=False,
    )


def compare(patches):
    return {
        "status": "ahead",
        "files": [
            {
                "filename": path,
                "status": "modified",
                "additions": 1,
                "deletions": 0,
                "changes": 1,
                **({"patch": patch} if patch is not None else {}),
            }
            for path, patch in patches
        ],
    }


class PacketTests(unittest.TestCase):
    def test_public_packet_export(self):
        self.assertIs(pr_attention.collect_review_packet, collect_review_packet)

    def test_complete_packet_contains_all_patches(self):
        packet = build_review_packet(snapshot(), compare([("b.py", "+b"), ("a.py", "+a")]))
        self.assertTrue(packet.complete)
        self.assertEqual(packet.coverage, "COMPLETE")
        self.assertEqual([item.path for item in packet.files], ["a.py", "b.py"])
        self.assertEqual(packet.content_trust, CONTENT_TRUST)

    def test_missing_patch_is_partial(self):
        packet = build_review_packet(snapshot(), compare([("a.py", "+a"), ("blob.bin", None)]))
        self.assertFalse(packet.complete)
        self.assertEqual(packet.coverage, "PARTIAL")
        self.assertEqual(packet.files[1].omission_reason, "patch-unavailable")

    def test_file_budget_truncates_utf8_safely(self):
        packet = build_review_packet(snapshot(), compare([("a.py", "é" * 20)]), max_total_patch_bytes=100, max_file_patch_bytes=11)
        self.assertEqual(packet.coverage, "PARTIAL")
        self.assertLessEqual(packet.files[0].included_patch_bytes, 11)
        self.assertEqual(packet.files[0].patch.encode("utf-8").decode("utf-8"), packet.files[0].patch)

    def test_total_budget_never_exceeded(self):
        packet = build_review_packet(
            snapshot(),
            compare([("a.py", "a" * 10), ("b.py", "b" * 10)]),
            max_total_patch_bytes=12,
            max_file_patch_bytes=10,
        )
        self.assertLessEqual(packet.included_patch_bytes, 12)
        self.assertEqual(packet.coverage, "PARTIAL")

    def test_none_scope_is_complete_empty_packet(self):
        packet = build_review_packet(snapshot("NONE", relation="CURRENT"), None)
        self.assertEqual((packet.coverage, packet.complete, packet.files), ("COMPLETE", True, []))

    def test_full_scope_refuses_delta_packet(self):
        packet = build_review_packet(snapshot("FULL"), None)
        self.assertEqual((packet.coverage, packet.complete), ("NONE", False))

    def test_head_move_invalidates_packet(self):
        packet = build_review_packet(snapshot(), compare([("a.py", "+a")]), final_head_sha="c" * 40)
        self.assertEqual((packet.coverage, packet.attention, packet.next_action_class), ("UNKNOWN", "STALE", "REFRESH_SNAPSHOT"))

    def test_invalid_budget_rejected(self):
        with self.assertRaises(ValueError):
            build_review_packet(snapshot(), compare([]), max_total_patch_bytes=0)


class FakeClient:
    def __init__(self, final_packet_head=HEAD):
        self.pr_calls = 0
        self.final_packet_head = final_packet_head

    def pull_request(self, repo, number):
        self.pr_calls += 1
        sha = HEAD if self.pr_calls < 3 else self.final_packet_head
        return {
            "title": "x",
            "head": {"sha": sha, "ref": "feature"},
            "base": {"ref": "main"},
            "mergeable": True,
            "mergeable_state": "clean",
            "additions": 1,
            "deletions": 0,
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
            "status": "ahead",
            "ahead_by": 1,
            "behind_by": 0,
            "files": [
                {
                    "filename": "a.py",
                    "status": "modified",
                    "additions": 1,
                    "deletions": 0,
                    "changes": 1,
                    "patch": "+x",
                }
            ],
        }


class CollectPacketTests(unittest.TestCase):
    def test_collect_packet_is_complete(self):
        packet = collect_review_packet(FakeClient(), "o/r", 1, BASE)
        self.assertEqual((packet.coverage, packet.head_sha, packet.final_head_sha), ("COMPLETE", HEAD, HEAD))

    def test_collect_packet_detects_late_head_race(self):
        packet = collect_review_packet(FakeClient(final_packet_head="c" * 40), "o/r", 1, BASE)
        self.assertEqual((packet.coverage, packet.next_action_class), ("UNKNOWN", "REFRESH_SNAPSHOT"))


if __name__ == "__main__":
    unittest.main()
