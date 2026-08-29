from __future__ import annotations

from .models import (
    AttentionState,
    CheckSummary,
    DeltaSummary,
    MergeSummary,
    NextActionClass,
    ReviewSummary,
    ThreadSummary,
)


def classify_attention(
    *,
    initial_head_sha: str,
    final_head_sha: str,
    checks: CheckSummary,
    reviews: ReviewSummary,
    threads: ThreadSummary,
    merge: MergeSummary,
    facts_complete: bool,
) -> tuple[AttentionState, list[str], list[str]]:
    blockers: list[str] = []
    pending: list[str] = []

    if initial_head_sha != final_head_sha:
        return "STALE", ["pull request head changed while snapshot was collected"], []

    if not facts_complete:
        return "UNKNOWN", ["one or more required GitHub facts could not be retrieved"], []

    if checks.state == "FAILURE":
        blockers.append("CI has failing checks")
    elif checks.state == "PENDING":
        pending.append("CI is still running")
    elif checks.state == "UNKNOWN":
        pending.append("CI state is unknown or no CI evidence exists")

    required = checks.required
    if required.known:
        if required.state == "FAILURE":
            blockers.append("required GitHub checks are failing")
        elif required.state == "PENDING":
            pending.append("required GitHub checks are pending or missing")
        elif required.state == "UNKNOWN":
            return "UNKNOWN", ["required GitHub check state is ambiguous"], pending

    if reviews.current_head_changes_requested:
        blockers.append("current-head review requests changes")

    native = reviews.native_policy
    if native.known:
        if native.draft is True:
            blockers.append("pull request is draft")
        if native.review_decision == "CHANGES_REQUESTED":
            blockers.append("GitHub native review decision requests changes")
        elif native.review_decision == "REVIEW_REQUIRED":
            pending.append("GitHub native review policy still requires review")

    if threads.unresolved_current:
        blockers.append(f"{threads.unresolved_current} unresolved current review thread(s)")

    if merge.conflict is True:
        blockers.append("pull request has merge conflicts")
    elif merge.mergeable is None:
        pending.append("GitHub mergeability is not yet known")

    if blockers:
        return "BLOCKED", blockers, pending
    if pending:
        return "PENDING", [], pending
    return "READY", [], []


def classify_next_action(attention: AttentionState, delta: DeltaSummary) -> NextActionClass:
    if attention == "STALE":
        return "REFRESH_SNAPSHOT"
    if attention == "UNKNOWN":
        return "INVESTIGATE_UNKNOWN"
    if attention == "BLOCKED":
        return "REPAIR"
    if attention == "PENDING":
        return "WAIT_FOR_GATES"

    if delta.review_scope == "NONE":
        return "MERGE_CANDIDATE"
    if delta.review_scope == "DELTA":
        return "REVIEW_DELTA"
    if delta.review_scope == "FULL":
        return "FULL_REVIEW"
    return "INVESTIGATE_UNKNOWN"
