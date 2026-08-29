from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from typing import Any, Sequence

from .classify import classify_attention, classify_next_action
from .github import GitHubClient, GitHubError
from .handoff import build_review_envelope, build_review_result_template
from .integration_gate import build_integration_gate
from .models import MergeSummary, ScopeSummary, Snapshot
from .packet import (
    DEFAULT_MAX_FILE_PATCH_BYTES,
    DEFAULT_MAX_TOTAL_PATCH_BYTES,
    collect_review_packet,
)
from .review_result import load_json_object, packet_sha256, validate_review_result
from .normalize import normalize_checks, normalize_delta, normalize_reviews, normalize_threads
from .render import render_packet_text, render_text

EXIT_CODES = {"READY": 0, "PENDING": 10, "BLOCKED": 20, "STALE": 30, "UNKNOWN": 40}
PACKET_EXIT_CODES = {"COMPLETE": 0, "PARTIAL": 50, "NONE": 60, "UNKNOWN": 70}
RESULT_EXIT_CODES = {
    "VALID_PASS": 0,
    "VALID_FAIL": 80,
    "VALID_NEEDS_HUMAN": 81,
    "STALE": 82,
    "INVALID": 83,
}
INTEGRATION_EXIT_CODES = {
    "READY_TO_MERGE": 0,
    "WAIT_FOR_GATES": 90,
    "REPAIR": 91,
    "REVIEW_REQUIRED": 92,
    "NEEDS_HUMAN": 93,
    "VERIFY_LIVE": 94,
    "STALE": 95,
    "UNKNOWN": 96,
}
_FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")


def collect_snapshot(client: GitHubClient, repo: str, number: int, *, accepted_head_sha: str | None = None) -> Snapshot:
    if accepted_head_sha and not _FULL_SHA.fullmatch(accepted_head_sha):
        raise ValueError("--accepted-head must be a full 40-character hexadecimal commit SHA")

    pr = client.pull_request(repo, number)
    head_sha = str(((pr.get("head") or {}).get("sha") or ""))
    if not head_sha:
        raise GitHubError("pull request response did not contain head SHA")

    facts_complete = True
    try:
        check_runs = client.check_runs(repo, head_sha)
        status_contexts = client.status_contexts(repo, head_sha)
        reviews_raw = client.reviews(repo, number)
        thread_nodes = client.review_threads(repo, number)
    except GitHubError:
        facts_complete = False
        check_runs = []
        status_contexts = []
        reviews_raw = []
        thread_nodes = []

    compare_payload = None
    if accepted_head_sha and accepted_head_sha != head_sha:
        try:
            compare_payload = client.compare(repo, accepted_head_sha, head_sha)
        except GitHubError:
            compare_payload = None

    checks = normalize_checks(check_runs, status_contexts)
    reviews = normalize_reviews(reviews_raw, head_sha)
    threads = normalize_threads(thread_nodes)
    delta = normalize_delta(accepted_head_sha, head_sha, compare_payload)

    mergeable = pr.get("mergeable") if isinstance(pr.get("mergeable"), bool) else None
    merge = MergeSummary(
        mergeable=mergeable,
        mergeable_state=pr.get("mergeable_state"),
        conflict=False if mergeable is True else (True if mergeable is False else None),
    )

    final_pr = client.pull_request(repo, number)
    final_head_sha = str(((final_pr.get("head") or {}).get("sha") or ""))
    if not final_head_sha:
        facts_complete = False
        final_head_sha = head_sha

    attention, blockers, pending = classify_attention(
        initial_head_sha=head_sha,
        final_head_sha=final_head_sha,
        checks=checks,
        reviews=reviews,
        threads=threads,
        merge=merge,
        facts_complete=facts_complete,
    )
    next_action = classify_next_action(attention, delta)

    return Snapshot(
        schema_version=2,
        repository=repo,
        pr_number=number,
        title=str(pr.get("title") or ""),
        base_ref=str(((pr.get("base") or {}).get("ref") or "")),
        head_ref=str(((pr.get("head") or {}).get("ref") or "")),
        head_sha=head_sha,
        final_head_sha=final_head_sha,
        generated_at=datetime.now(timezone.utc).isoformat(),
        scope=ScopeSummary(
            additions=int(pr.get("additions") or 0),
            deletions=int(pr.get("deletions") or 0),
            changed_files=int(pr.get("changed_files") or 0),
        ),
        checks=checks,
        reviews=reviews,
        threads=threads,
        merge=merge,
        delta=delta,
        attention=attention,
        next_action_class=next_action,
        blockers=blockers,
        pending_reasons=pending,
        facts_complete=facts_complete,
        stale=head_sha != final_head_sha,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pr-attention", description="Deterministic exact-head pull request attention snapshot")
    sub = parser.add_subparsers(dest="command", required=True)
    snapshot = sub.add_parser("snapshot", help="collect one pull request snapshot")
    snapshot.add_argument("repository", help="owner/repository")
    snapshot.add_argument("pr_number", type=int)
    snapshot.add_argument("--accepted-head", help="last semantically accepted full commit SHA; enables incremental review planning")
    snapshot.add_argument("--json", action="store_true", dest="json_output")
    snapshot.add_argument("--output", help="write JSON snapshot to a file")
    snapshot.add_argument("--no-state-exit", action="store_true", help="always exit 0 after a successful retrieval")

    packet = sub.add_parser("review-packet", help="collect a bounded exact-head delta review packet")
    packet.add_argument("repository", help="owner/repository")
    packet.add_argument("pr_number", type=int)
    packet.add_argument("--accepted-head", required=True, help="last semantically accepted full commit SHA")
    packet.add_argument("--expected-head", help="caller-bound full head SHA; mismatch forces STALE/UNKNOWN")
    packet.add_argument("--max-total-patch-bytes", type=int, default=DEFAULT_MAX_TOTAL_PATCH_BYTES)
    packet.add_argument("--max-file-patch-bytes", type=int, default=DEFAULT_MAX_FILE_PATCH_BYTES)
    packet.add_argument("--json", action="store_true", dest="json_output")
    packet.add_argument("--output", help="write JSON review packet to a file")
    packet.add_argument("--no-coverage-exit", action="store_true", help="always exit 0 after successful packet retrieval")

    digest = sub.add_parser("packet-digest", help="compute the stable SHA-256 identity of a review packet")
    digest.add_argument("packet_file")
    digest.add_argument("--json", action="store_true", dest="json_output")

    template = sub.add_parser("review-result-template", help="create a reviewer result JSON template already bound to a packet")
    template.add_argument("packet_file")
    template.add_argument("--reviewer-name", required=True)
    template.add_argument("--reviewer-model")
    template.add_argument("--prefill-reviewed-files", action="store_true", help="explicitly prefill reviewed_files with every packet file")
    template.add_argument("--output", help="write the JSON template to a file")

    envelope = sub.add_parser("review-envelope", help="create a deterministic reviewer handoff envelope around a packet")
    envelope.add_argument("packet_file")
    envelope.add_argument("--reviewer-name", required=True)
    envelope.add_argument("--reviewer-model")
    envelope.add_argument("--output", help="write the JSON envelope to a file")

    validation = sub.add_parser("validate-review-result", help="validate a structured reviewer verdict against an exact review packet")
    validation.add_argument("packet_file")
    validation.add_argument("result_file")
    validation.add_argument("--live", action="store_true", help="also require the live pull request head to still match the reviewed head")
    validation.add_argument("--json", action="store_true", dest="json_output")
    validation.add_argument("--output", help="write JSON validation result to a file")
    validation.add_argument("--no-validation-exit", action="store_true", help="always exit 0 after validation, even for FAIL/STALE/INVALID")

    gate = sub.add_parser("integration-gate", help="combine exact GitHub snapshot evidence with structured semantic-review validation")
    gate.add_argument("snapshot_file")
    gate.add_argument("validation_file")
    gate.add_argument("--output", help="write JSON integration gate to a file")
    gate.add_argument("--no-gate-exit", action="store_true", help="always exit 0 after computing the integration gate")
    return parser


def _render_result_validation(validation) -> str:
    lines = [
        f"Review result: {validation.status}",
        f"Valid: {'yes' if validation.valid else 'no'}",
        f"Head: {validation.head_sha or '-'}",
        f"Verdict: {validation.verdict or '-'}",
        f"Packet: {validation.packet_sha256 or '-'}",
    ]
    if validation.live_head_sha:
        lines.append(f"Live head: {validation.live_head_sha}")
    if validation.reasons:
        lines.append("Reasons:")
        lines.extend(f"  - {reason}" for reason in validation.reasons)
    return "\n".join(lines)


def _emit_json(payload: dict[str, Any], output: str | None = None) -> None:
    text = json.dumps(payload, sort_keys=True, indent=2)
    if output:
        with open(output, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "packet-digest":
            packet = load_json_object(args.packet_file)
            digest = packet_sha256(packet)
            print(json.dumps({"packet_sha256": digest}, sort_keys=True) if args.json_output else digest)
            return 0

        if args.command == "review-result-template":
            packet = load_json_object(args.packet_file)
            result_template = build_review_result_template(
                packet,
                reviewer_name=args.reviewer_name,
                reviewer_model=args.reviewer_model,
                prefill_reviewed_files=args.prefill_reviewed_files,
            )
            _emit_json(result_template, args.output)
            return 0

        if args.command == "review-envelope":
            packet = load_json_object(args.packet_file)
            review_envelope = build_review_envelope(
                packet,
                reviewer_name=args.reviewer_name,
                reviewer_model=args.reviewer_model,
            )
            _emit_json(review_envelope, args.output)
            return 0

        if args.command == "integration-gate":
            snapshot_payload = load_json_object(args.snapshot_file)
            validation_payload = load_json_object(args.validation_file)
            gate_result = build_integration_gate(snapshot_payload, validation_payload)
            _emit_json(gate_result.to_dict(), args.output)
            return 0 if args.no_gate_exit else INTEGRATION_EXIT_CODES[gate_result.status]

        if args.command == "validate-review-result":
            packet = load_json_object(args.packet_file)
            review_result = load_json_object(args.result_file)
            live_head_sha = None
            if args.live:
                repository = packet.get("repository")
                pr_number = packet.get("pr_number")
                if not isinstance(repository, str) or not repository or not isinstance(pr_number, int) or isinstance(pr_number, bool):
                    raise ValueError("--live requires valid repository and pr_number fields in the review packet")
                client = GitHubClient.from_env()
                pr = client.pull_request(repository, pr_number)
                live_head_sha = str(((pr.get("head") or {}).get("sha") or ""))
                if not live_head_sha:
                    raise GitHubError("pull request response did not contain live head SHA")
            validation = validate_review_result(packet, review_result, live_head_sha=live_head_sha)
            payload = json.dumps(validation.to_dict(), sort_keys=True, indent=2)
            if args.output:
                with open(args.output, "w", encoding="utf-8") as handle:
                    handle.write(payload + "\n")
            print(payload if args.json_output else _render_result_validation(validation))
            return 0 if args.no_validation_exit else RESULT_EXIT_CODES[validation.status]

        client = GitHubClient.from_env()
        if args.command == "snapshot":
            result = collect_snapshot(
                client,
                args.repository,
                args.pr_number,
                accepted_head_sha=args.accepted_head,
            )
            payload = json.dumps(result.to_dict(), sort_keys=True, indent=2)
            if args.output:
                with open(args.output, "w", encoding="utf-8") as handle:
                    handle.write(payload + "\n")
            print(payload if args.json_output else render_text(result))
            return 0 if args.no_state_exit else EXIT_CODES[result.attention]

        result = collect_review_packet(
            client,
            args.repository,
            args.pr_number,
            args.accepted_head,
            expected_head_sha=args.expected_head,
            max_total_patch_bytes=args.max_total_patch_bytes,
            max_file_patch_bytes=args.max_file_patch_bytes,
        )
        payload = json.dumps(result.to_dict(), sort_keys=True, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as handle:
                handle.write(payload + "\n")
        print(payload if args.json_output else render_packet_text(result))
        return 0 if args.no_coverage_exit else PACKET_EXIT_CODES[result.coverage]
    except (GitHubError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"pr-attention: {exc}", file=sys.stderr)
        if args.command == "snapshot":
            return 40
        if args.command == "review-packet":
            return 70
        if args.command == "integration-gate":
            return 96
        return 83
