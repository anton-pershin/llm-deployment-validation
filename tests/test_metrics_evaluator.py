"""T2: metrics evaluator status rules (R6)."""

from __future__ import annotations

from llm_deployment_validation.metrics_evaluator import evaluate_all
from llm_deployment_validation.profile_loader import load_profile


def test_statuses_per_rules(profile_path, synthetic_metric_values) -> None:
    profile = load_profile(profile_path)
    results = evaluate_all(profile, synthetic_metric_values)

    # VM1=1.0 < 2.0 -> accepted; AC1 accepted
    assert results["AC1"].status == "accepted"
    # VM2=6.0 > 5.0 -> rejected -> criterion valid (measured, condition unmet)
    assert results["AC2"].status == "valid"
    assert results["AC2"].metrics_status["VM2"].acceptance_status == "rejected"
    # VM3=0.01 < 0.05, VM4=0.2 > 0.1 -> valid
    assert results["AC3"].status == "accepted"
    assert results["AC4"].status == "valid"
    assert results["AC6"].status == "accepted"


def test_out_of_scope_criteria_absent(profile_path, synthetic_metric_values) -> None:
    profile = load_profile(profile_path)
    results = evaluate_all(profile, synthetic_metric_values)
    assert "AC5" not in results


def test_failed_computation_yields_invalid(profile_path) -> None:
    profile = load_profile(profile_path)
    values = {"VM1": {"computed_value": None, "error_message": "boom"}}
    results = evaluate_all(profile, values)
    assert results["AC1"].status == "invalid"
    assert results["AC1"].metrics_status["VM1"].computation_status == "failed_to_compute"
    assert results["AC1"].metrics_status["VM1"].error_message == "boom"


def test_thresholds_come_from_profile(profile_path, synthetic_metric_values) -> None:
    profile = load_profile(profile_path)
    results = evaluate_all(profile, synthetic_metric_values)
    assert results["AC1"].metrics_status["VM1"].expected_value_or_threshold == 2.0
