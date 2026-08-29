from __future__ import annotations

import hashlib
import json
from typing import Any

from .compact import DEFAULT_MAX_DETAIL_CHARS, DEFAULT_MAX_ITEMS, build_attention_digest, build_repair_packet
from .evidence_bundle import verify_evidence_bundle

METRICS_SCHEMA_VERSION = 1
METRICS_KIND = "PR_ATTENTION_COMPACTION_METRICS"


def _canonical_bytes(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(payload: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _basis_points(numerator: int, denominator: int) -> int | None:
    if denominator <= 0:
        return None
    return (numerator * 10_000 + denominator // 2) // denominator


def measure_compaction(
    bundle: dict[str, Any],
    *,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_detail_chars: int = DEFAULT_MAX_DETAIL_CHARS,
) -> dict[str, Any]:
    verification = verify_evidence_bundle(bundle)
    if not verification.valid:
        raise ValueError("evidence bundle is invalid: " + "; ".join(verification.reasons))

    digest = build_attention_digest(bundle, max_items=max_items, max_detail_chars=max_detail_chars)
    evidence = bundle.get("evidence") or {}
    packet = evidence.get("review_packet") if isinstance(evidence.get("review_packet"), dict) else None
    review_result = evidence.get("review_result") if isinstance(evidence.get("review_result"), dict) else None
    snapshot = evidence.get("snapshot") if isinstance(evidence.get("snapshot"), dict) else {}
    threads = snapshot.get("threads") if isinstance(snapshot.get("threads"), dict) else {}
    delta = snapshot.get("delta") if isinstance(snapshot.get("delta"), dict) else {}

    bundle_bytes = len(_canonical_bytes(bundle))
    digest_bytes = len(_canonical_bytes(digest))
    avoided = max(0, bundle_bytes - digest_bytes)
    digest_share_bps = _basis_points(digest_bytes, bundle_bytes)
    reduction_bps = None if digest_share_bps is None else max(0, 10_000 - digest_share_bps)
    patch_bytes = int(packet.get("included_patch_bytes") or 0) if packet else 0
    packet_files = len(packet.get("files") or []) if packet else 0
    findings = len(review_result.get("findings") or []) if review_result else 0

    repair_packet_bytes: int | None = None
    repair_packet_sha256: str | None = None
    gate = evidence.get("integration_gate") if isinstance(evidence.get("integration_gate"), dict) else None
    if gate and gate.get("status") == "REPAIR":
        repair = build_repair_packet(bundle, max_items=max_items, max_detail_chars=max_detail_chars)
        repair_packet_bytes = len(_canonical_bytes(repair))
        repair_packet_sha256 = repair.get("repair_packet_sha256")

    metrics: dict[str, Any] = {
        "schema_version": METRICS_SCHEMA_VERSION,
        "kind": METRICS_KIND,
        "source_bundle_sha256": bundle.get("bundle_sha256"),
        "attention_digest_sha256": digest.get("attention_digest_sha256"),
        "repository": bundle.get("repository"),
        "pr_number": bundle.get("pr_number"),
        "head_sha": bundle.get("head_sha"),
        "phase": bundle.get("phase"),
        "next_exact_action_class": digest.get("next_exact_action_class"),
        "canonical_json_bytes": {
            "evidence_bundle": bundle_bytes,
            "compact_digest": digest_bytes,
            "bytes_avoided_by_first_read": avoided,
            "digest_share_basis_points": digest_share_bps,
            "first_read_reduction_basis_points": reduction_bps,
            "included_patch_evidence": patch_bytes,
            "repair_packet": repair_packet_bytes,
        },
        "evidence_counts": {
            "delta_files": int(delta.get("changed_files") or 0),
            "packet_files": packet_files,
            "semantic_findings": findings,
            "unresolved_current_threads": int(threads.get("unresolved_current") or 0),
            "unresolved_outdated_threads": int(threads.get("unresolved_outdated") or 0),
            "stale_reviews": int((snapshot.get("reviews") or {}).get("stale_review_count") or 0) if isinstance(snapshot.get("reviews"), dict) else 0,
        },
        "repair_packet_sha256": repair_packet_sha256,
        "measurement_boundary": {
            "unit": "UTF-8 bytes of canonical compact JSON",
            "token_estimate": None,
            "note": "No token-saving claim is inferred from bytes; model/token telemetry must be measured by the consumer.",
        },
        "bounds": {"max_items": max_items, "max_detail_chars": max_detail_chars},
    }
    metrics["metrics_sha256"] = _sha(metrics)
    return metrics
