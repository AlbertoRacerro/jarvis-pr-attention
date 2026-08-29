from __future__ import annotations

from .models import AttentionState, CheckSummary, MergeSummary, ReviewSummary, ThreadSummary


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

    if reviews.current_head_changes_requested:
        blockers.append("current-head review requests changes")

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
