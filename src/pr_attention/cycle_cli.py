from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

from .continuity import DEFAULT_MAX_THREAD_BYTES, DEFAULT_MAX_THREADS, DEFAULT_MAX_TOTAL_THREAD_BYTES
from .cycle import run_cycle
from .github import GitHubClient, GitHubError
from .packet import DEFAULT_MAX_FILE_PATCH_BYTES, DEFAULT_MAX_TOTAL_PATCH_BYTES
from .review_result import load_json_object


_ARTIFACT_KEYS = {
    "snapshot": "snapshot.json",
    "review_packet": "review-packet.json",
    "review_result_template": "review-result-template.json",
    "review_envelope": "review-envelope.json",
    "review_validation": "review-validation.json",
    "integration_gate": "integration-gate.json",
    "evidence_bundle": "evidence-bundle.json",
    "checkpoint": "checkpoint.json",
}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError(f"refusing to overwrite existing artifact: {path}")
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, indent=2) + "\n")


def _prepare_output_dir(path: Path) -> Path:
    if path.exists():
        if not path.is_dir():
            raise ValueError(f"output directory path is not a directory: {path}")
        if any(path.iterdir()):
            raise ValueError(f"refusing to reuse non-empty output directory: {path}")
    else:
        path.mkdir(parents=True, exist_ok=False)
    return path


def _fresh_default_output_dir(pr_number: int) -> Path:
    root = Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir())
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"pr-attention-cycle-{pr_number}-", dir=root))


def _materialize(result: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    _prepare_output_dir(output_dir)
    artifacts: dict[str, str] = {}
    for key, filename in _ARTIFACT_KEYS.items():
        payload = result.get(key)
        if isinstance(payload, dict):
            path = output_dir / filename
            _write_json(path, payload)
            artifacts[f"{key}_file"] = str(path)
        else:
            artifacts[f"{key}_file"] = ""

    safety = result.get("safety") if isinstance(result.get("safety"), dict) else {}
    manifest = {
        "schema_version": result["schema_version"],
        "kind": result["kind"],
        "repository": result["repository"],
        "pr_number": result["pr_number"],
        "head_sha": result["head_sha"],
        "attention": result["attention"],
        "review_mode": result["review_mode"],
        "next_action": result["next_action"],
        "gate_status": result["gate_status"],
        "semantic_status": result["semantic_status"],
        "live_review_bound": result["live_review_bound"],
        "merge_candidate": result["merge_candidate"],
        "safety_status": safety.get("status", "BLOCKED"),
        "baseline_authority": safety.get("baseline_authority", "NONE"),
        "safety_blockers": list(safety.get("blockers", [])) if isinstance(safety.get("blockers"), list) else [],
        "safety": safety,
        "artifacts": artifacts,
    }
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pr-attention-cycle",
        description="Run one strict V1.11 PR attention/re-review cycle with fail-closed misuse prevention",
    )
    parser.add_argument("repository", help="owner/repository")
    parser.add_argument("pr_number", type=int)
    parser.add_argument("--expected-head", help="caller-bound exact live head; mismatch fails the cycle")
    parser.add_argument("--accepted-head", help="last semantically accepted exact head")
    parser.add_argument(
        "--confirm-accepted-head-authority",
        action="store_true",
        help="explicitly assert that --accepted-head is semantic authority; requires --accepted-head-source",
    )
    parser.add_argument("--accepted-head-source", help="traceable external authority reference for the accepted head")
    parser.add_argument("--previous-failed-source-file", help="prior failed evidence bundle/checkpoint for continuity mode")
    parser.add_argument("--review-result-file", help="ordinary structured review result JSON")
    parser.add_argument("--review-result-source", help="traceable provenance reference for --review-result-file")
    parser.add_argument("--continuity-result-file", help="V1.11 continuity structured re-review result JSON")
    parser.add_argument("--continuity-result-source", help="traceable provenance reference for --continuity-result-file")
    parser.add_argument("--reviewer-name", default="external-reviewer")
    parser.add_argument("--reviewer-model")
    parser.add_argument("--max-total-patch-bytes", type=int, default=DEFAULT_MAX_TOTAL_PATCH_BYTES)
    parser.add_argument("--max-file-patch-bytes", type=int, default=DEFAULT_MAX_FILE_PATCH_BYTES)
    parser.add_argument("--max-thread-bytes", type=int, default=DEFAULT_MAX_THREAD_BYTES)
    parser.add_argument("--max-total-thread-bytes", type=int, default=DEFAULT_MAX_TOTAL_THREAD_BYTES)
    parser.add_argument("--max-threads", type=int, default=DEFAULT_MAX_THREADS)
    parser.add_argument("--output-dir", help="fresh/empty directory for generated evidence artifacts")
    parser.add_argument("--output", help="fresh path for compact cycle manifest JSON")
    parser.add_argument("--json", action="store_true", dest="json_output", help="print compact manifest JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        previous = load_json_object(args.previous_failed_source_file) if args.previous_failed_source_file else None
        review_result = load_json_object(args.review_result_file) if args.review_result_file else None
        continuity_result = load_json_object(args.continuity_result_file) if args.continuity_result_file else None
        client = GitHubClient.from_env()
        result = run_cycle(
            client,
            args.repository,
            args.pr_number,
            expected_head_sha=args.expected_head,
            accepted_head_sha=args.accepted_head,
            accepted_head_authority_confirmed=args.confirm_accepted_head_authority,
            accepted_head_source=args.accepted_head_source,
            previous_failed_source=previous,
            review_result=review_result,
            review_result_source=args.review_result_source,
            continuity_result=continuity_result,
            continuity_result_source=args.continuity_result_source,
            reviewer_name=args.reviewer_name,
            reviewer_model=args.reviewer_model,
            max_total_patch_bytes=args.max_total_patch_bytes,
            max_file_patch_bytes=args.max_file_patch_bytes,
            max_thread_bytes=args.max_thread_bytes,
            max_total_thread_bytes=args.max_total_thread_bytes,
            max_threads=args.max_threads,
        )
        output_dir = Path(args.output_dir) if args.output_dir else _fresh_default_output_dir(args.pr_number)
        manifest = _materialize(result, output_dir)
        manifest_path = Path(args.output) if args.output else output_dir / "cycle.json"
        _write_json(manifest_path, manifest)
        if args.json_output or not args.output:
            print(json.dumps(manifest, sort_keys=True, indent=2))
        return 0
    except (ValueError, OSError, json.JSONDecodeError, GitHubError) as exc:
        print(f"pr-attention-cycle: {exc}", file=sys.stderr)
        return 98


if __name__ == "__main__":
    raise SystemExit(main())
