"""slam-eval adapter: runs the measurement and extracts raw VM values (spec 5.2)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


def _collection_group_path(collection_name: str) -> str:
    """Convert a slam-core collection name (merge_quality__merge_quality_easy_tiny)
    to its hydra group path (merge_quality/merge_quality_easy_tiny)."""
    parts = collection_name.split("__", 1)
    if len(parts) != 2:
        raise ValueError(
            f"collection name {collection_name!r} must be of the form '<group>__<name>'"
        )
    group, name = parts
    return f"{group}/{name}"


class SlamEvalAdapter:
    """Runs slam_eval/scripts/main.py in the service's own environment."""

    def __init__(
        self,
        slam_eval_root: str | Path,
        slam_eval_python: str | Path,
        dataset_root: str | Path,
        result_root: str | Path,
        slam_shared_config_path: str | Path | None = None,
    ) -> None:
        self.slam_eval_root = Path(slam_eval_root)
        self.slam_eval_python = Path(slam_eval_python)
        self.dataset_root = Path(dataset_root)
        # slam-core's shared config group dir, referenced by slam-eval's hydra
        # searchpath (file://${SLAM_SHARED_CONFIG_PATH}). The non-editable
        # slam-core install does not ship config/, so this must point at a
        # real slam-core config checkout.
        if slam_shared_config_path is None:
            raise ValueError(
                "slam_shared_config_path is required: point it at the slam-core "
                "config directory (user_settings.slam_shared_config_path)"
            )
        self.slam_shared_config_path = Path(slam_shared_config_path)
        self.slam_eval_config_path = self.slam_eval_root / "config"
        self.result_root = Path(result_root)
        self.result_root.mkdir(parents=True, exist_ok=True)

    def run_evaluation(
        self,
        base_url: str,
        collection: str,
        run_name: str,
        max_concurrent_requests: int = 8,
        max_output_tokens: int = 512,
        gpu_pids: list[int] | None = None,
        ram_pids: list[int] | None = None,
    ) -> Path:
        """Run one slam-eval evaluation against the deployment; return the result dir."""
        hydra_dir = self.result_root / run_name
        cmd = [
            str(self.slam_eval_python),
            str(self.slam_eval_root / "slam_eval" / "scripts" / "main.py"),
            # The installed (non-editable) slam_eval package does not ship its
            # config/ dir, so the primary config path must be overridden to the
            # slam-eval checkout (SLAM_EVAL_ROOT).
            "--config-path",
            str(self.slam_eval_config_path),
            f"hydra_dir={hydra_dir}",
            f"result_dir={hydra_dir}",
            # performance storage uses result_dir for run-keyed artifacts
            # (aggregated.json, raw.jsonl, memory_samples.jsonl)
            "user_settings.result_dir=" + str(hydra_dir),
            f"dataset_root={self.dataset_root}",
            f"group_id={run_name}",
            f"collection={_collection_group_path(collection)}",
            "scorer=merge_quality",
            "storage_adapter=local_jsonl",
            # Performance monitoring produces the aggregated.json artifact with
            # TTFT/TPOT statistics (VM1-VM4 source). Memory sampling needs the
            # deployment's process group explicitly: in the local_llm scenario
            # slam-eval builds no sampler at all when gpu_pids/ram_pids are
            # unset and self_monitor is false, which leaves the vram_bytes
            # statistics empty and VM5 (AC5) failed_to_compute.
            "performance_monitor=enabled",
            "storage_adapter.path_to_jsonl=" + str(hydra_dir / "predictions.jsonl"),
            "model=local_llm",
            f"model.llm.url={base_url}/v1/chat/completions",
            f"model.llm.max_concurrent_requests={max_concurrent_requests}",
            f"model.llm.max_output_tokens={max_output_tokens}",
        ]
        if gpu_pids:
            cmd.append(
                "performance_monitor.gpu_pids=[" + ",".join(str(pid) for pid in gpu_pids) + "]"
            )
        if ram_pids:
            cmd.append(
                "performance_monitor.ram_pids=[" + ",".join(str(pid) for pid in ram_pids) + "]"
            )
        LOGGER.info(
            "stage 'evaluation': running slam-eval (%s cases config: collection=%s) against %s; "
            "artifacts will be written to %s",
            run_name,
            collection,
            base_url,
            hydra_dir,
        )
        hydra_dir.mkdir(parents=True, exist_ok=True)
        eval_log = hydra_dir / "slam_eval.log"
        env = dict(os.environ)
        # Non-editable slam install: hydra's searchpath needs the shared config
        # dir; set it explicitly instead of relying on the caller's shell env.
        env["SLAM_SHARED_CONFIG_PATH"] = str(self.slam_shared_config_path)
        try:
            with open(eval_log, "ab") as log_file:
                subprocess.run(
                    cmd,
                    cwd=str(self.slam_eval_root),
                    check=True,
                    env=env,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"stage 'evaluation' failed (slam-eval return code {exc.returncode}); "
                f"slam-eval log preserved: {eval_log}"
            ) from exc
        LOGGER.info("stage 'evaluation': done (artifacts in %s, log: %s)", hydra_dir, eval_log)
        return hydra_dir

    def extract_metrics(self, run_dir: str | Path) -> dict[str, Any]:
        """Extract raw VM1-VM6 values from slam-eval output artifacts.

        VM1-VM4 come from aggregated TTFT/TPOT statistics, VM5 from GPU memory
        samples (failed_to_compute without a GPU), VM6 as the score difference
        (computed by the caller across solution and baseline runs).
        """
        run_dir = Path(run_dir)
        # A result dir is reused across validation runs of the same
        # (pair, scope), so slam-eval's run-keyed performance_* dirs accumulate.
        # Take the newest artifact: the oldest one belongs to an earlier run and
        # would silently report that run's numbers.
        candidates = [run_dir / "aggregated.json"]
        candidates.extend(run_dir.glob("performance_*/aggregated.json"))
        existing = [c for c in candidates if c.is_file()]
        if not existing:
            raise FileNotFoundError(
                f"stage 'metric extraction' failed: aggregated artifact not found in "
                f"{run_dir} (checked aggregated.json and performance_*/aggregated.json); "
                f"check the slam-eval run artifacts in {run_dir}"
            )
        aggregated = max(existing, key=lambda path: path.stat().st_mtime)
        data = json.loads(aggregated.read_text())

        ttft = data.get("ttft_s", {}) or {}
        tpot = data.get("tpot_s", {}) or {}
        vram = data.get("vram_bytes", {}) or {}

        metrics: dict[str, Any] = {}
        metrics["VM1"] = self._stat_metric(ttft, "median")
        metrics["VM2"] = self._stat_metric(ttft, "q95")  # q90 if provided
        metrics["VM3"] = self._stat_metric(tpot, "median")
        metrics["VM4"] = self._stat_metric(tpot, "q95")  # q90 if provided

        # VM5: implemented for future GPU profiles; failed_to_compute without samples.
        if vram:
            peak = vram.get("max")
            metrics["VM5"] = (
                {"computed_value": peak / 2**30 if peak is not None else None}
                if peak is not None
                else {"computed_value": None, "error_message": "no VRAM samples"}
            )
        else:
            metrics["VM5"] = {
                "computed_value": None,
                "error_message": "no GPU on this machine; VRAM not sampled",
            }
        return metrics

    @staticmethod
    def _stat_metric(stats: dict[str, Any], key: str) -> dict[str, Any]:
        value = stats.get(key)
        if value is None:
            return {"computed_value": None, "error_message": f"statistic {key} missing"}
        return {"computed_value": value}

    def quality_score(self, run_dir: str | Path) -> float | None:
        """Read the mean quality score of a run from its score artifact.

        The local_jsonl storage adapter writes one record per run into
        predictions.jsonl with the per-case scores list.
        """
        run_dir = Path(run_dir)
        predictions = run_dir / "predictions.jsonl"
        if predictions.is_file():
            last = None
            with open(predictions, encoding="utf-8") as pred_file:
                for line in pred_file:
                    line = line.strip()
                    if line:
                        last = json.loads(line)
            if last is not None:
                scores = last.get("scores") or []
                numeric = [s for s in scores if isinstance(s, (int, float))]
                if numeric:
                    return sum(numeric) / len(numeric)
        LOGGER.error(
            "stage 'score extraction': no per-case scores found in %s",
            predictions,
        )
        return None
