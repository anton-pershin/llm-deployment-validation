"""T4: CLI entry points (R1) - hydra-app style."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "llm_deployment_validation" / "scripts"


def test_scripts_exist() -> None:
    for name in ("validation_cli.py", "validation_cli_partial.py", "validation_service.py"):
        assert (SCRIPTS / name).is_file(), name


def test_cli_config_has_mandatory_fields() -> None:
    """The CLI hydra config must declare the mandatory args (repo, commit, output_json)."""
    config = (REPO_ROOT / "config" / "config_cli.yaml").read_text()
    for field in ("repo", "commit", "output_json", "solution_overrides"):
        assert f"{field}:" in config, field


def _run_cli(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPTS / script), *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_cli_fails_without_mandatory_args() -> None:
    """repo/commit/output_json default to null; main must fail with a clear error."""
    result = _run_cli("validation_cli.py")
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "missing mandatory arguments" in combined


def test_cli_writes_output_json(tmp_path, monkeypatch) -> None:
    """With a mocked heavy pipeline, the CLI writes the response to output_json."""
    from llm_deployment_validation import run_lib

    response = {"profile": "default", "validation_scope": "full"}

    class FakeEngine:
        def run(self, **kwargs):
            assert kwargs["validation_scope"] == "full"
            return response

    monkeypatch.setattr(run_lib, "build_engine", lambda profile, s: FakeEngine())
    output = tmp_path / "out.json"
    run_lib.execute_run(
        repo="x",
        commit="abc",
        output_json=str(output),
        solution_overrides="",
        profile_name="default",
        validation_scope="full",
        settings=run_lib.default_settings(),
    )
    assert json.loads(output.read_text())["profile"] == "default"


def test_partial_cli_uses_partial_scope(tmp_path, monkeypatch) -> None:
    from llm_deployment_validation import run_lib

    seen = {}

    class FakeEngine:
        def run(self, **kwargs):
            seen["scope"] = kwargs["validation_scope"]
            return {"profile": "default", "validation_scope": kwargs["validation_scope"]}

    monkeypatch.setattr(run_lib, "build_engine", lambda profile, s: FakeEngine())
    output = tmp_path / "out_partial.json"
    run_lib.execute_run(
        repo="x",
        commit="abc",
        output_json=str(output),
        solution_overrides="",
        profile_name="default",
        validation_scope="partial",
        settings=run_lib.default_settings(),
    )
    assert seen["scope"] == "partial"
    assert json.loads(output.read_text())["validation_scope"] == "partial"
