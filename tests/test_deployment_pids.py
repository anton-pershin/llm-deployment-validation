"""Memory sampling targets: the deployment's process group (VM5 plumbing)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from llm_deployment_validation.solution_runner import (
    DeploymentHandle,
    deployment_process_pids,
)


def _stub_handle(process: subprocess.Popen) -> DeploymentHandle:
    placeholder = Path("/nonexistent")
    return DeploymentHandle(
        process=process,
        venv_dir=placeholder,
        repo_dir=placeholder,
        port=0,
        log_path=placeholder,
    )


def test_deployment_process_pids_covers_group_children() -> None:
    """The sampling targets must include the processes the deployment spawns.

    deploy.py only runs the vLLM server as a subprocess, so the GPU memory
    holders are children in the deployment's process group.
    """
    deployment = subprocess.Popen(
        ["bash", "-c", "sleep 30 & echo $!; wait"],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        assert deployment.stdout is not None
        spawned_child = int(deployment.stdout.readline().strip())
        time.sleep(0.5)

        pids = deployment_process_pids(_stub_handle(deployment))

        assert deployment.pid in pids
        assert spawned_child in pids
        assert os.getpid() not in pids  # the service's own process is not a target
    finally:
        try:
            os.killpg(os.getpgid(deployment.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        deployment.wait(timeout=10)


def test_deployment_process_pids_empty_for_dead_deployment() -> None:
    deployment = subprocess.Popen(["bash", "-c", "true"], start_new_session=True)
    deployment.wait(timeout=10)
    assert deployment_process_pids(_stub_handle(deployment)) == []
