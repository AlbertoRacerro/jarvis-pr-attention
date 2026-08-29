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
        author = comment.get("author")
        login = author.get("login") if isinstance(author, dict) else None
        body = comment.get("body")
        if not isinstance(body, str):
            raise GitHubError("review-thread comment body was not a string")
        if author is not None and (not isinstance(author, dict) or not isinstance(login, str) or not login):
            raise GitHubError("review-thread comment author was malformed")
        rendered.append(
            json.dumps(
                {"comment_index": index, "author": login, "body": body},
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    return "\n".join(rendered)


def collect_review_threads_v11(client: GitHubClient, repo: str, number: int) -> tuple[list[dict[str, Any]], bool]:
    """Return review-thread evidence without silently accepting partial GraphQL facts.

    Thread pagination is complete up to MAX_PAGES. Each thread carries up to
    100 comments. If GitHub reports more nested comments than that cap, the
    returned evidence is explicitly incomplete so callers cannot produce a
    COMPLETE incremental packet or semantic PASS from partial thread history.
    """

    if "/" not in repo or not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise GitHubError("invalid repository or pull-request identifier for review-thread collection")
    owner, name = repo.split("/", 1)
    if not owner or not name:
        raise GitHubError("invalid repository identifier for review-thread collection")

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
        if not isinstance(data, dict):
            raise GitHubError("reviewThreads GraphQL response was not an object")
        repository = data.get("repository")
        if not isinstance(repository, dict):
            raise GitHubError("reviewThreads GraphQL response omitted repository evidence")
        pr = repository.get("pullRequest")
        if not isinstance(pr, dict):
            raise GitHubError("reviewThreads GraphQL response omitted pull-request evidence")
        connection = pr.get("reviewThreads")
        if not isinstance(connection, dict):
            raise GitHubError("reviewThreads GraphQL response omitted thread connection evidence")
        raw_nodes = connection.get("nodes")
        if not isinstance(raw_nodes, list):
            raise GitHubError("reviewThreads nodes were not a list")

        for raw in raw_nodes:
            if not isinstance(raw, dict):
                raise GitHubError("reviewThreads contained an invalid thread node")
            thread_id = raw.get("id")
            path = raw.get("path")
            if not isinstance(thread_id, str) or not thread_id:
                raise GitHubError("review thread omitted a valid id")
            if not isinstance(path, str) or not path:
                raise GitHubError("review thread omitted a valid path")
            if not isinstance(raw.get("isResolved"), bool) or not isinstance(raw.get("isOutdated"), bool):
                raise GitHubError("review thread omitted resolved/outdated truth")

            comments_connection = raw.get("comments")
            if not isinstance(comments_connection, dict):
                raise GitHubError("review thread omitted comment connection evidence")
            comments = comments_connection.get("nodes")
            if not isinstance(comments, list) or not comments:
                raise GitHubError("review thread omitted its comment history")
            if any(not isinstance(comment, dict) for comment in comments):
                raise GitHubError("review-thread comments contained an invalid node")
            comments_page = comments_connection.get("pageInfo")
            if not isinstance(comments_page, dict) or not isinstance(comments_page.get("hasNextPage"), bool):
                raise GitHubError("review-thread comment pagination evidence was malformed")
            if comments_page["hasNextPage"] is True:
                comments_complete = False

            first_author = comments[0].get("author")
            first_login = first_author.get("login") if isinstance(first_author, dict) else None
            rendered_body = _render_thread_comments(comments)
            normalized = dict(raw)
            normalized["comments"] = {
                "nodes": [
                    {
                        "author": {"login": first_login} if isinstance(first_login, str) and first_login else None,
                        "body": rendered_body,
                    }
                ]
            }
            nodes.append(normalized)

        page_info = connection.get("pageInfo")
        if not isinstance(page_info, dict) or not isinstance(page_info.get("hasNextPage"), bool):
            raise GitHubError("reviewThreads pagination evidence was malformed")
        threads_have_next = page_info["hasNextPage"] is True
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
