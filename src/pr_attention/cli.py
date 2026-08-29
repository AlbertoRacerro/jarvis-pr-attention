from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from typing import Sequence

from .classify import classify_attention, classify_next_action
from .github import GitHubClient, GitHubError
from .models import MergeSummary, ScopeSummary, Snapshot
from .packet import (
    DEFAULT_MAX_FILE_PATCH_BYTES,
    DEFAULT_MAX_TOTAL_PATCH_BYTES,
    collect_review_packet,
)
from .normalize import normalize_checks, normalize_delta, normalize_reviews, normalize_threads
from .render import render_packet_text, render_text

EXIT_CODES = {"READY": 0, "PENDING": 10, "BLOCKED": 20, "STALE": 30, "UNKNOWN": 40}
PACKET_EXIT_CODES = {"COMPLETE": 0, "PARTIAL": 50, "NONE": 60, "UNKNOWN": 70}
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
    packet.add_argument("--max-total-patch-bytes", type=int, default=DEFAULT_MAX_TOTAL_PATCH_BYTES)
    packet.add_argument("--max-file-patch-bytes", type=int, default=DEFAULT_MAX_FILE_PATCH_BYTES)
    packet.add_argument("--json", action="store_true", dest="json_output")
    packet.add_argument("--output", help="write JSON review packet to a file")
    packet.add_argument("--no-coverage-exit", action="store_true", help="always exit 0 after successful packet retrieval")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
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
            max_total_patch_bytes=args.max_total_patch_bytes,
            max_file_patch_bytes=args.max_file_patch_bytes,
        )
        payload = json.dumps(result.to_dict(), sort_keys=True, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as handle:
                handle.write(payload + "\n")
        print(payload if args.json_output else render_packet_text(result))
        return 0 if args.no_coverage_exit else PACKET_EXIT_CODES[result.coverage]
    except (GitHubError, ValueError) as exc:
        print(f"pr-attention: {exc}", file=sys.stderr)
        return 40 if args.command == "snapshot" else 70
