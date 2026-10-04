"""T1: default profile validation (R2)."""

from __future__ import annotations

import pytest

from llm_deployment_validation.profile_loader import load_profile


def test_default_profile_exists(profile_path) -> None:
    assert profile_path.is_file(), f"missing profile: {profile_path}"


def test_default_profile_scope_and_thresholds(profile_path) -> None:
    profile = load_profile(profile_path)
    assert profile.acceptance_criteria == ["AC1", "AC2", "AC3", "AC4", "AC6"]
    assert profile.threshold_overrides == {}
    assert profile.thresholds() == {
        "AC1": 2.0,
        "AC2": 5.0,
        "AC3": 0.05,
        "AC4": 0.1,
        "AC6": 1.0,
    }


def test_default_profile_collections(profile_path) -> None:
    profile = load_profile(profile_path)
    assert profile.collection_for_scope("full") == "merge_quality__merge_quality_easy"
    assert profile.collection_for_scope("partial") == ("merge_quality__merge_quality_easy_tiny")


def test_default_profile_baseline_reference(profile_path) -> None:
    profile = load_profile(profile_path)
    assert profile.model == "Qwen/Qwen3-0.6B"
    assert profile.hardware == "huawei-cpu"
    assert profile.baseline_repo.startswith("http")
    assert profile.baseline_commit


def test_malformed_profiles_rejected(tmp_path) -> None:
    from llm_deployment_validation.profile_loader import ProfileError

    bad = tmp_path / "bad.yaml"
    bad.write_text("acceptance_criteria: [AC99]\nname: bad\n")
    with pytest.raises(ProfileError):
        load_profile(bad)

    bad2 = tmp_path / "bad2.yaml"
    bad2.write_text(
        "name: bad2\nacceptance_criteria: [AC1]\nthreshold_overrides: {AC1: notanumber}\n"
    )
    with pytest.raises(ProfileError):
        load_profile(bad2)
