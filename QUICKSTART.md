# jarvis-pr-attention 0.13.1 quickstart

V1.11 has one recommended orchestration surface: **cycle**. Version 0.13.1 runs the cycle in `STRICT_V1` safety mode by default. It composes the existing exact-head snapshot, bounded delta packet, reviewer handoff, structured result validation, advisory gate, and multi-generation failed-review continuity without adding repository-write or merge authority.

## Safety rules first

The strict cycle is intentionally harder to misuse than the lower-level APIs:

1. A naked `accepted-head` is **not authority**. It does not reduce review scope and cannot produce a merge signal.
2. Incremental review requires all three: `accepted-head`, `--confirm-accepted-head-authority`, and `--accepted-head-source`.
3. A structured review result requires a provenance reference (`--review-result-source` or `--continuity-result-source`).
4. `merge_candidate=true` is impossible without a **current-cycle `VALID_PASS` live-bound to the exact head** plus a `READY_TO_MERGE` gate.
5. On `pull_request` GitHub Actions events, the cycle automatically binds itself to `github.event.pull_request.head.sha`. A mismatch fails closed.
6. Generated artifact directories must be fresh/empty. Existing files are never overwritten.
7. Ambiguous authority combinations, malformed repository/PR identifiers, invalid budgets, stale heads, incomplete evidence, and tampered result bindings fail closed.

See `docs/STRICT_CYCLE_SAFETY.md` for the complete contract.

## First/full review

With no established semantic baseline, do not invent one:

```bash
export GITHUB_TOKEN=...
pr-attention-cycle owner/repo 123 \
  --expected-head <EXACT_HEAD_SHA> \
  --reviewer-name ChatGPT \
  --json
```

The cycle returns `review_mode=FULL`, `next_action=FULL_REVIEW`, and `merge_candidate=false`. The tool deliberately does not manufacture full-review authority.

## Confirmed incremental review

Only reduce review scope when your governance already knows the exact accepted semantic baseline:

```bash
pr-attention-cycle owner/repo 123 \
  --expected-head <CURRENT_HEAD_SHA> \
  --accepted-head <ACCEPTED_HEAD_SHA> \
  --confirm-accepted-head-authority \
  --accepted-head-source "github-review:5058401558" \
  --reviewer-name ChatGPT \
  --json
```

If the accepted head is a safe ancestor, the result is a bounded `DELTA` handoff. If you omit the explicit authority confirmation/source, strict mode falls back to `FULL_REVIEW` and emits no delta handoff.

The compact manifest exposes:

```text
head_sha
attention
review_mode
next_action
gate_status
semantic_status
live_review_bound
merge_candidate
safety_status
baseline_authority
safety_blockers
artifacts.*
```

Full evidence remains in the referenced JSON artifacts.

## Validate a reviewer result

When feeding a structured result back, always attach a traceable source:

```bash
pr-attention-cycle owner/repo 123 \
  --expected-head <CURRENT_HEAD_SHA> \
  --accepted-head <ACCEPTED_HEAD_SHA> \
  --confirm-accepted-head-authority \
  --accepted-head-source "github-review:baseline" \
  --review-result-file review-result.json \
  --review-result-source "chatgpt:review-session-42" \
  --reviewer-name ChatGPT \
  --json
```

A `READY_TO_MERGE` engine gate is not enough by itself. The strict wrapper sets `merge_candidate=true` only when the review validation is `VALID_PASS`, `live_review_bound=true`, the snapshot is exact/current/complete, and the gate is `READY_TO_MERGE`.

## Multi-generation continuity

After a semantic FAIL, feed the emitted checkpoint back explicitly:

```bash
pr-attention-cycle owner/repo 123 \
  --expected-head <REPAIRED_HEAD_SHA> \
  --previous-failed-source-file checkpoint.json \
  --reviewer-name Claude \
  --json
```

Then validate the continuity result with provenance:

```bash
pr-attention-cycle owner/repo 123 \
  --expected-head <REPAIRED_HEAD_SHA> \
  --previous-failed-source-file checkpoint.json \
  --continuity-result-file rereview-result.json \
  --continuity-result-source "claude:rereview-session-7" \
  --reviewer-name Claude \
  --json
```

A valid continuity FAIL emits the next-generation checkpoint. A valid PASS clears it.

## GitHub Action

Pin an exact commit and use the strict cycle sub-action:

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

  - run: |
      echo "${{ steps.attention.outputs.head-sha }}"
      echo "${{ steps.attention.outputs.review-mode }}"
      echo "${{ steps.attention.outputs.safety-status }}"
      echo "${{ steps.attention.outputs.next-action }}"
```

On `pull_request`, `expected-head` is automatically bound to the event head when omitted. For other events, pass `expected-head` explicitly.

The existing root `action.yml` remains available for backward compatibility. New integrations should prefer `cycle/action.yml`.
