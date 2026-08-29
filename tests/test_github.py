import unittest

from pr_attention.github import GitHubClient


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


if __name__ == "__main__":
    unittest.main()
