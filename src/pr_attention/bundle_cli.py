from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from .evidence_bundle import build_evidence_bundle, verify_evidence_bundle
from .review_result import load_json_object


def _optional(path: str | None):
    return load_json_object(path) if path else None


def _write(payload: dict, output: str | None) -> None:
    text = json.dumps(payload, sort_keys=True, indent=2)
    if output:
        with open(output, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pr-attention-bundle", description="Build or verify one deterministic PR evidence bundle")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="combine PR Attention evidence files into one verified bundle")
    build.add_argument("snapshot_file")
    build.add_argument("--packet-file")
    build.add_argument("--envelope-file")
    build.add_argument("--review-result-file")
    build.add_argument("--validation-file")
    build.add_argument("--integration-gate-file")
    build.add_argument("--output")

    verify = sub.add_parser("verify", help="verify an evidence bundle from embedded evidence only")
    verify.add_argument("bundle_file")
    verify.add_argument("--output")
    verify.add_argument("--no-verification-exit", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            bundle = build_evidence_bundle(
                load_json_object(args.snapshot_file),
                packet=_optional(args.packet_file),
                envelope=_optional(args.envelope_file),
                review_result=_optional(args.review_result_file),
                validation=_optional(args.validation_file),
                integration_gate=_optional(args.integration_gate_file),
            )
            verification = verify_evidence_bundle(bundle)
            if not verification.valid:
                raise ValueError("generated evidence bundle failed self-verification: " + "; ".join(verification.reasons))
            _write(bundle, args.output)
            return 0

        result = verify_evidence_bundle(load_json_object(args.bundle_file))
        _write(result.to_dict(), args.output)
        return 0 if args.no_verification_exit or result.valid else 97
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"pr-attention-bundle: {exc}", file=sys.stderr)
        return 97


if __name__ == "__main__":
    raise SystemExit(main())
