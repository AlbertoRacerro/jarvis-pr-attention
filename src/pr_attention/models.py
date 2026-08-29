from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

AttentionState = Literal["READY", "PENDING", "BLOCKED", "STALE", "UNKNOWN"]
CIState = Literal["SUCCESS", "PENDING", "FAILURE", "UNKNOWN"]
ReviewState = Literal["APPROVED", "CHANGES_REQUESTED", "NONE", "STALE_ONLY", "MIXED"]
DeltaRelation = Literal["ABSENT", "CURRENT", "AHEAD", "BEHIND", "DIVERGED", "UNKNOWN"]
AcceptanceValidity = Literal["ABSENT", "CURRENT", "REUSABLE_FOR_UNCHANGED", "INVALID", "UNKNOWN"]
ReviewScope = Literal["NONE", "DELTA", "FULL", "UNKNOWN"]
PacketCoverage = Literal["COMPLETE", "PARTIAL", "NONE", "UNKNOWN"]
NextActionClass = Literal[
    "MERGE_CANDIDATE",
    "REVIEW_DELTA",
    "FULL_REVIEW",
    "REPAIR",
    "WAIT_FOR_GATES",
    "REFRESH_SNAPSHOT",
    "INVESTIGATE_UNKNOWN",
]


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
    dismissed_review_count: int = 0


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
class DeltaFile:
    path: str
    status: str
    additions: int = 0
    deletions: int = 0
    changes: int = 0
    previous_path: str | None = None


@dataclass(frozen=True)
class DeltaSummary:
    accepted_head_sha: str | None
    relation: DeltaRelation
    acceptance_validity: AcceptanceValidity
    review_scope: ReviewScope
    complete: bool
    commits_ahead: int | None = None
    commits_behind: int | None = None
    additions: int = 0
    deletions: int = 0
    changed_files: int = 0
    files: list[DeltaFile] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


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
    delta: DeltaSummary
    attention: AttentionState
    next_action_class: NextActionClass
    blockers: list[str]
    pending_reasons: list[str]
    facts_complete: bool
    stale: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReviewPacketFile:
    path: str
    status: str
    additions: int = 0
    deletions: int = 0
    changes: int = 0
    previous_path: str | None = None
    patch: str | None = None
    original_patch_bytes: int = 0
    included_patch_bytes: int = 0
    truncated: bool = False
    omission_reason: str | None = None


@dataclass(frozen=True)
class ReviewPacket:
    schema_version: int
    repository: str
    pr_number: int
    accepted_head_sha: str
    head_sha: str
    final_head_sha: str
    generated_at: str
    relation: DeltaRelation
    review_scope: ReviewScope
    attention: AttentionState
    next_action_class: NextActionClass
    content_trust: str
    coverage: PacketCoverage
    complete: bool
    max_total_patch_bytes: int
    max_file_patch_bytes: int
    included_patch_bytes: int
    files: list[ReviewPacketFile] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
