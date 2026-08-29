from __future__ import annotations

import json
from typing import Any

from .github import GitHubClient, GitHubError, MAX_PAGES
from .rereview_packet_v11 import (
    DEFAULT_MAX_FILE_PATCH_BYTES,
    DEFAULT_MAX_THREAD_BODY_BYTES,
    DEFAULT_MAX_TOTAL_PATCH_BYTES,
    DEFAULT_MAX_TOTAL_THREAD_BYTES,
    _valid_sha,
    build_rereview_packet,
    failed_checkpoint,
)


def _render_thread_comments(comments: list[dict[str, Any]]) -> str:
    rendered: list[str] = []
    for index, comment in enumerate(comments, start=1):
        author = ((comment.get("author") or {}).get("login")) if isinstance(comment.get("author"), dict) else None
        body = comment.get("body") if isinstance(comment.get("body"), str) else ""
        rendered.append(
            json.dumps(
                {"comment_index": index, "author": author if isinstance(author, str) else None, "body": body},
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    return "\n".join(rendered)


def collect_review_threads_v11(client: GitHubClient, repo: str, number: int) -> tuple[list[dict[str, Any]], bool]:
    """Return all current thread comments up to GitHub's nested 100-comment cap.

    Thread pagination is complete up to MAX_PAGES. A thread with more than 100
    comments is returned with its first 100 comments but marks the overall
    collection incomplete, so the caller cannot produce a COMPLETE re-review
    packet or a semantic PASS from partial thread evidence.
    """

    owner, name = repo.split("/", 1)
    query = """
    query ReviewThreadsV11($owner: String!, $name: String!, $number: Int!, $after: String) {
      repository(owner: $owner, name: $name) {
        pullRequest(number: $number) {
          reviewThreads(first: 100, after: $after) {
            nodes {
              id
              isResolved
              isOutdated
              path
              comments(first: 100) {
                nodes { author { login } body }
                pageInfo { hasNextPage endCursor }
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
    threads_have_next = False
    comments_complete = True

    for _ in range(MAX_PAGES):
        data = client.graphql(query, {"owner": owner, "name": name, "number": number, "after": after})
        pr = (((data.get("repository") or {}).get("pullRequest")) or {})
        connection = pr.get("reviewThreads") or {}
        raw_nodes = connection.get("nodes") or []
        if not isinstance(raw_nodes, list):
            raise GitHubError("reviewThreads nodes were not a list")

        for raw in raw_nodes:
            if not isinstance(raw, dict):
                raise GitHubError("reviewThreads contained an invalid thread node")
            comments_connection = raw.get("comments") or {}
            comments = comments_connection.get("nodes") or []
            if not isinstance(comments, list):
                raise GitHubError("review-thread comments nodes were not a list")
            if any(not isinstance(comment, dict) for comment in comments):
                raise GitHubError("review-thread comments contained an invalid node")
            comments_page = comments_connection.get("pageInfo") or {}
            if comments_page.get("hasNextPage") is True:
                comments_complete = False

            normalized = dict(raw)
            first_author = None
            if comments:
                author = comments[0].get("author")
                if isinstance(author, dict) and isinstance(author.get("login"), str):
                    first_author = author["login"]
            normalized["comments"] = {
                "nodes": [
                    {
                        "author": {"login": first_author} if first_author else None,
                        "body": _render_thread_comments(comments),
                    }
                ]
            }
            nodes.append(normalized)

        page_info = connection.get("pageInfo") or {}
        threads_have_next = page_info.get("hasNextPage") is True
        if not threads_have_next:
            return nodes, comments_complete
        after = page_info.get("endCursor")
        if not isinstance(after, str) or not after:
            raise GitHubError("reviewThreads pagination reported next page without cursor")

    if threads_have_next:
        raise GitHubError("GitHub review-thread pagination safety ceiling exhausted before all pages were retrieved")
    return nodes, comments_complete


def collect_rereview_packet(
    client: GitHubClient,
    repo: str,
    number: int,
    previous_bundle: dict[str, Any],
    *,
    expected_head_sha: str | None = None,
    max_total_patch_bytes: int = DEFAULT_MAX_TOTAL_PATCH_BYTES,
    max_file_patch_bytes: int = DEFAULT_MAX_FILE_PATCH_BYTES,
    max_total_thread_bytes: int = DEFAULT_MAX_TOTAL_THREAD_BYTES,
    max_thread_body_bytes: int = DEFAULT_MAX_THREAD_BODY_BYTES,
) -> dict[str, Any]:
    checkpoint = failed_checkpoint(previous_bundle)
    if checkpoint["repository"] != repo or checkpoint["pr_number"] != number:
        raise ValueError("previous evidence bundle repository/PR does not match requested pull request")

    initial_pr = client.pull_request(repo, number)
    current_head = str(((initial_pr.get("head") or {}).get("sha") or ""))
    if not _valid_sha(current_head):
        raise GitHubError("GitHub pull request did not expose a valid current head SHA")

    compare_payload: dict[str, Any] | None = None
    if current_head != checkpoint["previous_reviewed_head_sha"]:
        try:
            compare_payload = client.compare(repo, checkpoint["previous_reviewed_head_sha"], current_head)
        except GitHubError:
            compare_payload = None

    review_threads_payload: list[dict[str, Any]] | None = None
    review_threads_complete = True
    try:
        review_threads_payload, review_threads_complete = collect_review_threads_v11(client, repo, number)
    except GitHubError:
        review_threads_complete = False

    final_pr = client.pull_request(repo, number)
    final_head = str(((final_pr.get("head") or {}).get("sha") or "")) or current_head
    return build_rereview_packet(
        previous_bundle,
        compare_payload,
        current_head_sha=current_head,
        final_head_sha=final_head,
        expected_head_sha=expected_head_sha,
        max_total_patch_bytes=max_total_patch_bytes,
        max_file_patch_bytes=max_file_patch_bytes,
        review_threads_payload=review_threads_payload,
        review_threads_complete=review_threads_complete,
        max_total_thread_bytes=max_total_thread_bytes,
        max_thread_body_bytes=max_thread_body_bytes,
    )
