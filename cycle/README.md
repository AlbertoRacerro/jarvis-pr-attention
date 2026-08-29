# V1.11 cycle action

This is the recommended compact integration surface for `jarvis-pr-attention` V1.11.

It is read-only and advisory. It never merges, approves, comments, resolves threads, labels, or persists review authority. GitHub remains the live source of truth; accepted heads and failed-review checkpoints are explicit caller inputs.

## Ordinary review

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
      reviewer-name: ChatGPT
```

Consume only the compact orchestration outputs in normal control flow:

```text
head-sha
attention
review-mode
next-action
gate-status
merge-candidate
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

The same call supports H1 FAIL -> H2 FAIL -> H3 PASS. A valid FAIL emits the next generation checkpoint. A valid PASS clears the checkpoint and may produce `merge-candidate=true` only when the exact live GitHub gates are also ready.

`accepted-head` and `previous-failed-source-file` are mutually exclusive. The tool does not guess semantic authority.
