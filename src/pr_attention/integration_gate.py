from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

IntegrationGateStatus = Literal[
    "READY_TO_MERGE",
    "WAIT_FOR_GATES",
    "REPAIR",
    "REVIEW_REQUIRED",
    "NEEDS_HUMAN",
    "VERIFY_LIVE",
    "STALE",
    "UNKNOWN",
]

INTEGRATION_GATE_SCHEMA_VERSION = 1
MERGE_SAFETY_NOTICE = (
    "READY_TO_MERGE is advisory evidence only; the caller must still re-check current GitHub state and merge with an exact-head guard"
)
_FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_VALID_ATTENTION = {"READY", "PENDING", "BLOCKED", "STALE", "UNKNOWN"}
_VALID_REVIEW_STATUSES = {"VALID_PASS", "VALID_FAIL", "VALID_NEEDS_HUMAN", "STALE", "INVALID"}


@dataclass(frozen=True)
class IntegrationGate:
    schema_version: int
    status: IntegrationGateStatus
    merge_ready: bool
    repository: str | None
    pr_number: int | None
    head_sha: str | None
    packet_sha256: str | None
    attention: str | None
    semantic_review_status: str | None
    live_review_bound: bool
    reasons: list[str] = field(default_factory=list)
    safety_notice: str = MERGE_SAFETY_NOTICE

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _unknown(snapshot: dict[str, Any], validation: dict[str, Any], reasons: list[str]) -> IntegrationGate:
    pr_number = snapshot.get("pr_number")
    return IntegrationGate(
        schema_version=INTEGRATION_GATE_SCHEMA_VERSION,
        status="UNKNOWN",
        merge_ready=False,
        repository=snapshot.get("repository") if isinstance(snapshot.get("repository"), str) else None,
        pr_number=pr_number if isinstance(pr_number, int) and not isinstance(pr_number, bool) else None,
        head_sha=snapshot.get("head_sha") if isinstance(snapshot.get("head_sha"), str) else None,
        packet_sha256=validation.get("packet_sha256") if isinstance(validation.get("packet_sha256"), str) else None,
        attention=snapshot.get("attention") if isinstance(snapshot.get("attention"), str) else None,
        semantic_review_status=validation.get("status") if isinstance(validation.get("status"), str) else None,
        live_review_bound=False,
        reasons=reasons,
    )


def build_integration_gate(snapshot: dict[str, Any], validation: dict[str, Any]) -> IntegrationGate:
    reasons: list[str] = []

    snapshot_schema = snapshot.get("schema_version")
    if not isinstance(snapshot_schema, int) or isinstance(snapshot_schema, bool) or snapshot_schema != 2:
        reasons.append("unsupported snapshot schema_version")
    validation_schema = validation.get("schema_version")
    if not isinstance(validation_schema, int) or isinstance(validation_schema, bool) or validation_schema != 1:
        reasons.append("unsupported review validation schema_version")

    repository = snapshot.get("repository")
    validation_repository = validation.get("repository")
    pr_number = snapshot.get("pr_number")
    validation_pr_number = validation.get("pr_number")
    head_sha = snapshot.get("head_sha")
    final_head_sha = snapshot.get("final_head_sha")
    validation_head_sha = validation.get("head_sha")
    live_head_sha = validation.get("live_head_sha")
    attention = snapshot.get("attention")
    semantic_status = validation.get("status")
    packet_digest = validation.get("packet_sha256")

    if not isinstance(repository, str) or not repository or "/" not in repository:
        reasons.append("snapshot repository is invalid")
    if validation_repository != repository:
        reasons.append("review validation repository does not match snapshot")
    if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number < 1:
        reasons.append("snapshot pr_number is invalid")
    if validation_pr_number != pr_number or isinstance(validation_pr_number, bool):
        reasons.append("review validation pr_number does not match snapshot")
    for name, value in (("snapshot head_sha", head_sha), ("snapshot final_head_sha", final_head_sha), ("review validation head_sha", validation_head_sha)):
        if not isinstance(value, str) or not _FULL_SHA.fullmatch(value):
            reasons.append(f"{name} is invalid")
    if attention not in _VALID_ATTENTION:
        reasons.append("snapshot attention is invalid")
    if semantic_status not in _VALID_REVIEW_STATUSES:
        reasons.append("semantic review validation status is invalid")
    if not isinstance(packet_digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", packet_digest):
        reasons.append("review validation packet_sha256 is invalid")
    if not isinstance(snapshot.get("facts_complete"), bool):
        reasons.append("snapshot facts_complete flag is invalid")
    if not isinstance(snapshot.get("stale"), bool):
        reasons.append("snapshot stale flag is invalid")
    if not isinstance(validation.get("valid"), bool):
        reasons.append("review validation valid flag is invalid")

    if reasons:
        return _unknown(snapshot, validation, reasons)

    if head_sha != validation_head_sha:
        return IntegrationGate(
            schema_version=INTEGRATION_GATE_SCHEMA_VERSION,
            status="STALE",
            merge_ready=False,
            repository=repository,
            pr_number=pr_number,
            head_sha=head_sha,
            packet_sha256=packet_digest,
            attention=attention,
            semantic_review_status=semantic_status,
            live_review_bound=False,
            reasons=["snapshot head and semantically reviewed head differ"],
        )

    if snapshot["stale"] or head_sha != final_head_sha or attention == "STALE" or semantic_status == "STALE":
        return IntegrationGate(
            schema_version=INTEGRATION_GATE_SCHEMA_VERSION,
            status="STALE",
            merge_ready=False,
            repository=repository,
            pr_number=pr_number,
            head_sha=head_sha,
            packet_sha256=packet_digest,
            attention=attention,
            semantic_review_status=semantic_status,
            live_review_bound=False,
            reasons=["snapshot or semantic review evidence is stale"],
        )

    if semantic_status == "INVALID" or validation["valid"] is False:
        return IntegrationGate(
            schema_version=INTEGRATION_GATE_SCHEMA_VERSION,
            status="REVIEW_REQUIRED",
            merge_ready=False,
            repository=repository,
            pr_number=pr_number,
            head_sha=head_sha,
            packet_sha256=packet_digest,
            attention=attention,
            semantic_review_status=semantic_status,
            live_review_bound=False,
            reasons=["no valid semantic review result is bound to the current head"],
        )

    if semantic_status == "VALID_FAIL":
        return IntegrationGate(
            schema_version=INTEGRATION_GATE_SCHEMA_VERSION,
            status="REPAIR",
            merge_ready=False,
            repository=repository,
            pr_number=pr_number,
            head_sha=head_sha,
            packet_sha256=packet_digest,
            attention=attention,
            semantic_review_status=semantic_status,
            live_review_bound=live_head_sha == head_sha,
            reasons=["semantic review contains a valid blocking failure"],
        )

    if semantic_status == "VALID_NEEDS_HUMAN":
        return IntegrationGate(
            schema_version=INTEGRATION_GATE_SCHEMA_VERSION,
            status="NEEDS_HUMAN",
            merge_ready=False,
            repository=repository,
            pr_number=pr_number,
            head_sha=head_sha,
            packet_sha256=packet_digest,
            attention=attention,
            semantic_review_status=semantic_status,
            live_review_bound=live_head_sha == head_sha,
            reasons=["semantic reviewer explicitly requires human judgment"],
        )

    if semantic_status != "VALID_PASS":
        return _unknown(snapshot, validation, ["semantic review status cannot be mapped safely"])

    if live_head_sha is None:
        return IntegrationGate(
            schema_version=INTEGRATION_GATE_SCHEMA_VERSION,
            status="VERIFY_LIVE",
            merge_ready=False,
            repository=repository,
            pr_number=pr_number,
            head_sha=head_sha,
            packet_sha256=packet_digest,
            attention=attention,
            semantic_review_status=semantic_status,
            live_review_bound=False,
            reasons=["semantic PASS is valid offline but has not been live-bound to the current pull request head"],
        )
    if not isinstance(live_head_sha, str) or not _FULL_SHA.fullmatch(live_head_sha):
        return _unknown(snapshot, validation, ["review validation live_head_sha is invalid"])
    if live_head_sha != head_sha:
        return IntegrationGate(
            schema_version=INTEGRATION_GATE_SCHEMA_VERSION,
            status="STALE",
            merge_ready=False,
            repository=repository,
            pr_number=pr_number,
            head_sha=head_sha,
            packet_sha256=packet_digest,
            attention=attention,
            semantic_review_status=semantic_status,
            live_review_bound=False,
            reasons=["live head no longer matches the semantically reviewed head"],
        )

    if attention == "BLOCKED":
        status: IntegrationGateStatus = "REPAIR"
        gate_reasons = ["GitHub live state contains a blocking condition after semantic PASS"]
    elif attention == "PENDING":
        status = "WAIT_FOR_GATES"
        gate_reasons = ["semantic review passed but GitHub checks or mergeability are still pending"]
    elif attention == "UNKNOWN" or snapshot["facts_complete"] is False:
        status = "UNKNOWN"
        gate_reasons = ["semantic review passed but GitHub live evidence is incomplete or unknown"]
    elif attention == "READY":
        status = "READY_TO_MERGE"
        gate_reasons = ["semantic review is valid/live-bound and GitHub live gates are ready"]
    else:
        status = "UNKNOWN"
        gate_reasons = ["GitHub attention state cannot be mapped safely"]

    return IntegrationGate(
        schema_version=INTEGRATION_GATE_SCHEMA_VERSION,
        status=status,
        merge_ready=status == "READY_TO_MERGE",
        repository=repository,
        pr_number=pr_number,
        head_sha=head_sha,
        packet_sha256=packet_digest,
        attention=attention,
        semantic_review_status=semantic_status,
        live_review_bound=True,
        reasons=gate_reasons,
    )
