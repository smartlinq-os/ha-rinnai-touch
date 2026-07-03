"""Offline structural tests for the project scaffold.

These tests assert safe project-level facts only: constants, metadata
validity, phase boundaries, and side-effect-free imports. They must run with
no network access and must not import Home Assistant.
"""

from __future__ import annotations

import ast
import importlib
import json
import socket
import sys
from pathlib import Path
from types import ModuleType


def _fresh_import(module_name: str) -> ModuleType:
    """Import a module with the custom_components tree purged first.

    Purging ensures each test observes real import behaviour rather than a
    module cached by an earlier test.
    """
    stale = [
        name
        for name in sys.modules
        if name == "custom_components" or name.startswith("custom_components.")
    ]
    for name in stale:
        sys.modules.pop(name)
    return importlib.import_module(module_name)


def _top_level_imports(path: Path) -> set[str]:
    """Return the top-level module names imported anywhere in a source file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    return imported


def test_domain_is_rinnai_touch() -> None:
    const = _fresh_import("custom_components.rinnai_touch.const")
    assert const.DOMAIN == "rinnai_touch"


def test_default_tcp_port() -> None:
    const = _fresh_import("custom_components.rinnai_touch.const")
    assert const.DEFAULT_TCP_PORT == 27847


def test_timing_constants_match_approved_values() -> None:
    const = _fresh_import("custom_components.rinnai_touch.const")
    assert const.CONNECT_TIMEOUT_SECONDS == 10
    assert const.COMMAND_ACK_TIMEOUT_SECONDS == 15
    assert const.STALE_STATUS_THRESHOLD_SECONDS == 180
    assert const.RECONNECT_BACKOFF_SCHEDULE_SECONDS == (2, 5, 10, 30, 60)
    assert const.KEEPALIVE_MIN_SPACING_SECONDS == 60


def test_timing_constants_are_internally_consistent() -> None:
    const = _fresh_import("custom_components.rinnai_touch.const")
    backoff = const.RECONNECT_BACKOFF_SCHEDULE_SECONDS
    assert list(backoff) == sorted(backoff), "backoff must never decrease"
    assert backoff[-1] == 60, "documented backoff ceiling is 60 seconds"
    assert all(step > 0 for step in backoff)
    # A keepalive-maintained session must not be considered stale between
    # keepalives, and connecting must resolve well before staleness.
    assert const.KEEPALIVE_MIN_SPACING_SECONDS < const.STALE_STATUS_THRESHOLD_SECONDS
    assert const.CONNECT_TIMEOUT_SECONDS < const.STALE_STATUS_THRESHOLD_SECONDS


def test_sequence_constants_are_consistent() -> None:
    const = _fresh_import("custom_components.rinnai_touch.const")
    assert const.MESSAGE_PREFIX == "N"
    assert const.SEQUENCE_DIGITS == 6
    assert const.SEQUENCE_MODULO == 255
    # Every value in the modulo range must be representable in the padded width.
    assert const.SEQUENCE_MODULO < 10**const.SEQUENCE_DIGITS


def test_zone_letters_include_common_zone() -> None:
    const = _fresh_import("custom_components.rinnai_touch.const")
    assert const.ZONE_LETTERS == ("U", "A", "B", "C", "D")
    assert const.MT_NO_READING == "999"


def test_manifest_is_valid_and_matches_scope(integration_dir: Path) -> None:
    manifest = json.loads((integration_dir / "manifest.json").read_text("utf-8"))
    const = _fresh_import("custom_components.rinnai_touch.const")
    assert manifest["domain"] == const.DOMAIN
    assert manifest["iot_class"] == "local_push", "local-only push design; no polling"
    assert manifest["requirements"] == [], "no runtime dependencies at this stage"
    assert manifest["version"], "a provisional version must be declared"
    # No config flow milestone has been approved yet; the manifest must not
    # imply one exists.
    assert "config_flow" not in manifest
    assert "cloud" not in json.dumps(manifest).lower()


def test_hacs_metadata_is_valid(repo_root: Path) -> None:
    hacs = json.loads((repo_root / "hacs.json").read_text("utf-8"))
    assert hacs["name"] == "Rinnai Touch"


def test_control_modules_do_not_exist_yet(integration_dir: Path) -> None:
    # AGENT_SCOPE.md: climate.py and switch.py must remain absent until
    # explicit Phase 2 approval.
    assert not (integration_dir / "climate.py").exists()
    assert not (integration_dir / "switch.py").exists()


def test_scaffold_modules_import_nothing_unsafe(integration_dir: Path) -> None:
    forbidden = {"socket", "asyncio", "homeassistant", "aiohttp"}
    for module_file in ("__init__.py", "const.py", "models.py"):
        imported = _top_level_imports(integration_dir / module_file)
        overlap = imported & forbidden
        assert not overlap, f"{module_file} imports forbidden modules: {overlap}"
    # protocol.py is a pure parser and client.py is asyncio-based by design,
    # so asyncio is not prohibited for them — but neither may ever import
    # socket, aiohttp, or Home Assistant.
    for module_file in ("protocol.py", "client.py"):
        imported = _top_level_imports(integration_dir / module_file)
        overlap = imported & {"socket", "homeassistant", "aiohttp"}
        assert not overlap, f"{module_file} imports forbidden modules: {overlap}"


def test_package_import_creates_no_sockets(monkeypatch) -> None:
    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("socket created during package import")

    monkeypatch.setattr(socket, "socket", _forbidden)
    package = _fresh_import("custom_components.rinnai_touch")
    const = _fresh_import("custom_components.rinnai_touch.const")
    assert package.__doc__ is not None
    assert const.DOMAIN == "rinnai_touch"
