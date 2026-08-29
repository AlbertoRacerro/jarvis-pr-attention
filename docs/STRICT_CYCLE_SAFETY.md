# Strict cycle safety contract

`pr-attention-cycle` 0.13.1 uses safety profile `STRICT_V1`. Its purpose is to make accidental authority escalation, stale-evidence reuse, and misleading merge signals difficult even for automated callers.

## Non-negotiable invariants

### 1. GitHub is live truth

Every cycle re-reads the PR and is exact-head bound. On `pull_request` GitHub Actions events, the event head is automatically used as the caller expected head. A caller may also supply `--expected-head`. Mismatch is a hard error.

If the head moves during initial fact collection, the cycle emits no review packet or merge signal and returns `REFRESH_SNAPSHOT`.

### 2. A SHA is not semantic authority

`accepted-head` is only a claim until the caller explicitly sets `--confirm-accepted-head-authority` and supplies `--accepted-head-source`.

Without both, strict mode:
- does not pass the head into incremental review planning;
- returns `review_mode=FULL`;
- emits no delta review envelope;
- sets `baseline_authority=UNCONFIRMED_CLAIM`;
- keeps `merge_candidate=false`.

This prevents the common misuse of passing the current/base SHA merely to obtain a smaller review.

### 3. Result provenance is explicit

An ordinary `review-result-file` requires `review-result-source`.
A `continuity-result-file` requires `continuity-result-source`.

These are traceability references, not cryptographic signatures. The underlying validators still bind the result structurally to the exact packet/head/digest and reject tampering.

### 4. Merge signal has one route

`merge_candidate=true` requires all of the following in the current cycle:

- exact snapshot is `READY`;
- required GitHub facts are complete;
- snapshot did not become stale;
- structured semantic validation is `valid=true`;
- semantic status is `VALID_PASS`;
- validation `head_sha` equals the snapshot head;
- validation `live_head_sha` equals the snapshot head;
- integration gate is `READY_TO_MERGE`;
- integration gate `merge_ready=true`.

No current-cycle semantic validation means no merge candidate, even when `accepted-head == current head`.

`merge_candidate` remains advisory. The tool still has no merge authority.

### 5. Failed-review lineage is explicit

Continuity mode requires a caller-provided failed evidence bundle/checkpoint. The existing V1.11 continuity guard validates repository/PR identity, lineage digest, generation, ancestor relation, patch completeness, thread continuity, prior findings, and exact head.

A valid FAIL advances the checkpoint. A valid PASS clears it.

### 6. Artifact reuse fails closed

The CLI uses a unique temporary output directory by default. An explicitly supplied output directory must be empty. Existing artifact files are never overwritten.

This prevents a new cycle from silently inheriting `review-result.json`, `checkpoint.json`, or other evidence from an older head.

### 7. Input ambiguity fails closed

The strict wrapper rejects, among other cases:

- `accepted-head` together with failed-lineage mode;
- ordinary and continuity results in the same call;
- review results without the corresponding authority/provenance inputs;
- authority source without authority confirmation;
- malformed repository or PR identifiers;
- non-full SHA bindings;
- zero, negative, boolean, or excessive evidence budgets;
- reviewer/source strings with control characters or excessive length.

## Safety states

The compact manifest exposes `safety_status`:

- `SAFE_TO_MERGE_ADVISORY` — strict merge-signal requirements are satisfied.
- `SAFE_TO_REVIEW` — complete bounded review evidence is ready, but no semantic result has been accepted.
- `REPAIR_REQUIRED` — deterministic semantic/GitHub evidence requires repair.
- `WAIT_FOR_GATES` — semantic PASS exists but live gates are pending.
- `BLOCKED` — a safety invariant or evidence-completeness condition blocks safe reuse.
- `NO_MERGE_SIGNAL` — the current cycle is valid, but it deliberately cannot authorize even an advisory merge signal.

Consumers should key merge-related automation on `merge-candidate == true`, never on an accepted SHA, review mode, or raw gate string alone.

## Threat model

`STRICT_V1` is designed primarily against accidental and orchestration-level misuse: stale files, wrong SHAs, accidental scope reduction, mixed generations, malformed/tampered structured results, or interpreting a baseline claim as a merge approval.

It does not claim cryptographic identity of the human/model named in a reviewer result. If hostile callers can fabricate both governance inputs and provenance strings, an external signing/attestation system is required. The tool intentionally does not pretend otherwise.
