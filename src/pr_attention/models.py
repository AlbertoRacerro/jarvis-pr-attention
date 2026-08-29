from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

AttentionState = Literal["READY", "PENDING", "BLOCKED", "STALE", "UNKNOWN"]
CIState = Literal["SUCCESS", "PENDING", "FAILURE", "UNKNOWN"]
ReviewState = Literal["APPROVED", "CHANGES_REQUESTED", "NONE", "STALE_ONLY", "MIXED"]


@dataclass(frozen=True)
class CheckSummary:
    state: CIState
    total: int = 0
    passed: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReviewSummary:
    state: ReviewState
    current_head_approvals: list[str] = field(default_factory=list)
    current_head_changes_requested: list[str] = field(default_factory=list)
    current_head_commented: list[str] = field(default_factory=list)
    stale_review_count: int = 0


@dataclass(frozen=True)
class ThreadSummary:
    total: int = 0
    unresolved_current: int = 0
    unresolved_outdated: int = 0
    resolved: int = 0
    unresolved_current_items: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class MergeSummary:
    mergeable: bool | None
    mergeable_state: str | None
    conflict: bool | None


@dataclass(frozen=True)
class ScopeSummary:
    additions: int
    deletions: int
    changed_files: int


@dataclass(frozen=True)
class Snapshot:
    schema_version: int
    repository: str
    pr_number: int
    title: str
    base_ref: str
    head_ref: str
    head_sha: str
    final_head_sha: str
    generated_at: str
    scope: ScopeSummary
    checks: CheckSummary
    reviews: ReviewSummary
    threads: ThreadSummary
    merge: MergeSummary
    attention: AttentionState
    blockers: list[str]
    pending_reasons: list[str]
    facts_complete: bool
    stale: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
