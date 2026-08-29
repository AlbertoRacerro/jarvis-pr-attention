# Third-party reference coverage

This document tracks the public open-source projects that informed `jarvis-pr-attention` and separates three things that should not be conflated:

1. behavior already implemented by this project;
2. behavior intentionally excluded because it conflicts with the read-only/stateless design;
3. genuine gaps that may improve correctness or review efficiency.

Percentages refer to the **subset relevant to this project's goals**, not feature parity with an entire third-party application. The implementation remains original; these are engineering coverage estimates, not compatibility claims.

## deployhq/pr-radar — relevant subset: about 95–100% covered

Covered:

- exact PR head identity and late-head stale detection;
- paginated REST review retrieval;
- current-head review classification using review `commit_id`;
- stale and dismissed review handling;
- Check Runs plus legacy Commit Status aggregation;
- fail-closed CI normalization;
- GraphQL review-thread pagination with resolved/outdated separation;
- mergeability/conflict and change-scope facts;
- explicit fail-closed pagination-ceiling detection;
- branch/ruleset-aware required-check truth, kept separate from aggregate CI.

Deliberately excluded:

- browser extension UI and local cache;
- background polling and notifications;
- multi-forge GitLab/Bitbucket support;
- local AI summaries;
- merge/deployment UI.

The remaining differences are product-surface differences rather than correctness gaps for this tool.

## GrantBirki/pr-status — relevant subset: about 95% covered

Covered:

- exact head binding and stale-head detection;
- SUCCESS / PENDING / FAILURE / UNKNOWN check normalization;
- success for `success`, `neutral`, `skipped`;
- pending for queued/in-progress/pending/requested/waiting/expected;
- failure for failure/error/cancelled/timed-out/action-required/startup-failure/stale;
- aggregation precedence `FAILURE > UNKNOWN > PENDING > SUCCESS`;
- absent check evidence fails closed;
- mergeability/conflict evidence;
- branch/ruleset required-check awareness, including optional integration-id binding;
- draft PR state;
- native GitHub `reviewDecision` as a separate repository-policy fact.

Jarvis semantic acceptance remains separate from native GitHub approval policy. A native `APPROVED` value is evidence about repository review state, not semantic acceptance by JarvisOS.

## frankyxhl/sweeping-monk — desired subset: about 85–90% covered

Covered:

- read-only PR watchdog semantics;
- deterministic READY/BLOCKED/PENDING-style classification;
- compact attention presentation;
- exact head and CI/merge/review/thread evidence;
- structured blockers and next-action classification;
- extensive deterministic/adversarial tests;
- repair-oriented evidence packets;
- native draft/review-policy facts and fail-closed fact completeness.

Deliberately excluded:

- append-only JSONL history as authority;
- notification/webhook subsystem;
- Codex-specific reaction signals;
- automatic thread resolution;
- automatic approval/merge behavior.

Those omissions are architectural requirements, not backlog. GitHub live state remains the truth source and this tool does not actuate repository state.

## dan-sotnik/llama-pr-reviewer — relevant subset: about 90–95% covered

Covered:

- explicit previous semantic SHA;
- accepted-head-to-current-head delta review;
- hard total/per-file patch budgets;
- exact-head regeneration and stale detection;
- failed-review checkpoint reuse;
- failed-checkpoint-to-current repair-only re-review;
- multi-generation `FULL FAIL H1 -> incremental FAIL H2 -> incremental H3` chaining;
- accepted semantic baseline kept distinct from failed reviewed checkpoints;
- unresolved prior blocking-finding lineage across generations;
- explicit resolved/remaining finding classification;
- scope-expansion file identification;
- global-invariant recheck requirement;
- current unresolved/non-outdated GitHub review-thread continuity evidence;
- bounded thread evidence with nested-comment and thread-pagination fail-closed behavior;
- explicit trust boundary that treats thread bodies and patch text as untrusted evidence;
- bounded incremental PASS/FAIL validation.

Remaining differences:

- no prior-self-comment echo suppression because top-level reviewer conversation is deliberately not ingested as review input;
- the exact `base -> PR net diff` plus path-narrowing algorithm used there is not replicated; this project compares from an explicit reviewed/accepted or failed-reviewed SHA.

These are not current correctness blockers for the chosen architecture.

## SamuelCabralCruz/unresolved-review-threads — relevant subset: about 95% covered

Covered:

- GraphQL review-thread retrieval;
- resolved/unresolved distinction;
- outdated unresolved threads separated from current unresolved threads;
- current unresolved threads act as blockers;
- paginated review-thread retrieval;
- V1.11 re-review continuity for current unresolved/non-outdated threads;
- up to 100 comments per thread carried as bounded untrusted evidence;
- nested comment overflow and thread pagination exhaustion fail closed.

Deliberately excluded:

- labels;
- commit-status mutation;
- merge enforcement as an actuator;
- automatic thread resolution.

## GitHub CLI (`cli/cli`) — data concepts covered; transport backend intentionally absent

The current reusable Action uses an original Python-standard-library REST/GraphQL client with `GITHUB_TOKEN` / `GH_TOKEN` rather than shelling out to `gh`.

PR/review/status/policy data concepts are covered. `gh` transport parity remains 0% by design and is not a correctness blocker. An optional `gh` backend may still be useful later for local operator ergonomics.

## Danger, Policy Bot and reviewdog — intentionally not adopted

These were evaluated as ecosystem references but are not target architectures. Rule-engine automation, external approval-policy authority and static-finding actuation would broaden this tool beyond its deterministic read-only evidence boundary.

## Cross-cutting remaining work after V1.11

The two correctness/efficiency gaps identified after V1.10 are now covered:

1. **Re-review thread continuity** — current unresolved/non-outdated review threads are carried into bounded re-review evidence with an explicit untrusted-content boundary and fail-closed comment/thread pagination handling.
2. **Multi-generation failed-review chaining** — a validated incremental FAIL can become the next bounded checkpoint while the accepted semantic baseline remains unchanged and unresolved finding lineage is preserved.

The remaining optional engineering item is:

3. **Optional `gh` transport** — convenience backend for local use, not correctness-critical.

Top-level issue comments, deployment dashboards, notifications, persistence as authority, auto-resolve, auto-approve and auto-merge remain non-goals unless a future consumer demonstrates a concrete need.
