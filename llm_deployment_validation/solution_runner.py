"""Solution runner: deploys the solution via the invocation contract (constitution 3.2/3.3)."""

from __future__ import annotations

import atexit
import logging
import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import venv
from dataclasses import dataclass
from pathlib import Path

import requests

LOGGER = logging.getLogger(__name__)

SLUG_FIRST_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def pair_slug(model: str, hardware: str) -> str:
    """Derive the pair slug: identifiers joined by '_', lowercased,
    every remaining non-alphanumeric character replaced by '_'
    (solution constitution spec section 4.3)."""
    joined = f"{model}_{hardware}".lower()
    slug = joined.replace("/", "_")
    slug = SLUG_FIRST_NON_ALNUM.sub("_", slug)
    return slug.strip("_")


@dataclass
class DeploymentHandle:
    """A started deployment: process, venv dir, repo dir, port, artifact log path."""

    process: subprocess.Popen
    venv_dir: Path
    repo_dir: Path
    port: int
    log_path: Path

    def stop(self) -> None:
        """Terminate the deployment process group and remove the temporary venv."""
        if self.process.poll() is None:
            LOGGER.info("stage 'deployment stop': terminating deployment on port %s", self.port)
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                try:
                    self.process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    LOGGER.warning(
                        "stage 'deployment stop': SIGTERM timed out; sending SIGKILL to the "
                        "deployment process group (port %s)",
                        self.port,
                    )
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                    self.process.wait(timeout=15)
            except ProcessLookupError:
                pass  # the process group is already gone
        shutil.rmtree(self.venv_dir, ignore_errors=True)
        LOGGER.info("stage 'deployment stop': venv %s removed", self.venv_dir)


def deployment_process_pids(handle: DeploymentHandle) -> list[int]:
    """Return the PIDs of the deployment's process group (memory sampling targets).

    The deployment is started in its own session (``start_new_session=True``),
    so its process group id equals the deployment process pid and every process
    it spawns belongs to that group. The GPU memory holders are among those
    children (``deploy.py`` only runs the vLLM server as a subprocess), so
    sampling the ``deploy.py`` pid alone would measure nothing.
    """
    pgid = handle.process.pid
    pids: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
            # Fields after the (comm) field: state, ppid, pgrp, ...
            fields = stat[stat.rindex(")") + 2 :].split()
            if int(fields[2]) == pgid:
                pids.append(int(entry.name))
        except (OSError, ValueError, IndexError):  # pragma: no cover - process races
            continue
    return sorted(pids)


def _allocate_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(
    port: int, timeout_s: float, interval_s: float, process: subprocess.Popen
) -> None:
    """Poll GET /health until HTTP 200 (constitution 3.3)."""
    deadline = time.monotonic() + timeout_s
    url = f"http://127.0.0.1:{port}/health"
    LOGGER.info(
        "stage 'readiness poll': polling %s every %ss (timeout %ss)",
        url,
        interval_s,
        timeout_s,
    )
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"deployment process exited with status {process.returncode} "
                f"while waiting for readiness"
            )
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                LOGGER.info("stage 'readiness poll': deployment is ready (HTTP 200)")
                return
        except requests.RequestException:
            pass
        time.sleep(interval_s)
    raise TimeoutError(f"deployment did not become healthy within {timeout_s}s: {url}")


def start_deployment(  # noqa: PLR0913 - explicit invocation-contract surface
    repo_link: str,
    commit: str,
    model: str,
    hardware: str,
    port: int,
    solution_overrides: str = "",
    workdir: str | Path | None = None,
    run_setup_script: bool = True,
    health_timeout_s: float = 900.0,
    health_interval_s: float = 2.0,
) -> DeploymentHandle:
    """Deploy the solution: temp venv -> clone -> setup script -> deploy.py -> /health.

    Deployments must be run strictly sequentially (validation spec 5.1); the
    caller is responsible for stopping the previous deployment first.
    """
    work = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="val_deploy_"))
    work.mkdir(parents=True, exist_ok=True)

    if port <= 0:
        port = _allocate_free_port()

    LOGGER.info(
        "stage 'venv creation': creating temporary venv at %s",
        work / "venv",
    )
    venv_dir = work / "venv"
    builder = venv.EnvBuilder(with_pip=True)
    builder.create(str(venv_dir))
    python = venv_dir / "bin" / "python"
    pip = venv_dir / "bin" / "pip"
    LOGGER.info("stage 'venv creation': done")

    LOGGER.info(
        "stage 'clone': cloning %s at commit %s into %s",
        repo_link,
        commit,
        work / "repo",
    )
    repo_dir = work / "repo"
    try:
        subprocess.run(
            ["git", "clone", "--quiet", repo_link, str(repo_dir)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "checkout", "--quiet", commit],
            cwd=str(repo_dir),
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        error_details = (exc.stderr or b"").decode(errors="replace")[-500:]
        raise RuntimeError(
            f"stage 'clone' failed for {repo_link} at {commit}: {error_details}"
        ) from exc
    LOGGER.info("stage 'clone': done")

    slug = pair_slug(model, hardware)
    setup_script = repo_dir / "config" / "deployment_configurations" / f"{slug}.sh"
    setup_log = work / "setup.log"
    if run_setup_script and setup_script.is_file():
        LOGGER.info(
            "stage 'environment setup': running %s in the temp venv (this may take minutes; "
            "artifact log: %s)",
            setup_script,
            setup_log,
        )
        env = dict(os.environ, VIRTUAL_ENV=str(venv_dir))
        env["PATH"] = f"{venv_dir / 'bin'}{os.pathsep}{env.get('PATH', '')}"
        try:
            with open(setup_log, "ab") as setup_log_file:
                subprocess.run(
                    ["bash", str(setup_script)],
                    cwd=str(repo_dir),
                    check=True,
                    env=env,
                    stdout=setup_log_file,
                    stderr=subprocess.STDOUT,
                )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"stage 'environment setup' failed (pair slug {slug}); "
                f"setup log preserved: {setup_log}"
            ) from exc
        LOGGER.info("stage 'environment setup': done")
    else:
        LOGGER.info("stage 'environment setup': no setup script for pair slug %s; skipping", slug)
        subprocess.run([str(pip), "install", "--quiet", "-U", "pip"], check=True)

    cmd = [
        str(python),
        "deploy.py",
        f"model={model}",
        f"hardware={hardware}",
        f"port={port}",
    ]
    if solution_overrides:
        cmd.extend(solution_overrides.split())

    log_path = work / "deployment.log"
    LOGGER.info(
        "stage 'deployment start': %s (artifact log: %s)",
        " ".join(cmd),
        log_path,
    )
    with open(log_path, "ab") as log_file:
        # Own session/process group: vllm spawns worker subprocesses; killing the
        # group takes them all down with the parent (no leaked workers/RAM).
        process = subprocess.Popen(
            cmd,
            cwd=str(repo_dir),
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )

    handle = DeploymentHandle(
        process=process, venv_dir=venv_dir, repo_dir=repo_dir, port=port, log_path=log_path
    )
    try:
        _wait_for_health(port, health_timeout_s, health_interval_s, process)
    except Exception as exc:  # noqa: BLE001 - any failure stops the deployment
        handle.stop()
        raise RuntimeError(
            f"deployment failed while waiting for readiness: {exc}; "
            f"deployment log preserved: {log_path}"
        ) from exc
    atexit.register(handle.stop)
    return handle
