"""Shared fixtures: make ``src`` importable and load the real question types."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from familygame.questions.base import Environment  # noqa: E402
from familygame.questions.registry import TypeRegistry, load_question_types  # noqa: E402


@pytest.fixture(scope="session")
def registry() -> TypeRegistry:
    reg = load_question_types(ROOT / "question_types")
    assert not reg.errors, reg.errors
    return reg


@pytest.fixture
def env() -> Environment:
    return Environment(internet=True, google_maps_api_key="test-key")


@pytest.fixture
def root() -> Path:
    return ROOT
