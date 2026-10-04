"""T3: HTTP service request validation (R1, R7)."""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

pytest.importorskip("requests")

import requests  # noqa: E402

from llm_deployment_validation.scripts import validation_service as service  # noqa: E402


@pytest.fixture()
def server_url():
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    STATE = service.STATE
    import json

    STATE["json"] = json
    import logging

    STATE["logger"] = logging.getLogger("test")
    from llm_deployment_validation.profile_loader import load_profile

    STATE["profile"] = (
        load_profile(__file__.replace("test_http_service.py", "conftest.py")) if False else None
    )
    from pathlib import Path

    STATE["profile"] = load_profile(
        Path(__file__).resolve().parents[1] / "config" / "profile" / "default.yaml"
    )
    httpd = service.ThreadingHTTPServer(("127.0.0.1", port), service.ValidationHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()


def test_missing_repo_is_400(server_url) -> None:
    response = requests.post(f"{server_url}/validate", json={"commit": "abc"}, timeout=5)
    assert response.status_code == 400


def test_missing_commit_is_400(server_url) -> None:
    response = requests.post(f"{server_url}/validate_partial", json={"repo": "x"}, timeout=5)
    assert response.status_code == 400


def test_wrong_types_are_400(server_url) -> None:
    response = requests.post(
        f"{server_url}/validate",
        json={"repo": 1, "commit": "abc", "solution_overrides": 2},
        timeout=5,
    )
    assert response.status_code == 400


def test_malformed_body_is_400(server_url) -> None:
    response = requests.post(
        f"{server_url}/validate",
        data="not json",
        headers={"Content-Type": "application/json"},
        timeout=5,
    )
    assert response.status_code == 400


def test_well_formed_reaches_engine(server_url) -> None:
    class FakeEngine:
        def run(self, **kwargs):
            FakeEngine.called = True
            FakeEngine.kwargs = kwargs
            return {"profile": "default", "validation_scope": "full"}

    FakeEngine.called = False
    FakeEngine.kwargs = {}
    service.STATE["engine_builder"] = lambda profile: FakeEngine()
    response = requests.post(
        f"{server_url}/validate",
        json={"repo": "x", "commit": "abc", "solution_overrides": ""},
        timeout=5,
    )
    assert response.status_code == 200
    assert FakeEngine.called
    assert FakeEngine.kwargs["validation_scope"] == "full"


def test_unknown_endpoint_is_404(server_url) -> None:
    response = requests.post(f"{server_url}/nope", json={}, timeout=5)
    assert response.status_code == 404
