"""Shared test configuration.

Every test in this repository is offline: no network access, no Home
Assistant instance, and no connection to any Rinnai or Brivis hardware.

This conftest makes the repository root importable so that
``custom_components.rinnai_touch`` resolves as a namespace package during
tests, and hosts the shared loopback-socket opt-in fixture for the four
modules that run in-process 127.0.0.1 servers. There is deliberately no
``tests/__init__.py``: pytest discovers these tests by path, and keeping
``tests`` out of the import namespace avoids shadowing anything.
"""

from __future__ import annotations

import importlib.util
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


@pytest.fixture
def loopback_socket_enabled(request: pytest.FixtureRequest) -> None:
    """Opt-in for test modules that bind in-process 127.0.0.1 servers.

    With the ha-test dependency group installed,
    pytest-homeassistant-custom-component blocks socket creation before
    every test (``pytest_socket.disable_socket``) after pre-arming a
    loopback-only connect guard (``socket_allow_hosts(["127.0.0.1"])``)
    and loopback-only DNS validators. Requesting pytest-socket's
    ``socket_enabled`` fixture restores socket *creation* for the
    requesting test only; the connect guard and DNS restrictions remain
    active, so any attempt to reach a non-loopback destination still
    fails. Without pytest-socket installed (base dev group), sockets were
    never blocked and this fixture is deliberately a no-op.
    """
    if importlib.util.find_spec("pytest_socket") is not None:
        request.getfixturevalue("socket_enabled")
