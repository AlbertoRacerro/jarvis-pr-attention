from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from .continuity import (
    DEFAULT_MAX_FILE_PATCH_BYTES,
    DEFAULT_MAX_THREAD_BYTES,
    DEFAULT_MAX_THREADS,
    DEFAULT_MAX_TOTAL_PATCH_BYTES,
    DEFAULT_MAX_TOTAL_THREAD_BYTES,
    build_lineage_result_template,
    lineage_packet_sha256,
)
from .continuity_guard import (
    collect_lineage_rereview_packet,
    failed_checkpoint_from_bundle,
    validate_lineage_result,
)
from .continuity_handoff import build_lineage_envelope
from .github import GitHubClient, GitHubError
from .rereview_gate import build_rereview_integration_gate
from .review_result import load_json_object


def _write(payload: dict, output: str | None) -> None:
    text = json.dumps(payload, sort_keys=True, indent=2)
    if output:
        with open(output, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pr-attention-continuity",
        description="Carry exact-head semantic FAIL lineage across multiple bounded repair generations",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    checkpoint = sub.add_parser("checkpoint", help="derive/verify the reusable failed-review checkpoint from a prior evidence source")
    checkpoint.add_argument("source_file")
    checkpoint.add_argument("--output")

    packet = sub.add_parser("packet", help="collect latest-failed-head to current-head repair delta plus finding/thread continuity")
    packet.add_argument("repository")
    packet.add_argument("pr_number", type=int)
    packet.add_argument("source_file")
    packet.add_argument("--expected-head")
    packet.add_argument("--max-total-patch-bytes", type=int, default=DEFAULT_MAX_TOTAL_PATCH_BYTES)
    packet.add_argument("--max-file-patch-bytes", type=int, default=DEFAULT_MAX_FILE_PATCH_BYTES)
    packet.add_argument("--max-thread-bytes", type=int, default=DEFAULT_MAX_THREAD_BYTES)
    packet.add_argument("--max-total-thread-bytes", type=int, default=DEFAULT_MAX_TOTAL_THREAD_BYTES)
    packet.add_argument("--max-threads", type=int, default=DEFAULT_MAX_THREADS)
    packet.add_argument("--output")
    packet.add_argument("--no-coverage-exit", action="store_true")

    digest = sub.add_parser("digest", help="print stable content identity of a lineage re-review packet")
    digest.add_argument("packet_file")

    template = sub.add_parser("template", help="build a structured reviewer result template")
    template.add_argument("packet_file")
    template.add_argument("--reviewer-name", required=True)
    template.add_argument("--reviewer-model")
    template.add_argument("--output")

    envelope = sub.add_parser("envelope", help="build deterministic control plane plus untrusted continuity evidence")
    envelope.add_argument("packet_file")
    envelope.add_argument("--reviewer-name", required=True)
    envelope.add_argument("--reviewer-model")
    envelope.add_argument("--output")

    validate = sub.add_parser("validate", help="validate a structured lineage re-review result")
    validate.add_argument("packet_file")
    validate.add_argument("result_file")
    validate.add_argument("--live", action="store_true")
    validate.add_argument("--output")
    validate.add_argument("--no-validation-exit", action="store_true")

    gate = sub.add_parser("gate", help="reuse the V1.9 advisory integration gate with a V1.11 validation")
    gate.add_argument("snapshot_file")
    gate.add_argument("validation_file")
    gate.add_argument("--output")
    gate.add_argument("--no-gate-exit", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "checkpoint":
            payload = failed_checkpoint_from_bundle(load_json_object(args.source_file))
            _write(payload, args.output)
            return 0

        if args.command == "packet":
            source = load_json_object(args.source_file)
            client = GitHubClient.from_env()
            payload = collect_lineage_rereview_packet(
                client,
                args.repository,
                args.pr_number,
                source,
                expected_head_sha=args.expected_head,
                max_total_patch_bytes=args.max_total_patch_bytes,
                max_file_patch_bytes=args.max_file_patch_bytes,
                max_thread_bytes=args.max_thread_bytes,
                max_total_thread_bytes=args.max_total_thread_bytes,
                max_threads=args.max_threads,
            )
            _write(payload, args.output)
            if args.no_coverage_exit:
                return 0
            if payload.get("incremental_eligible") is not True:
                return 94
            return 0 if payload.get("complete") is True and payload.get("coverage") == "COMPLETE" and payload.get("thread_coverage") == "COMPLETE" else 95

        if args.command == "gate":
            snapshot = load_json_object(args.snapshot_file)
            validation = load_json_object(args.validation_file)
            gate = build_rereview_integration_gate(snapshot, validation)
            payload = gate.to_dict()
            _write(payload, args.output)
            if args.no_gate_exit:
                return 0
            return {
                "READY_TO_MERGE": 0,
                "WAIT_FOR_GATES": 80,
                "REPAIR": 81,
                "REVIEW_REQUIRED": 82,
                "NEEDS_HUMAN": 83,
                "VERIFY_LIVE": 84,
                "STALE": 85,
                "UNKNOWN": 86,
            }[gate.status]

        packet = load_json_object(args.packet_file)
        if args.command == "digest":
            print(lineage_packet_sha256(packet))
            return 0
        if args.command == "template":
            payload = build_lineage_result_template(
                packet,
                reviewer_name=args.reviewer_name,
                reviewer_model=args.reviewer_model,
            )
            _write(payload, args.output)
            return 0
        if args.command == "envelope":
            payload = build_lineage_envelope(
                packet,
                reviewer_name=args.reviewer_name,
                reviewer_model=args.reviewer_model,
            )
            _write(payload, args.output)
            return 0

        result = load_json_object(args.result_file)
        live_head: str | None = None
        if args.live:
            client = GitHubClient.from_env()
            pr = client.pull_request(str(packet.get("repository")), int(packet.get("pr_number")))
            live_head = str(((pr.get("head") or {}).get("sha") or "")) or None
        payload = validate_lineage_result(packet, result, live_head_sha=live_head)
        _write(payload, args.output)
        if args.no_validation_exit:
            return 0
        return {
            "VALID_PASS": 0,
            "VALID_FAIL": 90,
            "VALID_NEEDS_HUMAN": 91,
            "STALE": 92,
            "INVALID": 93,
        }[payload["status"]]
    except (ValueError, OSError, json.JSONDecodeError, GitHubError) as exc:
        print(f"pr-attention-continuity: {exc}", file=sys.stderr)
        return 98


if __name__ == "__main__":
    raise SystemExit(main())
