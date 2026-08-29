# GitHub truth hardening

V1.10 hardens the live GitHub facts used by `jarvis-pr-attention` without expanding the tool's authority. GitHub remains the source of repository truth; this project still performs no merge, approval, comment, label, thread-resolution, or other repository mutation.

## Aggregate CI vs required checks

The snapshot keeps the existing aggregate Check Runs + legacy Commit Status view under `checks`, but now adds a separate `checks.required` block.

Required-check policy is derived from two GitHub sources for the pull request base branch:

1. the branch metadata protection summary;
2. GitHub's effective branch rules endpoint, including active rulesets.

The tool only claims `checks.required.known=true` when both policy sources were retrieved successfully. Policy retrieval failure therefore cannot silently turn into “no required checks”.

A required status-check entry is normalized to a context plus an optional GitHub integration id. When an integration id is present, only a Check Run with the same context and GitHub App id can satisfy that requirement. A legacy commit status cannot impersonate an app-bound requirement.

Required-check state is one of:

- `NONE` — policy is known and requires no status checks;
- `SUCCESS` — every required check is satisfied;
- `PENDING` — at least one required check is pending or has not appeared yet;
- `FAILURE` — at least one required check is failing;
- `UNKNOWN` — policy is known but the matching execution evidence is ambiguous.

Aggregate CI remains visible because optional checks are still useful operational evidence. Required-check truth is not inferred from the aggregate result.

## Pagination safety ceilings

The GitHub client intentionally caps pagination to bound work. V1.10 makes that bound fail closed.

If REST review pagination, Check Runs, legacy statuses, or GraphQL review threads still report more data after the configured page ceiling, collection raises a bounded `GitHubError`. The snapshot then records incomplete GitHub facts and attention becomes `UNKNOWN`; a truncated prefix is never presented as complete truth.

## Draft and native GitHub review decision

The snapshot now adds `reviews.native_policy` with:

- `known`;
- `draft`;
- `review_decision` (`NONE`, `APPROVED`, `CHANGES_REQUESTED`, `REVIEW_REQUIRED`, or `UNKNOWN`);
- explanatory reasons.

The data comes from GraphQL `isDraft` and `reviewDecision`; draft state is cross-checked against the REST pull-request payload when both are available.

These fields are **GitHub repository-policy facts only**. `APPROVED` never becomes Jarvis semantic acceptance. Jarvis semantic acceptance remains represented by the exact-head structured reviewer-result contract and its evidence bundle.

Attention mapping is conservative:

- draft => `BLOCKED`;
- native `CHANGES_REQUESTED` => `BLOCKED`;
- native `REVIEW_REQUIRED` => `PENDING`;
- native `APPROVED` or `NONE` => no extra semantic authority.

## Evidence compatibility

V1.10 deliberately keeps snapshot `schema_version=2` and extends the already-hashed `checks` and `reviews` objects additively. This has two advantages:

- historical V2 evidence bundles remain verifiable with their original digest semantics;
- fresh V1.10 bundles bind required-check and native-policy truth because the existing snapshot digest already hashes the complete `checks` and `reviews` blocks.

This avoids an unnecessary schema fork while preserving exact evidence identity.

## Failure boundary

Any unavailable required source — including an exhausted pagination ceiling, branch policy retrieval failure, or native-policy retrieval failure — sets `facts_complete=false`. The tool does not guess a permissive result.
