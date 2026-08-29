"""Deterministic exact-head pull request attention snapshots."""

from .cli import collect_snapshot
from .compact import build_attention_digest, build_repair_packet
from .evidence_bundle import build_evidence_bundle, bundle_sha256, verify_evidence_bundle
from .handoff import build_review_envelope, build_review_result_template
from .integration_gate import build_integration_gate
from .metrics import measure_compaction
from .packet import collect_review_packet
from .review_result import packet_sha256, validate_review_result

__all__ = [
    "collect_snapshot",
    "collect_review_packet",
    "packet_sha256",
    "validate_review_result",
    "build_review_result_template",
    "build_review_envelope",
    "build_integration_gate",
    "build_evidence_bundle",
    "bundle_sha256",
    "verify_evidence_bundle",
    "build_attention_digest",
    "build_repair_packet",
    "measure_compaction",
]
__version__ = "0.9.0"
