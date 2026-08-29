from __future__ import annotations

from typing import Any

from .cli import collect_snapshot
from .continuity import (
    DEFAULT_MAX_FILE_PATCH_BYTES as DEFAULT_CONTINUITY_MAX_FILE_PATCH_BYTES,
    DEFAULT_MAX_THREAD_BYTES,
    DEFAULT_MAX_THREADS,
    DEFAULT_MAX_TOTAL_PATCH_BYTES as DEFAULT_CONTINUITY_MAX_TOTAL_PATCH_BYTES,
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


def _live_head(client: Any, repository: str, pr_number: int) -> str | None:
    pr = client.pull_request(repository, pr_number)
    head = str(((pr.get("head") or {}).get("sha") or ""))
    return head or None


def _ordinary_mode(snapshot: dict[str, Any], accepted_head_sha: str | None) -> str:
    if accepted_head_sha is None:
        return "FULL"
    scope = ((snapshot.get("delta") or {}).get("review_scope"))
    if scope == "DELTA":
        return "DELTA"
    if scope == "NONE":
        return "NONE"
    return "FULL"


def _ordinary_next_action(
    snapshot: dict[str, Any],
    packet: dict[str, Any] | None,
    gate: dict[str, Any] | None,
) -> str:
    if gate is not None:
        return _GATE_NEXT_ACTION.get(str(gate.get("status")), "INVESTIGATE_UNKNOWN")
    if packet is not None and packet.get("complete") is not True:
        if packet.get("review_scope") == "FULL" or packet.get("coverage") == "NONE":
            return "FULL_REVIEW"
        return "INVESTIGATE_UNKNOWN"
    return str(snapshot.get("next_action_class") or "INVESTIGATE_UNKNOWN")


def _continuity_next_action(packet: dict[str, Any], gate: dict[str, Any] | None) -> str:
    if gate is not None:
        return _GATE_NEXT_ACTION.get(str(gate.get("status")), "INVESTIGATE_UNKNOWN")
    if (
        packet.get("incremental_eligible") is True
        and packet.get("coverage") == "COMPLETE"
        and packet.get("thread_coverage") == "COMPLETE"
        and packet.get("complete") is True
    ):
        return "REREVIEW_DELTA"
    if packet.get("review_scope") == "FULL" or packet.get("relation") in {"BEHIND", "DIVERGED"}:
        return "FULL_REVIEW"
    return "INVESTIGATE_UNKNOWN"


def run_cycle(
    client: Any,
    repository: str,
    pr_number: int,
    *,
    accepted_head_sha: str | None = None,
    previous_failed_source: dict[str, Any] | None = None,
    review_result: dict[str, Any] | None = None,
    continuity_result: dict[str, Any] | None = None,
    reviewer_name: str = "external-reviewer",
    reviewer_model: str | None = None,
    max_total_patch_bytes: int = DEFAULT_MAX_TOTAL_PATCH_BYTES,
    max_file_patch_bytes: int = DEFAULT_MAX_FILE_PATCH_BYTES,
    max_thread_bytes: int = DEFAULT_MAX_THREAD_BYTES,
    max_total_thread_bytes: int = DEFAULT_MAX_TOTAL_THREAD_BYTES,
    max_threads: int = DEFAULT_MAX_THREADS,
) -> dict[str, Any]:
    """Run one deterministic read-only PR attention cycle.

    This is orchestration only. It composes the existing V1.11 collectors, handoff
    contracts, validators, and advisory gates without adding persistence or write
    authority. GitHub remains the live source of truth; prior checkpoints are
    explicit caller inputs.
    """

    if previous_failed_source is not None and accepted_head_sha is not None:
        raise ValueError("accepted_head_sha and previous_failed_source are mutually exclusive")
    if review_result is not None and accepted_head_sha is None:
        raise ValueError("review_result requires accepted_head_sha")
    if continuity_result is not None and previous_failed_source is None:
        raise ValueError("continuity_result requires previous_failed_source")
    if review_result is not None and continuity_result is not None:
        raise ValueError("ordinary and continuity review results cannot be supplied together")

    snapshot_obj = collect_snapshot(client, repository, pr_number, accepted_head_sha=accepted_head_sha)
    snapshot = snapshot_obj.to_dict()

    if previous_failed_source is not None:
        checkpoint = failed_checkpoint_from_bundle(previous_failed_source)
        packet = collect_lineage_rereview_packet(
            client,
            repository,
            pr_number,
            previous_failed_source,
            expected_head_sha=snapshot_obj.head_sha,
            max_total_patch_bytes=max_total_patch_bytes or DEFAULT_CONTINUITY_MAX_TOTAL_PATCH_BYTES,
            max_file_patch_bytes=max_file_patch_bytes or DEFAULT_CONTINUITY_MAX_FILE_PATCH_BYTES,
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

        next_action = _continuity_next_action(packet, gate)
        return {
            "schema_version": 1,
            "kind": "PR_ATTENTION_CYCLE",
            "repository": repository,
            "pr_number": pr_number,
            "head_sha": snapshot_obj.head_sha,
            "attention": snapshot_obj.attention,
            "review_mode": "CONTINUITY",
            "next_action": next_action,
            "gate_status": gate.get("status") if gate is not None else "NOT_RUN",
            "merge_candidate": bool(gate is not None and gate.get("status") == "READY_TO_MERGE"),
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

    if accepted_head_sha is not None:
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

    next_action = _ordinary_next_action(snapshot, packet_dict, gate_dict)
    return {
        "schema_version": 1,
        "kind": "PR_ATTENTION_CYCLE",
        "repository": repository,
        "pr_number": pr_number,
        "head_sha": snapshot_obj.head_sha,
        "attention": snapshot_obj.attention,
        "review_mode": _ordinary_mode(snapshot, accepted_head_sha),
        "next_action": next_action,
        "gate_status": gate_dict.get("status") if gate_dict is not None else "NOT_RUN",
        "merge_candidate": bool(
            (gate_dict is not None and gate_dict.get("status") == "READY_TO_MERGE")
            or (gate_dict is None and next_action == "MERGE_CANDIDATE")
        ),
        "snapshot": snapshot,
        "review_packet": packet_dict,
        "review_result_template": template,
        "review_envelope": envelope,
        "review_validation": validation_dict,
        "integration_gate": gate_dict,
        "evidence_bundle": evidence_bundle,
        "checkpoint": checkpoint,
    }
