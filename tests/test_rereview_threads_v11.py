import json
import unittest

from pr_attention.github import GitHubError
from pr_attention.rereview_threads_v11 import collect_review_threads_v11


class FakeGitHubClient:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def graphql(self, query, variables):
        self.calls.append((query, variables))
        if not self.payloads:
            raise AssertionError("unexpected GraphQL call")
        return self.payloads.pop(0)


def payload(*, comments, comments_have_next=False, threads_have_next=False, cursor=None):
    return {
        "repository": {
            "pullRequest": {
                "reviewThreads": {
                    "nodes": [
                        {
                            "id": "T1",
                            "isResolved": False,
                            "isOutdated": False,
                            "path": "src/a.py",
                            "comments": {
                                "nodes": comments,
                                "pageInfo": {
                                    "hasNextPage": comments_have_next,
                                    "endCursor": "comment-cursor" if comments_have_next else None,
                                },
                            },
                        }
                    ],
                    "pageInfo": {
                        "hasNextPage": threads_have_next,
                        "endCursor": cursor,
                    },
                }
            }
        }
    }


class ReviewThreadTransportV11Tests(unittest.TestCase):
    def test_all_returned_thread_comments_are_preserved_as_untrusted_evidence_text(self):
        client = FakeGitHubClient(
            [
                payload(
                    comments=[
                        {"author": {"login": "alice"}, "body": "initial blocker"},
                        {"author": {"login": "bob"}, "body": "repair does not address edge case"},
                    ]
                )
            ]
        )
        threads, complete = collect_review_threads_v11(client, "o/r", 7)

        self.assertTrue(complete)
        self.assertEqual(len(threads), 1)
        body = threads[0]["comments"]["nodes"][0]["body"]
        rendered = [json.loads(line) for line in body.splitlines()]
        self.assertEqual([item["author"] for item in rendered], ["alice", "bob"])
        self.assertEqual(
            [item["body"] for item in rendered],
            ["initial blocker", "repair does not address edge case"],
        )

    def test_nested_comment_pagination_ceiling_fails_closed(self):
        client = FakeGitHubClient(
            [
                payload(
                    comments=[{"author": {"login": "alice"}, "body": "first 100 are not enough"}],
                    comments_have_next=True,
                )
            ]
        )
        threads, complete = collect_review_threads_v11(client, "o/r", 7)

        self.assertFalse(complete)
        self.assertEqual(len(threads), 1)

    def test_review_thread_connection_is_paginated(self):
        client = FakeGitHubClient(
            [
                payload(
                    comments=[{"author": {"login": "alice"}, "body": "page one"}],
                    threads_have_next=True,
                    cursor="thread-cursor",
                ),
                payload(comments=[{"author": {"login": "bob"}, "body": "page two"}]),
            ]
        )
        threads, complete = collect_review_threads_v11(client, "o/r", 7)

        self.assertTrue(complete)
        self.assertEqual(len(threads), 2)
        self.assertEqual(client.calls[1][1]["after"], "thread-cursor")

    def test_missing_pull_request_truth_is_not_treated_as_zero_threads(self):
        client = FakeGitHubClient([{"repository": {"pullRequest": None}}])
        with self.assertRaises(GitHubError):
            collect_review_threads_v11(client, "o/r", 7)

    def test_thread_without_comment_history_is_malformed_evidence(self):
        client = FakeGitHubClient([payload(comments=[])])
        with self.assertRaises(GitHubError):
            collect_review_threads_v11(client, "o/r", 7)


if __name__ == "__main__":
    unittest.main()
