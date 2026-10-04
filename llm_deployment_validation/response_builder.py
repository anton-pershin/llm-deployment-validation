"""Response builder: assembles the response JSON (validation spec 5.1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_deployment_validation.metrics_evaluator import CriterionResult


def build_response(
    profile_name: str, validation_scope: str, results: dict[str, CriterionResult]
) -> dict[str, Any]:
    """Build the response dict: profile, scope and in-scope criteria only."""
    response: dict[str, Any] = {
        "profile": profile_name,
        "validation_scope": validation_scope,
    }
    for criterion, result in results.items():
        response[criterion] = {
            "status": result.status,
            "metrics_status": {
                metric: {
                    "computation_status": metric_result.computation_status,
                    "acceptance_status": metric_result.acceptance_status,
                    "computed_value": metric_result.computed_value,
                    "expected_value_or_threshold": metric_result.expected_value_or_threshold,
                    "error_message": metric_result.error_message,
                }
                for metric, metric_result in result.metrics_status.items()
            },
        }
    return response


def write_response(response: dict[str, Any], output_json: str | Path) -> None:
    """Write the response JSON to the output file (CLI runs)."""
    path = Path(output_json)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(response, indent=2) + "\n")
