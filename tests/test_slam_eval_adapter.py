"""T6: slam-eval adapter extraction from fixture artifacts (R4, R5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_deployment_validation.slam_eval_adapter import SlamEvalAdapter


@pytest.fixture()
def adapter(tmp_path: Path) -> SlamEvalAdapter:
    return SlamEvalAdapter(
        slam_eval_root=tmp_path / "slam_eval",
        slam_eval_python="python",
        dataset_root=tmp_path / "datasets",
        result_root=tmp_path / "results",
        slam_shared_config_path=tmp_path / "shared_config",
    )


@pytest.fixture()
def run_dir(tmp_path: Path) -> Path:
    run = tmp_path / "results" / "run1"
    run.mkdir(parents=True)
    aggregated = {
        "ttft_s": {"median": 0.5, "q95": 1.2},
        "tpot_s": {"median": 0.02, "q95": 0.08},
        "vram_bytes": {},
    }
    (run / "aggregated.json").write_text(json.dumps(aggregated))
    record = {
        "group_id": "run1",
        "scores": [0.8, 0.9],
        "model_answers": ["a", "b"],
    }
    (run / "predictions.jsonl").write_text(json.dumps(record) + "\n")
    return run


def test_extract_vm1_vm4(adapter, run_dir) -> None:
    metrics = adapter.extract_metrics(run_dir)
    assert metrics["VM1"] == {"computed_value": 0.5}
    assert metrics["VM2"]["computed_value"] == pytest.approx(1.2)
    assert metrics["VM3"] == {"computed_value": 0.02}
    assert metrics["VM4"]["computed_value"] == pytest.approx(0.08)


def test_vm5_failed_to_compute_without_gpu(adapter, run_dir) -> None:
    metrics = adapter.extract_metrics(run_dir)
    assert metrics["VM5"]["computed_value"] is None
    assert "error_message" in metrics["VM5"]


def test_vm5_from_gpu_samples(adapter, tmp_path) -> None:
    run = tmp_path / "results" / "run2"
    run.mkdir(parents=True)
    aggregated = {
        "ttft_s": {"median": 0.5},
        "tpot_s": {"median": 0.02},
        "vram_bytes": {"max": 8 * 2**30},
    }
    (run / "aggregated.json").write_text(json.dumps(aggregated))
    metrics = adapter.extract_metrics(run)
    assert metrics["VM5"]["computed_value"] == pytest.approx(8.0)


def test_vm6_is_score_difference(adapter, tmp_path) -> None:
    solution_score = 0.85
    baseline_score = 0.90
    loss = 100.0 * (baseline_score - solution_score) / baseline_score
    assert loss == pytest.approx(5.555555, abs=1e-3)


def test_quality_score(adapter, run_dir) -> None:
    # mean of the per-case scores [0.8, 0.9] in predictions.jsonl
    assert adapter.quality_score(run_dir) == pytest.approx(0.85)


def test_missing_aggregated_raises(adapter, tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        adapter.extract_metrics(tmp_path / "results" / "nope")
