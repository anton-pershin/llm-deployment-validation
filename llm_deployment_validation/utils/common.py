"""Shared helpers: paths, venv tools (kiss spec 3.4)."""

from __future__ import annotations

import subprocess
from pathlib import Path


def get_project_path() -> Path:
    """Return the validation repo root."""
    return Path(__file__).resolve().parents[2]


def get_config_path() -> Path:
    """Return the hydra config directory."""
    return get_project_path() / "config"


def create_temp_venv(parent_dir: str | Path) -> Path:
    """Create a temporary venv and return its path."""
    import tempfile
    import venv

    parent = Path(parent_dir)
    parent.mkdir(parents=True, exist_ok=True)
    venv_dir = Path(tempfile.mkdtemp(prefix="venv_", dir=str(parent)))
    venv.EnvBuilder(with_pip=True).create(str(venv_dir))
    return venv_dir


def run_in_venv(venv_dir: str | Path, cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command with the venv's python on PATH."""
    import os

    env = dict(os.environ)
    env["VIRTUAL_ENV"] = str(venv_dir)
    env["PATH"] = f"{Path(venv_dir) / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(cmd, env=env, **kwargs)  # noqa: S603
