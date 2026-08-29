# Incremental re-review after a semantic FAIL

V1.11 extends the bounded re-review path introduced in V1.8. A complete semantic FAIL can be reused as a deterministic checkpoint for a repair, and a later **incremental FAIL** can itself become the next checkpoint without turning that failed head into accepted semantic authority.

The intended lineage is:

```text
accepted semantic baseline A
        |
H1 FULL REVIEW -> FAIL F1
        |
repair H1..H2
        |
H2 INCREMENTAL REVIEW -> FAIL (F1 remaining and/or new F2)
        |
repair H2..H3
        |
H3 INCREMENTAL REVIEW -> PASS
```

The tool remains read-only and stateless. The complete chain is carried inside self-verifying evidence bundles; GitHub live state remains the only repository source of truth.

## Reusable failed checkpoints

The first failed checkpoint is reusable only when a self-verifying full-review evidence bundle proves all of the following:

- phase `INTEGRATION_EVALUATED`;
- live-bound semantic `VALID_FAIL`;
- integration gate exactly `REPAIR`;
- previous review packet `COMPLETE` and complete;
- every file in that packet explicitly reviewed;
- at least one blocking finding;
- exact reviewed head unchanged during validation.

A later incremental checkpoint is reusable only when a self-verifying re-review evidence bundle proves:

- phase `REREVIEW_INTEGRATION_EVALUATED`;
- live-bound `VALID_FAIL`;
- integration gate exactly `REPAIR`;
- exact failed re-review head binding;
- intact finding lineage;
- a generation below the safety ceiling.

Partial or stale FAIL evidence is useful evidence but is **not** a reusable checkpoint.

## Authority and lineage fields

V1.11 separates concepts that must not be conflated:

- `accepted_semantic_baseline_sha` — the previously accepted semantic authority; it does not move merely because a later review failed;
- `failed_reviewed_checkpoint_sha` — the exact head whose valid FAIL is being repaired;
- `latest_rereview_checkpoint_sha` — the immediately preceding incremental review head when the source is a re-review FAIL;
- `lineage_generation` — bounded generation number for incremental chaining;
- `source_checkpoint_kind` — `FULL_REVIEW_FAIL` or `REREVIEW_FAIL`;
- `unresolved_finding_lineage` / `prior_blocking_findings` — blockers that still require explicit disposition.

A failed checkpoint is never promoted into accepted semantic authority. Across `H1 -> H2 -> H3`, the accepted baseline stays fixed unless an external authority explicitly supplies a new accepted state outside this failed-review chain.

## Finding continuity

For each generation, the next packet carries:

1. prior blocker IDs explicitly reported as `remaining` by the previous validated FAIL;
2. new blocking findings introduced by that previous re-review result.

Prior blockers explicitly classified `resolved` do not remain in the next active blocker set. New blockers receive their first-seen checkpoint metadata. Duplicate or missing finding IDs fail closed.

A reviewer must still classify **every** carried blocker as resolved or remaining. `PASS` is impossible while any carried blocker remains open or a new blocking finding is reported.

## Review-thread continuity

Current GitHub review threads are fetched separately from top-level issue conversation. Only threads that are both:

- unresolved; and
- non-outdated

are included as active continuity evidence.

Thread text is always `UNTRUSTED_REPOSITORY_CONTENT`. It is evidence, never instructions, policy, or authority for the reviewer.

V1.11 retrieves up to 100 comments for each thread and paginates the review-thread connection. All returned comments are preserved deterministically inside the bounded thread evidence. If GitHub reports more than 100 comments in one thread, if thread pagination cannot be completed, or if thread retrieval fails, the packet cannot claim complete coverage. Thread body and aggregate byte budgets also fail closed on truncation.

Resolved and outdated threads are not copied into the active re-review packet. Top-level PR/issue comments are deliberately not ingested as semantic-review input.

## Failed-checkpoint -> current-head packet

`pr-attention-rereview packet` compares the exact failed reviewed checkpoint to the current PR head and emits `PR_ATTENTION_REREVIEW_PACKET`.

The packet contains:

- exact accepted semantic baseline;
- exact failed reviewed checkpoint;
- exact current/final head;
- source bundle and prior packet identities;
- current unresolved finding lineage;
- bounded prior context for paths referenced by blockers;
- bounded repair-delta patches from the failed checkpoint to the current head;
- current unresolved/non-outdated review-thread evidence;
- paths introduced outside the prior reviewed file set;
- an explicit global-invariant recheck requirement.

Incremental re-review is allowed only when GitHub proves the failed checkpoint is a strict ancestor of the current head. Behind, diverged, identical, stale, unavailable, compare-capped, thread-incomplete, or budget-truncated evidence cannot produce a complete incremental PASS path.

## Result contract

The structured result remains bound to the re-review packet digest and exact heads:

```json
{
  "schema_version": 1,
  "repository": "owner/repo",
  "pr_number": 123,
  "previous_reviewed_head_sha": "H2...",
  "head_sha": "H3...",
  "rereview_packet_sha256": "sha256:...",
  "reviewer": {"name": "reviewer", "model": "optional"},
  "verdict": "PASS",
  "reviewed_files": ["repair.py"],
  "rechecked_finding_ids": ["F2"],
  "resolved_finding_ids": ["F2"],
  "remaining_finding_ids": [],
  "global_invariants_rechecked": true,
  "findings": [],
  "notes": []
}
```

For `PASS`, validation requires:

- incrementally eligible, complete `COMPLETE` packet;
- every repair-delta file reviewed;
- every carried blocking finding explicitly rechecked and resolved;
- zero remaining prior blockers;
- global invariants rechecked;
- zero new blocking findings;
- live PR head still equal to the reviewed head when live validation is requested.

`FAIL` requires every prior blocker to be classified plus at least one remaining prior blocker or one new blocking finding. `NEEDS_HUMAN` is available whenever bounded evidence is insufficient for safe semantic judgment.

## CLI

Collect a packet from either a complete full-review FAIL bundle or a valid previous re-review FAIL bundle:

```bash
GITHUB_TOKEN=... pr-attention-rereview packet owner/repo 123 previous-failed-bundle.json \
  --expected-head <current-full-sha> \
  --output rereview-packet.json
```

Generate a conservative template or reviewer envelope:

```bash
pr-attention-rereview template rereview-packet.json \
  --reviewer-name reviewer \
  --output rereview-result.json

pr-attention-rereview envelope rereview-packet.json \
  --reviewer-name reviewer \
  --output rereview-envelope.json
```

Validate offline or require live exact-head binding:

```bash
pr-attention-rereview validate rereview-packet.json rereview-result.json
GITHUB_TOKEN=... pr-attention-rereview validate rereview-packet.json rereview-result.json --live
```

Validation exit codes are `0` PASS, `90` FAIL, `91` NEEDS_HUMAN, `92` STALE and `93` INVALID. Collection returns `94` when incremental re-review is not eligible and `95` when evidence is eligible but incomplete; `--no-coverage-exit` lets an orchestrator always receive JSON and apply its own policy.

## Safety boundary

A failed review checkpoint proves only what was reviewed, what failed, and how the next bounded repair evidence relates to it. It never authorizes merge, approval, thread resolution, repository mutation, promotion, or skipping global-invariant checks. If exact ancestry, finding continuity, review-thread completeness, packet coverage, or live head binding cannot be proven, the optimization is abandoned or escalated rather than guessed.
