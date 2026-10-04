"""Profile loader: loads and validates validation profiles (validation spec 5.2)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ALL_CRITERIA = ["AC1", "AC2", "AC3", "AC4", "AC5", "AC6"]
DEFAULT_THRESHOLDS: dict[str, float] = {
    "AC1": 2.0,
    "AC2": 5.0,
    "AC3": 0.05,
    "AC4": 0.1,
    "AC5": 1.0,
    "AC6": 1.0,
}
CRITERIA_TO_METRICS: dict[str, list[str]] = {
    "AC1": ["VM1"],
    "AC2": ["VM2"],
    "AC3": ["VM3"],
    "AC4": ["VM4"],
    "AC5": ["VM5"],
    "AC6": ["VM6"],
}


@dataclass
class ValidationProfile:
    """A resolved validation profile (validation spec section 4)."""

    name: str
    solution_subproject: str
    acceptance_criteria: list[str]
    threshold_overrides: dict[str, float]
    full_collection: str
    partial_collection: str
    model: str
    hardware: str
    baseline_repo: str
    baseline_commit: str

    def thresholds(self) -> dict[str, float]:
        """Resolve thresholds: overrides win over section-3 defaults."""
        thresholds = dict(DEFAULT_THRESHOLDS)
        thresholds.update(self.threshold_overrides)
        return {ac: thresholds[ac] for ac in self.acceptance_criteria}

    def collection_for_scope(self, scope: str) -> str:
        """Return the slam-eval collection name for the validation scope."""
        if scope == "full":
            return self.full_collection
        if scope == "partial":
            return self.partial_collection
        raise ValueError(f"unknown validation scope: {scope!r}")


@dataclass
class ProfileError(Exception):
    """Raised when a profile file is malformed."""

    message: str


def load_profile(path: str | Path) -> ValidationProfile:
    """Load a profile yaml and validate it against the validation spec."""
    path = Path(path)
    if not path.is_file():
        raise ProfileError(f"profile file not found: {path}")
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ProfileError(f"profile {path} is not a mapping")
    return profile_from_raw(raw, source=str(path))


def profile_from_cfg(cfg: Any) -> ValidationProfile:
    """Build a ValidationProfile from the profile config composed by hydra."""
    from omegaconf import DictConfig, OmegaConf

    if isinstance(cfg, DictConfig):
        raw = OmegaConf.to_container(cfg, resolve=True)
    else:
        raw = dict(cfg)
    assert isinstance(raw, dict)
    return profile_from_raw(raw, source="hydra composition")


def profile_from_raw(raw: dict, source: str) -> ValidationProfile:
    """Validate a raw profile mapping against the validation spec."""
    path = source

    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise ProfileError(f"profile {path} misses a non-empty 'name'")

    criteria = raw.get("acceptance_criteria")
    if not isinstance(criteria, list) or not criteria:
        raise ProfileError(f"profile {path} misses a non-empty 'acceptance_criteria' list")
    unknown = [ac for ac in criteria if ac not in ALL_CRITERIA]
    if unknown:
        raise ProfileError(f"profile {path} references unknown acceptance criteria: {unknown}")

    overrides = raw.get("threshold_overrides", {})
    if not isinstance(overrides, dict):
        raise ProfileError(f"profile {path} 'threshold_overrides' must be a mapping")
    bad_overrides = {
        ac: value
        for ac, value in overrides.items()
        if ac not in ALL_CRITERIA or not isinstance(value, (int, float))
    }
    if bad_overrides:
        raise ProfileError(
            f"profile {path} has invalid threshold overrides (must be numeric values "
            f"for known criteria): {bad_overrides}"
        )

    full_cfg = raw.get("full_validation", {})
    partial_cfg = raw.get("partial_validation", {})
    for scope, cfg in (("full", full_cfg), ("partial", partial_cfg)):
        if not isinstance(cfg, dict) or not isinstance(cfg.get("collection"), str):
            raise ProfileError(
                f"profile {path} must define full and partial validation "
                f"with a 'collection' string (got bad {scope} config: {cfg})"
            )

    baseline = raw.get("baseline", {})
    if (
        not isinstance(baseline, dict)
        or not isinstance(baseline.get("repo"), str)
        or not isinstance(baseline.get("commit"), str)
    ):
        raise ProfileError(f"profile {path} must define a baseline (repo, commit) reference")

    return ValidationProfile(
        name=name,
        solution_subproject=str(raw.get("solution_subproject", "")),
        acceptance_criteria=list(criteria),
        threshold_overrides={ac: float(v) for ac, v in overrides.items()},
        full_collection=full_cfg["collection"],
        partial_collection=partial_cfg["collection"],
        model=str(raw.get("model", "")),
        hardware=str(raw.get("hardware", "")),
        baseline_repo=baseline["repo"],
        baseline_commit=baseline["commit"],
    )
