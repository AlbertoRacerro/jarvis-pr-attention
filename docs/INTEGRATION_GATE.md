# Advisory integration gate

The integration gate combines two independently collected evidence sets for the same exact pull-request head:

1. a `snapshot` describing current GitHub checks, review threads, mergeability, and staleness;
2. a structured semantic-review validation produced by `validate-review-result`.

It does not merge, approve, comment, resolve threads, or write repository state.

## Command

```bash
PYTHONPATH=src python -m pr_attention integration-gate \
  snapshot.json review-validation.json \
  --output integration-gate.json
```

The command is offline: it evaluates the evidence already present in the two input files. For `READY_TO_MERGE`, the semantic validation itself must have been live-bound previously (`live_head_sha == head_sha`).

## Statuses

| Status | Meaning |
| --- | --- |
| `READY_TO_MERGE` | semantic review is a valid live-bound PASS and current GitHub evidence is READY |
| `WAIT_FOR_GATES` | semantic review passed, but GitHub checks/mergeability are still pending |
| `REPAIR` | semantic review failed or current GitHub state is blocked |
| `REVIEW_REQUIRED` | no valid semantic-review result is bound to the current head |
| `NEEDS_HUMAN` | semantic reviewer explicitly escalated to human judgment |
| `VERIFY_LIVE` | semantic PASS is valid offline but lacks live-head binding |
| `STALE` | snapshot, review validation, or live head refers to a different/moved head |
| `UNKNOWN` | required evidence is malformed, incomplete, or cannot be mapped safely |

Exit codes are `0`, `90`, `91`, `92`, `93`, `94`, `95`, and `96` respectively. `--no-gate-exit` returns zero after a successfully computed gate so an orchestrator can consume the JSON directly.

## Ready-to-merge is not merge authority

`READY_TO_MERGE` is advisory evidence only. The caller must still:

- re-read current GitHub state as required by its own governance;
- ensure no newer head superseded the reviewed SHA;
- perform the merge with an exact-head guard / expected head SHA;
- obey repository-specific branch protection and authorization policy.

The gate intentionally does not call the GitHub merge API.

## Fail-closed precedence

The gate gives staleness and binding failures precedence over positive evidence. A semantic PASS cannot override stale evidence, incomplete GitHub facts, blockers, or pending gates. A current valid semantic FAIL maps directly to `REPAIR`; `NEEDS_HUMAN` remains an explicit escalation rather than being collapsed into PASS/FAIL.

## GitHub Action

When `review-result-file` is supplied, the composite Action already regenerates the review packet and live-validates the result. It now also computes the integration gate and emits:

- `integration-gate-status`
- `integration-merge-ready`
- `integration-gate-file`

When no review result is supplied, the status is `NOT_RUN` and `integration-merge-ready=false`.
