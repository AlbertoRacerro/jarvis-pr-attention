from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from .github import GitHubClient, GitHubError
from .review_result import load_json_object
from .rereview_packet import (
    DEFAULT_MAX_FILE_PATCH_BYTES,
    DEFAULT_MAX_TOTAL_PATCH_BYTES,
    collect_rereview_packet,
    rereview_packet_sha256,
)
from .rereview_result import build_rereview_result_template, validate_rereview_result


def _write(payload: dict, output: str | None) -> None:
    text = json.dumps(payload, sort_keys=True, indent=2)
    if output:
        with open(output, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pr-attention-rereview",
        description="Build and validate exact-head incremental re-review evidence after a complete semantic FAIL",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    packet = sub.add_parser("packet", help="collect H1->H2 repair delta plus prior blocking-finding context")
    packet.add_argument("repository")
    packet.add_argument("pr_number", type=int)
    packet.add_argument("previous_bundle_file")
    packet.add_argument("--expected-head")
    packet.add_argument("--max-total-patch-bytes", type=int, default=DEFAULT_MAX_TOTAL_PATCH_BYTES)
    packet.add_argument("--max-file-patch-bytes", type=int, default=DEFAULT_MAX_FILE_PATCH_BYTES)
    packet.add_argument("--output")
    packet.add_argument("--no-coverage-exit", action="store_true")

    digest = sub.add_parser("digest", help="print stable content identity of a re-review packet")
    digest.add_argument("packet_file")

    template = sub.add_parser("template", help="build a result template bound to one re-review packet")
    template.add_argument("packet_file")
    template.add_argument("--reviewer-name", required=True)
    template.add_argument("--reviewer-model")
    template.add_argument("--output")

    validate = sub.add_parser("validate", help="validate a structured re-review result")
    validate.add_argument("packet_file")
    validate.add_argument("result_file")
    validate.add_argument("--live", action="store_true")
    validate.add_argument("--output")
    validate.add_argument("--no-validation-exit", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "packet":
            previous_bundle = load_json_object(args.previous_bundle_file)
            client = GitHubClient.from_env()
            payload = collect_rereview_packet(
                client,
                args.repository,
                args.pr_number,
                previous_bundle,
                expected_head_sha=args.expected_head,
                max_total_patch_bytes=args.max_total_patch_bytes,
                max_file_patch_bytes=args.max_file_patch_bytes,
            )
            _write(payload, args.output)
            if args.no_coverage_exit:
                return 0
            if payload.get("incremental_eligible") is not True:
                return 94
            return 0 if payload.get("coverage") == "COMPLETE" and payload.get("complete") is True else 95

        packet = load_json_object(args.packet_file)
        if args.command == "digest":
            print(rereview_packet_sha256(packet))
            return 0
        if args.command == "template":
            payload = build_rereview_result_template(
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
        validation = validate_rereview_result(packet, result, live_head_sha=live_head)
        payload = validation.to_dict()
        _write(payload, args.output)
        if args.no_validation_exit:
            return 0
        return {
            "VALID_PASS": 0,
            "VALID_FAIL": 90,
            "VALID_NEEDS_HUMAN": 91,
            "STALE": 92,
            "INVALID": 93,
        }[validation.status]
    except (ValueError, OSError, json.JSONDecodeError, GitHubError) as exc:
        print(f"pr-attention-rereview: {exc}", file=sys.stderr)
        return 98


if __name__ == "__main__":
    raise SystemExit(main())
