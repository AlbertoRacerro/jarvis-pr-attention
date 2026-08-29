from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from .evidence_bundle import verify_evidence_bundle
from .github import GitHubClient, GitHubError

REREVIEW_PACKET_SCHEMA_VERSION = 1
REREVIEW_PACKET_KIND = "PR_ATTENTION_REREVIEW_PACKET"
CONTENT_TRUST = "UNTRUSTED_REPOSITORY_CONTENT"
DEFAULT_MAX_TOTAL_PATCH_BYTES = 120_000
DEFAULT_MAX_FILE_PATCH_BYTES = 30_000
MAX_PACKET_BUDGET = 5_000_000
_FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

_DIGEST_FIELDS = (
    "schema_version",
    "kind",
    "repository",
    "pr_number",
    "source_bundle_sha256",
    "accepted_head_sha",
    "previous_reviewed_head_sha",
    "head_sha",
    "final_head_sha",
    "relation",
    "review_scope",
    "incremental_eligible",
    "content_trust",
    "coverage",
    "complete",
    "max_total_patch_bytes",
    "max_file_patch_bytes",
    "included_patch_bytes",
    "prior_packet_sha256",
    "prior_blocking_findings",
    "finding_context_files",
    "repair_delta_files",
    "scope_expansion_files",
    "global_invariants_recheck_required",
)


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def rereview_packet_sha256(packet: dict[str, Any]) -> str:
    payload = {key: packet.get(key) for key in _DIGEST_FIELDS}
    return "sha256:" + hashlib.sha256(_canonical_json(payload)).hexdigest()


def _validate_budget(name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > MAX_PACKET_BUDGET:
        raise ValueError(f"{name} must be between 1 and {MAX_PACKET_BUDGET} bytes")


def _truncate_utf8(text: str, byte_limit: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= byte_limit:
        return text
    return raw[:byte_limit].decode("utf-8", errors="ignore")


def _strict_pr(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(_FULL_SHA.fullmatch(value))


def _copy_finding(finding: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": finding.get("id"),
        "severity": finding.get("severity"),
        "blocking": finding.get("blocking"),
        "title": finding.get("title"),
        "detail": finding.get("detail"),
        "path": finding.get("path"),
        "line": finding.get("line"),
    }


def _checkpoint(bundle: dict[str, Any]) -> dict[str, Any]:
    verification = verify_evidence_bundle(bundle)
    if not verification.valid:
        raise ValueError("previous evidence bundle is invalid: " + "; ".join(verification.reasons))
    if bundle.get("phase") != "INTEGRATION_EVALUATED":
        raise ValueError("previous evidence bundle must be INTEGRATION_EVALUATED")

    evidence = bundle.get("evidence")
    if not isinstance(evidence, dict):
        raise ValueError("previous evidence bundle has no evidence object")
    packet = evidence.get("review_packet")
    result = evidence.get("review_result")
    validation = evidence.get("review_validation")
    gate = evidence.get("integration_gate")
    if not all(isinstance(item, dict) for item in (packet, result, validation, gate)):
        raise ValueError("previous evidence bundle lacks review packet/result/validation/gate")
    if validation.get("valid") is not True or validation.get("status") != "VALID_FAIL" or result.get("verdict") != "FAIL":
        raise ValueError("incremental re-review requires a previously valid semantic FAIL")
    if gate.get("status") != "REPAIR":
        raise ValueError("incremental re-review requires a previous deterministic REPAIR gate")
    if packet.get("coverage") != "COMPLETE" or packet.get("complete") is not True:
        raise ValueError("previous FAIL is not reusable because its review packet was incomplete")
    previous_head = packet.get("head_sha")
    if not _valid_sha(previous_head) or packet.get("final_head_sha") != previous_head:
        raise ValueError("previous review packet head binding is invalid or stale")
    if validation.get("head_sha") != previous_head or validation.get("live_head_sha") != previous_head:
        raise ValueError("previous FAIL was not live-bound to its exact reviewed head")

    packet_files = packet.get("files")
    reviewed_files = result.get("reviewed_files")
    if not isinstance(packet_files, list) or not isinstance(reviewed_files, list):
        raise ValueError("previous review file evidence is invalid")
    packet_paths = [item.get("path") for item in packet_files if isinstance(item, dict) and isinstance(item.get("path"), str)]
    if len(packet_paths) != len(packet_files) or len(packet_paths) != len(set(packet_paths)):
        raise ValueError("previous review packet file inventory is invalid")
    if set(reviewed_files) != set(packet_paths):
        raise ValueError("previous FAIL is not a reusable checkpoint because not every packet file was reviewed")

    findings = result.get("findings")
    if not isinstance(findings, list):
        raise ValueError("previous review findings are invalid")
    blocking = [_copy_finding(item) for item in findings if isinstance(item, dict) and item.get("blocking") is True]
    if not blocking:
        raise ValueError("previous FAIL has no blocking findings")
    ids = [item.get("id") for item in blocking]
    if any(not isinstance(item, str) or not item for item in ids) or len(ids) != len(set(ids)):
        raise ValueError("previous blocking finding IDs are invalid")

    bundle_digest = bundle.get("bundle_sha256")
    prior_packet_digest = validation.get("packet_sha256")
    if not isinstance(bundle_digest, str) or not _DIGEST.fullmatch(bundle_digest):
        raise ValueError("previous bundle digest is invalid")
    if not isinstance(prior_packet_digest, str) or not _DIGEST.fullmatch(prior_packet_digest):
        raise ValueError("previous review packet digest is invalid")

    file_by_path = {item["path"]: item for item in packet_files}
    return {
        "repository": bundle.get("repository"),
        "pr_number": bundle.get("pr_number"),
        "source_bundle_sha256": bundle_digest,
        "accepted_head_sha": packet.get("accepted_head_sha"),
        "previous_reviewed_head_sha": previous_head,
        "prior_packet_sha256": prior_packet_digest,
        "reviewed_paths": packet_paths,
        "file_by_path": file_by_path,
        "blocking_findings": blocking,
    }


def _bounded_file(
    item: dict[str, Any],
    *,
    remaining: int,
    max_file_patch_bytes: int,
) -> tuple[dict[str, Any], int, bool]:
    path = str(item.get("filename") or item.get("path") or "")
    patch = item.get("patch")
    original_bytes = len(patch.encode("utf-8")) if isinstance(patch, str) else 0
    included_patch: str | None = None
    included_bytes = 0
    truncated = False
    omission_reason: str | None = None
    if not isinstance(patch, str):
        omission_reason = "patch-unavailable"
    elif remaining <= 0:
        truncated = True
        omission_reason = "total-budget-exhausted"
    else:
        allowance = min(max_file_patch_bytes, remaining)
        included_patch = _truncate_utf8(patch, allowance)
        included_bytes = len(included_patch.encode("utf-8"))
        if included_bytes < original_bytes:
            truncated = True
            omission_reason = "file-or-total-budget"
    return (
        {
            "path": path,
            "status": item.get("status") or "unknown",
            "additions": int(item.get("additions") or 0),
            "deletions": int(item.get("deletions") or 0),
            "changes": int(item.get("changes") or 0),
            "previous_path": item.get("previous_filename") or item.get("previous_path"),
            "patch": included_patch,
            "original_patch_bytes": original_bytes,
            "included_patch_bytes": included_bytes,
            "truncated": truncated,
            "omission_reason": omission_reason,
        },
        included_bytes,
        isinstance(patch, str) and not truncated,
    )


def _terminal_packet(
    checkpoint: dict[str, Any],
    *,
    head_sha: str,
    final_head_sha: str,
    relation: str,
    coverage: str,
    reasons: list[str],
    max_total_patch_bytes: int,
    max_file_patch_bytes: int,
) -> dict[str, Any]:
    packet = {
        "schema_version": REREVIEW_PACKET_SCHEMA_VERSION,
        "kind": REREVIEW_PACKET_KIND,
        "repository": checkpoint["repository"],
        "pr_number": checkpoint["pr_number"],
        "source_bundle_sha256": checkpoint["source_bundle_sha256"],
        "accepted_head_sha": checkpoint["accepted_head_sha"],
        "previous_reviewed_head_sha": checkpoint["previous_reviewed_head_sha"],
        "head_sha": head_sha,
        "final_head_sha": final_head_sha,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "relation": relation,
        "review_scope": "FULL" if relation in {"BEHIND", "DIVERGED"} else "UNKNOWN",
        "incremental_eligible": False,
        "content_trust": CONTENT_TRUST,
        "coverage": coverage,
        "complete": False,
        "max_total_patch_bytes": max_total_patch_bytes,
        "max_file_patch_bytes": max_file_patch_bytes,
        "included_patch_bytes": 0,
        "prior_packet_sha256": checkpoint["prior_packet_sha256"],
        "prior_blocking_findings": checkpoint["blocking_findings"],
        "finding_context_files": [],
        "repair_delta_files": [],
        "scope_expansion_files": [],
        "global_invariants_recheck_required": True,
        "reasons": reasons,
    }
    packet["rereview_packet_sha256"] = rereview_packet_sha256(packet)
    return packet


def build_rereview_packet(
    previous_bundle: dict[str, Any],
    compare_payload: dict[str, Any] | None,
    *,
    current_head_sha: str,
    final_head_sha: str | None = None,
    expected_head_sha: str | None = None,
    max_total_patch_bytes: int = DEFAULT_MAX_TOTAL_PATCH_BYTES,
    max_file_patch_bytes: int = DEFAULT_MAX_FILE_PATCH_BYTES,
) -> dict[str, Any]:
    _validate_budget("max_total_patch_bytes", max_total_patch_bytes)
    _validate_budget("max_file_patch_bytes", max_file_patch_bytes)
    checkpoint = _checkpoint(previous_bundle)
    if not _valid_sha(current_head_sha):
        raise ValueError("current head SHA is invalid")
    observed_final = final_head_sha or current_head_sha
    if not _valid_sha(observed_final):
        raise ValueError("final head SHA is invalid")

    if expected_head_sha is not None and expected_head_sha != current_head_sha:
        return _terminal_packet(
            checkpoint,
            head_sha=current_head_sha,
            final_head_sha=observed_final,
            relation="UNKNOWN",
            coverage="UNKNOWN",
            reasons=["current head no longer matches caller-bound expected head"],
            max_total_patch_bytes=max_total_patch_bytes,
            max_file_patch_bytes=max_file_patch_bytes,
        )
    if observed_final != current_head_sha:
        return _terminal_packet(
            checkpoint,
            head_sha=current_head_sha,
            final_head_sha=observed_final,
            relation="UNKNOWN",
            coverage="UNKNOWN",
            reasons=["pull request head changed while re-review packet was collected"],
            max_total_patch_bytes=max_total_patch_bytes,
            max_file_patch_bytes=max_file_patch_bytes,
        )
    if current_head_sha == checkpoint["previous_reviewed_head_sha"]:
        return _terminal_packet(
            checkpoint,
            head_sha=current_head_sha,
            final_head_sha=observed_final,
            relation="CURRENT",
            coverage="NONE",
            reasons=["no repair delta exists after the failed reviewed head"],
            max_total_patch_bytes=max_total_patch_bytes,
            max_file_patch_bytes=max_file_patch_bytes,
        )
    if not isinstance(compare_payload, dict):
        return _terminal_packet(
            checkpoint,
            head_sha=current_head_sha,
            final_head_sha=observed_final,
            relation="UNKNOWN",
            coverage="UNKNOWN",
            reasons=["GitHub compare evidence from failed reviewed head to current head is unavailable"],
            max_total_patch_bytes=max_total_patch_bytes,
            max_file_patch_bytes=max_file_patch_bytes,
        )

    status = str(compare_payload.get("status") or "").lower()
    relation = {
        "ahead": "AHEAD",
        "behind": "BEHIND",
        "diverged": "DIVERGED",
        "identical": "CURRENT",
    }.get(status, "UNKNOWN")
    raw_files = compare_payload.get("files")
    if relation != "AHEAD":
        return _terminal_packet(
            checkpoint,
            head_sha=current_head_sha,
            final_head_sha=observed_final,
            relation=relation,
            coverage="NONE" if relation in {"BEHIND", "DIVERGED", "CURRENT"} else "UNKNOWN",
            reasons=["previous failed head is not a strict ancestor of the current head; incremental re-review is unsafe"],
            max_total_patch_bytes=max_total_patch_bytes,
            max_file_patch_bytes=max_file_patch_bytes,
        )
    if not isinstance(raw_files, list):
        return _terminal_packet(
            checkpoint,
            head_sha=current_head_sha,
            final_head_sha=observed_final,
            relation=relation,
            coverage="UNKNOWN",
            reasons=["GitHub compare file evidence is unavailable"],
            max_total_patch_bytes=max_total_patch_bytes,
            max_file_patch_bytes=max_file_patch_bytes,
        )
    if len(raw_files) >= 300:
        return _terminal_packet(
            checkpoint,
            head_sha=current_head_sha,
            final_head_sha=observed_final,
            relation=relation,
            coverage="NONE",
            reasons=["GitHub compare reached the 300-file evidence cap; full semantic review is required"],
            max_total_patch_bytes=max_total_patch_bytes,
            max_file_patch_bytes=max_file_patch_bytes,
        )

    raw_files = sorted(raw_files, key=lambda item: str(item.get("filename") or ""))
    if any(not isinstance(item, dict) or not item.get("filename") for item in raw_files):
        return _terminal_packet(
            checkpoint,
            head_sha=current_head_sha,
            final_head_sha=observed_final,
            relation=relation,
            coverage="UNKNOWN",
            reasons=["GitHub compare returned an invalid repair file entry"],
            max_total_patch_bytes=max_total_patch_bytes,
            max_file_patch_bytes=max_file_patch_bytes,
        )

    remaining = max_total_patch_bytes
    included_total = 0
    complete = True
    repair_files: list[dict[str, Any]] = []
    for item in raw_files:
        bounded, used, item_complete = _bounded_file(item, remaining=remaining, max_file_patch_bytes=max_file_patch_bytes)
        repair_files.append(bounded)
        remaining -= used
        included_total += used
        complete = complete and item_complete

    finding_paths = sorted({
        finding.get("path")
        for finding in checkpoint["blocking_findings"]
        if isinstance(finding.get("path"), str) and finding.get("path")
    })
    finding_context_files: list[dict[str, Any]] = []
    for path in finding_paths:
        source = checkpoint["file_by_path"].get(path)
        if not isinstance(source, dict):
            complete = False
            continue
        bounded, used, item_complete = _bounded_file(source, remaining=remaining, max_file_patch_bytes=max_file_patch_bytes)
        finding_context_files.append(bounded)
        remaining -= used
        included_total += used
        complete = complete and item_complete

    previous_paths = set(checkpoint["reviewed_paths"])
    expansion = sorted({
        str(item.get("filename"))
        for item in raw_files
        if item.get("filename") and str(item.get("filename")) not in previous_paths
    })

    if complete:
        coverage = "COMPLETE"
        reasons = [
            "all repair-delta patches and prior blocking-finding context are included within configured budgets",
            "unchanged evidence from the complete failed review checkpoint may be reused, but global invariants must still be rechecked",
        ]
    elif included_total > 0:
        coverage = "PARTIAL"
        reasons = ["re-review evidence is missing or truncated; PASS is not permitted"]
    else:
        coverage = "NONE"
        reasons = ["no patch evidence could be included; incremental re-review is not sufficient"]

    packet = {
        "schema_version": REREVIEW_PACKET_SCHEMA_VERSION,
        "kind": REREVIEW_PACKET_KIND,
        "repository": checkpoint["repository"],
        "pr_number": checkpoint["pr_number"],
        "source_bundle_sha256": checkpoint["source_bundle_sha256"],
        "accepted_head_sha": checkpoint["accepted_head_sha"],
        "previous_reviewed_head_sha": checkpoint["previous_reviewed_head_sha"],
        "head_sha": current_head_sha,
        "final_head_sha": observed_final,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "relation": relation,
        "review_scope": "REREVIEW_DELTA_PLUS_FINDINGS",
        "incremental_eligible": True,
        "content_trust": CONTENT_TRUST,
        "coverage": coverage,
        "complete": complete,
        "max_total_patch_bytes": max_total_patch_bytes,
        "max_file_patch_bytes": max_file_patch_bytes,
        "included_patch_bytes": included_total,
        "prior_packet_sha256": checkpoint["prior_packet_sha256"],
        "prior_blocking_findings": checkpoint["blocking_findings"],
        "finding_context_files": finding_context_files,
        "repair_delta_files": repair_files,
        "scope_expansion_files": expansion,
        "global_invariants_recheck_required": True,
        "reasons": reasons,
    }
    packet["rereview_packet_sha256"] = rereview_packet_sha256(packet)
    return packet


def collect_rereview_packet(
    client: GitHubClient,
    repo: str,
    number: int,
    previous_bundle: dict[str, Any],
    *,
    expected_head_sha: str | None = None,
    max_total_patch_bytes: int = DEFAULT_MAX_TOTAL_PATCH_BYTES,
    max_file_patch_bytes: int = DEFAULT_MAX_FILE_PATCH_BYTES,
) -> dict[str, Any]:
    checkpoint = _checkpoint(previous_bundle)
    if checkpoint["repository"] != repo or checkpoint["pr_number"] != number:
        raise ValueError("previous evidence bundle repository/PR does not match requested pull request")

    initial_pr = client.pull_request(repo, number)
    current_head = str(((initial_pr.get("head") or {}).get("sha") or ""))
    if not _valid_sha(current_head):
        raise GitHubError("GitHub pull request did not expose a valid current head SHA")

    compare_payload: dict[str, Any] | None = None
    if current_head != checkpoint["previous_reviewed_head_sha"]:
        try:
            compare_payload = client.compare(repo, checkpoint["previous_reviewed_head_sha"], current_head)
        except GitHubError:
            compare_payload = None

    final_pr = client.pull_request(repo, number)
    final_head = str(((final_pr.get("head") or {}).get("sha") or "")) or current_head
    return build_rereview_packet(
        previous_bundle,
        compare_payload,
        current_head_sha=current_head,
        final_head_sha=final_head,
        expected_head_sha=expected_head_sha,
        max_total_patch_bytes=max_total_patch_bytes,
        max_file_patch_bytes=max_file_patch_bytes,
    )
