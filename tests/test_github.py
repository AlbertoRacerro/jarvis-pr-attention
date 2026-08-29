import unittest

from pr_attention.github import GitHubClient, GitHubError, MAX_PAGES


class RecordingClient(GitHubClient):
    def __init__(self):
        super().__init__(token="x")
        self.paths = []

    def rest(self, path):
        self.paths.append(path)
        if "/compare/" in path:
            return {"status": "ahead", "files": []}
        if "/status?" in path:
            page = int(path.rsplit("page=", 1)[1])
            count = 100 if page == 1 else 1
            return {"statuses": [{"context": f"c-{page}-{i}"} for i in range(count)]}
        raise AssertionError(path)


class EndlessRestPaginationClient(GitHubClient):
    def __init__(self):
        super().__init__(token="x")

    def _request(self, url, **kwargs):
        return [{"id": 1}], {"link": '<https://api.github.com/next>; rel="next"'}


class EndlessStatusClient(GitHubClient):
    def __init__(self):
        super().__init__(token="x")

    def rest(self, path):
        if "/status?" in path:
            return {"statuses": [{"context": f"c-{i}"} for i in range(100)]}
        raise AssertionError(path)


class EndlessCheckRunClient(GitHubClient):
    def __init__(self):
        super().__init__(token="x")

    def rest(self, path):
        if "/check-runs?" in path:
            return {"check_runs": [{"name": f"c-{i}"} for i in range(100)]}
        raise AssertionError(path)


class EndlessThreadClient(GitHubClient):
    def __init__(self):
        super().__init__(token="x")
        self.calls = 0

    def graphql(self, query, variables):
        self.calls += 1
        return {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [],
                        "pageInfo": {"hasNextPage": True, "endCursor": f"cursor-{self.calls}"},
                    }
                }
            }
        }


class GitHubClientTests(unittest.TestCase):
    def test_compare_uses_exact_base_and_head(self):
        c = RecordingClient()
        base = "a" * 40
        head = "b" * 40
        payload = c.compare("o/r", base, head)
        self.assertEqual(payload["status"], "ahead")
        self.assertIn(f"/compare/{base}...{head}", c.paths[0])

    def test_status_contexts_paginate(self):
        c = RecordingClient()
        statuses = c.status_contexts("o/r", "b" * 40)
        self.assertEqual(len(statuses), 101)
        self.assertEqual(len(c.paths), 2)

    def test_rest_pagination_ceiling_fails_closed(self):
        with self.assertRaisesRegex(GitHubError, "pagination safety ceiling"):
            EndlessRestPaginationClient().rest_paginated("/repos/o/r/pulls/1/reviews?per_page=100", max_pages=1)

    def test_status_pagination_ceiling_fails_closed(self):
        with self.assertRaisesRegex(GitHubError, "status-context pagination safety ceiling"):
            EndlessStatusClient().status_contexts("o/r", "b" * 40)

    def test_check_run_pagination_ceiling_fails_closed(self):
        with self.assertRaisesRegex(GitHubError, "check-runs pagination safety ceiling"):
            EndlessCheckRunClient().check_runs("o/r", "b" * 40)

    def test_review_thread_pagination_ceiling_fails_closed(self):
        client = EndlessThreadClient()
        with self.assertRaisesRegex(GitHubError, "review-thread pagination safety ceiling"):
            client.review_threads("o/r", 1)
        self.assertEqual(client.calls, MAX_PAGES)


if __name__ == "__main__":
    unittest.main()
