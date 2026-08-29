from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

RereviewGateStatus = Literal[
    "READY_TO_MERGE",
    "WAIT_FOR_GATES",
    "REPAIR",
    "REVIEW_REQUIRED",
    "NEEDS_HUMAN",
    "VERIFY_LIVE",
    "STALE",
    "UNKNOWN",
]

REREVIEW_GATE_SCHEMA_VERSION = 1
REREVIEW_MERGE_SAFETY_NOTICE = (
    "READY_TO_MERGE is advisory evidence only; the caller must still re-check current GitHub state and merge with an exact-head guard"
)
_FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_VALID_ATTENTION = {"READY", "PENDING", "BLOCKED", "STALE", "UNKNOWN"}
_VALID_REVIEW_STATUSES = {"VALID_PASS", "VALID_FAIL", "VALID_NEEDS_HUMAN", "STALE", "INVALID"}
_EXPECTED_VERDICT = {
    "VALID_PASS": "PASS",
    "VALID_FAIL": "FAIL",
    "VALID_NEEDS_HUMAN": "NEEDS_HUMAN",
}


@dataclass(frozen=True)
class RereviewIntegrationGate:
    schema_version: int
    kind: str
    status: RereviewGateStatus
    merge_ready: bool
    repository: str | None
    pr_number: int | None
    previous_reviewed_head_sha: str | None
    head_sha: str | None
    rereview_packet_sha256: str | None
    attention: str | None
    semantic_review_status: str | None
    live_review_bound: bool
    reasons: list[str] = field(default_factory=list)
    safety_notice: str = REREVIEW_MERGE_SAFETY_NOTICE

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _strict_pr(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _unknown(snapshot: dict[str, Any], validation: dict[str, Any], reasons: list[str]) -> RereviewIntegrationGate:
    return RereviewIntegrationGate(
        schema_version=REREVIEW_GATE_SCHEMA_VERSION,
        kind="PR_ATTENTION_REREVIEW_INTEGRATION_GATE",
        status="UNKNOWN",
        merge_ready=False,
        repository=snapshot.get("repository") if isinstance(snapshot.get("repository"), str) else None,
        pr_number=_strict_pr(snapshot.get("pr_number")),
        previous_reviewed_head_sha=validation.get("previous_reviewed_head_sha") if isinstance(validation.get("previous_reviewed_head_sha"), str) else None,
        head_sha=snapshot.get("head_sha") if isinstance(snapshot.get("head_sha"), str) else None,
        rereview_packet_sha256=validation.get("rereview_packet_sha256") if isinstance(validation.get("rereview_packet_sha256"), str) else None,
        attention=snapshot.get("attention") if isinstance(snapshot.get("attention"), str) else None,
        semantic_review_status=validation.get("status") if isinstance(validation.get("status"), str) else None,
        live_review_bound=False,
        reasons=reasons,
    )


def _gate(
    *,
    status: RereviewGateStatus,
    repository: str,
    pr_number: int,
    previous_reviewed_head_sha: str,
    head_sha: str,
    packet_digest: str,
    attention: str,
    semantic_status: str,
    live_review_bound: bool,
    reasons: list[str],
) -> RereviewIntegrationGate:
    return RereviewIntegrationGate(
        schema_version=REREVIEW_GATE_SCHEMA_VERSION,
        kind="PR_ATTENTION_REREVIEW_INTEGRATION_GATE",
        status=status,
        merge_ready=status == "READY_TO_MERGE",
        repository=repository,
        pr_number=pr_number,
        previous_reviewed_head_sha=previous_reviewed_head_sha,
        head_sha=head_sha,
        rereview_packet_sha256=packet_digest,
        attention=attention,
        semantic_review_status=semantic_status,
        live_review_bound=live_review_bound,
        reasons=reasons,
    )


def build_rereview_integration_gate(snapshot: dict[str, Any], validation: dict[str, Any]) -> RereviewIntegrationGate:
    reasons: list[str] = []
    if snapshot.get("schema_version") != 2 or isinstance(snapshot.get("schema_version"), bool):
        reasons.append("unsupported snapshot schema_version")
    if validation.get("schema_version") != 1 or isinstance(validation.get("schema_version"), bool):
        reasons.append("unsupported re-review validation schema_version")
    if validation.get("kind") != "PR_ATTENTION_REREVIEW_VALIDATION":
        reasons.append("re-review validation kind is invalid")

    repository = snapshot.get("repository")
    pr_number = _strict_pr(snapshot.get("pr_number"))
    head_sha = snapshot.get("head_sha")
    final_head_sha = snapshot.get("final_head_sha")
    previous_head = validation.get("previous_reviewed_head_sha")
    validation_head = validation.get("head_sha")
    live_head = validation.get("live_head_sha")
    attention = snapshot.get("attention")
    semantic_status = validation.get("status")
    packet_digest = validation.get("rereview_packet_sha256")
    validation_valid = validation.get("valid")
    verdict = validation.get("verdict")

    if not isinstance(repository, str) or not repository or "/" not in repository:
        reasons.append("snapshot repository is invalid")
    if validation.get("repository") != repository:
        reasons.append("re-review validation repository does not match snapshot")
    if pr_number is None:
        reasons.append("snapshot pr_number is invalid")
    if _strict_pr(validation.get("pr_number")) != pr_number:
        reasons.append("re-review validation pr_number does not match snapshot")
    for label, value in (
        ("snapshot head_sha", head_sha),
        ("snapshot final_head_sha", final_head_sha),
        ("previous reviewed head", previous_head),
        ("re-review validation head_sha", validation_head),
    ):
        if not isinstance(value, str) or not _FULL_SHA.fullmatch(value):
            reasons.append(f"{label} is invalid")
    if attention not in _VALID_ATTENTION:
        reasons.append("snapshot attention is invalid")
    if semantic_status not in _VALID_REVIEW_STATUSES:
        reasons.append("re-review validation status is invalid")
    if not isinstance(packet_digest, str) or not _DIGEST.fullmatch(packet_digest):
        reasons.append("re-review packet digest is invalid")
    if not isinstance(snapshot.get("facts_complete"), bool) or not isinstance(snapshot.get("stale"), bool):
        reasons.append("snapshot completeness/stale fields are invalid")
    if not isinstance(validation_valid, bool):
        reasons.append("re-review validation valid flag is invalid")

    if semantic_status in _EXPECTED_VERDICT:
        if validation_valid is not True:
            reasons.append(f"{semantic_status} requires valid=true")
        if verdict != _EXPECTED_VERDICT[semantic_status]:
            reasons.append(f"{semantic_status} requires verdict={_EXPECTED_VERDICT[semantic_status]}")
    elif semantic_status in {"STALE", "INVALID"} and validation_valid is not False:
        reasons.append(f"{semantic_status} requires valid=false")

    if live_head is not None and (not isinstance(live_head, str) or not _FULL_SHA.fullmatch(live_head)):
        reasons.append("re-review validation live_head_sha is invalid")

    if reasons:
        return _unknown(snapshot, validation, reasons)

    if head_sha != validation_head:
        return _gate(
            status="STALE", repository=repository, pr_number=pr_number,
            previous_reviewed_head_sha=previous_head, head_sha=head_sha,
            packet_digest=packet_digest, attention=attention, semantic_status=semantic_status,
            live_review_bound=False, reasons=["snapshot head and re-reviewed head differ"],
        )
    if live_head is not None and live_head != head_sha:
        return _gate(
            status="STALE", repository=repository, pr_number=pr_number,
            previous_reviewed_head_sha=previous_head, head_sha=head_sha,
            packet_digest=packet_digest, attention=attention, semantic_status=semantic_status,
            live_review_bound=False, reasons=["live head no longer matches the re-reviewed head"],
        )
    if snapshot["stale"] or head_sha != final_head_sha or attention == "STALE" or semantic_status == "STALE":
        return _gate(
            status="STALE", repository=repository, pr_number=pr_number,
            previous_reviewed_head_sha=previous_head, head_sha=head_sha,
            packet_digest=packet_digest, attention=attention, semantic_status=semantic_status,
            live_review_bound=False, reasons=["snapshot or re-review evidence is stale"],
        )
    if snapshot["facts_complete"] is False:
        return _gate(
            status="UNKNOWN", repository=repository, pr_number=pr_number,
            previous_reviewed_head_sha=previous_head, head_sha=head_sha,
            packet_digest=packet_digest, attention=attention, semantic_status=semantic_status,
            live_review_bound=live_head == head_sha, reasons=["GitHub snapshot facts are incomplete"],
        )
    if semantic_status == "INVALID":
        return _gate(
            status="REVIEW_REQUIRED", repository=repository, pr_number=pr_number,
            previous_reviewed_head_sha=previous_head, head_sha=head_sha,
            packet_digest=packet_digest, attention=attention, semantic_status=semantic_status,
            live_review_bound=False, reasons=["no valid incremental semantic re-review is bound to the current head"],
        )
    if semantic_status == "VALID_FAIL":
        return _gate(
            status="REPAIR", repository=repository, pr_number=pr_number,
            previous_reviewed_head_sha=previous_head, head_sha=head_sha,
            packet_digest=packet_digest, attention=attention, semantic_status=semantic_status,
            live_review_bound=live_head == head_sha, reasons=["incremental semantic re-review contains a valid blocking failure"],
        )
    if semantic_status == "VALID_NEEDS_HUMAN":
        return _gate(
            status="NEEDS_HUMAN", repository=repository, pr_number=pr_number,
            previous_reviewed_head_sha=previous_head, head_sha=head_sha,
            packet_digest=packet_digest, attention=attention, semantic_status=semantic_status,
            live_review_bound=live_head == head_sha, reasons=["incremental semantic reviewer explicitly requires human judgment"],
        )
    if semantic_status != "VALID_PASS":
        return _unknown(snapshot, validation, ["re-review status cannot be mapped safely"])
    if live_head is None:
        return _gate(
            status="VERIFY_LIVE", repository=repository, pr_number=pr_number,
            previous_reviewed_head_sha=previous_head, head_sha=head_sha,
            packet_digest=packet_digest, attention=attention, semantic_status=semantic_status,
            live_review_bound=False, reasons=["incremental semantic PASS is valid offline but is not live-bound"],
        )

    if attention == "BLOCKED":
        status: RereviewGateStatus = "REPAIR"
        mapped_reasons = ["GitHub live state contains a blocking condition after incremental semantic PASS"]
    elif attention == "PENDING":
        status = "WAIT_FOR_GATES"
        mapped_reasons = ["incremental semantic re-review passed but GitHub checks or mergeability are pending"]
    elif attention == "UNKNOWN":
        status = "UNKNOWN"
        mapped_reasons = ["incremental semantic re-review passed but GitHub live evidence is unknown"]
    elif attention == "READY":
        status = "READY_TO_MERGE"
        mapped_reasons = ["incremental semantic re-review is valid/live-bound and GitHub live gates are ready"]
    else:
        status = "UNKNOWN"
        mapped_reasons = ["GitHub attention state cannot be mapped safely"]

    return _gate(
        status=status,
        repository=repository,
        pr_number=pr_number,
        previous_reviewed_head_sha=previous_head,
        head_sha=head_sha,
        packet_digest=packet_digest,
        attention=attention,
        semantic_status=semantic_status,
        live_review_bound=True,
        reasons=mapped_reasons,
    )
