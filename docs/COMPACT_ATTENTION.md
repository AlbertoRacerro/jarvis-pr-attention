# Compact attention and repair evidence

V1.6 derives bounded agent-facing evidence from a verified V1.5 evidence bundle.

The compact layer never reads GitHub directly, invokes no model, and contains no patch bodies. The source evidence bundle remains the complete inspectable evidence record.

## Attention digest

```bash
pr-attention-compact digest evidence-bundle.json --output attention-digest.json
```

The digest contains:

- exact repository, PR, accepted head and current head bindings;
- current attention and one deterministic `next_exact_action_class`;
- failing/pending/unknown checks;
- current-head review state plus stale/dismissed review counts;
- unresolved current review threads, separated from outdated/resolved counts;
- merge state and deterministic blockers/pending reasons;
- accepted-head delta metadata and changed-file identities, without patches;
- structured semantic findings when available;
- advisory integration-gate state;
- explicit item/detail truncation metadata.

The digest is bound to `source_bundle_sha256` and has its own `attention_digest_sha256` content identity.

## Repair packet

```bash
pr-attention-compact repair evidence-bundle.json --output repair-packet.json
```

A repair packet is emitted only when the verified source bundle is `INTEGRATION_EVALUATED` and its deterministic integration gate is exactly `REPAIR`. Stale, unknown, waiting, review-required, human-required, and ready-to-merge states fail closed instead of producing repair authority.

The repair packet contains only bounded repair evidence:

- blocking structured semantic findings;
- GitHub blockers and failed checks;
- unresolved current thread evidence;
- exact delta file identities and change metadata;
- exact head/baseline bindings.

It deliberately contains no source patch body. A coding worker that needs code must retrieve exact-head repository content through the caller's authorized path.

The packet carries `REPAIR_EVIDENCE_ONLY` and grants no write, merge, architecture, policy, or promotion authority.

## Bounds

Both commands accept:

```text
--max-items N
--max-detail-chars N
```

Truncation is explicit in the output. Default bounds are conservative but configurable by the consumer. Content hashes are identities, not signatures.
