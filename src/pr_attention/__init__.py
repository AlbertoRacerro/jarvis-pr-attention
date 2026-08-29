"""Deterministic exact-head pull request attention snapshots."""

from .cli import collect_snapshot
from .handoff import build_review_envelope, build_review_result_template
from .integration_gate import build_integration_gate
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
]
__version__ = "0.6.0"
