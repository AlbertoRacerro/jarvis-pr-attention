# V1.11 strict cycle action

This is the recommended compact integration surface for `jarvis-pr-attention` V1.11/0.13.1.

It is read-only and advisory. It never merges, approves, comments, resolves threads, labels, or persists review authority. GitHub remains the live source of truth.

## Strict misuse-prevention contract

The sub-action runs `STRICT_V1`:

- `accepted-head` alone is treated as `UNCONFIRMED_CLAIM` and **cannot** reduce scope.
- Delta reuse requires `confirm-accepted-head-authority: "true"` plus `accepted-head-source`.
- Review-result files require a matching provenance input.
- On `pull_request`, the event head becomes the automatic expected-head guard.
- Each invocation uses a fresh temporary artifact directory.
- Existing artifacts are never overwritten.
- `merge-candidate=true` requires a current-cycle, exact-live-head `VALID_PASS` and `READY_TO_MERGE`; a baseline claim by itself can never produce it.
- Stale, incomplete, tampered, ambiguous, or malformed evidence fails closed.

See `../docs/STRICT_CYCLE_SAFETY.md`.

## Ordinary incremental review

```yaml
permissions:
  contents: read
  checks: read
  statuses: read
  pull-requests: read

steps:
  - uses: AlbertoRacerro/jarvis-pr-attention/cycle@<PINNED_COMMIT_SHA>
    id: attention
    with:
      pr-number: ${{ github.event.pull_request.number }}
      accepted-head: ${{ steps.authority.outputs.last-accepted-head }}
      confirm-accepted-head-authority: "true"
      accepted-head-source: ${{ steps.authority.outputs.source_ref }}
      reviewer-name: ChatGPT
```

Normal control flow should consume only:

```text
head-sha
attention
review-mode
next-action
gate-status
semantic-status
live-review-bound
merge-candidate
safety-status
baseline-authority
checkpoint-file
review-envelope-file
review-result-template-file
```

The full evidence remains in the generated JSON artifacts.

## Multi-generation continuity

After a live-bound semantic FAIL, carry the emitted `checkpoint-file` forward explicitly:

```yaml
  - uses: AlbertoRacerro/jarvis-pr-attention/cycle@<PINNED_COMMIT_SHA>
    id: rereview
    with:
      pr-number: ${{ github.event.pull_request.number }}
      previous-failed-source-file: previous-checkpoint.json
      reviewer-name: Claude
```

When supplying the completed result:

```yaml
      continuity-result-file: rereview-result.json
      continuity-result-source: "claude:rereview-session-7"
```

H1 FAIL -> H2 FAIL -> H3 PASS remains supported. Each valid FAIL advances the checkpoint generation. A valid PASS clears the checkpoint.

## Deliberately unsupported shortcuts

There is no `unsafe`, `trust-me`, `skip-live-check`, `overwrite-artifacts`, or `merge-now` option in this Action. If a caller needs lower-level primitives, they remain available in the package, but the recommended orchestration surface intentionally refuses those shortcuts.
