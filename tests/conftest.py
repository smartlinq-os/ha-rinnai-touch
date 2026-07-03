"""Shared test configuration.

Every test in this repository is offline: no network access, no Home
Assistant instance, and no connection to any Rinnai or Brivis hardware.

This conftest only makes the repository root importable so that
``custom_components.rinnai_touch`` resolves as a namespace package during
tests. There is deliberately no ``tests/__init__.py``: pytest discovers these
tests by path, and keeping ``tests`` out of the import namespace avoids
shadowing anything.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def repo_root() -> Path:
    """Absolute path of the repository root."""
    return REPO_ROOT


@pytest.fixture
def integration_dir(repo_root: Path) -> Path:
    """Absolute path of the custom integration package."""
    return repo_root / "custom_components" / "rinnai_touch"
