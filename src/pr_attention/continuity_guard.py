from __future__ import annotations

from typing import Any

from .continuity import (
    CHECKPOINT_KIND,
    _require_checkpoint,
    _valid_sha,
    build_lineage_rereview_packet,
    failed_checkpoint_from_evidence_bundle,
    failed_checkpoint_from_rereview_bundle as _core_failed_checkpoint_from_rereview_bundle,
    lineage_packet_sha256,
    validate_lineage_result as _core_validate_lineage_result,
)
from .github import GitHubClient, GitHubError


def failed_checkpoint_from_rereview_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Reuse a legacy V1.9 FAIL only when its full repair delta was actually reviewed."""
    evidence = bundle.get("evidence")
    packet = evidence.get("rereview_packet") if isinstance(evidence, dict) else None
    result = evidence.get("rereview_result") if isinstance(evidence, dict) else None
    if not isinstance(packet, dict) or not isinstance(result, dict):
        return _core_failed_checkpoint_from_rereview_bundle(bundle)
    if (
        packet.get("incremental_eligible") is not True
        or packet.get("coverage") != "COMPLETE"
        or packet.get("complete") is not True
    ):
        raise ValueError("failed re-review packet is not a complete reusable checkpoint")
    delta_paths = {
        item.get("path")
        for item in packet.get("repair_delta_files", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str) and item.get("path")
    }
    reviewed = result.get("reviewed_files")
    if not isinstance(reviewed, list) or any(not isinstance(path, str) or not path for path in reviewed):
        raise ValueError("failed re-review reviewed_files are invalid")
    if set(reviewed) != delta_paths:
        raise ValueError("failed re-review did not review every repair-delta file")
    return _core_failed_checkpoint_from_rereview_bundle(bundle)


def failed_checkpoint_from_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    kind = bundle.get("kind")
    if kind == "PR_ATTENTION_EVIDENCE_BUNDLE":
        return failed_checkpoint_from_evidence_bundle(bundle)
    if kind == "PR_ATTENTION_REREVIEW_EVIDENCE_BUNDLE":
        return failed_checkpoint_from_rereview_bundle(bundle)
    if kind == CHECKPOINT_KIND:
        _require_checkpoint(bundle)
        return dict(bundle)
    raise ValueError("unsupported failed-review source kind")


def collect_lineage_rereview_packet(
    client: GitHubClient,
    repo: str,
    number: int,
    previous_source: dict[str, Any],
    *,
    expected_head_sha: str | None = None,
    **budgets: int,
) -> dict[str, Any]:
    checkpoint = failed_checkpoint_from_bundle(previous_source)
    if checkpoint["repository"] != repo or checkpoint["pr_number"] != number:
        raise ValueError("failed-review checkpoint repository/PR does not match requested pull request")
    initial_pr = client.pull_request(repo, number)
    current_head = str(((initial_pr.get("head") or {}).get("sha") or ""))
    if not _valid_sha(current_head):
        raise GitHubError("GitHub pull request did not expose a valid current head SHA")
    compare_payload: dict[str, Any] | None = None
    if current_head != checkpoint["failed_reviewed_checkpoint_sha"]:
        try:
            compare_payload = client.compare(repo, checkpoint["failed_reviewed_checkpoint_sha"], current_head)
        except GitHubError:
            compare_payload = None
    try:
        threads: list[dict[str, Any]] | None = client.review_threads(repo, number)
    except GitHubError:
        threads = None
    final_pr = client.pull_request(repo, number)
    final_head = str(((final_pr.get("head") or {}).get("sha") or "")) or current_head
    return build_lineage_rereview_packet(
        checkpoint,
        compare_payload,
        threads,
        current_head_sha=current_head,
        final_head_sha=final_head,
        expected_head_sha=expected_head_sha,
        **budgets,
    )


def _gate_compatible(validation: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    payload = dict(validation)
    payload["kind"] = "PR_ATTENTION_REREVIEW_VALIDATION"
    payload["previous_reviewed_head_sha"] = packet.get("previous_failed_checkpoint_sha")
    payload["rereview_packet_sha256"] = lineage_packet_sha256(packet)
    return payload


def validate_lineage_result(
    packet: dict[str, Any],
    result: dict[str, Any],
    *,
    live_head_sha: str | None = None,
) -> dict[str, Any]:
    """Do not let an incompletely reviewed PASS or FAIL advance semantic authority/lineage."""
    validation = _core_validate_lineage_result(packet, result, live_head_sha=live_head_sha)
    if not validation.get("valid") or result.get("verdict") not in {"PASS", "FAIL"}:
        return _gate_compatible(validation, packet)

    reasons: list[str] = []
    if (
        packet.get("incremental_eligible") is not True
        or packet.get("coverage") != "COMPLETE"
        or packet.get("thread_coverage") != "COMPLETE"
        or packet.get("complete") is not True
    ):
        reasons.append(f"{result['verdict']} requires complete patch and thread continuity evidence")

    delta_paths = {
        item.get("path")
        for item in packet.get("repair_delta_files", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str) and item.get("path")
    }
    reviewed = result.get("reviewed_files")
    if not isinstance(reviewed, list) or set(reviewed) != delta_paths:
        reasons.append(f"{result['verdict']} requires every repair-delta file to be reviewed")

    if reasons:
        validation = dict(validation)
        validation.update(
            valid=False,
            status="INVALID",
            next_failed_checkpoint=None,
            reasons=reasons,
        )
    return _gate_compatible(validation, packet)
