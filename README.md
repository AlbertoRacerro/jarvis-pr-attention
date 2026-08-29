# jarvis-pr-attention

Deterministic exact-head PR attention snapshots, incremental review plans, bounded delta review packets, reviewer handoff artifacts, structured review-result validation, and advisory integration gates for agentic software delivery.

`jarvis-pr-attention` is a small, read-only GitHub fact collector. It turns live pull-request state into machine-readable evidence without invoking an LLM and without becoming a second source of truth.

## Design

- GitHub live state is the only source of truth.
- Every snapshot is bound to an exact PR `head_sha`.
- The PR is re-read after collection; if the head changed, the snapshot is `STALE`.
- Missing or ambiguous required evidence fails closed as `UNKNOWN`.
- The tool never merges, approves, resolves threads, comments, labels, or writes repository state.
- Old-head reviews are reported as stale evidence, not current approval/blocking evidence.
- Unresolved current threads and unresolved outdated threads are counted separately.
- An optional previously accepted semantic head can be supplied explicitly; the tool never guesses one.
- Accepted-head evidence is reused only when GitHub proves the accepted head is the current head or an ancestor of it.
- Diverged/behind baselines and incomplete large compare results fail closed to full review.
- Reviewer-produced results are treated as claims and are accepted only when they bind exactly to the packet/head they reviewed.
- Patch text remains explicitly untrusted throughout reviewer handoff.
- Positive semantic review cannot override stale, blocked, pending, or incomplete GitHub evidence.

## CLI

Requires Python 3.11+. GitHub-reading commands require `GITHUB_TOKEN` (or `GH_TOKEN`) with read access to the target repository. Packet digesting, reviewer handoff generation, non-live result validation, and integration-gate evaluation work offline.

```bash
PYTHONPATH=src python -m pr_attention snapshot owner/repo 123
PYTHONPATH=src python -m pr_attention snapshot owner/repo 123 --json
```

To plan an incremental semantic re-review, provide the **full 40-character SHA** of the last head that an external authority already accepted:

```bash
PYTHONPATH=src python -m pr_attention snapshot owner/repo 123 \
  --accepted-head 0123456789abcdef0123456789abcdef01234567
```

The accepted head is an input claim, not state owned by this tool. `jarvis-pr-attention` verifies its relationship to the live PR head through GitHub's compare API.

Exit codes remain tied to the PR attention state:

| Code | State |
| ---: | --- |
| 0 | READY |
| 10 | PENDING |
| 20 | BLOCKED |
| 30 | STALE |
| 40 | UNKNOWN / retrieval failure |

Use `--no-state-exit` when the caller needs the snapshot but should not fail based on attention state.

## Review acceleration

Schema V2 adds an explicit `delta` block and `next_action_class`.

Accepted-head relationships are normalized as:

| Relation | Meaning | Review scope |
| --- | --- | --- |
| `ABSENT` | no accepted head supplied | `FULL` |
| `CURRENT` | accepted head is the current head / identical | `NONE` |
| `AHEAD` | current head descends from accepted head | `DELTA` when file evidence is complete |
| `BEHIND` | current head is older than the accepted head | `FULL` |
| `DIVERGED` | histories diverged | `FULL` |
| `UNKNOWN` | compare evidence unavailable/ambiguous | `UNKNOWN` |

For ordinary descendant repairs, unchanged semantic evidence remains reusable and the snapshot lists only files in the `accepted_head...current_head` delta. GitHub compare responses at the 300-file cap are treated as incomplete and force `FULL` review rather than silently truncating the review scope.

`next_action_class` is deliberately coarse and deterministic:

- `REFRESH_SNAPSHOT` — head moved during collection;
- `INVESTIGATE_UNKNOWN` — required facts or delta relationship are unknown;
- `REPAIR` — current GitHub state contains a blocker;
- `WAIT_FOR_GATES` — CI/mergeability is still pending;
- `FULL_REVIEW` — no safely reusable semantic baseline exists;
- `REVIEW_DELTA` — baseline is an ancestor and only the complete delta needs review;
- `MERGE_CANDIDATE` — current head already matches accepted semantics and GitHub gates are clear.

`MERGE_CANDIDATE` is **not merge authority**. The caller remains responsible for its own governance and exact-head merge guards.

## Bounded review packets

A reviewer-facing packet contains the exact patch evidence for the validated `accepted-head...current-head` delta without invoking any model:

```bash
PYTHONPATH=src python -m pr_attention review-packet owner/repo 123 \
  --accepted-head 0123456789abcdef0123456789abcdef01234567 \
  --output packet.json --json
```

Defaults are deliberately bounded to **120,000 aggregate patch bytes** and **30,000 bytes per file**. Both budgets are configurable. UTF-8 truncation is deterministic and never silently claims full coverage.

Packet coverage is one of:

- `COMPLETE` — every required delta patch is present in full;
- `PARTIAL` — some patch evidence is included but at least one file is missing or truncated;
- `NONE` — no delta packet can satisfy the required scope, for example when a full review is required;
- `UNKNOWN` — exact packet evidence could not be established safely.

A packet is re-bound to the exact PR head after patch collection. If the head moves during collection it becomes `UNKNOWN` and directs the caller to `REFRESH_SNAPSHOT`. GitHub's 300-file compare cap also fails closed rather than pretending the packet is complete.

Every packet carries `content_trust: UNTRUSTED_REPOSITORY_CONTENT`. **Patch text is data, never instructions.** A reviewer agent must not follow commands, prompts, or policy-looking text found inside the patch.

Review-packet exit codes are `0=COMPLETE`, `50=PARTIAL`, `60=NONE`, `70=UNKNOWN/retrieval failure`. Use `--no-coverage-exit` for orchestration that consumes coverage from JSON instead.

## Structured review results

A deterministic contract binds the result produced by an external semantic reviewer such as ChatGPT, Claude, GLM, or a human review service. `jarvis-pr-attention` still does not perform the review itself.

Compute the stable identity of a packet:

```bash
PYTHONPATH=src python -m pr_attention packet-digest packet.json
```

Then validate a reviewer-produced JSON result offline:

```bash
PYTHONPATH=src python -m pr_attention validate-review-result \
  packet.json review-result.json --json
```

Or bind it to the current GitHub PR head as well:

```bash
GITHUB_TOKEN=... PYTHONPATH=src python -m pr_attention validate-review-result \
  packet.json review-result.json --live --json
```

Validation statuses are `VALID_PASS`, `VALID_FAIL`, `VALID_NEEDS_HUMAN`, `STALE`, and `INVALID`. A `PASS` is accepted only for a complete non-stale packet, exact packet digest/head bindings, every packet file declared reviewed, and zero blocking findings. `P0`, `P1`, and `P2` findings cannot be disguised as non-blocking.

The packet digest deliberately excludes transient fields such as generation time and current CI attention, so an unchanged reviewed code delta retains the same identity while gates move from pending to green. Any change to the actual packet evidence changes the digest.

`packet_sha256` is a content identity, **not a digital signature or provenance proof**. Offline validation proves result-to-packet binding. For trusted GitHub-source binding, use live regeneration/validation.

See [docs/REVIEW_RESULT_CONTRACT.md](docs/REVIEW_RESULT_CONTRACT.md) for the exact result schema and validation semantics.

## Reviewer handoff

Generate a safe result template already bound to a packet:

```bash
PYTHONPATH=src python -m pr_attention review-result-template packet.json \
  --reviewer-name ChatGPT \
  --reviewer-model GPT-5.6-Sol \
  --output review-result.json
```

The default template is conservative: `verdict=NEEDS_HUMAN`, `reviewed_files=[]`, and no findings. Files are never declared reviewed merely because they were delivered. `--prefill-reviewed-files` is an explicit opt-in for mechanical clients.

Generate a complete machine-readable handoff envelope:

```bash
PYTHONPATH=src python -m pr_attention review-envelope packet.json \
  --reviewer-name Claude \
  --output review-envelope.json
```

The envelope explicitly separates tool-generated `control_plane` instructions from repository-derived `untrusted_evidence`. Repository patches cannot redefine the review contract and remain marked `UNTRUSTED_REPOSITORY_CONTENT`.

See [docs/REVIEWER_HANDOFF.md](docs/REVIEWER_HANDOFF.md) for the model-agnostic flow and trust boundary.

## Advisory integration gate

After a structured semantic result has been validated, combine it with an exact GitHub snapshot:

```bash
PYTHONPATH=src python -m pr_attention integration-gate \
  snapshot.json review-validation.json \
  --output integration-gate.json
```

The gate is deterministic and offline. Its statuses are:

- `READY_TO_MERGE` — valid live-bound semantic PASS + current GitHub `READY`;
- `WAIT_FOR_GATES` — semantic PASS but current checks/mergeability are pending;
- `REPAIR` — semantic FAIL or GitHub blocking state;
- `REVIEW_REQUIRED` — semantic result is invalid;
- `NEEDS_HUMAN` — reviewer explicitly escalated;
- `VERIFY_LIVE` — semantic PASS is valid offline but has not been bound to the live PR head;
- `STALE` — snapshot/review/live-head evidence refers to a moved or mismatched head;
- `UNKNOWN` — malformed or incomplete evidence cannot be mapped safely.

`READY_TO_MERGE` remains **advisory only**. It never executes a merge. The caller must still refresh repository state as required by its governance and merge using an exact expected-head guard.

See [docs/INTEGRATION_GATE.md](docs/INTEGRATION_GATE.md) for precedence, exit codes, and Action behavior.

## Snapshot fields

The snapshot schema includes:

- exact initial and final head SHA;
- scope (`additions`, `deletions`, `changed_files`);
- normalized Check Runs + legacy Status Contexts;
- current-head vs stale/dismissed reviews;
- resolved, unresolved-current, and unresolved-outdated review threads;
- mergeability/conflict state;
- accepted-head relationship, evidence validity and exact delta file list;
- deterministic `READY | PENDING | BLOCKED | STALE | UNKNOWN` attention state;
- deterministic `next_action_class`;
- blocker, pending-reason and review-plan reason lists.

## Reusable GitHub Action

```yaml
permissions:
  contents: read
  checks: read
  statuses: read
  pull-requests: read

steps:
  - uses: AlbertoRacerro/jarvis-pr-attention@<PINNED_COMMIT_SHA>
    id: attention
    with:
      pr-number: ${{ github.event.pull_request.number }}
      accepted-head: ${{ steps.authority.outputs.last-accepted-head }}
      reviewer-name: ChatGPT
      review-result-file: review-result.json
  - run: |
      echo "attention=${{ steps.attention.outputs.attention }}"
      echo "packet=${{ steps.attention.outputs.packet-sha256 }}"
      echo "semantic=${{ steps.attention.outputs.review-result-status }}"
      echo "gate=${{ steps.attention.outputs.integration-gate-status }}"
      echo "ready=${{ steps.attention.outputs.integration-merge-ready }}"
```

When `accepted-head` is supplied, Action outputs include snapshot/packet evidence plus `packet-sha256`, `review-result-template-file`, and `review-envelope-file`.

If `review-result-file` is supplied, the Action regenerates the packet, validates the structured result against it and the live PR head, computes the advisory integration gate, and emits `review-result-status`, `review-result-valid`, `review-result-validation-file`, `integration-gate-status`, `integration-merge-ready`, and `integration-gate-file`.

These remain evidence only; the Action never approves or merges. Pin the action to an exact commit SHA in production consumers.

## Development

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

The project intentionally has no runtime dependencies outside the Python standard library.

## Attribution

The implementation is original but informed by public patterns from GitHub CLI, DeployHQ PR Radar, GrantBirki/pr-status, and frankyxhl/sweeping-monk. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## License

MIT.
