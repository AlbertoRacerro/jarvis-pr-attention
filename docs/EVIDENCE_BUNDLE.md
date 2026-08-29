# Evidence bundle

V1.5 adds one consumer-facing JSON contract that summarizes the exact PR evidence already produced by `jarvis-pr-attention`.

The bundle is read-only and deterministic. It does not replace GitHub as source of truth and does not grant merge authority.

## Phases

- `SNAPSHOT_ONLY`: live PR snapshot only.
- `PACKET_READY`: a bounded review packet exists without a handoff control plane.
- `REVIEW_HANDOFF_READY`: packet plus reviewer control plane are bound.
- `REVIEW_VALIDATED`: a structured review result and its validation are bound.
- `INTEGRATION_EVALUATED`: semantic validation and the advisory integration gate are both present.

## Build

```bash
pr-attention-bundle build snapshot.json \
  --packet-file packet.json \
  --envelope-file envelope.json \
  --review-result-file review-result.json \
  --validation-file validation.json \
  --integration-gate-file gate.json \
  --output evidence-bundle.json
```

Only one copy of repository-derived patch evidence is retained in the bundle. The reviewer envelope is reduced to its tool-generated `control_plane`; the packet remains marked `UNTRUSTED_REPOSITORY_CONTENT`.

When semantic review has run, the structured reviewer result is retained as evidence as well. This preserves finding IDs, severity, blocking state, paths and details needed for a later repair packet. Bundle construction independently recomputes `review_result -> validation` through the deterministic validator and rejects any mismatch.

## Verify offline

```bash
pr-attention-bundle verify evidence-bundle.json
```

Verification recomputes component identities and all cross-component bindings from embedded evidence. `build` also performs this verification before emitting a bundle. Exit code `97` means the bundle is invalid or cannot be verified safely.

`generated_at` is intentionally excluded from the stable snapshot identity, so regenerating an otherwise identical snapshot does not create a false semantic change.

## Trust

`bundle_sha256` and component SHA-256 fields are content identities, not signatures. A valid offline bundle proves internal consistency only. Callers that need current GitHub truth must still refresh live state and enforce exact-head guards before any mutation or merge.
