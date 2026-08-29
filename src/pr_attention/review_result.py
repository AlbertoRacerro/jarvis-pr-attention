from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ReviewVerdict = Literal["PASS", "FAIL", "NEEDS_HUMAN"]
ValidationStatus = Literal["VALID_PASS", "VALID_FAIL", "VALID_NEEDS_HUMAN", "STALE", "INVALID"]

RESULT_SCHEMA_VERSION = 1
VALIDATION_SCHEMA_VERSION = 1
_PACKET_DIGEST_FIELDS = (
    "schema_version",
    "repository",
    "pr_number",
    "accepted_head_sha",
    "head_sha",
    "final_head_sha",
    "relation",
    "review_scope",
    "content_trust",
    "coverage",
    "complete",
    "max_total_patch_bytes",
    "max_file_patch_bytes",
    "included_patch_bytes",
    "files",
)
_FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_HIGH_SEVERITIES = {"P0", "P1", "P2"}
_ALL_SEVERITIES = _HIGH_SEVERITIES | {"P3"}
_ALL_VERDICTS = {"PASS", "FAIL", "NEEDS_HUMAN"}


@dataclass(frozen=True)
class ReviewResultValidation:
    schema_version: int
    valid: bool
    status: ValidationStatus
    repository: str | None
    pr_number: int | None
    head_sha: str | None
    packet_sha256: str | None
    verdict: str | None
    live_head_sha: str | None = None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def packet_digest_payload(packet: dict[str, Any]) -> dict[str, Any]:
    """Return the stable semantic evidence envelope covered by the packet digest."""
    return {key: packet.get(key) for key in _PACKET_DIGEST_FIELDS}


def packet_sha256(packet: dict[str, Any]) -> str:
    digest = hashlib.sha256(_canonical_json(packet_digest_payload(packet))).hexdigest()
    return f"sha256:{digest}"


def load_json_object(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return payload


def _invalid(
    packet: dict[str, Any],
    result: dict[str, Any],
    reasons: list[str],
    *,
    live_head_sha: str | None = None,
) -> ReviewResultValidation:
    return ReviewResultValidation(
        schema_version=VALIDATION_SCHEMA_VERSION,
        valid=False,
        status="INVALID",
        repository=packet.get("repository") if isinstance(packet.get("repository"), str) else None,
        pr_number=packet.get("pr_number") if isinstance(packet.get("pr_number"), int) else None,
        head_sha=packet.get("head_sha") if isinstance(packet.get("head_sha"), str) else None,
        packet_sha256=packet_sha256(packet),
        verdict=result.get("verdict") if isinstance(result.get("verdict"), str) else None,
        live_head_sha=live_head_sha,
        reasons=reasons,
    )


def validate_review_result(
    packet: dict[str, Any],
    result: dict[str, Any],
    *,
    live_head_sha: str | None = None,
) -> ReviewResultValidation:
    reasons: list[str] = []

    if packet.get("schema_version") != 1:
        reasons.append("unsupported review packet schema_version")
    repository = packet.get("repository")
    pr_number = packet.get("pr_number")
    accepted_head = packet.get("accepted_head_sha")
    head_sha = packet.get("head_sha")
    final_head_sha = packet.get("final_head_sha")
    if not isinstance(repository, str) or not repository or "/" not in repository:
        reasons.append("review packet repository is invalid")
    if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number < 1:
        reasons.append("review packet pr_number is invalid")
    if not isinstance(accepted_head, str) or not _FULL_SHA.fullmatch(accepted_head):
        reasons.append("review packet accepted_head_sha is invalid")
    if not isinstance(head_sha, str) or not _FULL_SHA.fullmatch(head_sha):
        reasons.append("review packet head_sha is invalid")
    if not isinstance(final_head_sha, str) or not _FULL_SHA.fullmatch(final_head_sha):
        reasons.append("review packet final_head_sha is invalid")
    if packet.get("content_trust") != "UNTRUSTED_REPOSITORY_CONTENT":
        reasons.append("review packet content_trust marker is invalid")
    if packet.get("coverage") not in {"COMPLETE", "PARTIAL", "NONE", "UNKNOWN"}:
        reasons.append("review packet coverage is invalid")
    if not isinstance(packet.get("complete"), bool):
        reasons.append("review packet complete flag is invalid")
    files = packet.get("files")
    if not isinstance(files, list):
        reasons.append("review packet files must be a list")
        files = []

    packet_paths: list[str] = []
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not item.get("path"):
            reasons.append("review packet contains an invalid file entry")
            continue
        packet_paths.append(item["path"])
    if len(packet_paths) != len(set(packet_paths)):
        reasons.append("review packet contains duplicate file paths")

    expected_digest = packet_sha256(packet)

    if result.get("schema_version") != RESULT_SCHEMA_VERSION:
        reasons.append("unsupported review result schema_version")
    verdict = result.get("verdict")
    if verdict not in _ALL_VERDICTS:
        reasons.append("review result verdict is invalid")
    if result.get("repository") != repository:
        reasons.append("review result repository does not match packet")
    if result.get("pr_number") != pr_number:
        reasons.append("review result pr_number does not match packet")
    if result.get("accepted_head_sha") != accepted_head:
        reasons.append("review result accepted_head_sha does not match packet")
    if result.get("head_sha") != head_sha:
        reasons.append("review result head_sha does not match packet")
    supplied_digest = result.get("packet_sha256")
    if not isinstance(supplied_digest, str) or not _DIGEST.fullmatch(supplied_digest):
        reasons.append("review result packet_sha256 is invalid")
    elif supplied_digest != expected_digest:
        reasons.append("review result packet_sha256 does not match packet")

    reviewer = result.get("reviewer")
    if not isinstance(reviewer, dict) or not isinstance(reviewer.get("name"), str) or not reviewer.get("name", "").strip():
        reasons.append("review result reviewer.name is required")

    reviewed_files = result.get("reviewed_files")
    if not isinstance(reviewed_files, list) or any(not isinstance(path, str) or not path for path in reviewed_files):
        reasons.append("reviewed_files must be a list of non-empty strings")
        reviewed_files = []
    if len(reviewed_files) != len(set(reviewed_files)):
        reasons.append("reviewed_files contains duplicates")
    unknown_reviewed = sorted(set(reviewed_files) - set(packet_paths))
    if unknown_reviewed:
        reasons.append("reviewed_files contains paths outside the packet: " + ", ".join(unknown_reviewed))

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
            reasons.append("every finding requires a non-empty id")
        elif finding_id in finding_ids:
            reasons.append(f"duplicate finding id: {finding_id}")
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
            if not isinstance(path, str) or path not in packet_paths:
                reasons.append(f"finding {finding_id or '<unknown>'} path is outside the packet")
            elif path not in reviewed_files:
                reasons.append(f"finding {finding_id or '<unknown>'} path was not declared reviewed")
        if line is not None and (not isinstance(line, int) or isinstance(line, bool) or line < 1):
            reasons.append(f"finding {finding_id or '<unknown>'} line must be a positive integer or null")

    notes = result.get("notes", [])
    if not isinstance(notes, list) or any(not isinstance(note, str) for note in notes):
        reasons.append("notes must be a list of strings")

    if verdict == "PASS":
        if packet.get("coverage") != "COMPLETE" or packet.get("complete") is not True:
            reasons.append("PASS requires a COMPLETE review packet")
        if head_sha != final_head_sha:
            reasons.append("PASS requires a non-stale packet head")
        missing_reviewed = sorted(set(packet_paths) - set(reviewed_files))
        if missing_reviewed:
            reasons.append("PASS requires every packet file to be reviewed: " + ", ".join(missing_reviewed))
        if blocking_count:
            reasons.append("PASS cannot contain blocking findings")
    elif verdict == "FAIL":
        if blocking_count == 0:
            reasons.append("FAIL requires at least one blocking finding")

    if reasons:
        return _invalid(packet, result, reasons, live_head_sha=live_head_sha)

    if live_head_sha is not None:
        if not isinstance(live_head_sha, str) or not _FULL_SHA.fullmatch(live_head_sha):
            return _invalid(packet, result, ["live head SHA is invalid"], live_head_sha=live_head_sha)
        if live_head_sha != head_sha:
            return ReviewResultValidation(
                schema_version=VALIDATION_SCHEMA_VERSION,
                valid=False,
                status="STALE",
                repository=repository,
                pr_number=pr_number,
                head_sha=head_sha,
                packet_sha256=expected_digest,
                verdict=verdict,
                live_head_sha=live_head_sha,
                reasons=["live pull request head no longer matches reviewed head"],
            )

    status: ValidationStatus
    if verdict == "PASS":
        status = "VALID_PASS"
    elif verdict == "FAIL":
        status = "VALID_FAIL"
    else:
        status = "VALID_NEEDS_HUMAN"
    return ReviewResultValidation(
        schema_version=VALIDATION_SCHEMA_VERSION,
        valid=True,
        status=status,
        repository=repository,
        pr_number=pr_number,
        head_sha=head_sha,
        packet_sha256=expected_digest,
        verdict=verdict,
        live_head_sha=live_head_sha,
        reasons=[],
    )
