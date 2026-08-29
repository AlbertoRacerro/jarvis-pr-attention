# Compaction metrics

V1.7 measures how much deterministic JSON context can be avoided when an agent reads the compact attention digest before opening the complete evidence bundle.

```bash
pr-attention-compact measure evidence-bundle.json --output metrics.json
```

Metrics are derived from a verified bundle and the same bounded digest configuration used by `pr-attention-compact digest`.

## Measurements

`canonical_json_bytes` reports:

- `evidence_bundle`: UTF-8 bytes of canonical compact JSON for the complete evidence bundle;
- `compact_digest`: UTF-8 bytes of canonical compact JSON for the first-read digest;
- `bytes_avoided_by_first_read`: non-negative bundle minus digest byte count;
- `digest_share_basis_points`: digest size as basis points of bundle size;
- `first_read_reduction_basis_points`: corresponding size reduction;
- `included_patch_evidence`: patch bytes present in the source review packet but excluded from the digest;
- `repair_packet`: bounded repair-packet bytes when the deterministic gate is `REPAIR`, otherwise `null`.

The report also records evidence counts such as delta files, packet files, semantic findings, unresolved current/outdated threads, and stale reviews.

## No synthetic token claim

The tool deliberately emits:

```json
"token_estimate": null
```

Byte reduction is not presented as token or monetary savings. A consumer such as JarvisOS can record its actual model input tokens alongside these deterministic measurements and calculate real savings over multiple PRs.

All measurements are bound to the source bundle digest and exact head SHA. `metrics_sha256` is a content identity, not a signature.
