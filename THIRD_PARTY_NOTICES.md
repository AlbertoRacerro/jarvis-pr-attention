# Third-party references

`jarvis-pr-attention` uses an original implementation. The following open-source projects were studied as technical references while designing its behavior:

- `cli/cli` — GitHub CLI query and pull-request status patterns (MIT).
- `deployhq/pr-radar` — review-thread pagination, current-head review handling, CI aggregation, and mergeability patterns (MIT).
- `GrantBirki/pr-status` — fail-closed CI / merge normalization concepts (MIT).
- `frankyxhl/sweeping-monk` — read-only PR watchdog and READY/BLOCKED/PENDING presentation concepts (MIT).
- `dan-sotnik/llama-pr-reviewer` — bounded incremental re-review, prior-reviewed-SHA, active-thread and delta-scoping patterns (MIT).
- `SamuelCabralCruz/unresolved-review-threads` — unresolved review-thread gate patterns.

No dependency on those projects is required at runtime. No source from those projects is intentionally vendored or copied here. If a future version copies or adapts source code rather than merely using public interfaces or concepts, the corresponding copyright and license notices must be preserved here.

See `docs/THIRD_PARTY_REFERENCE_COVERAGE.md` for the current behavior-by-behavior coverage audit and deliberate non-goals.
