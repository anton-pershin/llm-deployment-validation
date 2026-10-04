"""Shared helpers for the entry-point scripts (profile loading, engine building, CLI run)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from llm_deployment_validation.baseline_cache import BaselineCache
from llm_deployment_validation.engine import ValidationEngine
from llm_deployment_validation.profile_loader import ValidationProfile, load_profile
from llm_deployment_validation.slam_eval_adapter import SlamEvalAdapter

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "config"


def load_profile_by_name(profile_name: str) -> ValidationProfile:
    """Load a profile by name from config/profile/."""
    return load_profile(CONFIG_DIR / "profile" / f"{profile_name}.yaml")


def build_engine(profile: ValidationProfile, settings: dict[str, Any]) -> ValidationEngine:
    """Build the validation engine wired with adapter and cache from resolved settings."""
    slam_eval_python = settings.get("slam_eval_python") or sys.executable
    adapter = SlamEvalAdapter(
        slam_eval_root=settings["slam_eval_root"],
        slam_eval_python=slam_eval_python,
        dataset_root=settings["dataset_root"],
        result_root=Path(settings["result_root"]),
        slam_shared_config_path=settings.get("slam_shared_config_path") or None,
    )
    cache = BaselineCache(cache_dir=settings["cache_dir"])
    return ValidationEngine(profile=profile, adapter=adapter, cache=cache)


def resolved_user_settings(cfg: Any) -> dict[str, Any]:
    """Extract the resolved user settings from the hydra config.

    The config composition guarantees interpolations (${oc.env:...}) are
    resolved by hydra before main() is called.
    """
    user_settings = cfg.user_settings
    return {
        "slam_eval_root": user_settings.slam_eval_root,
        "slam_eval_python": user_settings.slam_eval_python,
        "dataset_root": user_settings.dataset_root,
        "result_root": user_settings.result_root,
        "cache_dir": user_settings.cache_dir,
        "slam_shared_config_path": user_settings.slam_shared_config_path,
        "health_check_timeout_s": user_settings.get("health_check_timeout_s", 900),
        "health_check_interval_s": user_settings.get("health_check_interval_s", 2.0),
    }


def execute_run_from_cfg(
    cfg: Any,
    repo: str,
    commit: str,
    output_json: str,
    solution_overrides: str,
    validation_scope: str,
    settings: dict[str, Any] | None = None,
) -> None:
    """Execute a CLI validation run using the profile composed into the hydra config."""
    from llm_deployment_validation.profile_loader import profile_from_cfg

    profile = profile_from_cfg(cfg.profile)
    execute_run(
        repo=repo,
        commit=commit,
        output_json=output_json,
        solution_overrides=solution_overrides,
        profile=profile,
        validation_scope=validation_scope,
        settings=settings,
    )


def execute_run(
    repo: str,
    commit: str,
    output_json: str,
    solution_overrides: str,
    profile: ValidationProfile | None = None,
    profile_name: str | None = None,
    validation_scope: str = "partial",
    settings: dict[str, Any] | None = None,
) -> None:
    """Execute a CLI validation run (profile by name or preloaded instance)."""
    if profile is None:
        if profile_name is None:
            raise ValueError("either profile or profile_name must be provided")
        profile = load_profile_by_name(profile_name)
    if settings is None:
        settings = default_settings()
    engine = build_engine(profile, settings)
    response = engine.run(
        repo=repo,
        commit=commit,
        solution_overrides=solution_overrides,
        validation_scope=validation_scope,
    )

    from llm_deployment_validation.response_builder import write_response

    write_response(response, output_json)
    print(f"validation response written to {output_json}")


def default_settings() -> dict[str, Any]:
    """Resolve user settings outside a hydra run (e.g. for tests).

    Registers the same resolver set hydra provides at runtime so that
    interpolations like ${now:...} resolve identically.
    """
    from omegaconf import DictConfig, OmegaConf

    OmegaConf.register_new_resolver("now", _now_resolver, replace=True)

    settings_path = CONFIG_DIR / "user_settings" / "user_settings.yaml"
    if not settings_path.is_file():
        raise FileNotFoundError(f"user settings not found: {settings_path}")
    loaded = OmegaConf.load(settings_path)
    assert isinstance(loaded, DictConfig)
    resolved = OmegaConf.to_container(loaded, resolve=True)
    assert isinstance(resolved, dict)
    return {str(key): value for key, value in resolved.items()}  # type: ignore[arg-type]


def _now_resolver(pattern: str) -> str:
    """Mirror hydra's ${now:...} resolver (timestamp at config resolution)."""
    from datetime import datetime

    return datetime.now().strftime(pattern)


def validate_run_args(cfg: Any) -> tuple[str, str, str]:
    """Validate CLI-mandatory args; return (repo, commit, output_json)."""
    repo = cfg.get("repo")
    commit = cfg.get("commit")
    output_json = cfg.get("output_json")
    missing = [
        name
        for name, value in (("repo", repo), ("commit", commit), ("output_json", output_json))
        if not value
    ]
    if missing:
        raise ValueError(f"missing mandatory arguments: {', '.join(missing)}")
    return repo, commit, output_json
