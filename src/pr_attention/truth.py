from __future__ import annotations

from collections import OrderedDict
from typing import Any

from .models import NativeReviewPolicySummary, RequiredCheckSummary

_SUCCESS_CONCLUSIONS = {"success", "neutral", "skipped"}
_PENDING_STATES = {"queued", "in_progress", "pending", "requested", "waiting", "expected"}
_FAILURE_STATES = {
    "failure",
    "cancelled",
    "timed_out",
    "action_required",
    "startup_failure",
    "stale",
    "error",
}
_NATIVE_DECISIONS = {"APPROVED", "CHANGES_REQUESTED", "REVIEW_REQUIRED"}


def _requirement_key(context: str, integration_id: int | None) -> tuple[str, int | None]:
    return context, integration_id


def _clean_integration_id(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _add_requirement(
    out: OrderedDict[tuple[str, int | None], dict[str, Any]],
    *,
    context: Any,
    integration_id: Any,
    source: str,
) -> None:
    if not isinstance(context, str) or not context.strip():
        return
    context = context.strip()
    cleaned_id = _clean_integration_id(integration_id)
    key = _requirement_key(context, cleaned_id)
    existing = out.get(key)
    if existing is None:
        out[key] = {
            "context": context,
            "integration_id": cleaned_id,
            "sources": [source],
            "state": "UNKNOWN",
        }
    elif source not in existing["sources"]:
        existing["sources"].append(source)


def _candidate_state(run: dict[str, Any]) -> str:
    status = str(run.get("status") or "").lower()
    conclusion = run.get("conclusion")
    conclusion_s = str(conclusion).lower() if conclusion is not None else ""
    if conclusion_s in _FAILURE_STATES:
        return "FAILURE"
    if status in _PENDING_STATES or (status != "completed" and not conclusion_s):
        return "PENDING"
    if conclusion_s in _SUCCESS_CONCLUSIONS:
        return "SUCCESS"
    return "UNKNOWN"


def _legacy_state(context: dict[str, Any]) -> str:
    state = str(context.get("state") or "").lower()
    if state == "success":
        return "SUCCESS"
    if state in {"pending", "expected"}:
        return "PENDING"
    if state in {"failure", "error"}:
        return "FAILURE"
    return "UNKNOWN"


def _aggregate_candidate_states(states: list[str]) -> str:
    if "FAILURE" in states:
        return "FAILURE"
    if "UNKNOWN" in states:
        return "UNKNOWN"
    if "PENDING" in states:
        return "PENDING"
    if "SUCCESS" in states:
        return "SUCCESS"
    return "MISSING"


def normalize_required_checks(
    branch_payload: dict[str, Any] | None,
    branch_rules: list[dict[str, Any]] | None,
    check_runs: list[dict[str, Any]],
    status_contexts: list[dict[str, Any]],
) -> RequiredCheckSummary:
    """Resolve required GitHub check truth separately from aggregate CI evidence.

    Both classic branch-protection metadata and effective branch rules must be
    available before this function claims that the required-check policy is
    known. Missing policy evidence fails closed to UNKNOWN.
    """
    if not isinstance(branch_payload, dict) or not isinstance(branch_rules, list):
        return RequiredCheckSummary(
            known=False,
            state="UNKNOWN",
            reasons=["required-check policy evidence is unavailable"],
        )

    requirements: OrderedDict[tuple[str, int | None], dict[str, Any]] = OrderedDict()
    policy_sources: list[str] = []

    protection = branch_payload.get("protection")
    if isinstance(protection, dict):
        required_status = protection.get("required_status_checks")
        if isinstance(required_status, dict):
            policy_sources.append("branch-protection")
            explicit_contexts: set[str] = set()
            for item in required_status.get("checks") or []:
                if not isinstance(item, dict):
                    continue
                context = item.get("context")
                if isinstance(context, str) and context.strip():
                    explicit_contexts.add(context.strip())
                _add_requirement(
                    requirements,
                    context=context,
                    integration_id=item.get("app_id"),
                    source="branch-protection",
                )
            for context in required_status.get("contexts") or []:
                if isinstance(context, str) and context.strip() in explicit_contexts:
                    continue
                _add_requirement(
                    requirements,
                    context=context,
                    integration_id=None,
                    source="branch-protection",
                )

    for rule in branch_rules:
        if not isinstance(rule, dict) or rule.get("type") != "required_status_checks":
            continue
        source = f"ruleset:{rule.get('ruleset_id') or rule.get('id')}" if (rule.get("ruleset_id") or rule.get("id")) else "ruleset"
        if source not in policy_sources:
            policy_sources.append(source)
        parameters = rule.get("parameters")
        if not isinstance(parameters, dict):
            continue
        for item in parameters.get("required_status_checks") or []:
            if not isinstance(item, dict):
                continue
            _add_requirement(
                requirements,
                context=item.get("context"),
                integration_id=item.get("integration_id"),
                source=source,
            )

    if not requirements:
        return RequiredCheckSummary(
            known=True,
            state="NONE",
            required=[],
            sources=policy_sources,
            reasons=["no required status-check policy applies to the base branch"],
        )

    passed: list[str] = []
    pending: list[str] = []
    failed: list[str] = []
    missing: list[str] = []
    unknown: list[str] = []

    for requirement in requirements.values():
        context = requirement["context"]
        integration_id = requirement["integration_id"]
        states: list[str] = []

        for run in check_runs:
            if str(run.get("name") or "") != context:
                continue
            if integration_id is not None:
                app_id = ((run.get("app") or {}).get("id"))
                if app_id != integration_id:
                    continue
            states.append(_candidate_state(run))

        if integration_id is None:
            for item in status_contexts:
                if str(item.get("context") or "") == context:
                    states.append(_legacy_state(item))

        state = _aggregate_candidate_states(states)
        requirement["state"] = state
        label = context if integration_id is None else f"{context}@app:{integration_id}"
        if state == "SUCCESS":
            passed.append(label)
        elif state == "PENDING":
            pending.append(label)
        elif state == "FAILURE":
            failed.append(label)
        elif state == "MISSING":
            missing.append(label)
        else:
            unknown.append(label)

    if failed:
        overall = "FAILURE"
    elif unknown:
        overall = "UNKNOWN"
    elif pending or missing:
        overall = "PENDING"
    else:
        overall = "SUCCESS"

    return RequiredCheckSummary(
        known=True,
        state=overall,
        required=list(requirements.values()),
        passed=passed,
        pending=pending,
        failed=failed,
        missing=missing,
        unknown=unknown,
        sources=policy_sources,
        reasons=[],
    )


def normalize_native_review_policy(
    payload: dict[str, Any] | None,
    *,
    rest_draft: bool | None = None,
) -> NativeReviewPolicySummary:
    if not isinstance(payload, dict) or not isinstance(payload.get("isDraft"), bool):
        return NativeReviewPolicySummary(
            known=False,
            draft=rest_draft if isinstance(rest_draft, bool) else None,
            review_decision="UNKNOWN",
            reasons=["native pull-request review policy evidence is unavailable"],
        )

    draft = payload["isDraft"]
    if isinstance(rest_draft, bool) and rest_draft != draft:
        return NativeReviewPolicySummary(
            known=False,
            draft=draft,
            review_decision="UNKNOWN",
            reasons=["REST and GraphQL draft state disagree"],
        )

    raw_decision = payload.get("reviewDecision")
    if raw_decision is None:
        decision = "NONE"
    elif isinstance(raw_decision, str) and raw_decision in _NATIVE_DECISIONS:
        decision = raw_decision
    else:
        return NativeReviewPolicySummary(
            known=False,
            draft=draft,
            review_decision="UNKNOWN",
            reasons=["GitHub returned an unrecognized native review decision"],
        )

    return NativeReviewPolicySummary(
        known=True,
        draft=draft,
        review_decision=decision,
        reasons=["native GitHub review policy is repository state, not Jarvis semantic acceptance"],
    )
