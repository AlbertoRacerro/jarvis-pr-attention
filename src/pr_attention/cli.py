from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Sequence

from .classify import classify_attention
from .github import GitHubClient, GitHubError
from .models import MergeSummary, ScopeSummary, Snapshot
from .normalize import normalize_checks, normalize_reviews, normalize_threads
from .render import render_text

EXIT_CODES = {"READY": 0, "PENDING": 10, "BLOCKED": 20, "STALE": 30, "UNKNOWN": 40}


def collect_snapshot(client: GitHubClient, repo: str, number: int) -> Snapshot:
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

    checks = normalize_checks(check_runs, status_contexts)
    reviews = normalize_reviews(reviews_raw, head_sha)
    threads = normalize_threads(thread_nodes)

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

    return Snapshot(
        schema_version=1,
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
        attention=attention,
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
    snapshot.add_argument("--json", action="store_true", dest="json_output")
    snapshot.add_argument("--output", help="write JSON snapshot to a file")
    snapshot.add_argument("--no-state-exit", action="store_true", help="always exit 0 after a successful retrieval")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        snapshot = collect_snapshot(GitHubClient.from_env(), args.repository, args.pr_number)
    except (GitHubError, ValueError) as exc:
        print(f"pr-attention: {exc}", file=sys.stderr)
        return 40

    payload = json.dumps(snapshot.to_dict(), sort_keys=True, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
    print(payload if args.json_output else render_text(snapshot))
    if args.no_state_exit:
        return 0
    return EXIT_CODES[snapshot.attention]
