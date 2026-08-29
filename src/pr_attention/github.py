from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

API_BASE = "https://api.github.com"
GRAPHQL_URL = "https://api.github.com/graphql"
API_VERSION = "2022-11-28"
MAX_PAGES = 20


class GitHubError(RuntimeError):
    pass


@dataclass
class GitHubClient:
    token: str
    timeout: int = 30

    @classmethod
    def from_env(cls) -> "GitHubClient":
        token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        if not token:
            raise GitHubError("GITHUB_TOKEN or GH_TOKEN is required")
        return cls(token=token)

    def _request(
        self,
        url: str,
        *,
        method: str = "GET",
        data: bytes | None = None,
        accept: str = "application/vnd.github+json",
    ) -> tuple[Any, dict[str, str]]:
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": accept,
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "jarvis-pr-attention/0.12",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
                parsed = json.loads(payload) if payload else None
                headers = {k.lower(): v for k, v in response.headers.items()}
                return parsed, headers
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise GitHubError(f"GitHub API {exc.code}: {body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise GitHubError(f"GitHub API transport error: {exc}") from exc

    def rest(self, path: str) -> Any:
        payload, _ = self._request(f"{API_BASE}{path}")
        return payload

    def rest_paginated(self, path: str, *, max_pages: int = MAX_PAGES) -> list[Any]:
        if max_pages < 1:
            raise ValueError("max_pages must be positive")
        results: list[Any] = []
        next_url: str | None = f"{API_BASE}{path}"
        pages = 0
        while next_url and pages < max_pages:
            payload, headers = self._request(next_url)
            if not isinstance(payload, list):
                raise GitHubError("paginated GitHub response was not a list")
            results.extend(payload)
            next_url = _next_link(headers.get("link"))
            pages += 1
        if next_url is not None:
            raise GitHubError("GitHub pagination safety ceiling exhausted before all pages were retrieved")
        return results

    def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
        payload, _ = self._request(GRAPHQL_URL, method="POST", data=body)
        if not isinstance(payload, dict):
            raise GitHubError("GraphQL response was not an object")
        if payload.get("errors"):
            raise GitHubError(f"GitHub GraphQL errors: {payload['errors']}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise GitHubError("GraphQL response did not include data")
        return data

    def pull_request(self, repo: str, number: int) -> dict[str, Any]:
        payload = self.rest(f"/repos/{repo}/pulls/{number}")
        if not isinstance(payload, dict):
            raise GitHubError("pull request response was not an object")
        return payload

    def branch(self, repo: str, branch: str) -> dict[str, Any]:
        quoted = urllib.parse.quote(branch, safe="")
        payload = self.rest(f"/repos/{repo}/branches/{quoted}")
        if not isinstance(payload, dict):
            raise GitHubError("branch response was not an object")
        return payload

    def branch_rules(self, repo: str, branch: str) -> list[dict[str, Any]]:
        quoted = urllib.parse.quote(branch, safe="")
        payload = self.rest_paginated(f"/repos/{repo}/rules/branches/{quoted}?per_page=100")
        if any(not isinstance(item, dict) for item in payload):
            raise GitHubError("branch rules response contained an invalid entry")
        return payload

    def review_policy(self, repo: str, number: int) -> dict[str, Any]:
        owner, name = repo.split("/", 1)
        query = """
        query PullRequestPolicy($owner: String!, $name: String!, $number: Int!) {
          repository(owner: $owner, name: $name) {
            pullRequest(number: $number) { isDraft reviewDecision }
          }
        }
        """
        data = self.graphql(query, {"owner": owner, "name": name, "number": number})
        pr = ((data.get("repository") or {}).get("pullRequest"))
        if not isinstance(pr, dict):
            raise GitHubError("GraphQL pull request policy response was unavailable")
        return pr

    def reviews(self, repo: str, number: int) -> list[dict[str, Any]]:
        return self.rest_paginated(f"/repos/{repo}/pulls/{number}/reviews?per_page=100")

    def check_runs(self, repo: str, head_sha: str) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        total_count: int | None = None
        for page in range(1, MAX_PAGES + 1):
            payload = self.rest(f"/repos/{repo}/commits/{head_sha}/check-runs?per_page=100&page={page}")
            if not isinstance(payload, dict):
                raise GitHubError("check-runs response was not an object")
            raw_total = payload.get("total_count")
            if isinstance(raw_total, int) and not isinstance(raw_total, bool) and raw_total >= 0:
                total_count = raw_total
            batch = list(payload.get("check_runs") or [])
            runs.extend(batch)
            if total_count is not None and len(runs) >= total_count:
                return runs
            if len(batch) < 100:
                return runs
        raise GitHubError("GitHub check-runs pagination safety ceiling exhausted before all pages were retrieved")

    def status_contexts(self, repo: str, head_sha: str) -> list[dict[str, Any]]:
        statuses: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            payload = self.rest(f"/repos/{repo}/commits/{head_sha}/status?per_page=100&page={page}")
            if not isinstance(payload, dict):
                raise GitHubError("combined status response was not an object")
            batch = list(payload.get("statuses") or [])
            statuses.extend(batch)
            if len(batch) < 100:
                return statuses
        raise GitHubError("GitHub status-context pagination safety ceiling exhausted before all pages were retrieved")

    def compare(self, repo: str, base_sha: str, head_sha: str) -> dict[str, Any]:
        base = urllib.parse.quote(base_sha, safe="")
        head = urllib.parse.quote(head_sha, safe="")
        payload = self.rest(f"/repos/{repo}/compare/{base}...{head}?per_page=100&page=1")
        if not isinstance(payload, dict):
            raise GitHubError("compare response was not an object")
        return payload

    def review_threads(self, repo: str, number: int) -> list[dict[str, Any]]:
        owner, name = repo.split("/", 1)
        query = """
        query ReviewThreads($owner: String!, $name: String!, $number: Int!, $after: String) {
          repository(owner: $owner, name: $name) {
            pullRequest(number: $number) {
              reviewThreads(first: 100, after: $after) {
                nodes {
                  id
                  isResolved
                  isOutdated
                  path
                  comments(first: 1) {
                    nodes { author { login } body }
                  }
                }
                pageInfo { hasNextPage endCursor }
              }
            }
          }
        }
        """
        nodes: list[dict[str, Any]] = []
        after: str | None = None
        has_next = False
        for _ in range(MAX_PAGES):
            data = self.graphql(query, {"owner": owner, "name": name, "number": number, "after": after})
            pr = (((data.get("repository") or {}).get("pullRequest")) or {})
            connection = pr.get("reviewThreads") or {}
            raw_nodes = connection.get("nodes") or []
            if not isinstance(raw_nodes, list):
                raise GitHubError("reviewThreads nodes were not a list")
            nodes.extend(raw_nodes)
            page_info = connection.get("pageInfo") or {}
            has_next = page_info.get("hasNextPage") is True
            if not has_next:
                return nodes
            after = page_info.get("endCursor")
            if not after:
                raise GitHubError("reviewThreads pagination reported next page without cursor")
        if has_next:
            raise GitHubError("GitHub review-thread pagination safety ceiling exhausted before all pages were retrieved")
        return nodes


def _next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        section = part.strip()
        if 'rel="next"' not in section:
            continue
        start = section.find("<")
        end = section.find(">")
        if start >= 0 and end > start:
            url = section[start + 1 : end]
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme == "https" and parsed.netloc == "api.github.com":
                return url
    return None
