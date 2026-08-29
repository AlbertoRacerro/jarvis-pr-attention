# jarvis-pr-attention

Deterministic exact-head PR attention snapshots for agentic software delivery.

`jarvis-pr-attention` is a small, read-only GitHub fact collector. It turns live pull-request state into a machine-readable snapshot and a compact human summary without using an LLM and without becoming a second source of truth.

## Design

- GitHub live state is the only source of truth.
- Every snapshot is bound to an exact PR `head_sha`.
- The PR is re-read after collection; if the head changed, the snapshot is `STALE`.
- Missing or ambiguous required evidence fails closed as `UNKNOWN`.
- The tool never merges, approves, resolves threads, comments, or writes repository state.
- Old-head reviews are reported as stale evidence, not current approval/blocking evidence.
- Unresolved current threads and unresolved outdated threads are counted separately.

## CLI

Requires Python 3.11+ and `GITHUB_TOKEN` (or `GH_TOKEN`) with read access to the target repository.

```bash
PYTHONPATH=src python -m pr_attention snapshot owner/repo 123
PYTHONPATH=src python -m pr_attention snapshot owner/repo 123 --json
```

Exit codes:

| Code | State |
| ---: | --- |
| 0 | READY |
| 10 | PENDING |
| 20 | BLOCKED |
| 30 | STALE |
| 40 | UNKNOWN / retrieval failure |

Use `--no-state-exit` when the caller needs the snapshot but should not fail based on attention state.

## Snapshot fields

The schema includes:

- exact initial and final head SHA;
- scope (`additions`, `deletions`, `changed_files`);
- normalized Check Runs + legacy Status Contexts;
- current-head vs stale reviews;
- resolved, unresolved-current, and unresolved-outdated review threads;
- mergeability/conflict state;
- deterministic `READY | PENDING | BLOCKED | STALE | UNKNOWN` classification;
- blocker and pending-reason lists.

## Reusable GitHub Action

```yaml
permissions:
  contents: read
  checks: read
  statuses: read
  pull-requests: read

steps:
  - uses: AlbertoRacerro/jarvis-pr-attention@<PINNED_COMMIT_SHA>
    id: attention
    with:
      pr-number: ${{ github.event.pull_request.number }}
  - run: echo "${{ steps.attention.outputs.attention }}"
```

Pin the action to an exact commit SHA in production consumers.

## Development

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

The initial version intentionally has no runtime dependencies outside the Python standard library.

## Attribution

The implementation is original but informed by public patterns from GitHub CLI, DeployHQ PR Radar, GrantBirki/pr-status, and frankyxhl/sweeping-monk. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## License

MIT.
