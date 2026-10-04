"""Baseline cache: caches baseline evaluation results (validation spec 5.2)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class BaselineCache:
    """Disk-backed cache keyed by (baseline repo, commit, model, hardware, scope)."""

    def __init__(self, cache_dir: str | Path) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _key_path(
        self, baseline_repo: str, baseline_commit: str, model: str, hardware: str, scope: str
    ) -> Path:
        raw = json.dumps(
            {
                "repo": baseline_repo,
                "commit": baseline_commit,
                "model": model,
                "hardware": hardware,
                "scope": scope,
            },
            sort_keys=True,
        )
        digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return self.cache_dir / f"baseline_{digest}.json"

    def get(
        self, baseline_repo: str, baseline_commit: str, model: str, hardware: str, scope: str
    ) -> dict[str, Any] | None:
        """Return the cached baseline scores or None on a miss."""
        path = self._key_path(baseline_repo, baseline_commit, model, hardware, scope)
        if not path.is_file():
            return None
        return json.loads(path.read_text())

    def put(
        self,
        baseline_repo: str,
        baseline_commit: str,
        model: str,
        hardware: str,
        scope: str,
        scores: dict[str, Any],
    ) -> None:
        """Store the baseline scores under the cache key."""
        path = self._key_path(baseline_repo, baseline_commit, model, hardware, scope)
        path.write_text(json.dumps(scores, indent=2, sort_keys=True) + "\n")
