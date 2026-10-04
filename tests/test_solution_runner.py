"""T5: solution runner against a stub repo (R3, B1)."""

from __future__ import annotations

import http.server
import json
import subprocess
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("requests")

import requests  # noqa: E402

from llm_deployment_validation.solution_runner import (  # noqa: E402
    pair_slug,
    start_deployment,
)


def test_pair_slug_rule() -> None:
    assert pair_slug("Qwen/Qwen3-0.6B", "huawei-cpu") == "qwen_qwen3_0_6b_huawei_cpu"
    assert pair_slug("meta-llama/Llama-2-7b", "GPU A100") == ("meta_llama_llama_2_7b_gpu_a100")


@pytest.fixture()
def stub_repo(tmp_path: Path) -> Path:
    """A stub solution repo with a deploy.py that serves /health on the given port."""
    repo = tmp_path / "stub_repo"
    repo.mkdir()
    (repo / "config" / "deployment_configurations").mkdir(parents=True)
    (repo / "config" / "deployment_configurations" / "stub_model_stub_cpu.yaml").write_text(
        "model: stub-model\nhardware: stub-cpu\n"
    )
    (repo / "config" / "deployment_configurations" / "stub_model_stub_cpu.sh").write_text(
        "#!/usr/bin/env bash\necho 'setup ran' > setup_ran_marker.txt\n"
    )
    deploy = repo / "deploy.py"
    deploy.write_text("""
import http.server, socketserver, sys, json
args = dict(a.split('=', 1) for a in sys.argv[1:] if '=' in a)
port = int(args.get('port', '8000'))
model = args.get('model')
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
        elif self.path == '/v1/models':
            body = json.dumps({"data": [{"id": model}]}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body)
        else:
            self.send_response(404); self.end_headers()
    def log_message(self, *a): pass
extra = dict(a.split('=', 1) for a in sys.argv[1:] if '=' in a)
if 'should_fail' in extra and extra['should_fail'] == '1':
    sys.exit(3)
with socketserver.TCPServer(('127.0.0.1', port), H) as httpd:
    httpd.serve_forever()
""")
    import json  # noqa: F401

    # make the repo a git repo and commit
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    return repo


def _local_clone_link(repo: Path) -> str:
    return str(repo)


def test_runner_deploys_and_polls_health(stub_repo, tmp_path) -> None:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=stub_repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    handle = start_deployment(
        repo_link=str(stub_repo),
        commit=commit,
        model="stub-model",
        hardware="stub-cpu",
        port=0,  # ignored by stub but required by the interface
        workdir=tmp_path / "run",
        health_timeout_s=30,
        health_interval_s=0.2,
    )
    try:
        assert handle.process.poll() is None
        assert handle.venv_dir.is_dir()
        marker = handle.repo_dir / "setup_ran_marker.txt"
        assert marker.is_file(), "setup script must have run in the venv"
        response = requests.get(f"http://127.0.0.1:{handle.port}/v1/models", timeout=5)
        assert response.status_code == 200
    finally:
        handle.stop()
    assert handle.process.poll() is not None
    assert not handle.venv_dir.exists(), "temporary venv must be destroyed"


def test_runner_appends_solution_overrides(stub_repo, tmp_path, monkeypatch) -> None:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=stub_repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    recorded = {}
    real_popen = subprocess.Popen

    def fake_popen(cmd, *args, **kwargs):
        recorded["cmd"] = cmd
        return real_popen(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    handle = start_deployment(
        repo_link=str(stub_repo),
        commit=commit,
        model="stub-model",
        hardware="stub-cpu",
        port=0,
        solution_overrides="max_model_len=8192 should_fail=0",
        workdir=tmp_path / "run2",
        health_timeout_s=30,
        health_interval_s=0.2,
    )
    try:
        cmd = recorded["cmd"]
        assert "model=stub-model" in cmd
        assert "hardware=stub-cpu" in cmd
        port_args = [c for c in cmd if c.startswith("port=")]
        assert len(port_args) == 1 and int(port_args[0].split("=")[1]) > 0
        assert "max_model_len=8192" in cmd
        assert "should_fail=0" in cmd
    finally:
        handle.stop()


def test_runner_fails_when_deployment_exits(stub_repo, tmp_path) -> None:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=stub_repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    with pytest.raises(RuntimeError):
        start_deployment(
            repo_link=str(stub_repo),
            commit=commit,
            model="stub-model",
            hardware="stub-cpu",
            port=8124,
            solution_overrides="should_fail=1",
            workdir=tmp_path / "run3",
            health_timeout_s=30,
            health_interval_s=0.2,
        )
