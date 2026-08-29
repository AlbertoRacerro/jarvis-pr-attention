from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from .compact import DEFAULT_MAX_DETAIL_CHARS, DEFAULT_MAX_ITEMS, build_attention_digest, build_repair_packet
from .review_result import load_json_object


def _write(payload: dict, output: str | None) -> None:
    text = json.dumps(payload, sort_keys=True, indent=2)
    if output:
        with open(output, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pr-attention-compact", description="Derive bounded agent-facing evidence from a verified PR Attention bundle")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("digest", "build the compact attention digest without patch bodies"),
        ("repair", "build a bounded repair-evidence packet for a deterministic REPAIR gate"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("bundle_file")
        command.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS)
        command.add_argument("--max-detail-chars", type=int, default=DEFAULT_MAX_DETAIL_CHARS)
        command.add_argument("--output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        bundle = load_json_object(args.bundle_file)
        if args.command == "digest":
            payload = build_attention_digest(bundle, max_items=args.max_items, max_detail_chars=args.max_detail_chars)
        else:
            payload = build_repair_packet(bundle, max_items=args.max_items, max_detail_chars=args.max_detail_chars)
        _write(payload, args.output)
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"pr-attention-compact: {exc}", file=sys.stderr)
        return 98


if __name__ == "__main__":
    raise SystemExit(main())
