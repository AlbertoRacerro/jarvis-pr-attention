# Incremental re-review Action and evidence bundle

V1.9 wires the V1.8 `FAIL H1 -> repair H2 -> bounded re-review` contract into the reusable GitHub Action and exposes one self-verifying evidence bundle for consumers.

The tool still does **not** invoke a reviewer. It only prepares evidence, validates an externally produced structured result, and evaluates an advisory integration gate.

## Action inputs

A consumer activates re-review mode by passing the exact previous ordinary evidence bundle that recorded a live-bound semantic FAIL:

```yaml
- uses: AlbertoRacerro/jarvis-pr-attention@<PINNED_COMMIT_SHA>
  id: attention
  with:
    pr-number: ${{ github.event.pull_request.number }}
    previous-failed-bundle-file: previous-fail-bundle.json
    reviewer-name: ChatGPT
```

The Action then regenerates the current exact-head snapshot and produces, when safely eligible:

- `rereview-packet-file` — H1-to-H2 repair delta plus prior blocking-finding context;
- `rereview-result-template-file` — conservative result skeleton;
- `rereview-envelope-file` — tool-generated control plane plus explicitly untrusted repository evidence;
- `rereview-evidence-bundle-file` — self-contained, offline-verifiable chain from the source FAIL through the current re-review packet.

If ancestry, coverage or source-checkpoint validity cannot be proven, the Action still emits fail-closed packet/bundle evidence but does not fabricate a reusable semantic checkpoint.

## External reviewer round

After the reviewer fills the generated template, pass its file on a fresh Action invocation:

```yaml
- uses: AlbertoRacerro/jarvis-pr-attention@<PINNED_COMMIT_SHA>
  id: evaluated
  with:
    pr-number: ${{ github.event.pull_request.number }}
    previous-failed-bundle-file: previous-fail-bundle.json
    rereview-result-file: rereview-result.json
    reviewer-name: ChatGPT
```

The Action regenerates the H1-to-H2 packet against the current GitHub head, validates the result live, computes the re-review integration gate and rebuilds the unified bundle. A moved head becomes `STALE`; malformed or inconsistent evidence fails closed.

## Unified re-review bundle

`PR_ATTENTION_REREVIEW_EVIDENCE_BUNDLE` contains:

- current exact GitHub snapshot;
- the fully verified ordinary source FAIL bundle;
- H1-to-H2 re-review packet;
- deterministic re-review control plane;
- optional structured re-review result;
- optional live-bound re-review validation;
- optional deterministic re-review integration gate;
- component digests and trust markers.

Phases are:

- `REREVIEW_PACKET_READY`;
- `REREVIEW_HANDOFF_READY`;
- `REREVIEW_VALIDATED`;
- `REREVIEW_INTEGRATION_EVALUATED`.

The bundle is built only if its offline verifier can immediately reconstruct it from its own evidence. The verifier also regenerates the control plane and integration gate, so simply editing those fields and recomputing the top-level digest cannot manufacture valid evidence.

## Next action

The bundle exposes one deterministic `next_action_class`:

- `REREVIEW_DELTA` — bounded H1-to-H2 semantic re-review is required;
- `FULL_REVIEW` — incremental reuse is unsafe;
- `MERGE_CANDIDATE` — live-bound re-review PASS and GitHub state are ready;
- `WAIT_FOR_GATES`;
- `REPAIR`;
- `NEEDS_HUMAN`;
- `VERIFY_LIVE`;
- `REFRESH_SNAPSHOT`;
- `INVESTIGATE_UNKNOWN`.

`MERGE_CANDIDATE` / `READY_TO_MERGE` remain advisory. This project never executes a merge and never supersedes repository governance.

## Trust boundary

The handoff has two explicit regions:

- `control_plane` = `TOOL_GENERATED_CONTROL_DATA`;
- `untrusted_evidence` = `UNTRUSTED_REPOSITORY_CONTENT`.

Repository patches, previous finding text and other repository-derived material are evidence only. They cannot redefine the reviewer contract.

SHA-256 fields are deterministic content identities, not digital signatures or provenance proofs. Trusted source binding requires live GitHub regeneration.

## Current checkpoint limitation

V1.9 accepts an **ordinary full/delta semantic FAIL bundle** as the source checkpoint. A later incremental `VALID_FAIL` is not yet promoted into a second-generation checkpoint automatically. Multi-generation `H1 FAIL -> H2 FAIL -> H3` chaining is a future hardening slice and must preserve every unresolved finding and ancestry invariant before it can be safe.
