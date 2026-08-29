# Structured review result contract

`jarvis-pr-attention` does not perform semantic review. It can, however, validate a reviewer-produced JSON result against the exact bounded review packet that reviewer received.

The contract is designed for ChatGPT, Claude, GLM, human review tooling, or any other external reviewer that can emit JSON. The reviewer is not trusted to establish repository truth: the validator re-binds the result to packet identity and, optionally, the live pull-request head.

## Stable packet identity

`packet_sha256` is a content identity over the stable semantic evidence envelope of a review packet:

- schema version;
- repository and PR number;
- accepted head, reviewed head, and final packet head;
- ancestry relation and review scope;
- content-trust marker;
- coverage/completeness and configured budgets;
- included patch byte count;
- exact ordered file evidence, including patch text.

Transient orchestration fields such as `generated_at`, current CI attention, `next_action_class`, and explanatory `reasons` are deliberately excluded. Therefore the same exact code delta can retain the same packet identity while CI moves from pending to green. Any change to reviewed patch evidence changes the digest.

The digest format is:

```text
sha256:<64 lowercase hexadecimal characters>
```

Use:

```bash
PYTHONPATH=src python -m pr_attention packet-digest packet.json
```

## Review result schema

A reviewer result is one JSON object:

```json
{
  "schema_version": 1,
  "repository": "owner/repo",
  "pr_number": 123,
  "accepted_head_sha": "0123456789abcdef0123456789abcdef01234567",
  "head_sha": "89abcdef0123456789abcdef0123456789abcdef",
  "packet_sha256": "sha256:...",
  "reviewer": {
    "name": "reviewer-name",
    "model": "optional-model-or-runtime-label"
  },
  "verdict": "PASS",
  "reviewed_files": ["src/example.py"],
  "findings": [],
  "notes": []
}
```

`verdict` is exactly one of:

- `PASS` — semantic review found no blocking issue in the complete packet;
- `FAIL` — semantic review found at least one blocking issue;
- `NEEDS_HUMAN` — the reviewer cannot safely reach PASS/FAIL without escalation.

`reviewer.name` is required. Other reviewer metadata may be added by the producer but is not review authority.

## Finding schema

Each finding is a JSON object with:

```json
{
  "id": "F1",
  "severity": "P1",
  "blocking": true,
  "title": "Short title",
  "detail": "Concrete explanation of the defect and its impact.",
  "path": "src/example.py",
  "line": 42
}
```

Rules:

- severity is `P0`, `P1`, `P2`, or `P3`;
- `P0`, `P1`, and `P2` findings must be declared blocking;
- `path`, when present, must exist in the packet and must also be listed in `reviewed_files`;
- `line`, when present, is a positive integer;
- finding IDs are non-empty and unique within one result.

## Fail-closed validation

A `PASS` is valid only when all of the following hold:

- packet coverage is `COMPLETE` and `complete=true`;
- packet `head_sha == final_head_sha`;
- repository, PR, accepted head, reviewed head, and packet digest all match exactly;
- every packet file is listed in `reviewed_files`;
- no blocking finding exists;
- when live validation is requested, the live PR head still equals the reviewed head.

A `FAIL` must contain at least one blocking finding.

A result with a moved live head becomes `STALE`, not PASS/FAIL. Malformed or contradictory evidence becomes `INVALID`.

Validation statuses are:

- `VALID_PASS`
- `VALID_FAIL`
- `VALID_NEEDS_HUMAN`
- `STALE`
- `INVALID`

## CLI validation

Offline binding validation does not require a GitHub token:

```bash
PYTHONPATH=src python -m pr_attention validate-review-result \
  packet.json review-result.json --json
```

To require the PR head to still match GitHub live state:

```bash
GITHUB_TOKEN=... PYTHONPATH=src python -m pr_attention validate-review-result \
  packet.json review-result.json --live --json
```

Exit codes are:

| Code | Validation status |
| ---: | --- |
| 0 | `VALID_PASS` |
| 80 | `VALID_FAIL` |
| 81 | `VALID_NEEDS_HUMAN` |
| 82 | `STALE` |
| 83 | `INVALID` or validation input/retrieval failure |

Use `--no-validation-exit` when an orchestrator should always receive JSON and decide policy itself.

## GitHub Action

When `review-result-file` is supplied, the composite Action regenerates the exact packet, validates the structured result, and performs a live-head check. It emits:

- `packet-sha256`
- `review-result-status`
- `review-result-valid`
- `review-result-validation-file`

These outputs are evidence only. They do not approve, comment, resolve threads, or merge a pull request.
