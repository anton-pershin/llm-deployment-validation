"""Shared test fixtures: profile path, stub artifacts, synthetic values."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = REPO_ROOT / "config" / "profile" / "default.yaml"


@pytest.fixture()
def profile_path() -> Path:
    return PROFILE_PATH


@pytest.fixture()
def synthetic_metric_values() -> dict:
    """Synthetic VM values for the metrics evaluator tests."""
    return {
        "VM1": {"computed_value": 1.0},
        "VM2": {"computed_value": 6.0},
        "VM3": {"computed_value": 0.01},
        "VM4": {"computed_value": 0.2},
        "VM6": {"computed_value": 0.5},
    }
