"""T8: full vs partial scope wiring (B2)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from llm_deployment_validation.profile_loader import load_profile
from llm_deployment_validation.response_builder import build_response


def test_scope_selects_collection(profile_path) -> None:
    profile = load_profile(profile_path)
    assert profile.collection_for_scope("full") == "merge_quality__merge_quality_easy"
    assert profile.collection_for_scope("partial") == ("merge_quality__merge_quality_easy_tiny")


def test_response_scope_label(profile_path) -> None:
    profile = load_profile(profile_path)
    for scope in ("full", "partial"):
        response = build_response(profile.name, scope, {})
        assert response["validation_scope"] == scope
        assert response["profile"] == "default"


def test_unknown_scope_rejected(profile_path) -> None:
    profile = load_profile(profile_path)
    try:
        profile.collection_for_scope("bogus")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown scope must raise ValueError")
