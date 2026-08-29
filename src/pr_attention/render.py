from __future__ import annotations

from .models import Snapshot


def render_text(snapshot: Snapshot) -> str:
    checks = snapshot.checks
    reviews = snapshot.reviews
    threads = snapshot.threads
    merge = snapshot.merge
    delta = snapshot.delta

    accepted = delta.accepted_head_sha[:12] if delta.accepted_head_sha else "none"
    lines = [
        f"PR #{snapshot.pr_number} — ATTENTION",
        "",
        f"HEAD        {snapshot.head_sha[:12]} {'CURRENT' if not snapshot.stale else 'STALE'}",
        f"CI          {checks.state} ({len(checks.passed)} passed / {len(checks.pending)} pending / {len(checks.failed)} failed / {len(checks.unknown)} unknown)",
        f"REVIEW      {reviews.state} ({len(reviews.current_head_approvals)} current approval(s), {reviews.stale_review_count} stale review(s))",
        f"THREADS     {threads.unresolved_current} current unresolved / {threads.unresolved_outdated} outdated unresolved / {threads.resolved} resolved",
        f"MERGE       {'CONFLICT' if merge.conflict else ('MERGEABLE' if merge.mergeable else 'UNKNOWN')}",
        f"ACCEPTED    {accepted} ({delta.acceptance_validity})",
        f"DELTA       {delta.relation} / {delta.review_scope} ({delta.changed_files} file(s), +{delta.additions}/-{delta.deletions})",
        f"ATTENTION   {snapshot.attention}",
        f"NEXT        {snapshot.next_action_class}",
    ]

    if delta.reasons:
        lines.extend(["", "REVIEW PLAN", *[f"- {item}" for item in delta.reasons]])
    if delta.files and delta.review_scope == "DELTA":
        lines.extend(["", "DELTA FILES", *[f"- {item.path} (+{item.additions}/-{item.deletions})" for item in delta.files]])
    if snapshot.blockers:
        lines.extend(["", "BLOCKERS", *[f"- {item}" for item in snapshot.blockers]])
    if snapshot.pending_reasons:
        lines.extend(["", "PENDING", *[f"- {item}" for item in snapshot.pending_reasons]])
    return "\n".join(lines)
