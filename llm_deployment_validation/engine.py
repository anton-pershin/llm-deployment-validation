"""Validation engine: orchestrates the sequential validation run (validation spec 5.1)."""

from __future__ import annotations

import logging
import shutil
import socket
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm_deployment_validation.baseline_cache import BaselineCache
from llm_deployment_validation.metrics_evaluator import evaluate_all
from llm_deployment_validation.profile_loader import ValidationProfile
from llm_deployment_validation.response_builder import build_response
from llm_deployment_validation.slam_eval_adapter import SlamEvalAdapter
from llm_deployment_validation.solution_runner import start_deployment

LOGGER = logging.getLogger(__name__)


def allocate_free_port() -> int:
    """Allocate a free localhost port for a deployment."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class ValidationEngine:
    """Drives the sequential pipeline: solution deploy -> evaluate ->
    baseline deploy (cache miss) -> evaluate -> criteria evaluation."""

    profile: ValidationProfile
    adapter: SlamEvalAdapter
    cache: BaselineCache
    health_timeout_s: float = 900.0
    health_interval_s: float = 2.0

    def _preserve_deployment_log(self, work: Path, label: str, exc: Exception) -> None:
        """Copy the failed deployment's and setup logs into the results dir (they must
        survive the run-dir cleanup so the failure can be diagnosed afterwards)."""
        env_dir = work / f"{label}_env"
        dst_dir = self.adapter.result_root / "deployment_logs"
        dst_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        copied = []
        for artifact in ("deployment.log", "setup.log"):
            src = env_dir / artifact
            if src.is_file():
                dst = dst_dir / f"{label}_{stamp}_{artifact}"
                shutil.copy(src, dst)
                copied.append(str(dst))
        if copied:
            LOGGER.error(
                "diagnostic artifacts preserved after failure (%s): %s", exc, ", ".join(copied)
            )
        else:
            LOGGER.error(
                "failure (%s): no %s log artifacts found under %s to preserve "
                "(failure before log creation?)",
                exc,
                label,
                env_dir,
            )

    def run(
        self,
        repo: str,
        commit: str,
        solution_overrides: str = "",
        validation_scope: str = "partial",
        workdir: str | Path | None = None,
    ) -> dict[str, Any]:
        """Run the validation and return the response dict (spec 5.1)."""
        collection = self.profile.collection_for_scope(validation_scope)
        work = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="validation_run_"))
        work.mkdir(parents=True, exist_ok=True)
        LOGGER.info(
            "=== validation run started === profile=%s scope=%s collection=%s pair=(%s, %s) "
            "repo=%s commit=%s overrides='%s' workdir=%s",
            self.profile.name,
            validation_scope,
            collection,
            self.profile.model,
            self.profile.hardware,
            repo,
            commit,
            solution_overrides,
            work,
        )

        metric_values: dict[str, Any] = {}
        baseline_scores: dict[str, Any] | None = None
        solution_score: float | None = None
        deployment = None
        failed = False

        try:
            LOGGER.info("=== stage 1/5: deploy solution deployment ===")
            # 1. deploy solution (sequential)
            port = allocate_free_port()
            deployment = start_deployment(
                repo_link=repo,
                commit=commit,
                model=self.profile.model,
                hardware=self.profile.hardware,
                port=port,
                solution_overrides=solution_overrides,
                workdir=work / "solution_env",
                health_timeout_s=self.health_timeout_s,
                health_interval_s=self.health_interval_s,
            )
            LOGGER.info("=== stage 2/5: evaluate solution deployment ===")
            # 2. evaluate solution
            solution_run = self.adapter.run_evaluation(
                base_url=f"http://127.0.0.1:{port}",
                collection=collection,
                run_name=f"solution_{validation_scope}",
            )
            solution_score = self.adapter.quality_score(solution_run)
            solution_metrics = self.adapter.extract_metrics(solution_run)
            for metric in ("VM1", "VM2", "VM3", "VM4", "VM5"):
                if metric in solution_metrics:
                    metric_values[metric] = solution_metrics[metric]
        except Exception as exc:  # noqa: BLE001 - any failure -> failed_to_compute
            failed = True
            LOGGER.error("=== stage 1-2 FAILED: solution deployment/evaluation failed: %s ===", exc)
            LOGGER.exception("validation pipeline failure: %s", exc)
            self._preserve_deployment_log(work, "solution", exc)
            for metric in ("VM1", "VM2", "VM3", "VM4"):
                metric_values.setdefault(
                    metric, {"computed_value": None, "error_message": str(exc)}
                )
        finally:
            if deployment is not None:
                deployment.stop()

        # 3./4. baseline: cached scores on hit, otherwise deploy + evaluate
        if solution_score is not None:
            baseline_scores = self.cache.get(
                self.profile.baseline_repo,
                self.profile.baseline_commit,
                self.profile.model,
                self.profile.hardware,
                validation_scope,
            )
            if baseline_scores is not None:
                LOGGER.info(
                    "=== stages 3-4/5 SKIPPED: baseline cache hit for (%s, %s, %s, %s, %s); "
                    "cached scores: %s ===",
                    self.profile.baseline_repo,
                    self.profile.baseline_commit,
                    self.profile.model,
                    self.profile.hardware,
                    validation_scope,
                    baseline_scores,
                )
            if baseline_scores is None:
                LOGGER.info("=== stage 3/5: deploy baseline deployment (cache miss) ===")
                try:
                    baseline_port = allocate_free_port()
                    baseline_deployment = start_deployment(
                        repo_link=self.profile.baseline_repo,
                        commit=self.profile.baseline_commit,
                        model=self.profile.model,
                        hardware=self.profile.hardware,
                        port=baseline_port,
                        solution_overrides="",
                        workdir=work / "baseline_env",
                        health_timeout_s=self.health_timeout_s,
                        health_interval_s=self.health_interval_s,
                    )
                    LOGGER.info("=== stage 4/5: evaluate baseline deployment ===")
                    try:
                        baseline_run = self.adapter.run_evaluation(
                            base_url=f"http://127.0.0.1:{baseline_port}",
                            collection=collection,
                            run_name=f"baseline_{validation_scope}",
                        )
                        baseline_score = self.adapter.quality_score(baseline_run)
                        baseline_scores = {"score": baseline_score}
                        if baseline_score is not None:
                            self.cache.put(
                                self.profile.baseline_repo,
                                self.profile.baseline_commit,
                                self.profile.model,
                                self.profile.hardware,
                                validation_scope,
                                baseline_scores,
                            )
                    finally:
                        baseline_deployment.stop()
                except Exception as exc:  # noqa: BLE001
                    failed = True
                    LOGGER.error("=== stages 3-4 FAILED: baseline pipeline failed: %s ===", exc)
                    LOGGER.exception("baseline pipeline failure: %s", exc)
                    self._preserve_deployment_log(work, "baseline", exc)
                    baseline_scores = None

        if baseline_scores is not None and solution_score is not None:
            baseline_score = baseline_scores.get("score")
            if baseline_score:
                loss = 100.0 * (baseline_score - solution_score) / baseline_score
                metric_values["VM6"] = {"computed_value": loss}
            else:
                metric_values["VM6"] = {
                    "computed_value": None,
                    "error_message": "baseline score missing",
                }
        else:
            metric_values.setdefault(
                "VM6",
                {"computed_value": None, "error_message": "solution or baseline score missing"},
            )

        if "VM5" not in metric_values:
            metric_values["VM5"] = {
                "computed_value": None,
                "error_message": "no GPU on this machine; VRAM not sampled",
            }

        LOGGER.info("=== stage 5/5: evaluate acceptance criteria and build the response ===")
        results = evaluate_all(self.profile, metric_values)
        response = build_response(self.profile.name, validation_scope, results)
        for criterion, result in results.items():
            LOGGER.info(
                "criterion %s: status=%s (%s)",
                criterion,
                result.status,
                {
                    m: (mr.computed_value, mr.acceptance_status)
                    for m, mr in result.metrics_status.items()
                },
            )

        if failed and workdir is None:
            LOGGER.error(
                "=== validation run FAILED === run workdir preserved for diagnostics: %s "
                "(delete it manually when done)",
                work,
            )
        elif workdir is None:
            shutil.rmtree(work, ignore_errors=True)
            LOGGER.info("=== validation run finished === temporary workdir %s removed", work)
        else:
            LOGGER.info("=== validation run finished === workdir preserved: %s", work)
        return response
