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

## dan-sotnik/llama-pr-reviewer — relevant subset: about 75–80% covered

Covered:

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
- no explicit prior-self-comment echo suppression because this tool does not ingest top-level reviewer conversation as review input;
- the exact `base -> PR net diff` plus path narrowing algorithm used there is not replicated; this project compares from the explicit reviewed/accepted SHA;
- multi-generation `FAIL H1 -> FAIL H2 -> repair H3` checkpoint chaining is not yet supported by the unified re-review bundle.

## SamuelCabralCruz/unresolved-review-threads — relevant subset: about 90% covered

Covered:

- GraphQL review-thread retrieval;
- resolved/unresolved distinction;
- outdated unresolved threads separated from current unresolved threads;
- current unresolved threads act as blockers;
- pagination exhaustion now fails closed.

Deliberately excluded:

- labels;
- commit-status mutation;
- merge enforcement as an actuator.

## GitHub CLI (`cli/cli`) — data concepts covered; transport backend intentionally absent

The current reusable Action uses an original Python-standard-library REST/GraphQL client with `GITHUB_TOKEN` / `GH_TOKEN` rather than shelling out to `gh`.

PR/review/status/policy data concepts are covered. `gh` transport parity remains 0% by design and is not a correctness blocker. An optional `gh` backend may still be useful later for local operator ergonomics.

## Danger, Policy Bot and reviewdog — intentionally not adopted

These were evaluated as ecosystem references but are not target architectures. Rule-engine automation, external approval-policy authority and static-finding actuation would broaden this tool beyond its deterministic read-only evidence boundary.

## Cross-cutting remaining work after V1.10

Highest-value real gaps:

1. **Re-review thread continuity** — carry current unresolved/non-outdated review threads into bounded re-review evidence where they affect the repaired scope.
2. **Multi-generation failed-review chaining** — allow a validated incremental FAIL to become the next bounded checkpoint without forcing a new full review, subject to strict continuity rules.
3. **Optional `gh` transport** — convenience backend for local use, not correctness-critical.

Top-level issue comments, deployment dashboards, notifications, persistence as authority, auto-resolve, auto-approve and auto-merge remain non-goals unless a future consumer demonstrates a concrete need.
