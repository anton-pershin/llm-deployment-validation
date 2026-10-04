"""Metrics evaluator: computes criterion statuses (validation spec 5.1 rules)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from llm_deployment_validation.profile_loader import (
    CRITERIA_TO_METRICS,
    ValidationProfile,
)

MetricValues = dict[str, dict[str, Any]]  # VM -> {computed_value or error info}


@dataclass
class MetricResult:
    """Evaluation result of one metric within a criterion."""

    name: str
    computation_status: str  # computed | failed_to_compute
    acceptance_status: str | None  # accepted | rejected | None
    computed_value: float | None
    expected_value_or_threshold: float | None
    error_message: str | None


@dataclass
class CriterionResult:
    """Evaluation result of one acceptance criterion."""

    name: str
    status: str  # accepted | valid | invalid
    metrics_status: dict[str, MetricResult]


def evaluate_criterion(
    criterion: str, metric_values: MetricValues, threshold: float
) -> CriterionResult:
    """Evaluate one acceptance criterion per the validation spec 5.1 rules."""
    metric_results: dict[str, MetricResult] = {}
    for metric in CRITERIA_TO_METRICS[criterion]:
        raw = metric_values.get(metric)
        if raw is None:
            metric_results[metric] = MetricResult(
                name=metric,
                computation_status="failed_to_compute",
                acceptance_status=None,
                computed_value=None,
                expected_value_or_threshold=threshold,
                error_message=f"metric {metric} was not produced",
            )
            continue
        value = raw.get("computed_value")
        error = raw.get("error_message")
        if value is None:
            metric_results[metric] = MetricResult(
                name=metric,
                computation_status="failed_to_compute",
                acceptance_status=None,
                computed_value=None,
                expected_value_or_threshold=threshold,
                error_message=error or f"metric {metric} failed to compute",
            )
        else:
            accepted = value < threshold
            metric_results[metric] = MetricResult(
                name=metric,
                computation_status="computed",
                acceptance_status="accepted" if accepted else "rejected",
                computed_value=float(value),
                expected_value_or_threshold=threshold,
                error_message=None,
            )

    statuses = list(metric_results.values())
    if any(m.computation_status == "failed_to_compute" for m in statuses):
        status = "invalid"
    elif all(m.acceptance_status == "accepted" for m in statuses):
        status = "accepted"
    else:
        status = "valid"
    return CriterionResult(name=criterion, status=status, metrics_status=metric_results)


def evaluate_all(
    profile: ValidationProfile, metric_values: MetricValues
) -> dict[str, CriterionResult]:
    """Evaluate every acceptance criterion in scope of the profile."""
    thresholds = profile.thresholds()
    return {
        criterion: evaluate_criterion(criterion, metric_values, thresholds[criterion])
        for criterion in profile.acceptance_criteria
    }
