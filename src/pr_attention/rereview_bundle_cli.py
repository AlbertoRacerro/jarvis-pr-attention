from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from .review_result import load_json_object
from .rereview_evidence_bundle import build_rereview_evidence_bundle, verify_rereview_evidence_bundle


def _write(payload: dict, output: str | None) -> None:
    text = json.dumps(payload, sort_keys=True, indent=2)
    if output:
        with open(output, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pr-attention-rereview-bundle",
        description="Build or verify one self-contained incremental re-review evidence bundle",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="build a deterministic re-review evidence bundle")
    build.add_argument("snapshot_file")
    build.add_argument("source_failed_bundle_file")
    build.add_argument("rereview_packet_file")
    build.add_argument("--envelope-file")
    build.add_argument("--result-file")
    build.add_argument("--validation-file")
    build.add_argument("--integration-gate-file")
    build.add_argument("--output")

    verify = sub.add_parser("verify", help="verify a re-review evidence bundle offline")
    verify.add_argument("bundle_file")
    verify.add_argument("--output")
    verify.add_argument("--no-verification-exit", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            snapshot = load_json_object(args.snapshot_file)
            source = load_json_object(args.source_failed_bundle_file)
            packet = load_json_object(args.rereview_packet_file)
            envelope = load_json_object(args.envelope_file) if args.envelope_file else None
            result = load_json_object(args.result_file) if args.result_file else None
            validation = load_json_object(args.validation_file) if args.validation_file else None
            gate = load_json_object(args.integration_gate_file) if args.integration_gate_file else None
            payload = build_rereview_evidence_bundle(
                snapshot,
                source,
                packet,
                envelope=envelope,
                rereview_result=result,
                validation=validation,
                integration_gate=gate,
            )
            # Never emit a bundle the verifier cannot immediately reconstruct.
            verification = verify_rereview_evidence_bundle(payload)
            if not verification.valid:
                raise ValueError("self-verification failed: " + "; ".join(verification.reasons))
            _write(payload, args.output)
            return 0

        bundle = load_json_object(args.bundle_file)
        verification = verify_rereview_evidence_bundle(bundle)
        payload = verification.to_dict()
        _write(payload, args.output)
        if args.no_verification_exit:
            return 0
        return 0 if verification.valid else 97
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"pr-attention-rereview-bundle: {exc}", file=sys.stderr)
        return 98


if __name__ == "__main__":
    raise SystemExit(main())
