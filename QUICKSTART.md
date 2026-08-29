# jarvis-pr-attention 0.13.1 quickstart

V1.11 has one recommended orchestration surface: **cycle**. It composes the existing exact-head snapshot, bounded review packet, reviewer handoff, structured result validation, advisory gate, and multi-generation failed-review continuity without adding repository-write or merge authority.

## CLI

```bash
export GITHUB_TOKEN=...
pr-attention-cycle owner/repo 123 --json
```

With an already accepted exact head:

```bash
pr-attention-cycle owner/repo 123 \
  --accepted-head 0123456789abcdef0123456789abcdef01234567 \
  --reviewer-name ChatGPT \
  --json
```

The compact manifest gives normal orchestrators only:

```text
head_sha
attention
review_mode
next_action
gate_status
merge_candidate
artifacts.*
```

Full evidence remains in the referenced JSON artifacts.

After a semantic FAIL, feed the emitted checkpoint back explicitly:

```bash
pr-attention-cycle owner/repo 123 \
  --previous-failed-source-file checkpoint.json \
  --reviewer-name Claude \
  --json
```

A valid continuity FAIL emits the next-generation checkpoint. A valid PASS clears it. The tool never guesses a semantic baseline or failed-review checkpoint.

## GitHub Action

Use the V1.11-native sub-action and pin an exact commit:

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

  - run: |
      echo "${{ steps.attention.outputs.head-sha }}"
      echo "${{ steps.attention.outputs.review-mode }}"
      echo "${{ steps.attention.outputs.next-action }}"
```

For H1 FAIL -> H2 FAIL -> H3 PASS, carry `checkpoint-file` from one bounded cycle to the next as an explicit caller-owned artifact.

The existing root `action.yml` remains supported for backward compatibility. New integrations should prefer `cycle/action.yml` while 0.13.1 is dogfooded.
