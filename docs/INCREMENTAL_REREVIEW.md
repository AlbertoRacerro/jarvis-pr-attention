# Incremental re-review after a semantic FAIL

V1.8 allows a complete failed semantic review at head `H1` to become a bounded review checkpoint for a repair at `H2`.

The optimization is deliberately narrower than ordinary accepted-head delta review. A failed review is reusable only when all of the following are already proven by a self-verifying evidence bundle:

- the previous bundle is `INTEGRATION_EVALUATED`;
- the semantic result is a live-bound `VALID_FAIL`;
- the integration gate is exactly `REPAIR`;
- the previous review packet is `COMPLETE`;
- every file in that previous packet was explicitly reviewed;
- at least one blocking finding exists;
- `H1` remained the exact reviewed head.

A partial FAIL is useful evidence, but it is **not** a reusable checkpoint.

## H1 -> H2 packet

Given a reusable failed checkpoint, `pr-attention-rereview packet` compares `H1` to the current PR head `H2` and emits `PR_ATTENTION_REREVIEW_PACKET`.

The packet contains:

- the exact accepted head that preceded the original review;
- the exact failed reviewed head `H1`;
- the exact current/final head `H2`;
- the source evidence-bundle and prior review-packet identities;
- every prior blocking finding;
- prior patch context only for paths referenced by those blocking findings;
- bounded repair-delta patches for `H1..H2`;
- paths introduced outside the prior reviewed file set;
- an explicit requirement to re-check global invariants.

Repository-derived patch text remains `UNTRUSTED_REPOSITORY_CONTENT`.

Incremental re-review is allowed only when GitHub proves `H1` is a strict ancestor of `H2`. Behind, diverged, identical, stale, unavailable or 300-file-capped evidence fails closed to non-incremental/full-review handling.

## Result contract

A reviewer result is bound to the re-review packet digest and contains:

```json
{
  "schema_version": 1,
  "repository": "owner/repo",
  "pr_number": 123,
  "previous_reviewed_head_sha": "H1...",
  "head_sha": "H2...",
  "rereview_packet_sha256": "sha256:...",
  "reviewer": {"name": "reviewer", "model": "optional"},
  "verdict": "PASS",
  "reviewed_files": ["repair.py"],
  "rechecked_finding_ids": ["F1"],
  "resolved_finding_ids": ["F1"],
  "remaining_finding_ids": [],
  "global_invariants_rechecked": true,
  "findings": [],
  "notes": []
}
```

For `PASS`, the validator requires all of the following:

- the re-review packet is incrementally eligible, complete and `COMPLETE`;
- every `H1..H2` repair-delta file was reviewed;
- every prior blocking finding was explicitly rechecked;
- every prior blocking finding was resolved;
- no prior finding remains open;
- global invariants were rechecked;
- no new blocking finding exists;
- the live PR head still equals `H2` when live validation is requested.

`FAIL` requires either a still-open prior blocking finding or a new blocking finding. `NEEDS_HUMAN` is available when the bounded evidence is insufficient for safe judgment.

## CLI

Collect a re-review packet from a previous failed evidence bundle:

```bash
GITHUB_TOKEN=... pr-attention-rereview packet owner/repo 123 previous-bundle.json \
  --expected-head <current-full-sha> \
  --output rereview-packet.json
```

Generate a conservative result template:

```bash
pr-attention-rereview template rereview-packet.json \
  --reviewer-name reviewer \
  --output rereview-result.json
```

Validate offline:

```bash
pr-attention-rereview validate rereview-packet.json rereview-result.json
```

Or require a fresh live-head binding:

```bash
GITHUB_TOKEN=... pr-attention-rereview validate rereview-packet.json rereview-result.json --live
```

Validation exit codes are `0` PASS, `90` FAIL, `91` NEEDS_HUMAN, `92` STALE and `93` INVALID. Collection returns `94` when incremental re-review is not eligible and `95` when evidence is eligible but incomplete; `--no-coverage-exit` lets an orchestrator always receive the JSON and decide policy itself.

## Safety boundary

A failed review checkpoint is **not semantic acceptance**. It only proves what was reviewed at `H1` and which blockers were known. It never authorizes merge, promotion, repository mutation, or skipping global-invariant checks. If ancestry or evidence completeness cannot be proven, the optimization is abandoned and the caller must fall back to a broader review.
