# V1.11 — thread continuity and multi-generation re-review

V1.11 extends the existing V1.8/V1.9 incremental re-review path without turning a failed review into accepted authority.

## Failure mode addressed

Before V1.11, one complete semantic FAIL could be reused for one repair delta. If that incremental re-review also failed, the second failed checkpoint could not become the basis for a third bounded re-review. A caller either had to reconstruct state manually or restart a broader review. GitHub review threads were also present in the live snapshot but were not carried as bounded evidence into the incremental reviewer context.

## Failed-review checkpoint

`PR_ATTENTION_FAILED_REVIEW_CHECKPOINT` is deterministic control/evidence state derived only from a verified terminal FAIL with a deterministic `REPAIR` gate.

It records separately:

- `accepted_semantic_baseline_sha`: the last accepted semantic baseline; it never advances because a review failed;
- `failed_reviewed_checkpoint_sha`: the latest exact head that was reviewed and failed;
- `generation`: full-review FAIL is generation 1; each valid incremental FAIL advances one generation;
- unresolved finding lineage with stable finding IDs, origin head and latest-seen head;
- bounded finding-context patches;
- the previous checkpoint digest when one exists.

A failed checkpoint is not merge authority and is not semantic acceptance.

Legacy V1.9 evidence is bootstrap-compatible only when its reusable evidence was complete:

- a verified `PR_ATTENTION_EVIDENCE_BUNDLE` with `VALID_FAIL + REPAIR`, complete packet coverage and complete reviewed-file coverage becomes generation 1;
- a verified V1.9 `PR_ATTENTION_REREVIEW_EVIDENCE_BUNDLE` with `VALID_FAIL + REPAIR`, complete repair-delta evidence and every repair-delta file actually reviewed becomes generation 2.

After that, every valid V1.11 FAIL directly emits the next self-verifying failed checkpoint, so the chain can continue without replaying the original full review.

## Lineage re-review packet

`PR_ATTENTION_LINEAGE_REREVIEW_PACKET` compares only:

`latest failed reviewed checkpoint -> current exact PR head`

Incremental eligibility requires the prior failed head to be a strict ancestor (`AHEAD` compare relation), complete bounded repair patches and fresh exact-head binding. Divergence, stale collection, unavailable compare evidence, the GitHub 300-file compare ceiling, missing patches or budget truncation fail closed.

The packet carries:

- accepted semantic baseline;
- previous failed checkpoint;
- generation number;
- unresolved finding lineage;
- prior finding context;
- repair delta and scope expansion;
- pertinent unresolved/non-outdated GitHub review threads;
- mandatory global-invariant recheck.

## Review-thread trust boundary

Only GitHub **review threads** are considered. Top-level issue/PR comments are not ingested by this path.

A thread is included only when all are true:

1. it is unresolved;
2. it is not outdated;
3. its file path is relevant to the repair delta or an unresolved finding.

Thread bodies are marked `UNTRUSTED_GITHUB_REVIEW_CONTENT`. They are evidence, never instructions. The packet digest covers thread identity, path, bounded body, original-body digest and truncation state.

If thread collection is unavailable, a relevant thread is malformed, or configured bounds truncate relevant thread evidence, packet completeness is false and semantic PASS/FAIL cannot advance reusable lineage.

## Result contract

For every PASS or FAIL generation the reviewer must explicitly provide:

- every repair-delta file reviewed;
- every pertinent review thread considered;
- every prior unresolved finding rechecked and partitioned into `resolved` or `remaining`;
- `global_invariants_rechecked=true`;
- any newly discovered findings with stable new IDs.

PASS additionally requires:

- complete patch and thread evidence;
- all prior blockers resolved;
- no new blocking finding.

FAIL requires at least one remaining or newly discovered blocking finding. A valid FAIL emits the next failed checkpoint while preserving the accepted semantic baseline. An incomplete FAIL may still be useful human evidence, but the public V1.11 validator does not let it advance reusable lineage.

## Canonical chain example

```text
accepted semantic baseline B
        |
H1 FULL REVIEW -> FAIL F1
        |
        +-- checkpoint generation 1: baseline=B, failed=H1, unresolved={F1}
        |
repair -> H2
H2 lineage re-review -> resolve F1, discover FAIL F2
        |
        +-- checkpoint generation 2: baseline=B, failed=H2, unresolved={F2}
        |
repair -> H3
H3 lineage re-review -> resolve F2 -> PASS
```

At no point does H1 or H2 become an accepted semantic baseline merely because it is a reusable failed checkpoint.

## Public API

The supported package-level V1.11 API routes checkpoint promotion and validation through the strict fail-closed guards:

- `failed_checkpoint_from_bundle(...)`
- `failed_checkpoint_from_evidence_bundle(...)`
- `failed_checkpoint_from_rereview_bundle(...)`
- `checkpoint_sha256(...)`
- `build_lineage_rereview_packet(...)`
- `collect_lineage_rereview_packet(...)`
- `lineage_packet_sha256(...)`
- `build_lineage_result_template(...)`
- `validate_lineage_result(...)`

The live collector reuses the existing GitHub exact-head compare and GraphQL review-thread collector. V1.11 validation also exposes the compatibility aliases consumed by the existing deterministic re-review integration gate; the gate semantics are not duplicated.

## CLI

`pr-attention-continuity` exposes the multi-generation path directly:

```text
checkpoint <source.json>
packet <owner/repo> <pr> <source.json>
digest <packet.json>
template <packet.json> --reviewer-name <name>
envelope <packet.json> --reviewer-name <name>
validate <packet.json> <result.json> [--live]
gate <snapshot.json> <validation.json>
```

`packet` has independent patch and review-thread byte/count budgets and fails closed when exact-head, compare, patch or thread evidence is insufficient.

## Composite Action boundary

The root composite Action remains the backward-compatible V1.9 H1→H2 orchestration in this release. It is not silently reinterpreted as a V1.11 multi-generation bundle format. Multi-generation V1.11 is available through the supported Python API and `pr-attention-continuity` CLI.

Wiring the root Action to V1.11 should be done only together with a self-verifying V1.11 unified evidence-bundle contract, so the Action does not create a second partial authority/evidence format. Until then, callers must not claim root-Action multi-generation support.

GitHub remains the only source of PR truth; V1.11 adds no persistence or authority store.
