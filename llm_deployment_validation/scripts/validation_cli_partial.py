"""Partial-validation CLI (validation spec 5.1). Diagnostic results only.

Usage: same interface as validation_cli.py.
"""

import hydra
from omegaconf import DictConfig

from llm_deployment_validation.utils.common import get_config_path

CONFIG_NAME = "config_cli"


def main(cfg: DictConfig) -> None:
    """Run partial validation and write the response JSON."""
    from llm_deployment_validation.run_lib import (
        execute_run_from_cfg,
        resolved_user_settings,
        validate_run_args,
    )

    repo, commit, output_json = validate_run_args(cfg)
    execute_run_from_cfg(
        cfg=cfg,
        repo=repo,
        commit=commit,
        output_json=output_json,
        solution_overrides=cfg.get("solution_overrides", ""),
        validation_scope="partial",
        settings=resolved_user_settings(cfg),
    )


if __name__ == "__main__":
    hydra.main(
        config_path=str(get_config_path()),
        config_name=CONFIG_NAME,
        version_base="1.3",
    )(main)()
