from __future__ import annotations

from collections import OrderedDict
from typing import Any, Iterable

from .models import CheckSummary, DeltaFile, DeltaSummary, ReviewSummary, ThreadSummary

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
    dismissed_count = 0

    for review in reviews:
        user = ((review.get("user") or {}).get("login") or "").strip()
        state = str(review.get("state") or "").upper()
        if not user or state == "PENDING":
            continue
        latest_by_user[user] = review

    approvals: list[str] = []
    changes: list[str] = []
    commented: list[str] = []

    for user, review in latest_by_user.items():
        state = str(review.get("state") or "").upper()
        commit_id = str(review.get("commit_id") or "")
        if state == "DISMISSED":
            dismissed_count += 1
            continue
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
        dismissed_review_count=dismissed_count,
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


def normalize_delta(
    accepted_head_sha: str | None,
    head_sha: str,
    compare_payload: dict[str, Any] | None,
) -> DeltaSummary:
    if not accepted_head_sha:
        return DeltaSummary(
            accepted_head_sha=None,
            relation="ABSENT",
            acceptance_validity="ABSENT",
            review_scope="FULL",
            complete=True,
            reasons=["no previously accepted semantic head was supplied"],
        )

    if accepted_head_sha == head_sha:
        return DeltaSummary(
            accepted_head_sha=accepted_head_sha,
            relation="CURRENT",
            acceptance_validity="CURRENT",
            review_scope="NONE",
            complete=True,
            reasons=["previously accepted semantic head is the current head"],
        )

    if not isinstance(compare_payload, dict):
        return DeltaSummary(
            accepted_head_sha=accepted_head_sha,
            relation="UNKNOWN",
            acceptance_validity="UNKNOWN",
            review_scope="UNKNOWN",
            complete=False,
            reasons=["GitHub compare evidence could not be retrieved"],
        )

    status = str(compare_payload.get("status") or "").lower()
    raw_files = compare_payload.get("files")
    files_available = isinstance(raw_files, list)
    raw_files = raw_files if files_available else []
    files = [
        DeltaFile(
            path=str(item.get("filename") or ""),
            status=str(item.get("status") or "unknown"),
            additions=int(item.get("additions") or 0),
            deletions=int(item.get("deletions") or 0),
            changes=int(item.get("changes") or 0),
            previous_path=(str(item.get("previous_filename")) if item.get("previous_filename") else None),
        )
        for item in raw_files
        if item.get("filename")
    ]
    complete = files_available and len(raw_files) < 300
    additions = sum(item.additions for item in files)
    deletions = sum(item.deletions for item in files)
    common = dict(
        accepted_head_sha=accepted_head_sha,
        commits_ahead=_optional_int(compare_payload.get("ahead_by")),
        commits_behind=_optional_int(compare_payload.get("behind_by")),
        additions=additions,
        deletions=deletions,
        changed_files=len(files),
        files=files,
    )

    if status == "identical":
        return DeltaSummary(
            relation="CURRENT",
            acceptance_validity="CURRENT",
            review_scope="NONE",
            complete=True,
            reasons=["GitHub reports no delta from the accepted head"],
            **common,
        )

    if status == "ahead":
        if not complete:
            return DeltaSummary(
                relation="AHEAD",
                acceptance_validity="REUSABLE_FOR_UNCHANGED",
                review_scope="FULL",
                complete=False,
                reasons=["accepted head is an ancestor, but GitHub delta file evidence is incomplete; full review is required"],
                **common,
            )
        if not files:
            return DeltaSummary(
                relation="AHEAD",
                acceptance_validity="REUSABLE_FOR_UNCHANGED",
                review_scope="NONE",
                complete=True,
                reasons=["accepted head is an ancestor and the newer commits do not change file content"],
                **common,
            )
        return DeltaSummary(
            relation="AHEAD",
            acceptance_validity="REUSABLE_FOR_UNCHANGED",
            review_scope="DELTA",
            complete=True,
            reasons=["accepted head is an ancestor; unchanged evidence remains reusable and only the delta needs semantic review"],
            **common,
        )

    if status == "behind":
        return DeltaSummary(
            relation="BEHIND",
            acceptance_validity="INVALID",
            review_scope="FULL",
            complete=complete,
            reasons=["current head is behind the supplied accepted head; prior semantic acceptance cannot authorize this state"],
            **common,
        )

    if status == "diverged":
        return DeltaSummary(
            relation="DIVERGED",
            acceptance_validity="INVALID",
            review_scope="FULL",
            complete=complete,
            reasons=["current head diverged from the supplied accepted head; full semantic review is required"],
            **common,
        )

    return DeltaSummary(
        relation="UNKNOWN",
        acceptance_validity="UNKNOWN",
        review_scope="UNKNOWN",
        complete=False,
        reasons=[f"unrecognized GitHub compare status: {status or 'missing'}"],
        **common,
    )


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
