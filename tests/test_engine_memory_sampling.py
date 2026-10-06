"""Engine plumbing: the deployment's pids reach the adapter and AC5 gets computed."""

from __future__ import annotations

import json
import os
import signal
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest

from llm_deployment_validation import engine as engine_mod
from llm_deployment_validation.baseline_cache import BaselineCache
from llm_deployment_validation.engine import ValidationEngine
from llm_deployment_validation.profile_loader import load_profile
from llm_deployment_validation.slam_eval_adapter import SlamEvalAdapter
from llm_deployment_validation.solution_runner import DeploymentHandle

REPO_ROOT = Path(__file__).resolve().parents[1]
RTX3090_PROFILE = REPO_ROOT / "config" / "profile" / "rtx3090_oct_22.yaml"
VRAM_MAX_BYTES = int(0.5 * 2**30)  # 0.5 GiB peak < the AC5 default threshold of 1


class StubAdapter:
    """Adapter stub: records the sampling targets it was given and drops artifacts."""

    def __init__(self, root: Path) -> None:
        self.result_root = root
        self.result_root.mkdir(parents=True, exist_ok=True)
        self.sampling_calls: list[dict] = []
        self._real = SlamEvalAdapter(
            slam_eval_root="/nonexistent",
            slam_eval_python="python",
            dataset_root="/nonexistent",
            result_root=root,
            slam_shared_config_path="/nonexistent",
        )

    def run_evaluation(self, base_url, collection, run_name, gpu_pids=None, ram_pids=None, **kw):
        self.sampling_calls.append({"gpu_pids": gpu_pids, "ram_pids": ram_pids})
        run_dir = self.result_root / run_name
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "aggregated.json").write_text(
            json.dumps(
                {
                    "ttft_s": {"median": 0.05, "q95": 0.1},
                    "tpot_s": {"median": 0.003, "q95": 0.003},
                    "vram_bytes": {"n": 3, "max": VRAM_MAX_BYTES},
                }
            )
        )
        (run_dir / "predictions.jsonl").write_text(json.dumps({"scores": [0.5, 0.5]}) + "\n")
        return run_dir

    def extract_metrics(self, run_dir):
        return self._real.extract_metrics(run_dir)

    def quality_score(self, run_dir):
        return 0.5


@pytest.fixture()
def live_deployment() -> Iterator[subprocess.Popen]:
    """A real process group standing in for a deployment (start_new_session)."""
    process = subprocess.Popen(["bash", "-c", "sleep 30"], start_new_session=True)
    yield process
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except ProcessLookupError:
        pass


def test_engine_passes_deployment_pids_and_computes_ac5(tmp_path, monkeypatch, live_deployment):
    profile = load_profile(RTX3090_PROFILE)
    assert "AC5" in profile.acceptance_criteria

    def fake_start_deployment(**kwargs) -> DeploymentHandle:
        return DeploymentHandle(
            process=live_deployment,
            venv_dir=tmp_path / "venv",
            repo_dir=tmp_path / "repo",
            port=kwargs["port"],
            log_path=tmp_path / "deployment.log",
        )

    monkeypatch.setattr(engine_mod, "start_deployment", fake_start_deployment)

    work = tmp_path / "work"
    adapter = StubAdapter(work / "results")
    cache = BaselineCache(work / "cache")
    # seed a baseline cache hit: the baseline deployment must not run in this test
    cache.put(
        profile.baseline_repo,
        profile.baseline_commit,
        profile.model,
        profile.hardware,
        "partial",
        {"score": 0.5},
    )

    engine = ValidationEngine(profile=profile, adapter=cast(Any, adapter), cache=cache)
    response = engine.run(
        repo="https://example.invalid/llm-deployment.git",
        commit="deadbeef",
        validation_scope="partial",
        workdir=work,
    )

    # the adapter was told which processes to sample, and they are the
    # deployment's own process group
    assert adapter.sampling_calls, "adapter was never called"
    sampling = adapter.sampling_calls[0]
    assert live_deployment.pid in sampling["gpu_pids"]
    assert sampling["ram_pids"] == sampling["gpu_pids"]

    # VM5 flows through to AC5 instead of resolving to failed_to_compute
    ac5 = response["AC5"]
    assert ac5["status"] == "accepted"
    vm5 = ac5["metrics_status"]["VM5"]
    assert vm5["computation_status"] == "computed"
    assert vm5["computed_value"] == pytest.approx(0.5)
    assert vm5["expected_value_or_threshold"] == 1.0
