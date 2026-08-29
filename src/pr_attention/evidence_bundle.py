from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .review_result import packet_sha256

BUNDLE_SCHEMA_VERSION = 1
BUNDLE_KIND = "PR_ATTENTION_EVIDENCE_BUNDLE"
BUNDLE_TRUST = "TOOL_GENERATED_EVIDENCE_MANIFEST"
CONTENT_TRUST = "UNTRUSTED_REPOSITORY_CONTENT"
CONTROL_TRUST = "TOOL_GENERATED_CONTROL_DATA"
DIGEST_NOTICE = "SHA-256 values are deterministic content identities, not signatures or provenance proofs"
_FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_ATTENTION = {"READY", "PENDING", "BLOCKED", "STALE", "UNKNOWN"}
_RELATIONS = {"ABSENT", "CURRENT", "AHEAD", "BEHIND", "DIVERGED", "UNKNOWN"}
_SCOPES = {"NONE", "DELTA", "FULL", "UNKNOWN"}
_COVERAGE = {"COMPLETE", "PARTIAL", "NONE", "UNKNOWN"}
_VALIDATION = {"VALID_PASS", "VALID_FAIL", "VALID_NEEDS_HUMAN", "STALE", "INVALID"}
_GATE = {"READY_TO_MERGE", "WAIT_FOR_GATES", "REPAIR", "REVIEW_REQUIRED", "NEEDS_HUMAN", "VERIFY_LIVE", "STALE", "UNKNOWN"}
_EXPECTED_VERDICT = {"VALID_PASS": "PASS", "VALID_FAIL": "FAIL", "VALID_NEEDS_HUMAN": "NEEDS_HUMAN"}
_SNAPSHOT_FIELDS = (
    "schema_version", "repository", "pr_number", "title", "base_ref", "head_ref",
    "head_sha", "final_head_sha", "scope", "checks", "reviews", "threads", "merge",
    "delta", "attention", "next_action_class", "blockers", "pending_reasons",
    "facts_complete", "stale",
)


@dataclass(frozen=True)
class BundleVerification:
    schema_version: int
    valid: bool
    bundle_sha256: str | None
    repository: str | None
    pr_number: int | None
    head_sha: str | None
    phase: str | None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def snapshot_sha256(snapshot: dict[str, Any]) -> str:
    return _sha({key: snapshot.get(key) for key in _SNAPSHOT_FIELDS})


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(_FULL_SHA.fullmatch(value))


def _pr(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _require_snapshot(snapshot: dict[str, Any]) -> tuple[str, int, str, str, dict[str, Any]]:
    if snapshot.get("schema_version") != 2 or isinstance(snapshot.get("schema_version"), bool):
        raise ValueError("unsupported snapshot schema_version")
    repo, number = snapshot.get("repository"), _pr(snapshot.get("pr_number"))
    head, final = snapshot.get("head_sha"), snapshot.get("final_head_sha")
    delta = snapshot.get("delta")
    if not isinstance(repo, str) or "/" not in repo or number is None:
        raise ValueError("snapshot repository/pr_number is invalid")
    if not _valid_sha(head) or not _valid_sha(final):
        raise ValueError("snapshot head binding is invalid")
    if snapshot.get("attention") not in _ATTENTION or not isinstance(snapshot.get("facts_complete"), bool) or not isinstance(snapshot.get("stale"), bool):
        raise ValueError("snapshot attention/completeness fields are invalid")
    if not isinstance(delta, dict) or delta.get("relation") not in _RELATIONS or delta.get("review_scope") not in _SCOPES:
        raise ValueError("snapshot delta is invalid")
    accepted = delta.get("accepted_head_sha")
    if delta.get("relation") == "ABSENT":
        if accepted is not None:
            raise ValueError("ABSENT snapshot delta cannot contain accepted_head_sha")
    elif not _valid_sha(accepted):
        raise ValueError("snapshot accepted_head_sha is invalid")
    return repo, number, head, final, delta


def _require_packet(packet: dict[str, Any], snapshot: dict[str, Any], delta: dict[str, Any]) -> tuple[str, list[str]]:
    if packet.get("schema_version") != 1 or isinstance(packet.get("schema_version"), bool):
        raise ValueError("unsupported review packet schema_version")
    if packet.get("repository") != snapshot.get("repository") or _pr(packet.get("pr_number")) != snapshot.get("pr_number"):
        raise ValueError("review packet repository/pr_number does not match snapshot")
    for key in ("head_sha", "final_head_sha"):
        if packet.get(key) != snapshot.get(key):
            raise ValueError(f"review packet {key} does not match snapshot")
    if not _valid_sha(packet.get("accepted_head_sha")) or packet.get("accepted_head_sha") != delta.get("accepted_head_sha"):
        raise ValueError("review packet accepted head does not match snapshot")
    if packet.get("relation") not in _RELATIONS or packet.get("relation") != delta.get("relation") or packet.get("review_scope") not in _SCOPES or packet.get("review_scope") != delta.get("review_scope"):
        raise ValueError("review packet delta scope does not match snapshot")
    if packet.get("content_trust") != CONTENT_TRUST or packet.get("coverage") not in _COVERAGE or not isinstance(packet.get("complete"), bool):
        raise ValueError("review packet trust/coverage fields are invalid")
    files = packet.get("files")
    if not isinstance(files, list):
        raise ValueError("review packet files are invalid")
    paths = [item.get("path") for item in files if isinstance(item, dict)]
    if len(paths) != len(files) or any(not isinstance(path, str) or not path for path in paths) or len(paths) != len(set(paths)):
        raise ValueError("review packet file paths are invalid")
    return packet_sha256(packet), paths


def _control_from_envelope(envelope: dict[str, Any], packet: dict[str, Any], digest: str, paths: list[str]) -> dict[str, Any]:
    if envelope.get("schema_version") != 1 or isinstance(envelope.get("schema_version"), bool) or envelope.get("purpose") != "SEMANTIC_REVIEW" or envelope.get("packet_sha256") != digest:
        raise ValueError("review envelope binding is invalid")
    untrusted, control = envelope.get("untrusted_evidence"), envelope.get("control_plane")
    if not isinstance(untrusted, dict) or untrusted.get("content_trust") != CONTENT_TRUST or untrusted.get("packet") != packet:
        raise ValueError("review envelope evidence does not match packet")
    if not isinstance(control, dict) or control.get("trust") != CONTROL_TRUST:
        raise ValueError("review envelope control plane is invalid")
    contract, template = control.get("review_contract"), control.get("review_result_template")
    if not isinstance(contract, dict) or contract.get("required_file_paths") != paths or not isinstance(template, dict):
        raise ValueError("review envelope contract does not match packet")
    expected = {"repository": packet["repository"], "pr_number": packet["pr_number"], "accepted_head_sha": packet["accepted_head_sha"], "head_sha": packet["head_sha"], "packet_sha256": digest}
    if any(template.get(key) != value for key, value in expected.items()):
        raise ValueError("review result template binding does not match packet")
    return control


def _require_validation(validation: dict[str, Any], repo: str, number: int, head: str, digest: str) -> None:
    status, valid, verdict = validation.get("status"), validation.get("valid"), validation.get("verdict")
    if validation.get("schema_version") != 1 or isinstance(validation.get("schema_version"), bool):
        raise ValueError("review validation schema_version is invalid")
    if validation.get("repository") != repo or _pr(validation.get("pr_number")) != number or validation.get("head_sha") != head or validation.get("packet_sha256") != digest:
        raise ValueError("review validation binding does not match evidence")
    if status not in _VALIDATION or not isinstance(valid, bool):
        raise ValueError("review validation status/valid fields are invalid")
    if status in _EXPECTED_VERDICT and (valid is not True or verdict != _EXPECTED_VERDICT[status]):
        raise ValueError("review validation verdict is inconsistent with status")
    if status in {"STALE", "INVALID"} and valid is not False:
        raise ValueError("stale/invalid review validation requires valid=false")
    live_head = validation.get("live_head_sha")
    if live_head is not None and not _valid_sha(live_head):
        raise ValueError("review validation live_head_sha is invalid")


def _require_gate(gate: dict[str, Any], snapshot: dict[str, Any], validation: dict[str, Any], repo: str, number: int, head: str, digest: str) -> None:
    status = gate.get("status")
    if gate.get("schema_version") != 1 or isinstance(gate.get("schema_version"), bool):
        raise ValueError("integration gate schema_version is invalid")
    if gate.get("repository") != repo or _pr(gate.get("pr_number")) != number or gate.get("head_sha") != head or gate.get("packet_sha256") != digest:
        raise ValueError("integration gate binding does not match evidence")
    if status not in _GATE or not isinstance(gate.get("merge_ready"), bool) or not isinstance(gate.get("live_review_bound"), bool):
        raise ValueError("integration gate state fields are invalid")
    if gate.get("attention") != snapshot.get("attention") or gate.get("semantic_review_status") != validation.get("status"):
        raise ValueError("integration gate status binding does not match evidence")
    if gate.get("merge_ready") is not (status == "READY_TO_MERGE"):
        raise ValueError("integration gate merge_ready is inconsistent")


def _phase(packet: Any, control: Any, validation: Any, gate: Any) -> str:
    if packet is None:
        return "SNAPSHOT_ONLY"
    if validation is None:
        return "REVIEW_HANDOFF_READY" if control is not None else "PACKET_READY"
    return "INTEGRATION_EVALUATED" if gate is not None else "REVIEW_VALIDATED"


def bundle_sha256(bundle: dict[str, Any]) -> str:
    fields = {key: bundle.get(key) for key in (
        "schema_version", "kind", "repository", "pr_number", "accepted_head_sha", "head_sha",
        "final_head_sha", "phase", "attention", "next_action_class", "review_scope",
        "packet_coverage", "packet_complete", "semantic_review_status", "integration_gate_status",
        "merge_ready", "component_digests", "trust",
    )}
    return _sha(fields)


def build_evidence_bundle(snapshot: dict[str, Any], *, packet: dict[str, Any] | None = None, envelope: dict[str, Any] | None = None, validation: dict[str, Any] | None = None, integration_gate: dict[str, Any] | None = None) -> dict[str, Any]:
    repo, number, head, final, delta = _require_snapshot(snapshot)
    if packet is None and any(value is not None for value in (envelope, validation, integration_gate)):
        raise ValueError("review evidence requires a review packet")
    if integration_gate is not None and validation is None:
        raise ValueError("integration gate requires review validation")

    digest, paths, control = None, [], None
    if packet is not None:
        digest, paths = _require_packet(packet, snapshot, delta)
    if envelope is not None:
        control = _control_from_envelope(envelope, packet, digest, paths)
    if validation is not None:
        _require_validation(validation, repo, number, head, digest)
    if integration_gate is not None:
        _require_gate(integration_gate, snapshot, validation, repo, number, head, digest)

    bundle = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "kind": BUNDLE_KIND,
        "repository": repo,
        "pr_number": number,
        "accepted_head_sha": delta.get("accepted_head_sha"),
        "head_sha": head,
        "final_head_sha": final,
        "phase": _phase(packet, control, validation, integration_gate),
        "attention": snapshot.get("attention"),
        "next_action_class": snapshot.get("next_action_class"),
        "review_scope": delta.get("review_scope"),
        "packet_coverage": packet.get("coverage") if packet else "NONE",
        "packet_complete": packet.get("complete") if packet else False,
        "semantic_review_status": validation.get("status") if validation else "NOT_RUN",
        "integration_gate_status": integration_gate.get("status") if integration_gate else "NOT_RUN",
        "merge_ready": integration_gate.get("merge_ready") if integration_gate else False,
        "component_digests": {
            "snapshot_sha256": snapshot_sha256(snapshot),
            "packet_sha256": digest,
            "review_control_plane_sha256": _sha(control) if control else None,
            "review_validation_sha256": _sha(validation) if validation else None,
            "integration_gate_sha256": _sha(integration_gate) if integration_gate else None,
        },
        "trust": {"bundle": BUNDLE_TRUST, "repository_content": CONTENT_TRUST if packet else None, "digest_notice": DIGEST_NOTICE},
        "evidence": {"snapshot": snapshot, "review_packet": packet, "review_control_plane": control, "review_validation": validation, "integration_gate": integration_gate},
    }
    bundle["bundle_sha256"] = bundle_sha256(bundle)
    return bundle


def verify_evidence_bundle(bundle: dict[str, Any]) -> BundleVerification:
    reasons: list[str] = []
    supplied = bundle.get("bundle_sha256") if isinstance(bundle.get("bundle_sha256"), str) else None
    evidence = bundle.get("evidence")
    try:
        if bundle.get("schema_version") != BUNDLE_SCHEMA_VERSION or isinstance(bundle.get("schema_version"), bool) or bundle.get("kind") != BUNDLE_KIND:
            raise ValueError("evidence bundle schema/kind is invalid")
        if not isinstance(supplied, str) or not _DIGEST.fullmatch(supplied) or supplied != bundle_sha256(bundle):
            raise ValueError("evidence bundle digest is invalid")
        if not isinstance(evidence, dict) or not isinstance(evidence.get("snapshot"), dict):
            raise ValueError("evidence bundle payload is invalid")
        packet, control = evidence.get("review_packet"), evidence.get("review_control_plane")
        envelope = None
        if control is not None:
            if not isinstance(packet, dict) or not isinstance(control, dict):
                raise ValueError("review control plane requires a packet")
            envelope = {"schema_version": 1, "purpose": "SEMANTIC_REVIEW", "packet_sha256": packet_sha256(packet), "control_plane": control, "untrusted_evidence": {"content_trust": CONTENT_TRUST, "packet": packet}}
        rebuilt = build_evidence_bundle(evidence["snapshot"], packet=packet if isinstance(packet, dict) else None, envelope=envelope, validation=evidence.get("review_validation") if isinstance(evidence.get("review_validation"), dict) else None, integration_gate=evidence.get("integration_gate") if isinstance(evidence.get("integration_gate"), dict) else None)
        for key in ("repository", "pr_number", "accepted_head_sha", "head_sha", "final_head_sha", "phase", "attention", "next_action_class", "review_scope", "packet_coverage", "packet_complete", "semantic_review_status", "integration_gate_status", "merge_ready", "component_digests", "trust", "bundle_sha256"):
            if bundle.get(key) != rebuilt.get(key):
                reasons.append(f"evidence bundle {key} does not match embedded evidence")
    except ValueError as exc:
        reasons.append(str(exc))
    return BundleVerification(BUNDLE_SCHEMA_VERSION, not reasons, supplied, bundle.get("repository") if isinstance(bundle.get("repository"), str) else None, _pr(bundle.get("pr_number")), bundle.get("head_sha") if isinstance(bundle.get("head_sha"), str) else None, bundle.get("phase") if isinstance(bundle.get("phase"), str) else None, reasons)
