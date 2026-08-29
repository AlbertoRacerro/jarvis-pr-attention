from __future__ import annotations

from typing import Any

from .rereview_packet_v11 import (
    CONTENT_TRUST,
    DEFAULT_MAX_FILE_PATCH_BYTES,
    DEFAULT_MAX_THREAD_BODY_BYTES,
    DEFAULT_MAX_TOTAL_PATCH_BYTES,
    DEFAULT_MAX_TOTAL_THREAD_BYTES,
    MAX_PACKET_BUDGET,
    MAX_REREVIEW_GENERATIONS,
    REREVIEW_PACKET_KIND,
    REREVIEW_PACKET_SCHEMA_VERSION,
    build_rereview_packet as _build_rereview_packet,
    failed_checkpoint,
    rereview_packet_sha256,
)
from .rereview_threads_v11 import collect_rereview_packet


def _validate_direct_thread_payload(review_threads_payload: list[dict[str, Any]] | None) -> None:
    if review_threads_payload is None:
        return
    if not isinstance(review_threads_payload, list):
        raise ValueError("review_threads_payload must be a list when supplied")
    for item in review_threads_payload:
        if not isinstance(item, dict):
            raise ValueError("review_threads_payload contains an invalid thread entry")
        if not isinstance(item.get("id"), str) or not item["id"]:
            raise ValueError("review_threads_payload thread id must be a non-empty string")
        if not isinstance(item.get("path"), str) or not item["path"]:
            raise ValueError("review_threads_payload thread path must be a non-empty string")
        if not isinstance(item.get("isResolved"), bool) or not isinstance(item.get("isOutdated"), bool):
            raise ValueError("review_threads_payload must include boolean isResolved/isOutdated truth")
        comments = item.get("comments")
        if not isinstance(comments, dict):
            raise ValueError("review_threads_payload thread comments must be an object")
        nodes = comments.get("nodes")
        if not isinstance(nodes, list) or len(nodes) != 1 or not isinstance(nodes[0], dict):
            raise ValueError("direct review_threads_payload must contain exactly one normalized comment-evidence node")
        body = nodes[0].get("body")
        author = nodes[0].get("author")
        if not isinstance(body, str):
            raise ValueError("review_threads_payload normalized comment body must be a string")
        if author is not None:
            login = author.get("login") if isinstance(author, dict) else None
            if not isinstance(login, str) or not login:
                raise ValueError("review_threads_payload normalized comment author is malformed")


def build_rereview_packet(
    previous_bundle: dict[str, Any],
    compare_payload: dict[str, Any] | None,
    *,
    current_head_sha: str,
    final_head_sha: str | None = None,
    expected_head_sha: str | None = None,
    max_total_patch_bytes: int = DEFAULT_MAX_TOTAL_PATCH_BYTES,
    max_file_patch_bytes: int = DEFAULT_MAX_FILE_PATCH_BYTES,
    review_threads_payload: list[dict[str, Any]] | None = None,
    review_threads_complete: bool = True,
    max_total_thread_bytes: int = DEFAULT_MAX_TOTAL_THREAD_BYTES,
    max_thread_body_bytes: int = DEFAULT_MAX_THREAD_BODY_BYTES,
) -> dict[str, Any]:
    _validate_direct_thread_payload(review_threads_payload)
    return _build_rereview_packet(
        previous_bundle,
        compare_payload,
        current_head_sha=current_head_sha,
        final_head_sha=final_head_sha,
        expected_head_sha=expected_head_sha,
        max_total_patch_bytes=max_total_patch_bytes,
        max_file_patch_bytes=max_file_patch_bytes,
        review_threads_payload=review_threads_payload,
        review_threads_complete=review_threads_complete,
        max_total_thread_bytes=max_total_thread_bytes,
        max_thread_body_bytes=max_thread_body_bytes,
    )


__all__ = [
    "CONTENT_TRUST",
    "DEFAULT_MAX_FILE_PATCH_BYTES",
    "DEFAULT_MAX_THREAD_BODY_BYTES",
    "DEFAULT_MAX_TOTAL_PATCH_BYTES",
    "DEFAULT_MAX_TOTAL_THREAD_BYTES",
    "MAX_PACKET_BUDGET",
    "MAX_REREVIEW_GENERATIONS",
    "REREVIEW_PACKET_KIND",
    "REREVIEW_PACKET_SCHEMA_VERSION",
    "build_rereview_packet",
    "collect_rereview_packet",
    "failed_checkpoint",
    "rereview_packet_sha256",
]
