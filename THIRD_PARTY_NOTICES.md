# Third-party references

`jarvis-pr-attention` uses an original implementation. The following open-source projects were studied as technical references while designing the V0 behavior:

- `cli/cli` — GitHub CLI query and pull-request status patterns (MIT).
- `deployhq/pr-radar` — review-thread pagination, current-head review handling, and CI aggregation patterns (MIT).
- `GrantBirki/pr-status` — fail-closed CI / merge normalization concepts (MIT).
- `frankyxhl/sweeping-monk` — read-only PR watchdog and READY/BLOCKED/PENDING presentation concepts (MIT).

No dependency on those projects is required at runtime. If future versions copy or adapt source code rather than merely use public interfaces or concepts, the corresponding copyright and license notices must be preserved here.
