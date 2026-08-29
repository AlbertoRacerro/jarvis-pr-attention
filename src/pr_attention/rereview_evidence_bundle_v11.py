from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .rereview_gate import build_rereview_integration_gate
from .rereview_handoff import build_rereview_envelope
from .rereview_packet import CONTENT_TRUST, failed_checkpoint, rereview_packet_sha256
from .rereview_result import build_rereview_result_template, validate_rereview_result

REREVIEW_BUNDLE_SCHEMA_VERSION = 1
REREVIEW_BUNDLE_KIND = "PR_ATTENTION_REREVIEW_EVIDENCE_BUNDLE"
REREVIEW_BUNDLE_TRUST = "TOOL_GENERATED_EVIDENCE_MANIFEST"
CONTROL_TRUST = "TOOL_GENERATED_CONTROL_DATA"
DIGEST_NOTICE = "SHA-256 values are deterministic content identities, not signatures or provenance proofs"
_FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_PHASES = {
    "REREVIEW_PACKET_READY",
    "REREVIEW_HANDOFF_READY",
    "REREVIEW_VALIDATED",
    "REREVIEW_INTEGRATION_EVALUATED",
}
_GATE_STATUSES = {
    "READY_TO_MERGE",
    "WAIT_FOR_GATES",
    "REPAIR",
    "REVIEW_REQUIRED",
    "NEEDS_HUMAN",
    "VERIFY_LIVE",
    "STALE",
    "UNKNOWN",
}
_NEXT_ACTIONS = {
    "REREVIEW_DELTA",
    "FULL_REVIEW",
    "MERGE_CANDIDATE",
    "WAIT_FOR_GATES",
    "REPAIR",
    "NEEDS_HUMAN",
    "VERIFY_LIVE",
    "REFRESH_SNAPSHOT",
    "INVESTIGATE_UNKNOWN",
}


@dataclass(frozen=True)
class RereviewBundleVerification:
    schema_version: int
    valid: bool
    bundle_sha256: str | None
    repository: str | None
    pr_number: int | None
    previous_reviewed_head_sha: str | None
    head_sha: str | None
    phase: str | None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canonical_sha(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _strict_pr(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(_FULL_SHA.fullmatch(value))


def _valid_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(_DIGEST.fullmatch(value))


def _require_snapshot(snapshot: dict[str, Any]) -> tuple[str, int, str, str]:
    if snapshot.get("schema_version") != 2 or isinstance(snapshot.get("schema_version"), bool):
        raise ValueError("unsupported snapshot schema_version")
    repo = snapshot.get("repository")
    number = _strict_pr(snapshot.get("pr_number"))
    head = snapshot.get("head_sha")
    final = snapshot.get("final_head_sha")
    if not isinstance(repo, str) or "/" not in repo or number is None:
        raise ValueError("snapshot repository/pr_number is invalid")
    if not _valid_sha(head) or not _valid_sha(final):
        raise ValueError("snapshot head binding is invalid")
    if not isinstance(snapshot.get("facts_complete"), bool) or not isinstance(snapshot.get("stale"), bool):
        raise ValueError("snapshot completeness/stale fields are invalid")
    if snapshot.get("stale") is not (head != final):
        raise ValueError("snapshot stale flag is inconsistent with head binding")
    if snapshot.get("attention") not in {"READY", "PENDING", "BLOCKED", "STALE", "UNKNOWN"}:
        raise ValueError("snapshot attention is invalid")
    return repo, number, head, final


def _require_source_failed_bundle(source: dict[str, Any], repo: str, number: int) -> dict[str, Any]:
    try:
        checkpoint = failed_checkpoint(source)
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError(f"source failed bundle is invalid: {exc}") from exc
    if checkpoint.get("repository") != repo or _strict_pr(checkpoint.get("pr_number")) != number:
        raise ValueError("source failed bundle repository/pr_number does not match current snapshot")
    source_digest = checkpoint.get("source_bundle_sha256")
    previous_head = checkpoint.get("previous_reviewed_head_sha")
    accepted_head = checkpoint.get("accepted_head_sha")
    generation = checkpoint.get("lineage_generation")
    source_kind = checkpoint.get("source_checkpoint_kind")
    if not _valid_digest(source_digest) or not _valid_sha(previous_head):
        raise ValueError("source failed bundle checkpoint binding is invalid")
    if accepted_head is not None and not _valid_sha(accepted_head):
        raise ValueError("source failed bundle accepted semantic baseline is invalid")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
        raise ValueError("source failed bundle lineage generation is invalid")
    if source_kind not in {"FULL_REVIEW_FAIL", "REREVIEW_FAIL"}:
        raise ValueError("source failed bundle checkpoint kind is invalid")
    return {
        "source_digest": source_digest,
        "previous_head": previous_head,
        "accepted_head": accepted_head,
        "lineage_generation": generation,
        "source_checkpoint_kind": source_kind,
    }


def _require_packet(
    packet: dict[str, Any],
    *,
    repo: str,
    number: int,
    source: dict[str, Any],
    current_head: str,
    final_head: str,
) -> str:
    build_rereview_result_template(packet, reviewer_name="bundle-shape-check")
    if packet.get("repository") != repo or _strict_pr(packet.get("pr_number")) != number:
        raise ValueError("re-review packet repository/pr_number does not match bundle")
    if packet.get("source_bundle_sha256") != source["source_digest"]:
        raise ValueError("re-review packet source bundle digest does not match source bundle")
    if packet.get("previous_reviewed_head_sha") != source["previous_head"]:
        raise ValueError("re-review packet previous reviewed head does not match source bundle")
    if packet.get("failed_reviewed_checkpoint_sha") != source["previous_head"]:
        raise ValueError("re-review packet failed checkpoint does not match source bundle")
    if packet.get("accepted_head_sha") != source["accepted_head"]:
        raise ValueError("re-review packet accepted head does not match source bundle")
    if packet.get("accepted_semantic_baseline_sha") != source["accepted_head"]:
        raise ValueError("re-review packet accepted semantic baseline does not match source bundle")
    if packet.get("source_checkpoint_kind") != source["source_checkpoint_kind"]:
        raise ValueError("re-review packet source checkpoint kind does not match source bundle")
    if packet.get("lineage_generation") != source["lineage_generation"]:
        raise ValueError("re-review packet lineage generation does not match source bundle")
    expected_latest = source["previous_head"] if source["source_checkpoint_kind"] == "REREVIEW_FAIL" else None
    if packet.get("latest_rereview_checkpoint_sha") != expected_latest:
        raise ValueError("re-review packet latest rereview checkpoint does not match source lineage")
    if packet.get("head_sha") != current_head or packet.get("final_head_sha") != final_head:
        raise ValueError("re-review packet current/final head does not match snapshot")
    if packet.get("content_trust") != CONTENT_TRUST:
        raise ValueError("re-review packet content trust marker is invalid")
    supplied = packet.get("rereview_packet_sha256")
    expected = rereview_packet_sha256(packet)
    if not _valid_digest(supplied) or supplied != expected:
        raise ValueError("re-review packet digest is invalid")
    return expected


def _control_from_envelope(envelope: dict[str, Any], packet: dict[str, Any], digest: str) -> dict[str, Any]:
    if envelope.get("schema_version") != 1 or isinstance(envelope.get("schema_version"), bool):
        raise ValueError("re-review envelope schema_version is invalid")
    if envelope.get("purpose") != "SEMANTIC_REREVIEW" or envelope.get("rereview_packet_sha256") != digest:
        raise ValueError("re-review envelope binding is invalid")
    untrusted = envelope.get("untrusted_evidence")
    control = envelope.get("control_plane")
    if not isinstance(untrusted, dict) or untrusted.get("content_trust") != CONTENT_TRUST or untrusted.get("packet") != packet:
        raise ValueError("re-review envelope evidence does not match packet")
    if not isinstance(control, dict) or control.get("trust") != CONTROL_TRUST:
        raise ValueError("re-review envelope control plane is invalid")
    template = control.get("review_result_template")
    if not isinstance(template, dict):
        raise ValueError("re-review envelope result template is invalid")
    reviewer = template.get("reviewer")
    if not isinstance(reviewer, dict) or not isinstance(reviewer.get("name"), str) or not reviewer["name"].strip():
        raise ValueError("re-review envelope reviewer identity is invalid")
    model = reviewer.get("model")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise ValueError("re-review envelope reviewer model is invalid")
    rebuilt = build_rereview_envelope(packet, reviewer_name=reviewer["name"], reviewer_model=model)
    if rebuilt != envelope:
        raise ValueError("re-review envelope does not match deterministic control-plane contract")
    return control


def _require_validation(packet: dict[str, Any], result: dict[str, Any], validation: dict[str, Any]) -> None:
    rebuilt = validate_rereview_result(packet, result, live_head_sha=validation.get("live_head_sha"))
    if rebuilt.to_dict() != validation:
        raise ValueError("re-review validation does not match result and packet")


def _require_gate(snapshot: dict[str, Any], validation: dict[str, Any], gate: dict[str, Any]) -> None:
    if gate.get("schema_version") != 1 or isinstance(gate.get("schema_version"), bool):
        raise ValueError("re-review integration gate schema_version is invalid")
    if gate.get("kind") != "PR_ATTENTION_REREVIEW_INTEGRATION_GATE":
        raise ValueError("re-review integration gate kind is invalid")
    if gate.get("status") not in _GATE_STATUSES or not isinstance(gate.get("merge_ready"), bool):
        raise ValueError("re-review integration gate state is invalid")
    if gate.get("merge_ready") is not (gate.get("status") == "READY_TO_MERGE"):
        raise ValueError("re-review integration gate merge_ready is inconsistent")
    rebuilt = build_rereview_integration_gate(snapshot, validation).to_dict()
    if rebuilt != gate:
        raise ValueError("re-review integration gate does not match deterministic evaluation")


def _phase(control: Any, validation: Any, gate: Any) -> str:
    if validation is None:
        return "REREVIEW_HANDOFF_READY" if control is not None else "REREVIEW_PACKET_READY"
    return "REREVIEW_INTEGRATION_EVALUATED" if gate is not None else "REREVIEW_VALIDATED"


def _next_action(packet: dict[str, Any], gate: dict[str, Any] | None) -> str:
    if gate is None:
        if packet.get("incremental_eligible") is True and packet.get("coverage") == "COMPLETE" and packet.get("complete") is True:
            return "REREVIEW_DELTA"
        if packet.get("review_scope") == "FULL" or packet.get("relation") in {"BEHIND", "DIVERGED"}:
            return "FULL_REVIEW"
        return "INVESTIGATE_UNKNOWN"
    return {
        "READY_TO_MERGE": "MERGE_CANDIDATE",
        "WAIT_FOR_GATES": "WAIT_FOR_GATES",
        "REPAIR": "REPAIR",
        "REVIEW_REQUIRED": "REREVIEW_DELTA",
        "NEEDS_HUMAN": "NEEDS_HUMAN",
        "VERIFY_LIVE": "VERIFY_LIVE",
        "STALE": "REFRESH_SNAPSHOT",
        "UNKNOWN": "INVESTIGATE_UNKNOWN",
    }[gate["status"]]


def rereview_bundle_sha256(bundle: dict[str, Any]) -> str:
    fields = {key: bundle.get(key) for key in (
        "schema_version",
        "kind",
        "repository",
        "pr_number",
        "accepted_head_sha",
        "accepted_semantic_baseline_sha",
        "previous_reviewed_head_sha",
        "failed_reviewed_checkpoint_sha",
        "latest_rereview_checkpoint_sha",
        "lineage_generation",
        "source_checkpoint_kind",
        "head_sha",
        "final_head_sha",
        "phase",
        "incremental_eligible",
        "packet_coverage",
        "packet_complete",
        "semantic_review_status",
        "integration_gate_status",
        "merge_ready",
        "next_action_class",
        "source_bundle_sha256",
        "component_digests",
        "trust",
    )}
    return _canonical_sha(fields)


def build_rereview_evidence_bundle(
    current_snapshot: dict[str, Any],
    source_failed_bundle: dict[str, Any],
    rereview_packet: dict[str, Any],
    *,
    envelope: dict[str, Any] | None = None,
    rereview_result: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
    integration_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repo, number, head, final = _require_snapshot(current_snapshot)
    source = _require_source_failed_bundle(source_failed_bundle, repo, number)
    packet_digest = _require_packet(
        rereview_packet,
        repo=repo,
        number=number,
        source=source,
        current_head=head,
        final_head=final,
    )
    if (rereview_result is None) is not (validation is None):
        raise ValueError("re-review result and validation must be supplied together")
    if integration_gate is not None and validation is None:
        raise ValueError("re-review integration gate requires validation")

    control = _control_from_envelope(envelope, rereview_packet, packet_digest) if envelope is not None else None
    if validation is not None:
        _require_validation(rereview_packet, rereview_result, validation)
        if validation.get("repository") != repo or _strict_pr(validation.get("pr_number")) != number:
            raise ValueError("re-review validation repository/pr_number does not match bundle")
        if validation.get("previous_reviewed_head_sha") != source["previous_head"] or validation.get("head_sha") != head:
            raise ValueError("re-review validation head binding does not match bundle")
        if validation.get("rereview_packet_sha256") != packet_digest:
            raise ValueError("re-review validation packet digest does not match bundle")
    if integration_gate is not None:
        _require_gate(current_snapshot, validation, integration_gate)

    phase = _phase(control, validation, integration_gate)
    next_action = _next_action(rereview_packet, integration_gate)
    bundle = {
        "schema_version": REREVIEW_BUNDLE_SCHEMA_VERSION,
        "kind": REREVIEW_BUNDLE_KIND,
        "repository": repo,
        "pr_number": number,
        "accepted_head_sha": source["accepted_head"],
        "accepted_semantic_baseline_sha": source["accepted_head"],
        "previous_reviewed_head_sha": source["previous_head"],
        "failed_reviewed_checkpoint_sha": source["previous_head"],
        "latest_rereview_checkpoint_sha": rereview_packet.get("latest_rereview_checkpoint_sha"),
        "lineage_generation": source["lineage_generation"],
        "source_checkpoint_kind": source["source_checkpoint_kind"],
        "head_sha": head,
        "final_head_sha": final,
        "phase": phase,
        "incremental_eligible": rereview_packet.get("incremental_eligible") is True,
        "packet_coverage": rereview_packet.get("coverage"),
        "packet_complete": rereview_packet.get("complete") is True,
        "semantic_review_status": validation.get("status") if validation else "NOT_RUN",
        "integration_gate_status": integration_gate.get("status") if integration_gate else "NOT_RUN",
        "merge_ready": integration_gate.get("merge_ready") if integration_gate else False,
        "next_action_class": next_action,
        "source_bundle_sha256": source["source_digest"],
        "component_digests": {
            "source_bundle_sha256": source["source_digest"],
            "current_snapshot_sha256": _canonical_sha(current_snapshot),
            "rereview_packet_sha256": packet_digest,
            "rereview_control_plane_sha256": _canonical_sha(control) if control else None,
            "rereview_result_sha256": _canonical_sha(rereview_result) if rereview_result else None,
            "rereview_validation_sha256": _canonical_sha(validation) if validation else None,
            "rereview_integration_gate_sha256": _canonical_sha(integration_gate) if integration_gate else None,
        },
        "trust": {
            "bundle": REREVIEW_BUNDLE_TRUST,
            "repository_content": CONTENT_TRUST,
            "digest_notice": DIGEST_NOTICE,
        },
        "evidence": {
            "current_snapshot": current_snapshot,
            "source_failed_bundle": source_failed_bundle,
            "rereview_packet": rereview_packet,
            "rereview_control_plane": control,
            "rereview_result": rereview_result,
            "rereview_validation": validation,
            "rereview_integration_gate": integration_gate,
        },
    }
    bundle["bundle_sha256"] = rereview_bundle_sha256(bundle)
    return bundle


def verify_rereview_evidence_bundle(bundle: dict[str, Any]) -> RereviewBundleVerification:
    reasons: list[str] = []
    supplied = bundle.get("bundle_sha256") if isinstance(bundle.get("bundle_sha256"), str) else None
    evidence = bundle.get("evidence")
    try:
        if bundle.get("schema_version") != REREVIEW_BUNDLE_SCHEMA_VERSION or isinstance(bundle.get("schema_version"), bool):
            raise ValueError("re-review evidence bundle schema_version is invalid")
        if bundle.get("kind") != REREVIEW_BUNDLE_KIND:
            raise ValueError("re-review evidence bundle kind is invalid")
        if not _valid_digest(supplied) or supplied != rereview_bundle_sha256(bundle):
            raise ValueError("re-review evidence bundle digest is invalid")
        if bundle.get("phase") not in _PHASES or bundle.get("next_action_class") not in _NEXT_ACTIONS:
            raise ValueError("re-review evidence bundle phase/next action is invalid")
        if not isinstance(bundle.get("lineage_generation"), int) or isinstance(bundle.get("lineage_generation"), bool) or bundle.get("lineage_generation") < 1:
            raise ValueError("re-review evidence bundle lineage generation is invalid")
        if bundle.get("source_checkpoint_kind") not in {"FULL_REVIEW_FAIL", "REREVIEW_FAIL"}:
            raise ValueError("re-review evidence bundle source checkpoint kind is invalid")
        if not isinstance(evidence, dict):
            raise ValueError("re-review evidence bundle payload is invalid")
        snapshot = evidence.get("current_snapshot")
        source = evidence.get("source_failed_bundle")
        packet = evidence.get("rereview_packet")
        if not all(isinstance(item, dict) for item in (snapshot, source, packet)):
            raise ValueError("re-review evidence bundle lacks required snapshot/source/packet evidence")

        control = evidence.get("rereview_control_plane")
        envelope = None
        if control is not None:
            if not isinstance(control, dict):
                raise ValueError("re-review control plane is invalid")
            template = control.get("review_result_template")
            if not isinstance(template, dict) or not isinstance(template.get("reviewer"), dict):
                raise ValueError("re-review control plane template is invalid")
            reviewer = template["reviewer"]
            envelope = build_rereview_envelope(
                packet,
                reviewer_name=reviewer.get("name"),
                reviewer_model=reviewer.get("model"),
            )
            if envelope.get("control_plane") != control:
                raise ValueError("re-review control plane was modified")

        result = evidence.get("rereview_result")
        validation = evidence.get("rereview_validation")
        gate = evidence.get("rereview_integration_gate")
        rebuilt = build_rereview_evidence_bundle(
            snapshot,
            source,
            packet,
            envelope=envelope,
            rereview_result=result if isinstance(result, dict) else None,
            validation=validation if isinstance(validation, dict) else None,
            integration_gate=gate if isinstance(gate, dict) else None,
        )
        for key in (
            "schema_version", "kind", "repository", "pr_number", "accepted_head_sha",
            "accepted_semantic_baseline_sha", "previous_reviewed_head_sha", "failed_reviewed_checkpoint_sha",
            "latest_rereview_checkpoint_sha", "lineage_generation", "source_checkpoint_kind", "head_sha",
            "final_head_sha", "phase", "incremental_eligible", "packet_coverage", "packet_complete",
            "semantic_review_status", "integration_gate_status", "merge_ready", "next_action_class",
            "source_bundle_sha256", "component_digests", "trust", "evidence", "bundle_sha256",
        ):
            if rebuilt.get(key) != bundle.get(key):
                raise ValueError(f"re-review evidence bundle field {key} does not match deterministic reconstruction")
    except (ValueError, TypeError, KeyError) as exc:
        reasons.append(str(exc))

    return RereviewBundleVerification(
        schema_version=REREVIEW_BUNDLE_SCHEMA_VERSION,
        valid=not reasons,
        bundle_sha256=supplied,
        repository=bundle.get("repository") if isinstance(bundle.get("repository"), str) else None,
        pr_number=_strict_pr(bundle.get("pr_number")),
        previous_reviewed_head_sha=bundle.get("previous_reviewed_head_sha") if isinstance(bundle.get("previous_reviewed_head_sha"), str) else None,
        head_sha=bundle.get("head_sha") if isinstance(bundle.get("head_sha"), str) else None,
        phase=bundle.get("phase") if isinstance(bundle.get("phase"), str) else None,
        reasons=reasons,
    )
