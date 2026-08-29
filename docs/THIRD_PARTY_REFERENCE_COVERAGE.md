# Third-party reference coverage

This document tracks the public open-source projects that informed `jarvis-pr-attention` and separates three things that should not be conflated:

1. behavior already implemented by this project;
2. behavior intentionally excluded because it conflicts with the read-only/stateless design;
3. genuine gaps that may improve correctness or review efficiency.

Percentages below refer to the **subset relevant to this project's goals**, not to feature parity with the entire third-party application. The implementation remains original; the percentages are engineering coverage estimates, not compatibility claims.

## deployhq/pr-radar — relevant subset: about 90–95% covered

Already covered:

- exact PR head identity;
- paginated REST review retrieval;
- current-head review classification using review `commit_id`;
- stale old-head reviews separated from current evidence;
- dismissed-review handling;
- Check Runs plus legacy Commit Status collection;
- fail-closed CI state normalization;
- GraphQL `reviewThreads` collection with `isResolved`, `isOutdated`, path, author and leading body;
- unresolved-current vs unresolved-outdated thread separation;
- mergeability/conflict state;
- additions/deletions/file counts;
- late head re-read and `STALE` classification.

Deliberately not copied:

- browser extension UI;
- local cache/background polling;
- notifications;
- multi-forge GitLab/Bitbucket support;
- local AI summaries;
- merge UI and deployment presentation.

Genuine remaining gaps:

- branch-protection/ruleset-aware **required** check classification rather than only aggregate check evidence;
- explicit fail-closed detection when an API pagination safety ceiling is exhausted.

## GrantBirki/pr-status — relevant subset: about 85–90% covered

Already covered:

- exact head binding and stale-head detection;
- SUCCESS / PENDING / FAILURE / UNKNOWN check normalization;
- success for `success`, `neutral`, `skipped`;
- pending for queued/in-progress/pending/requested/waiting/expected;
- failure for failure/error/cancelled/timed-out/action-required/startup-failure/stale;
- aggregation precedence `FAILURE > UNKNOWN > PENDING > SUCCESS`;
- absent check evidence fails closed to UNKNOWN;
- mergeability/conflict evidence;
- deterministic machine-readable decision states.

Genuine remaining gaps:

- ruleset/branch-protection required-check awareness;
- native GitHub review-decision/approval-policy evidence as a separate field;
- draft PR state is not currently a first-class attention input.

The last two should remain separate from Jarvis semantic acceptance: native GitHub approval policy is repository state, while Jarvis semantic acceptance is represented by the structured review-result contract.

## frankyxhl/sweeping-monk — desired subset: about 85% covered

Already covered:

- read-only PR watchdog semantics;
- deterministic READY/BLOCKED/PENDING-style classification;
- compact attention presentation;
- exact head and CI/merge/review/thread evidence;
- structured blockers and next-action classification;
- extensive deterministic/adversarial tests;
- repair-oriented evidence packets.

Deliberately excluded:

- append-only JSONL history as authority;
- notification/webhook subsystem;
- Codex-specific reaction signals;
- automatic thread resolution;
- automatic approval/merge behavior.

Those omissions are architectural requirements, not backlog. GitHub live state remains the truth source and this tool does not actuate repository state.

## dan-sotnik/llama-pr-reviewer — relevant subset: about 75–80% covered

Already covered:

- explicit previous semantic SHA;
- accepted-head-to-current-head delta review;
- hard total/per-file patch budgets;
- exact-head regeneration and stale detection;
- failed-review checkpoint reuse;
- H1-to-H2 repair-only re-review;
- prior blocking-finding continuity;
- scope-expansion file identification;
- global-invariant recheck requirement;
- bounded incremental PASS/FAIL validation.

Genuine remaining gaps:

- active unresolved/non-outdated review threads are not yet folded into the re-review packet as continuity evidence;
- no explicit prior-self-comment echo suppression because this tool does not currently ingest top-level reviewer conversation as review input;
- the exact `base -> PR net diff` plus path narrowing algorithm used there is not replicated; this project currently uses GitHub compare from the explicit reviewed/accepted SHA;
- multi-generation `FAIL H1 -> FAIL H2 -> repair H3` checkpoint chaining is not yet supported by the unified re-review bundle.

## SamuelCabralCruz/unresolved-review-threads — relevant subset: about 90% covered

Covered:

- GraphQL review-thread retrieval;
- resolved/unresolved distinction;
- outdated unresolved threads separated from current unresolved threads;
- current unresolved threads act as blockers.

Deliberately excluded:

- labels;
- commit-status mutation;
- merge enforcement as an actuator.

## GitHub CLI (`cli/cli`) — data concepts covered; transport backend not implemented

The original design review considered `gh` as a convenient authentication/transport layer. The current reusable Action instead uses an original Python-standard-library REST/GraphQL client with `GITHUB_TOKEN` / `GH_TOKEN`.

Therefore:

- PR/review/status data concepts inspired by GitHub CLI are covered;
- **`gh` transport parity itself is 0%**, intentionally so far.

This is not currently an alpha blocker. A `gh` backend could be useful for local operator ergonomics, while the dependency-free HTTP backend is advantageous inside a reusable Action.

## Danger, Policy Bot and reviewdog — intentionally not adopted

These were evaluated as ecosystem references but are not target architectures. Rule-engine automation, external approval-policy authority and static-finding actuation would broaden this tool beyond its intended deterministic read-only evidence boundary.

## Cross-cutting remaining work

Highest-value real gaps after V1.9:

1. **Required-check truth** — read branch protection/rulesets and distinguish required gates from optional checks without losing the raw aggregate view.
2. **Pagination exhaustion fail-closed** — if review/thread/check/status pagination reaches the configured safety ceiling while a next page still exists, surface incomplete facts rather than silently accepting the prefix.
3. **Draft/native review-decision facts** — expose them as GitHub facts without conflating them with Jarvis semantic acceptance.
4. **Re-review thread continuity** — carry current unresolved/non-outdated review threads into bounded re-review evidence when useful.
5. **Multi-generation failed-review chaining** — allow a validated incremental FAIL to become the next bounded checkpoint without forcing a new full review, subject to strict continuity rules.
6. **Optional `gh` transport** — convenience backend, not correctness-critical.

Top-level issue comments, deployment status, browser dashboards, notifications, persistence, auto-resolve, auto-approve and auto-merge are currently non-goals unless a future consumer demonstrates a concrete need.
