from __future__ import annotations

from collections import OrderedDict
from typing import Any, Iterable

from .models import CheckSummary, ReviewSummary, ThreadSummary

_SUCCESS_CONCLUSIONS = {"success", "neutral", "skipped"}
_PENDING_STATUSES = {"queued", "in_progress", "pending", "requested", "waiting", "expected"}
_FAILURE_CONCLUSIONS = {
    "failure",
    "cancelled",
    "timed_out",
    "action_required",
    "startup_failure",
    "stale",
    "error",
}


def _unique(values: Iterable[str]) -> list[str]:
    return list(OrderedDict((v, None) for v in values if v).keys())


def normalize_checks(check_runs: list[dict[str, Any]], status_contexts: list[dict[str, Any]]) -> CheckSummary:
    passed: list[str] = []
    pending: list[str] = []
    failed: list[str] = []
    unknown: list[str] = []

    for run in check_runs:
        name = str(run.get("name") or "unnamed-check")
        status = str(run.get("status") or "").lower()
        conclusion = run.get("conclusion")
        conclusion_s = str(conclusion).lower() if conclusion is not None else ""

        if conclusion_s in _FAILURE_CONCLUSIONS:
            failed.append(name)
        elif status in _PENDING_STATUSES or (status != "completed" and not conclusion_s):
            pending.append(name)
        elif conclusion_s in _SUCCESS_CONCLUSIONS:
            passed.append(name)
        elif status == "completed" and not conclusion_s:
            unknown.append(name)
        else:
            unknown.append(name)

    for context in status_contexts:
        name = str(context.get("context") or "unnamed-status")
        state = str(context.get("state") or "").lower()
        if state == "success":
            passed.append(name)
        elif state in {"pending", "expected"}:
            pending.append(name)
        elif state in {"failure", "error"}:
            failed.append(name)
        else:
            unknown.append(name)

    passed = _unique(passed)
    pending = _unique(pending)
    failed = _unique(failed)
    unknown = _unique(unknown)
    total = len(set(passed + pending + failed + unknown))

    if failed:
        state = "FAILURE"
    elif unknown:
        state = "UNKNOWN"
    elif pending:
        state = "PENDING"
    elif total > 0:
        state = "SUCCESS"
    else:
        state = "UNKNOWN"

    return CheckSummary(state=state, total=total, passed=passed, pending=pending, failed=failed, unknown=unknown)


def normalize_reviews(reviews: list[dict[str, Any]], head_sha: str) -> ReviewSummary:
    latest_by_user: dict[str, dict[str, Any]] = {}
    stale_count = 0

    for review in reviews:
        user = ((review.get("user") or {}).get("login") or "").strip()
        state = str(review.get("state") or "").upper()
        if not user or state in {"PENDING", "DISMISSED"}:
            continue
        latest_by_user[user] = review

    approvals: list[str] = []
    changes: list[str] = []
    commented: list[str] = []

    for user, review in latest_by_user.items():
        state = str(review.get("state") or "").upper()
        commit_id = str(review.get("commit_id") or "")
        if commit_id != head_sha:
            stale_count += 1
            continue
        if state == "APPROVED":
            approvals.append(user)
        elif state == "CHANGES_REQUESTED":
            changes.append(user)
        elif state == "COMMENTED":
            commented.append(user)

    if changes and approvals:
        state = "MIXED"
    elif changes:
        state = "CHANGES_REQUESTED"
    elif approvals:
        state = "APPROVED"
    elif stale_count:
        state = "STALE_ONLY"
    else:
        state = "NONE"

    return ReviewSummary(
        state=state,
        current_head_approvals=sorted(approvals),
        current_head_changes_requested=sorted(changes),
        current_head_commented=sorted(commented),
        stale_review_count=stale_count,
    )


def normalize_threads(nodes: list[dict[str, Any]]) -> ThreadSummary:
    unresolved_current_items: list[dict[str, Any]] = []
    unresolved_current = 0
    unresolved_outdated = 0
    resolved = 0

    for node in nodes:
        if node.get("isResolved") is True:
            resolved += 1
            continue
        if node.get("isOutdated") is True:
            unresolved_outdated += 1
            continue

        unresolved_current += 1
        comments = ((node.get("comments") or {}).get("nodes") or [])
        first = comments[0] if comments else {}
        author = ((first.get("author") or {}).get("login") or "unknown")
        unresolved_current_items.append(
            {
                "path": node.get("path"),
                "author": author,
                "body": first.get("body") or "",
                "thread_id": node.get("id"),
            }
        )

    return ThreadSummary(
        total=len(nodes),
        unresolved_current=unresolved_current,
        unresolved_outdated=unresolved_outdated,
        resolved=resolved,
        unresolved_current_items=unresolved_current_items,
    )
