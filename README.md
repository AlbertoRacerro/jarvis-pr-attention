# jarvis-pr-attention

Deterministic exact-head PR attention snapshots and incremental review plans for agentic software delivery.

`jarvis-pr-attention` is a small, read-only GitHub fact collector. It turns live pull-request state into a machine-readable snapshot and a compact human summary without using an LLM and without becoming a second source of truth.

## Design

- GitHub live state is the only source of truth.
- Every snapshot is bound to an exact PR `head_sha`.
- The PR is re-read after collection; if the head changed, the snapshot is `STALE`.
- Missing or ambiguous required evidence fails closed as `UNKNOWN`.
- The tool never merges, approves, resolves threads, comments, labels, or writes repository state.
- Old-head reviews are reported as stale evidence, not current approval/blocking evidence.
- Unresolved current threads and unresolved outdated threads are counted separately.
- An optional previously accepted semantic head can be supplied explicitly; the tool never guesses one.
- Accepted-head evidence is reused only when GitHub proves the accepted head is the current head or an ancestor of it.
- Diverged/behind baselines and incomplete large compare results fail closed to full review.

## CLI

Requires Python 3.11+ and `GITHUB_TOKEN` (or `GH_TOKEN`) with read access to the target repository.

```bash
PYTHONPATH=src python -m pr_attention snapshot owner/repo 123
PYTHONPATH=src python -m pr_attention snapshot owner/repo 123 --json
```

To plan an incremental semantic re-review, provide the **full 40-character SHA** of the last head that an external authority already accepted:

```bash
PYTHONPATH=src python -m pr_attention snapshot owner/repo 123 \
  --accepted-head 0123456789abcdef0123456789abcdef01234567
```

The accepted head is an input claim, not state owned by this tool. `jarvis-pr-attention` verifies its relationship to the live PR head through GitHub's compare API.

Exit codes remain tied to the PR attention state:

| Code | State |
| ---: | --- |
| 0 | READY |
| 10 | PENDING |
| 20 | BLOCKED |
| 30 | STALE |
| 40 | UNKNOWN / retrieval failure |

Use `--no-state-exit` when the caller needs the snapshot but should not fail based on attention state.

## Review acceleration

Schema V2 adds an explicit `delta` block and `next_action_class`.

Accepted-head relationships are normalized as:

| Relation | Meaning | Review scope |
| --- | --- | --- |
| `ABSENT` | no accepted head supplied | `FULL` |
| `CURRENT` | accepted head is the current head / identical | `NONE` |
| `AHEAD` | current head descends from accepted head | `DELTA` when file evidence is complete |
| `BEHIND` | current head is older than the accepted head | `FULL` |
| `DIVERGED` | histories diverged | `FULL` |
| `UNKNOWN` | compare evidence unavailable/ambiguous | `UNKNOWN` |

For ordinary descendant repairs, unchanged semantic evidence remains reusable and the snapshot lists only files in the `accepted_head...current_head` delta. GitHub compare responses at the 300-file cap are treated as incomplete and force `FULL` review rather than silently truncating the review scope.

`next_action_class` is deliberately coarse and deterministic:

- `REFRESH_SNAPSHOT` — head moved during collection;
- `INVESTIGATE_UNKNOWN` — required facts or delta relationship are unknown;
- `REPAIR` — current GitHub state contains a blocker;
- `WAIT_FOR_GATES` — CI/mergeability is still pending;
- `FULL_REVIEW` — no safely reusable semantic baseline exists;
- `REVIEW_DELTA` — baseline is an ancestor and only the complete delta needs review;
- `MERGE_CANDIDATE` — current head already matches accepted semantics and GitHub gates are clear.

`MERGE_CANDIDATE` is **not merge authority**. The caller remains responsible for its own governance and exact-head merge guards.

## Snapshot fields

The schema includes:

- exact initial and final head SHA;
- scope (`additions`, `deletions`, `changed_files`);
- normalized Check Runs + legacy Status Contexts;
- current-head vs stale/dismissed reviews;
- resolved, unresolved-current, and unresolved-outdated review threads;
- mergeability/conflict state;
- accepted-head relationship, evidence validity and exact delta file list;
- deterministic `READY | PENDING | BLOCKED | STALE | UNKNOWN` attention state;
- deterministic `next_action_class`;
- blocker, pending-reason and review-plan reason lists.

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
      accepted-head: ${{ steps.authority.outputs.last-accepted-head }}
  - run: |
      echo "attention=${{ steps.attention.outputs.attention }}"
      echo "next=${{ steps.attention.outputs.next-action-class }}"
      echo "scope=${{ steps.attention.outputs.review-scope }}"
```

Action outputs include `attention`, `head-sha`, `next-action-class`, `review-scope`, `delta-files`, and `snapshot-file`.

Pin the action to an exact commit SHA in production consumers.

## Development

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

The project intentionally has no runtime dependencies outside the Python standard library.

## Attribution

The implementation is original but informed by public patterns from GitHub CLI, DeployHQ PR Radar, GrantBirki/pr-status, and frankyxhl/sweeping-monk. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## License

MIT.
