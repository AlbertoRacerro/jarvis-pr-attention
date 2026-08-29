from __future__ import annotations

import re
from typing import Any

from .cli import collect_snapshot
from .continuity import (
    DEFAULT_MAX_THREAD_BYTES,
    DEFAULT_MAX_THREADS,
    DEFAULT_MAX_TOTAL_THREAD_BYTES,
    build_lineage_result_template,
)
from .continuity_guard import (
    collect_lineage_rereview_packet,
    failed_checkpoint_from_bundle,
    validate_lineage_result,
)
from .continuity_handoff import build_lineage_envelope
from .evidence_bundle import build_evidence_bundle
from .handoff import build_review_envelope, build_review_result_template
from .integration_gate import build_integration_gate
from .packet import (
    DEFAULT_MAX_FILE_PATCH_BYTES,
    DEFAULT_MAX_TOTAL_PATCH_BYTES,
    collect_review_packet,
)
from .rereview_gate import build_rereview_integration_gate
from .review_result import validate_review_result


CYCLE_SCHEMA_VERSION = 2
SAFETY_PROFILE = "STRICT_V1"
_FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")

_GATE_NEXT_ACTION = {
    "READY_TO_MERGE": "MERGE_CANDIDATE",
    "WAIT_FOR_GATES": "WAIT_FOR_GATES",
    "REPAIR": "REPAIR",
    "REVIEW_REQUIRED": "REVIEW_DELTA",
    "NEEDS_HUMAN": "NEEDS_HUMAN",
    "VERIFY_LIVE": "VERIFY_LIVE",
    "STALE": "REFRESH_SNAPSHOT",
    "UNKNOWN": "INVESTIGATE_UNKNOWN",
}


def _bounded_text(name: str, value: str | None, *, required: bool = False, maximum: int = 500) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{name} is required")
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    normalized = value.strip()
    if required and not normalized:
        raise ValueError(f"{name} is required")
    if not normalized:
        return None
    if len(normalized) > maximum:
        raise ValueError(f"{name} exceeds {maximum} characters")
    if any(ord(ch) < 32 for ch in normalized):
        raise ValueError(f"{name} must not contain control characters")
    return normalized


def _validate_inputs(
    repository: str,
    pr_number: int,
    *,
    accepted_head_sha: str | None,
    accepted_head_authority_confirmed: bool,
    accepted_head_source: str | None,
    previous_failed_source: dict[str, Any] | None,
    review_result: dict[str, Any] | None,
    review_result_source: str | None,
    continuity_result: dict[str, Any] | None,
    continuity_result_source: str | None,
    expected_head_sha: str | None,
    reviewer_name: str,
    reviewer_model: str | None,
) -> tuple[str, str | None, str | None, str | None, str | None]:
    if not isinstance(repository, str) or not _REPOSITORY.fullmatch(repository):
        raise ValueError("repository must be exactly owner/repository using GitHub-safe name characters")
    if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number < 1:
        raise ValueError("pr_number must be a positive integer")
    if not isinstance(accepted_head_authority_confirmed, bool):
        raise ValueError("accepted_head_authority_confirmed must be boolean")
    for label, payload in (
        ("previous_failed_source", previous_failed_source),
        ("review_result", review_result),
        ("continuity_result", continuity_result),
    ):
        if payload is not None and not isinstance(payload, dict):
            raise ValueError(f"{label} must be a JSON object")
    if accepted_head_sha is not None and not _FULL_SHA.fullmatch(accepted_head_sha):
        raise ValueError("accepted_head_sha must be a full 40-character hexadecimal commit SHA")
    if expected_head_sha is not None and not _FULL_SHA.fullmatch(expected_head_sha):
        raise ValueError("expected_head_sha must be a full 40-character hexadecimal commit SHA")
    if previous_failed_source is not None and accepted_head_sha is not None:
        raise ValueError("accepted_head_sha and previous_failed_source are mutually exclusive")
    if review_result is not None and continuity_result is not None:
        raise ValueError("ordinary and continuity review results cannot be supplied together")
    if review_result is not None and accepted_head_sha is None:
        raise ValueError("review_result requires accepted_head_sha")
    if continuity_result is not None and previous_failed_source is None:
        raise ValueError("continuity_result requires previous_failed_source")

    accepted_source = _bounded_text("accepted_head_source", accepted_head_source, maximum=500)
    ordinary_source = _bounded_text("review_result_source", review_result_source, maximum=500)
    continuity_source = _bounded_text("continuity_result_source", continuity_result_source, maximum=500)
    normalized_reviewer = _bounded_text("reviewer_name", reviewer_name, required=True, maximum=200)
    normalized_model = _bounded_text("reviewer_model", reviewer_model, maximum=200)

    if accepted_head_authority_confirmed:
        if accepted_head_sha is None:
            raise ValueError("accepted_head_authority_confirmed requires accepted_head_sha")
        if accepted_source is None:
            raise ValueError("confirmed accepted-head authority requires accepted_head_source")
    elif accepted_source is not None:
        raise ValueError("accepted_head_source requires accepted_head_authority_confirmed=true")

    if review_result is not None:
        if not accepted_head_authority_confirmed:
            raise ValueError("review_result cannot reuse a delta baseline until accepted-head authority is explicitly confirmed")
        if ordinary_source is None:
            raise ValueError("review_result requires review_result_source for provenance traceability")
    elif ordinary_source is not None:
        raise ValueError("review_result_source requires review_result")

    if continuity_result is not None and continuity_source is None:
        raise ValueError("continuity_result requires continuity_result_source for provenance traceability")
    if continuity_result is None and continuity_source is not None:
        raise ValueError("continuity_result_source requires continuity_result")

    return normalized_reviewer or reviewer_name, normalized_model, accepted_source, ordinary_source, continuity_source


def _validate_budgets(
    *,
    max_total_patch_bytes: int,
    max_file_patch_bytes: int,
    max_thread_bytes: int,
    max_total_thread_bytes: int,
    max_threads: int,
) -> None:
    for name, value, maximum in (
        ("max_total_patch_bytes", max_total_patch_bytes, 5_000_000),
        ("max_file_patch_bytes", max_file_patch_bytes, 5_000_000),
        ("max_thread_bytes", max_thread_bytes, 5_000_000),
        ("max_total_thread_bytes", max_total_thread_bytes, 5_000_000),
        ("max_threads", max_threads, 500),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > maximum:
            raise ValueError(f"{name} must be an integer between 1 and {maximum}")


def _live_head(client: Any, repository: str, pr_number: int) -> str | None:
    pr = client.pull_request(repository, pr_number)
    head = str(((pr.get("head") or {}).get("sha") or ""))
    return head or None


def _strict_merge_candidate(snapshot: dict[str, Any], validation: dict[str, Any] | None, gate: dict[str, Any] | None) -> bool:
    if validation is None or gate is None:
        return False
    head = snapshot.get("head_sha")
    return bool(
        snapshot.get("attention") == "READY"
        and snapshot.get("facts_complete") is True
        and snapshot.get("stale") is False
        and validation.get("valid") is True
        and validation.get("status") == "VALID_PASS"
        and validation.get("head_sha") == head
        and validation.get("live_head_sha") == head
        and gate.get("status") == "READY_TO_MERGE"
        and gate.get("merge_ready") is True
    )


def _ordinary_mode(snapshot: dict[str, Any], *, baseline_confirmed: bool) -> str:
    if not baseline_confirmed:
        return "FULL"
    scope = ((snapshot.get("delta") or {}).get("review_scope"))
    if scope == "DELTA":
        return "DELTA"
    if scope == "NONE":
        return "NONE"
    return "FULL"


def _safety(
    *,
    snapshot: dict[str, Any],
    baseline_authority: str,
    accepted_head_source: str | None,
    result_source: str | None,
    packet: dict[str, Any] | None,
    validation: dict[str, Any] | None,
    gate: dict[str, Any] | None,
    merge_candidate: bool,
    extra_blockers: list[str] | None = None,
) -> dict[str, Any]:
    blockers = list(extra_blockers or [])
    if snapshot.get("stale") is True:
        blockers.append("PR head moved during live fact collection")
    if snapshot.get("facts_complete") is not True:
        blockers.append("required GitHub facts are incomplete")
    if packet is not None and packet.get("complete") is not True:
        blockers.append("review evidence is incomplete")
    if validation is not None and validation.get("status") in {"INVALID", "STALE"}:
        blockers.append(f"semantic result is {validation.get('status')}")
    live_bound = bool(
        validation is not None
        and validation.get("valid") is True
        and validation.get("live_head_sha") == snapshot.get("head_sha")
    )
    if merge_candidate:
        status = "SAFE_TO_MERGE_ADVISORY"
    elif gate is not None and gate.get("status") == "REPAIR":
        status = "REPAIR_REQUIRED"
    elif blockers:
        status = "BLOCKED"
    elif packet is not None and packet.get("complete") is True and validation is None:
        status = "SAFE_TO_REVIEW"
    elif gate is not None and gate.get("status") == "WAIT_FOR_GATES":
        status = "WAIT_FOR_GATES"
    else:
        status = "NO_MERGE_SIGNAL"
    return {
        "profile": SAFETY_PROFILE,
        "status": status,
        "baseline_authority": baseline_authority,
        "accepted_head_source": accepted_head_source,
        "result_source": result_source,
        "expected_head_bound": False,
        "semantic_result_live_bound": live_bound,
        "merge_signal_requires_current_live_pass": True,
        "fresh_output_required": True,
        "blockers": blockers,
    }


def _terminal_stale(
    snapshot: dict[str, Any],
    *,
    baseline_authority: str,
    accepted_head_source: str | None,
) -> dict[str, Any]:
    safety = _safety(
        snapshot=snapshot,
        baseline_authority=baseline_authority,
        accepted_head_source=accepted_head_source,
        result_source=None,
        packet=None,
        validation=None,
        gate=None,
        merge_candidate=False,
    )
    return {
        "schema_version": CYCLE_SCHEMA_VERSION,
        "kind": "PR_ATTENTION_CYCLE",
        "repository": snapshot["repository"],
        "pr_number": snapshot["pr_number"],
        "head_sha": snapshot["head_sha"],
        "attention": snapshot["attention"],
        "review_mode": "FULL",
        "next_action": "REFRESH_SNAPSHOT",
        "gate_status": "NOT_RUN",
        "semantic_status": "NOT_RUN",
        "live_review_bound": False,
        "merge_candidate": False,
        "safety": safety,
        "snapshot": snapshot,
        "review_packet": None,
        "review_result_template": None,
        "review_envelope": None,
        "review_validation": None,
        "integration_gate": None,
        "evidence_bundle": None,
        "checkpoint": None,
    }


def run_cycle(
    client: Any,
    repository: str,
    pr_number: int,
    *,
    accepted_head_sha: str | None = None,
    accepted_head_authority_confirmed: bool = False,
    accepted_head_source: str | None = None,
    previous_failed_source: dict[str, Any] | None = None,
    review_result: dict[str, Any] | None = None,
    review_result_source: str | None = None,
    continuity_result: dict[str, Any] | None = None,
    continuity_result_source: str | None = None,
    expected_head_sha: str | None = None,
    reviewer_name: str = "external-reviewer",
    reviewer_model: str | None = None,
    max_total_patch_bytes: int = DEFAULT_MAX_TOTAL_PATCH_BYTES,
    max_file_patch_bytes: int = DEFAULT_MAX_FILE_PATCH_BYTES,
    max_thread_bytes: int = DEFAULT_MAX_THREAD_BYTES,
    max_total_thread_bytes: int = DEFAULT_MAX_TOTAL_THREAD_BYTES,
    max_threads: int = DEFAULT_MAX_THREADS,
) -> dict[str, Any]:
    """Run one strict, deterministic, read-only PR attention cycle.

    The cycle deliberately refuses to reduce review scope from a naked accepted-head
    claim. Incremental review is enabled only after the caller explicitly confirms
    that the accepted head is semantic authority and supplies a traceable source.
    No merge-candidate signal is emitted without a current-cycle live-bound PASS.
    """

    (
        reviewer_name,
        reviewer_model,
        accepted_head_source,
        review_result_source,
        continuity_result_source,
    ) = _validate_inputs(
        repository,
        pr_number,
        accepted_head_sha=accepted_head_sha,
        accepted_head_authority_confirmed=accepted_head_authority_confirmed,
        accepted_head_source=accepted_head_source,
        previous_failed_source=previous_failed_source,
        review_result=review_result,
        review_result_source=review_result_source,
        continuity_result=continuity_result,
        continuity_result_source=continuity_result_source,
        expected_head_sha=expected_head_sha,
        reviewer_name=reviewer_name,
        reviewer_model=reviewer_model,
    )
    _validate_budgets(
        max_total_patch_bytes=max_total_patch_bytes,
        max_file_patch_bytes=max_file_patch_bytes,
        max_thread_bytes=max_thread_bytes,
        max_total_thread_bytes=max_total_thread_bytes,
        max_threads=max_threads,
    )

    baseline_confirmed = accepted_head_sha is not None and accepted_head_authority_confirmed
    effective_accepted_head = accepted_head_sha if baseline_confirmed else None
    baseline_authority = (
        "FAILED_REVIEW_LINEAGE"
        if previous_failed_source is not None
        else ("CONFIRMED_EXTERNAL" if baseline_confirmed else ("UNCONFIRMED_CLAIM" if accepted_head_sha else "NONE"))
    )

    snapshot_obj = collect_snapshot(client, repository, pr_number, accepted_head_sha=effective_accepted_head)
    snapshot = snapshot_obj.to_dict()
    if expected_head_sha is not None and snapshot_obj.head_sha != expected_head_sha:
        raise ValueError(
            f"live PR head {snapshot_obj.head_sha} does not match caller-bound expected head {expected_head_sha}"
        )
    if snapshot_obj.stale:
        result = _terminal_stale(
            snapshot,
            baseline_authority=baseline_authority,
            accepted_head_source=accepted_head_source,
        )
        result["safety"]["expected_head_bound"] = expected_head_sha is not None
        return result

    if previous_failed_source is not None:
        checkpoint = failed_checkpoint_from_bundle(previous_failed_source)
        packet = collect_lineage_rereview_packet(
            client,
            repository,
            pr_number,
            previous_failed_source,
            expected_head_sha=snapshot_obj.head_sha,
            max_total_patch_bytes=max_total_patch_bytes,
            max_file_patch_bytes=max_file_patch_bytes,
            max_thread_bytes=max_thread_bytes,
            max_total_thread_bytes=max_total_thread_bytes,
            max_threads=max_threads,
        )
        template = build_lineage_result_template(
            packet,
            reviewer_name=reviewer_name,
            reviewer_model=reviewer_model,
        )
        envelope = build_lineage_envelope(
            packet,
            reviewer_name=reviewer_name,
            reviewer_model=reviewer_model,
        )
        validation: dict[str, Any] | None = None
        gate: dict[str, Any] | None = None
        if continuity_result is not None:
            validation = validate_lineage_result(
                packet,
                continuity_result,
                live_head_sha=_live_head(client, repository, pr_number),
            )
            gate = build_rereview_integration_gate(snapshot, validation).to_dict()
            next_checkpoint = validation.get("next_failed_checkpoint")
            if validation.get("status") == "VALID_FAIL" and isinstance(next_checkpoint, dict):
                checkpoint = next_checkpoint
            elif validation.get("status") == "VALID_PASS":
                checkpoint = None

        merge_candidate = _strict_merge_candidate(snapshot, validation, gate)
        if merge_candidate:
            next_action = "MERGE_CANDIDATE"
        elif gate is not None:
            next_action = _GATE_NEXT_ACTION.get(str(gate.get("status")), "INVESTIGATE_UNKNOWN")
            if next_action == "MERGE_CANDIDATE":
                next_action = "VERIFY_MERGE_GOVERNANCE"
        elif (
            packet.get("incremental_eligible") is True
            and packet.get("coverage") == "COMPLETE"
            and packet.get("thread_coverage") == "COMPLETE"
            and packet.get("complete") is True
        ):
            next_action = "REREVIEW_DELTA"
        elif packet.get("review_scope") == "FULL" or packet.get("relation") in {"BEHIND", "DIVERGED"}:
            next_action = "FULL_REVIEW"
        else:
            next_action = "INVESTIGATE_UNKNOWN"

        safety = _safety(
            snapshot=snapshot,
            baseline_authority=baseline_authority,
            accepted_head_source=None,
            result_source=continuity_result_source,
            packet=packet,
            validation=validation,
            gate=gate,
            merge_candidate=merge_candidate,
        )
        safety["expected_head_bound"] = expected_head_sha is not None
        return {
            "schema_version": CYCLE_SCHEMA_VERSION,
            "kind": "PR_ATTENTION_CYCLE",
            "repository": repository,
            "pr_number": pr_number,
            "head_sha": snapshot_obj.head_sha,
            "attention": snapshot_obj.attention,
            "review_mode": "CONTINUITY",
            "next_action": next_action,
            "gate_status": gate.get("status") if gate is not None else "NOT_RUN",
            "semantic_status": validation.get("status") if validation is not None else "NOT_RUN",
            "live_review_bound": safety["semantic_result_live_bound"],
            "merge_candidate": merge_candidate,
            "safety": safety,
            "snapshot": snapshot,
            "review_packet": packet,
            "review_result_template": template,
            "review_envelope": envelope,
            "review_validation": validation,
            "integration_gate": gate,
            "evidence_bundle": None,
            "checkpoint": checkpoint,
        }

    packet_dict: dict[str, Any] | None = None
    template: dict[str, Any] | None = None
    envelope: dict[str, Any] | None = None
    validation_dict: dict[str, Any] | None = None
    gate_dict: dict[str, Any] | None = None
    checkpoint: dict[str, Any] | None = None
    extra_blockers: list[str] = []

    if accepted_head_sha is not None and not baseline_confirmed:
        extra_blockers.append(
            "accepted-head is only a caller claim; strict mode refuses incremental reuse until authority is explicitly confirmed"
        )

    if baseline_confirmed and snapshot_obj.delta.review_scope == "DELTA":
        packet_obj = collect_review_packet(
            client,
            repository,
            pr_number,
            accepted_head_sha,
            expected_head_sha=snapshot_obj.head_sha,
            max_total_patch_bytes=max_total_patch_bytes,
            max_file_patch_bytes=max_file_patch_bytes,
        )
        packet_dict = packet_obj.to_dict()
        template = build_review_result_template(
            packet_dict,
            reviewer_name=reviewer_name,
            reviewer_model=reviewer_model,
        )
        envelope = build_review_envelope(
            packet_dict,
            reviewer_name=reviewer_name,
            reviewer_model=reviewer_model,
        )
        if review_result is not None:
            validation = validate_review_result(
                packet_dict,
                review_result,
                live_head_sha=_live_head(client, repository, pr_number),
            )
            validation_dict = validation.to_dict()
            gate_dict = build_integration_gate(snapshot, validation_dict).to_dict()
    elif review_result is not None:
        raise ValueError("review_result requires a confirmed, complete DELTA review scope on the live head")

    evidence_bundle = build_evidence_bundle(
        snapshot,
        packet=packet_dict,
        envelope=envelope,
        review_result=review_result,
        validation=validation_dict,
        integration_gate=gate_dict,
    )
    if validation_dict is not None and validation_dict.get("status") == "VALID_FAIL":
        checkpoint = failed_checkpoint_from_bundle(evidence_bundle)

    merge_candidate = _strict_merge_candidate(snapshot, validation_dict, gate_dict)
    mode = _ordinary_mode(snapshot, baseline_confirmed=baseline_confirmed)
    if merge_candidate:
        next_action = "MERGE_CANDIDATE"
    elif gate_dict is not None:
        next_action = _GATE_NEXT_ACTION.get(str(gate_dict.get("status")), "INVESTIGATE_UNKNOWN")
        if next_action == "MERGE_CANDIDATE":
            next_action = "VERIFY_MERGE_GOVERNANCE"
    elif accepted_head_sha is not None and not baseline_confirmed:
        next_action = "FULL_REVIEW"
    elif mode == "NONE":
        next_action = "VERIFY_MERGE_GOVERNANCE"
    elif packet_dict is not None and packet_dict.get("complete") is True:
        next_action = "REVIEW_DELTA"
    elif packet_dict is not None:
        next_action = "FULL_REVIEW" if packet_dict.get("coverage") == "NONE" else "INVESTIGATE_UNKNOWN"
    else:
        next_action = "FULL_REVIEW"

    safety = _safety(
        snapshot=snapshot,
        baseline_authority=baseline_authority,
        accepted_head_source=accepted_head_source,
        result_source=review_result_source,
        packet=packet_dict,
        validation=validation_dict,
        gate=gate_dict,
        merge_candidate=merge_candidate,
        extra_blockers=extra_blockers,
    )
    safety["expected_head_bound"] = expected_head_sha is not None
    return {
        "schema_version": CYCLE_SCHEMA_VERSION,
        "kind": "PR_ATTENTION_CYCLE",
        "repository": repository,
        "pr_number": pr_number,
        "head_sha": snapshot_obj.head_sha,
        "attention": snapshot_obj.attention,
        "review_mode": mode,
        "next_action": next_action,
        "gate_status": gate_dict.get("status") if gate_dict is not None else "NOT_RUN",
        "semantic_status": validation_dict.get("status") if validation_dict is not None else "NOT_RUN",
        "live_review_bound": safety["semantic_result_live_bound"],
        "merge_candidate": merge_candidate,
        "safety": safety,
        "snapshot": snapshot,
        "review_packet": packet_dict,
        "review_result_template": template,
        "review_envelope": envelope,
        "review_validation": validation_dict,
        "integration_gate": gate_dict,
        "evidence_bundle": evidence_bundle,
        "checkpoint": checkpoint,
    }
