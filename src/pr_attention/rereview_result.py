from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .rereview_packet import MAX_REREVIEW_GENERATIONS, REREVIEW_PACKET_KIND, rereview_packet_sha256

REREVIEW_RESULT_SCHEMA_VERSION = 1
REREVIEW_VALIDATION_SCHEMA_VERSION = 1
REREVIEW_VALIDATION_KIND = "PR_ATTENTION_REREVIEW_VALIDATION"

RereviewVerdict = Literal["PASS", "FAIL", "NEEDS_HUMAN"]
RereviewValidationStatus = Literal["VALID_PASS", "VALID_FAIL", "VALID_NEEDS_HUMAN", "STALE", "INVALID"]

_FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_HIGH_SEVERITIES = {"P0", "P1", "P2"}
_ALL_SEVERITIES = _HIGH_SEVERITIES | {"P3"}
_ALL_VERDICTS = {"PASS", "FAIL", "NEEDS_HUMAN"}


@dataclass(frozen=True)
class RereviewResultValidation:
    schema_version: int
    kind: str
    valid: bool
    status: RereviewValidationStatus
    repository: str | None
    pr_number: int | None
    previous_reviewed_head_sha: str | None
    head_sha: str | None
    rereview_packet_sha256: str | None
    verdict: str | None
    live_head_sha: str | None = None
    resolved_finding_ids: list[str] = field(default_factory=list)
    remaining_finding_ids: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_rereview_result_template(
    packet: dict[str, Any],
    *,
    reviewer_name: str,
    reviewer_model: str | None = None,
) -> dict[str, Any]:
    if not isinstance(reviewer_name, str) or not reviewer_name.strip():
        raise ValueError("reviewer_name must be non-empty")
    if reviewer_model is not None and (not isinstance(reviewer_model, str) or not reviewer_model.strip()):
        raise ValueError("reviewer_model must be non-empty when supplied")
    _validate_packet_shape(packet)
    reviewer: dict[str, Any] = {"name": reviewer_name.strip()}
    if reviewer_model is not None:
        reviewer["model"] = reviewer_model.strip()
    prior_ids = [item["id"] for item in packet["prior_blocking_findings"]]
    return {
        "schema_version": REREVIEW_RESULT_SCHEMA_VERSION,
        "repository": packet["repository"],
        "pr_number": packet["pr_number"],
        "previous_reviewed_head_sha": packet["previous_reviewed_head_sha"],
        "head_sha": packet["head_sha"],
        "rereview_packet_sha256": rereview_packet_sha256(packet),
        "reviewer": reviewer,
        "verdict": "NEEDS_HUMAN",
        "reviewed_files": [],
        "rechecked_finding_ids": [],
        "resolved_finding_ids": [],
        "remaining_finding_ids": prior_ids,
        "global_invariants_rechecked": False,
        "findings": [],
        "notes": [],
    }


def _strict_pr(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(_FULL_SHA.fullmatch(value))


def _valid_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(_DIGEST.fullmatch(value))


def _strict_positive_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _strict_nonnegative_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _paths(items: Any, label: str, reasons: list[str]) -> list[str]:
    if not isinstance(items, list):
        reasons.append(f"{label} must be a list")
        return []
    values: list[str] = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not item.get("path"):
            reasons.append(f"{label} contains an invalid file entry")
            continue
        values.append(item["path"])
    if len(values) != len(set(values)):
        reasons.append(f"{label} contains duplicate paths")
    return values


def _validate_v11_lineage_and_threads(packet: dict[str, Any], reasons: list[str], *, complete: Any) -> None:
    source_kind = packet.get("source_checkpoint_kind")
    if source_kind is None:
        return
    if source_kind not in {"FULL_REVIEW_FAIL", "REREVIEW_FAIL"}:
        reasons.append("re-review packet source_checkpoint_kind is invalid")

    accepted = packet.get("accepted_head_sha")
    baseline = packet.get("accepted_semantic_baseline_sha")
    if not _valid_sha(baseline) or baseline != accepted:
        reasons.append("re-review packet accepted semantic baseline must equal accepted_head_sha")

    previous = packet.get("previous_reviewed_head_sha")
    failed_checkpoint = packet.get("failed_reviewed_checkpoint_sha")
    if not _valid_sha(failed_checkpoint) or failed_checkpoint != previous:
        reasons.append("re-review packet failed reviewed checkpoint must equal previous_reviewed_head_sha")

    generation = packet.get("lineage_generation")
    if (
        not isinstance(generation, int)
        or isinstance(generation, bool)
        or generation < 1
        or generation > MAX_REREVIEW_GENERATIONS
    ):
        reasons.append("re-review packet lineage_generation is invalid")

    latest = packet.get("latest_rereview_checkpoint_sha")
    if source_kind == "FULL_REVIEW_FAIL" and latest is not None:
        reasons.append("full-review FAIL source must not claim a previous re-review checkpoint")
    if source_kind == "REREVIEW_FAIL" and (not _valid_sha(latest) or latest != previous):
        reasons.append("re-review FAIL source must bind latest_rereview_checkpoint_sha to previous reviewed head")

    prior_findings = packet.get("prior_blocking_findings")
    unresolved_lineage = packet.get("unresolved_finding_lineage")
    if unresolved_lineage != prior_findings:
        reasons.append("unresolved_finding_lineage must exactly match active prior blocking findings")
    if isinstance(prior_findings, list) and isinstance(generation, int) and not isinstance(generation, bool):
        for finding in prior_findings:
            if not isinstance(finding, dict):
                continue
            finding_id = finding.get("id") or "<unknown>"
            first_seen = finding.get("first_seen_head_sha")
            last_failed = finding.get("last_failed_head_sha")
            finding_generation = finding.get("lineage_generation")
            if not _valid_sha(first_seen):
                reasons.append(f"prior finding {finding_id} first_seen_head_sha is invalid")
            if not _valid_sha(last_failed):
                reasons.append(f"prior finding {finding_id} last_failed_head_sha is invalid")
            if (
                not isinstance(finding_generation, int)
                or isinstance(finding_generation, bool)
                or finding_generation < 0
                or finding_generation >= generation
            ):
                reasons.append(f"prior finding {finding_id} lineage_generation is invalid")

    thread_total_budget = _strict_positive_int(packet.get("max_total_thread_bytes"))
    thread_body_budget = _strict_positive_int(packet.get("max_thread_body_bytes"))
    included_thread_bytes = _strict_nonnegative_int(packet.get("included_thread_bytes"))
    if thread_total_budget is None or thread_body_budget is None:
        reasons.append("re-review packet thread budgets must be positive integers")
    elif thread_body_budget > thread_total_budget:
        reasons.append("re-review packet per-thread body budget exceeds total thread budget")
    if included_thread_bytes is None:
        reasons.append("re-review packet included_thread_bytes is invalid")
    elif thread_total_budget is not None and included_thread_bytes > thread_total_budget:
        reasons.append("re-review packet included_thread_bytes exceeds total thread budget")

    thread_coverage = packet.get("review_thread_coverage")
    if thread_coverage not in {"COMPLETE", "PARTIAL", "UNKNOWN"}:
        reasons.append("re-review packet review_thread_coverage is invalid")
    if complete is True and thread_coverage != "COMPLETE":
        reasons.append("complete re-review packet requires COMPLETE review-thread coverage")

    threads = packet.get("review_threads")
    if not isinstance(threads, list):
        reasons.append("re-review packet review_threads must be a list")
        threads = []
    thread_ids: list[str] = []
    observed_thread_bytes = 0
    for thread in threads:
        if not isinstance(thread, dict):
            reasons.append("review_threads contains an invalid entry")
            continue
        thread_id = thread.get("id")
        path = thread.get("path")
        author = thread.get("author")
        body = thread.get("body")
        original_bytes = _strict_nonnegative_int(thread.get("original_body_bytes"))
        included_bytes = _strict_nonnegative_int(thread.get("included_body_bytes"))
        truncated = thread.get("truncated")
        if not isinstance(thread_id, str) or not thread_id:
            reasons.append("review thread requires a non-empty id")
        else:
            thread_ids.append(thread_id)
        if path is not None and (not isinstance(path, str) or not path):
            reasons.append(f"review thread {thread_id or '<unknown>'} path is invalid")
        if author is not None and (not isinstance(author, str) or not author):
            reasons.append(f"review thread {thread_id or '<unknown>'} author is invalid")
        if not isinstance(body, str):
            reasons.append(f"review thread {thread_id or '<unknown>'} body is invalid")
            body_bytes = None
        else:
            body_bytes = len(body.encode("utf-8"))
        if original_bytes is None or included_bytes is None:
            reasons.append(f"review thread {thread_id or '<unknown>'} byte accounting is invalid")
        else:
            observed_thread_bytes += included_bytes
            if body_bytes is not None and included_bytes != body_bytes:
                reasons.append(f"review thread {thread_id or '<unknown>'} included byte count does not match body")
            if original_bytes < included_bytes:
                reasons.append(f"review thread {thread_id or '<unknown>'} original bytes are smaller than included bytes")
            if thread_body_budget is not None and included_bytes > thread_body_budget:
                reasons.append(f"review thread {thread_id or '<unknown>'} exceeds per-thread body budget")
        if not isinstance(truncated, bool):
            reasons.append(f"review thread {thread_id or '<unknown>'} truncated flag is invalid")
        elif original_bytes is not None and included_bytes is not None and truncated is not (included_bytes < original_bytes):
            reasons.append(f"review thread {thread_id or '<unknown>'} truncated flag is inconsistent with byte counts")
        if thread.get("content_trust") != "UNTRUSTED_REPOSITORY_CONTENT":
            reasons.append(f"review thread {thread_id or '<unknown>'} content trust marker is invalid")
    if len(thread_ids) != len(set(thread_ids)):
        reasons.append("review thread IDs must be unique")
    if included_thread_bytes is not None and observed_thread_bytes != included_thread_bytes:
        reasons.append("included_thread_bytes does not equal the sum of included review-thread bodies")
    if thread_coverage == "COMPLETE" and any(isinstance(item, dict) and item.get("truncated") is True for item in threads):
        reasons.append("COMPLETE review-thread coverage cannot contain truncated thread evidence")


def _validate_packet_shape(packet: dict[str, Any]) -> None:
    reasons: list[str] = []
    if packet.get("schema_version") != 1 or isinstance(packet.get("schema_version"), bool):
        reasons.append("unsupported re-review packet schema_version")
    if packet.get("kind") != REREVIEW_PACKET_KIND:
        reasons.append("re-review packet kind is invalid")
    if not isinstance(packet.get("repository"), str) or "/" not in packet.get("repository", ""):
        reasons.append("re-review packet repository is invalid")
    if _strict_pr(packet.get("pr_number")) is None:
        reasons.append("re-review packet pr_number is invalid")
    for field_name in ("accepted_head_sha", "previous_reviewed_head_sha", "head_sha", "final_head_sha"):
        if not _valid_sha(packet.get(field_name)):
            reasons.append(f"re-review packet {field_name} is invalid")
    for field_name in ("source_bundle_sha256", "prior_packet_sha256"):
        if not _valid_digest(packet.get(field_name)):
            reasons.append(f"re-review packet {field_name} is invalid")
    supplied = packet.get("rereview_packet_sha256")
    if not _valid_digest(supplied) or supplied != rereview_packet_sha256(packet):
        reasons.append("re-review packet digest is invalid")
    if packet.get("content_trust") != "UNTRUSTED_REPOSITORY_CONTENT":
        reasons.append("re-review packet content_trust marker is invalid")

    relation = packet.get("relation")
    review_scope = packet.get("review_scope")
    eligible = packet.get("incremental_eligible")
    coverage = packet.get("coverage")
    complete = packet.get("complete")
    if relation not in {"AHEAD", "BEHIND", "DIVERGED", "CURRENT", "UNKNOWN"}:
        reasons.append("re-review packet relation is invalid")
    if coverage not in {"COMPLETE", "PARTIAL", "NONE", "UNKNOWN"}:
        reasons.append("re-review packet coverage is invalid")
    if not isinstance(complete, bool) or not isinstance(eligible, bool):
        reasons.append("re-review packet completeness/eligibility flags are invalid")
    if eligible is True and (relation != "AHEAD" or review_scope != "REREVIEW_DELTA_PLUS_FINDINGS"):
        reasons.append("incrementally eligible re-review packet requires AHEAD + REREVIEW_DELTA_PLUS_FINDINGS")
    if complete is True and (eligible is not True or coverage != "COMPLETE"):
        reasons.append("complete re-review packet requires incremental eligibility and COMPLETE coverage")
    if coverage == "COMPLETE" and complete is not True:
        reasons.append("COMPLETE coverage requires complete=true")
    if packet.get("global_invariants_recheck_required") is not True:
        reasons.append("re-review packet must require global invariant recheck")

    total_budget = _strict_positive_int(packet.get("max_total_patch_bytes"))
    file_budget = _strict_positive_int(packet.get("max_file_patch_bytes"))
    included_bytes = packet.get("included_patch_bytes")
    if total_budget is None or file_budget is None:
        reasons.append("re-review packet patch budgets must be positive integers")
    if not isinstance(included_bytes, int) or isinstance(included_bytes, bool) or included_bytes < 0:
        reasons.append("re-review packet included_patch_bytes is invalid")
    elif total_budget is not None and included_bytes > total_budget:
        reasons.append("re-review packet included_patch_bytes exceeds total budget")

    delta_paths = _paths(packet.get("repair_delta_files"), "repair_delta_files", reasons)
    context_paths = _paths(packet.get("finding_context_files"), "finding_context_files", reasons)
    if eligible is True and not delta_paths:
        reasons.append("incrementally eligible re-review packet requires at least one repair-delta file")

    expansion = packet.get("scope_expansion_files")
    if not isinstance(expansion, list) or any(not isinstance(path, str) or not path for path in expansion):
        reasons.append("scope_expansion_files must be a list of non-empty strings")
    elif len(expansion) != len(set(expansion)):
        reasons.append("scope_expansion_files contains duplicates")
    elif not set(expansion).issubset(set(delta_paths)):
        reasons.append("scope_expansion_files must be a subset of repair-delta files")

    findings = packet.get("prior_blocking_findings")
    if not isinstance(findings, list) or not findings:
        reasons.append("re-review packet requires prior blocking findings")
        findings = []
    finding_ids: list[str] = []
    for finding in findings:
        if not isinstance(finding, dict):
            reasons.append("prior blocking finding entries must be objects")
            continue
        finding_id = finding.get("id")
        if not isinstance(finding_id, str) or not finding_id:
            reasons.append("prior blocking findings require non-empty IDs")
        else:
            finding_ids.append(finding_id)
        if finding.get("blocking") is not True:
            reasons.append(f"prior finding {finding_id or '<unknown>'} must be blocking")
        path = finding.get("path")
        if path is not None and (not isinstance(path, str) or path not in context_paths):
            if complete is True:
                reasons.append(f"complete re-review packet lacks prior context for finding {finding_id or '<unknown>'}")
    if len(finding_ids) != len(set(finding_ids)):
        reasons.append("prior blocking finding IDs must be unique")

    _validate_v11_lineage_and_threads(packet, reasons, complete=complete)
    if reasons:
        raise ValueError("; ".join(reasons))


def _invalid(packet: dict[str, Any], result: dict[str, Any], reasons: list[str], live_head_sha: str | None) -> RereviewResultValidation:
    return RereviewResultValidation(
        schema_version=REREVIEW_VALIDATION_SCHEMA_VERSION,
        kind=REREVIEW_VALIDATION_KIND,
        valid=False,
        status="INVALID",
        repository=packet.get("repository") if isinstance(packet.get("repository"), str) else None,
        pr_number=_strict_pr(packet.get("pr_number")),
        previous_reviewed_head_sha=packet.get("previous_reviewed_head_sha") if isinstance(packet.get("previous_reviewed_head_sha"), str) else None,
        head_sha=packet.get("head_sha") if isinstance(packet.get("head_sha"), str) else None,
        rereview_packet_sha256=rereview_packet_sha256(packet),
        verdict=result.get("verdict") if isinstance(result.get("verdict"), str) else None,
        live_head_sha=live_head_sha,
        resolved_finding_ids=result.get("resolved_finding_ids") if isinstance(result.get("resolved_finding_ids"), list) else [],
        remaining_finding_ids=result.get("remaining_finding_ids") if isinstance(result.get("remaining_finding_ids"), list) else [],
        reasons=reasons,
    )


def _string_list(value: Any, label: str, reasons: list[str]) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        reasons.append(f"{label} must be a list of non-empty strings")
        return []
    if len(value) != len(set(value)):
        reasons.append(f"{label} contains duplicates")
    return list(value)


def validate_rereview_result(
    packet: dict[str, Any],
    result: dict[str, Any],
    *,
    live_head_sha: str | None = None,
) -> RereviewResultValidation:
    reasons: list[str] = []
    try:
        _validate_packet_shape(packet)
    except ValueError as exc:
        reasons.append(str(exc))

    repository = packet.get("repository")
    pr_number = _strict_pr(packet.get("pr_number"))
    previous_head = packet.get("previous_reviewed_head_sha")
    head_sha = packet.get("head_sha")
    final_head_sha = packet.get("final_head_sha")
    expected_digest = rereview_packet_sha256(packet)
    delta_paths = _paths(packet.get("repair_delta_files"), "repair_delta_files", reasons)
    context_paths = _paths(packet.get("finding_context_files"), "finding_context_files", reasons)
    allowed_finding_paths = set(delta_paths) | set(context_paths)
    prior_findings = packet.get("prior_blocking_findings") if isinstance(packet.get("prior_blocking_findings"), list) else []
    prior_ids = {item.get("id") for item in prior_findings if isinstance(item, dict) and isinstance(item.get("id"), str)}

    if result.get("schema_version") != REREVIEW_RESULT_SCHEMA_VERSION or isinstance(result.get("schema_version"), bool):
        reasons.append("unsupported re-review result schema_version")
    verdict = result.get("verdict")
    if verdict not in _ALL_VERDICTS:
        reasons.append("re-review result verdict is invalid")
    if result.get("repository") != repository:
        reasons.append("re-review result repository does not match packet")
    result_pr = _strict_pr(result.get("pr_number"))
    if result_pr is None:
        reasons.append("re-review result pr_number is invalid")
    elif result_pr != pr_number:
        reasons.append("re-review result pr_number does not match packet")
    if result.get("previous_reviewed_head_sha") != previous_head:
        reasons.append("re-review result previous_reviewed_head_sha does not match packet")
    if result.get("head_sha") != head_sha:
        reasons.append("re-review result head_sha does not match packet")
    if not _valid_digest(result.get("rereview_packet_sha256")) or result.get("rereview_packet_sha256") != expected_digest:
        reasons.append("re-review result packet digest does not match packet")

    reviewer = result.get("reviewer")
    if not isinstance(reviewer, dict) or not isinstance(reviewer.get("name"), str) or not reviewer.get("name", "").strip():
        reasons.append("re-review result reviewer.name is required")

    reviewed_files = _string_list(result.get("reviewed_files"), "reviewed_files", reasons)
    unknown_reviewed = sorted(set(reviewed_files) - set(delta_paths))
    if unknown_reviewed:
        reasons.append("reviewed_files contains paths outside repair delta: " + ", ".join(unknown_reviewed))

    rechecked = _string_list(result.get("rechecked_finding_ids"), "rechecked_finding_ids", reasons)
    resolved = _string_list(result.get("resolved_finding_ids"), "resolved_finding_ids", reasons)
    remaining = _string_list(result.get("remaining_finding_ids"), "remaining_finding_ids", reasons)
    for label, values in (("rechecked_finding_ids", rechecked), ("resolved_finding_ids", resolved), ("remaining_finding_ids", remaining)):
        unknown = sorted(set(values) - prior_ids)
        if unknown:
            reasons.append(f"{label} contains unknown prior finding IDs: " + ", ".join(unknown))
    if set(resolved) & set(remaining):
        reasons.append("resolved_finding_ids and remaining_finding_ids must not overlap")
    if not set(resolved).issubset(set(rechecked)) or not set(remaining).issubset(set(rechecked)):
        reasons.append("resolved/remaining prior findings must be explicitly rechecked")
    if set(rechecked) != set(resolved) | set(remaining):
        reasons.append("rechecked findings must be partitioned exactly into resolved and remaining")

    global_rechecked = result.get("global_invariants_rechecked")
    if not isinstance(global_rechecked, bool):
        reasons.append("global_invariants_rechecked must be boolean")

    findings = result.get("findings")
    if not isinstance(findings, list):
        reasons.append("findings must be a list")
        findings = []
    finding_ids: set[str] = set()
    blocking_count = 0
    for finding in findings:
        if not isinstance(finding, dict):
            reasons.append("finding entries must be JSON objects")
            continue
        finding_id = finding.get("id")
        severity = finding.get("severity")
        blocking = finding.get("blocking")
        title = finding.get("title")
        detail = finding.get("detail")
        path = finding.get("path")
        line = finding.get("line")
        if not isinstance(finding_id, str) or not finding_id.strip():
            reasons.append("every new finding requires a non-empty id")
        elif finding_id in finding_ids or finding_id in prior_ids:
            reasons.append(f"new finding id is duplicate or collides with prior finding: {finding_id}")
        else:
            finding_ids.add(finding_id)
        if severity not in _ALL_SEVERITIES:
            reasons.append(f"finding {finding_id or '<unknown>'} has invalid severity")
        if not isinstance(blocking, bool):
            reasons.append(f"finding {finding_id or '<unknown>'} blocking must be boolean")
        elif blocking:
            blocking_count += 1
        if severity in _HIGH_SEVERITIES and blocking is not True:
            reasons.append(f"finding {finding_id or '<unknown>'} severity {severity} must be blocking")
        if not isinstance(title, str) or not title.strip():
            reasons.append(f"finding {finding_id or '<unknown>'} requires a title")
        if not isinstance(detail, str) or not detail.strip():
            reasons.append(f"finding {finding_id or '<unknown>'} requires detail")
        if path is not None:
            if not isinstance(path, str) or path not in allowed_finding_paths:
                reasons.append(f"finding {finding_id or '<unknown>'} path is outside re-review evidence")
            elif path in delta_paths and path not in reviewed_files:
                reasons.append(f"finding {finding_id or '<unknown>'} repair-delta path was not declared reviewed")
        if line is not None and (not isinstance(line, int) or isinstance(line, bool) or line < 1):
            reasons.append(f"finding {finding_id or '<unknown>'} line must be a positive integer or null")

    notes = result.get("notes", [])
    if not isinstance(notes, list) or any(not isinstance(note, str) for note in notes):
        reasons.append("notes must be a list of strings")

    if verdict == "PASS":
        if packet.get("incremental_eligible") is not True or packet.get("coverage") != "COMPLETE" or packet.get("complete") is not True:
            reasons.append("PASS requires a complete incrementally eligible re-review packet")
        missing_files = sorted(set(delta_paths) - set(reviewed_files))
        if missing_files:
            reasons.append("PASS requires every repair-delta file to be reviewed: " + ", ".join(missing_files))
        if set(rechecked) != prior_ids or set(resolved) != prior_ids or remaining:
            reasons.append("PASS requires every prior blocking finding to be rechecked and resolved")
        if global_rechecked is not True:
            reasons.append("PASS requires global_invariants_rechecked=true")
        if blocking_count:
            reasons.append("PASS cannot contain new blocking findings")
    elif verdict == "FAIL":
        if set(rechecked) != prior_ids or set(resolved) | set(remaining) != prior_ids:
            reasons.append("FAIL requires every prior blocking finding to be rechecked and classified resolved or remaining")
        if not remaining and blocking_count == 0:
            reasons.append("FAIL requires at least one remaining prior finding or a new blocking finding")

    if reasons:
        return _invalid(packet, result, reasons, live_head_sha)

    if head_sha != final_head_sha:
        return RereviewResultValidation(
            schema_version=REREVIEW_VALIDATION_SCHEMA_VERSION,
            kind=REREVIEW_VALIDATION_KIND,
            valid=False,
            status="STALE",
            repository=repository,
            pr_number=pr_number,
            previous_reviewed_head_sha=previous_head,
            head_sha=head_sha,
            rereview_packet_sha256=expected_digest,
            verdict=verdict,
            live_head_sha=live_head_sha,
            resolved_finding_ids=resolved,
            remaining_finding_ids=remaining,
            reasons=["re-review packet head changed during collection"],
        )
    if live_head_sha is not None:
        if not _valid_sha(live_head_sha):
            return _invalid(packet, result, ["live head SHA is invalid"], live_head_sha)
        if live_head_sha != head_sha:
            return RereviewResultValidation(
                schema_version=REREVIEW_VALIDATION_SCHEMA_VERSION,
                kind=REREVIEW_VALIDATION_KIND,
                valid=False,
                status="STALE",
                repository=repository,
                pr_number=pr_number,
                previous_reviewed_head_sha=previous_head,
                head_sha=head_sha,
                rereview_packet_sha256=expected_digest,
                verdict=verdict,
                live_head_sha=live_head_sha,
                resolved_finding_ids=resolved,
                remaining_finding_ids=remaining,
                reasons=["live pull request head no longer matches re-reviewed head"],
            )

    status: RereviewValidationStatus
    if verdict == "PASS":
        status = "VALID_PASS"
    elif verdict == "FAIL":
        status = "VALID_FAIL"
    else:
        status = "VALID_NEEDS_HUMAN"
    return RereviewResultValidation(
        schema_version=REREVIEW_VALIDATION_SCHEMA_VERSION,
        kind=REREVIEW_VALIDATION_KIND,
        valid=True,
        status=status,
        repository=repository,
        pr_number=pr_number,
        previous_reviewed_head_sha=previous_head,
        head_sha=head_sha,
        rereview_packet_sha256=expected_digest,
        verdict=verdict,
        live_head_sha=live_head_sha,
        resolved_finding_ids=resolved,
        remaining_finding_ids=remaining,
        reasons=[],
    )
