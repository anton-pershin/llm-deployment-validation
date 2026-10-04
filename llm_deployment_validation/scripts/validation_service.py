"""HTTP validation service (validation spec 5.1).

Usage:
    python llm_deployment_validation/scripts/validation_service.py port=8456 [profile=default]

Endpoints:
    POST /validate          - full validation
    POST /validate_partial  - partial validation (diagnostic only)
"""

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import hydra
from omegaconf import DictConfig

from llm_deployment_validation.utils.common import get_config_path

CONFIG_NAME = "config_service"

STATE: dict[str, Any] = {}


class ValidationHandler(BaseHTTPRequestHandler):
    """Serve /validate and /validate_partial."""

    def _run_validation(self, scope: str) -> None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = STATE["json"].loads(self.rfile.read(length) or b"{}")
        except Exception:  # noqa: BLE001
            self._send(400, {"error": "malformed request body"})
            return

        if not isinstance(payload, dict):
            self._send(400, {"error": "request payload must be a json object"})
            return
        repo = payload.get("repo")
        commit = payload.get("commit")
        overrides = payload.get("solution_overrides", "")
        if not isinstance(repo, str) or not repo:
            self._send(400, {"error": "'repo' is required and must be a string"})
            return
        if not isinstance(commit, str) or not commit:
            self._send(400, {"error": "'commit' is required and must be a string"})
            return
        if not isinstance(overrides, str):
            self._send(400, {"error": "'solution_overrides' must be a string"})
            return

        try:
            engine = STATE["engine_builder"](STATE["profile"])
            response = engine.run(
                repo=repo,
                commit=commit,
                solution_overrides=overrides,
                validation_scope=scope,
            )
            self._send(200, response)
        except Exception as exc:  # noqa: BLE001
            STATE["logger"].exception("validation failed")
            self._send(500, {"error": f"unexpected validation failure: {exc}"})

    def _send(self, status: int, body: dict[str, Any]) -> None:
        data = STATE["json"].dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802  pylint: disable=invalid-name
        """Dispatch POST endpoints."""
        if self.path == "/validate":
            self._run_validation("full")
        elif self.path == "/validate_partial":
            self._run_validation("partial")
        else:
            self._send(404, {"error": f"unknown endpoint: {self.path}"})

    # pylint: disable-next=arguments-differ; http.server's log_message has the same signature
    def log_message(self, fmt: str, *args: Any) -> None:
        """Route default logging through our logger."""
        STATE["logger"].debug(fmt, *args)


def main(cfg: DictConfig) -> None:
    """Load the profile and serve until interrupted."""
    STATE["json"] = json
    STATE["logger"] = logging.getLogger("validation_service")

    from llm_deployment_validation.profile_loader import profile_from_cfg
    from llm_deployment_validation.run_lib import build_engine, resolved_user_settings

    settings = resolved_user_settings(cfg)
    STATE["profile"] = profile_from_cfg(cfg.profile)
    STATE["engine_builder"] = lambda profile: build_engine(profile, settings)

    server = ThreadingHTTPServer(("127.0.0.1", int(cfg.port)), ValidationHandler)
    print(
        f"validation service listening on http://127.0.0.1:{cfg.port} "
        f"(profile={STATE['profile'].name})"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    hydra.main(
        config_path=str(get_config_path()),
        config_name=CONFIG_NAME,
        version_base="1.3",
    )(main)()
