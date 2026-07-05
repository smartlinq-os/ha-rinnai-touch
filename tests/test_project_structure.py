"""Offline structural tests for the project scaffold.

These tests assert safe project-level facts only: constants, metadata
validity, phase boundaries, and side-effect-free imports. They must run
with no network access and without Home Assistant, except the single
package-import check, which is explicitly gated because ``__init__.py``
now hosts the config-entry lifecycle and therefore imports Home Assistant.
"""

from __future__ import annotations

import ast
import importlib
import json
import re
import socket
import sys
from pathlib import Path
from types import ModuleType

import pytest


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
    # Passive stale-session recycle (ADR 0002): provisional field-validation
    # parameters approved at Gate A of Commit 14B — not protocol facts.
    assert const.READ_IDLE_RECYCLE_THRESHOLD_SECONDS == 150
    assert const.RECYCLE_RECONNECT_DELAY_SECONDS == 10


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
    # Passive stale-session recycle (ADR 0002). The difference between the
    # freshness threshold and (recycle threshold + recycle delay) is a
    # target budget for normal reconnect and first-valid-frame latency,
    # not a no-stale guarantee: a brief truthful STALE state remains
    # possible when reconnect or first-frame latency exceeds the budget.
    assert (
        0
        < const.READ_IDLE_RECYCLE_THRESHOLD_SECONDS
        < const.STALE_STATUS_THRESHOLD_SECONDS
    )
    # RECYCLE_RECONNECT_DELAY_SECONDS >= the first backoff step: the floor
    # must never reconnect faster than the normal first retry.
    assert (
        const.RECONNECT_BACKOFF_SCHEDULE_SECONDS[0]
        <= const.RECYCLE_RECONNECT_DELAY_SECONDS
    )
    assert (
        const.READ_IDLE_RECYCLE_THRESHOLD_SECONDS
        + const.RECYCLE_RECONNECT_DELAY_SECONDS
        < const.STALE_STATUS_THRESHOLD_SECONDS
    )


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
    # The config-flow milestone (Commit 9) is approved: the manifest must
    # declare it so Home Assistant offers UI setup.
    assert manifest["config_flow"] is True
    assert "cloud" not in json.dumps(manifest).lower()


def test_hacs_metadata_is_valid(repo_root: Path) -> None:
    hacs = json.loads((repo_root / "hacs.json").read_text("utf-8"))
    assert hacs["name"] == "Rinnai Touch"


def test_control_modules_do_not_exist_yet(integration_dir: Path) -> None:
    # AGENT_SCOPE.md: control surfaces (climate, switch, fan, number,
    # select, button, services) must remain absent until explicit Phase 2
    # approval; diagnostics.py awaits its own approved Phase 1 milestone.
    for module_name in (
        "climate.py",
        "switch.py",
        "fan.py",
        "number.py",
        "select.py",
        "button.py",
        "services.yaml",
        "diagnostics.py",
    ):
        assert not (integration_dir / module_name).exists(), module_name


def test_read_only_entity_layer_modules_exist(integration_dir: Path) -> None:
    # The approved Commit 10 read-only entity layer: shared bases plus the
    # sensor and binary_sensor platforms.
    for module_name in ("entity.py", "sensor.py", "binary_sensor.py"):
        assert (integration_dir / module_name).exists(), module_name


def test_scaffold_modules_import_nothing_unsafe(integration_dir: Path) -> None:
    forbidden = {"socket", "asyncio", "homeassistant", "aiohttp"}
    for module_file in ("const.py", "models.py"):
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


def test_pure_layers_never_import_home_assistant(integration_dir: Path) -> None:
    """The four pure protocol-layer modules never import Home Assistant.

    protocol.py, models.py, client.py, and const.py must stay importable
    and testable without Home Assistant installed; coordinator.py is the
    single HA-aware module (see test_coordinator_import_boundaries). The
    scan walks the entire AST, so an import buried in a function body or
    a TYPE_CHECKING block is caught just the same, and dotted forms such
    as ``import homeassistant.util`` or ``from homeassistant.util import
    dt`` all reduce to the banned first segment.
    """
    for module_file in ("protocol.py", "models.py", "client.py", "const.py"):
        imported = _top_level_imports(integration_dir / module_file)
        assert "homeassistant" not in imported, (
            f"{module_file} must never import homeassistant"
        )


def _relative_import_targets(path: Path) -> set[str]:
    """Return the first segments of relative (``from .x import``) imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level >= 1:
            if node.module:
                targets.add(node.module.split(".")[0])
            else:
                targets |= {alias.name.split(".")[0] for alias in node.names}
    return targets


def test_ha_layer_import_boundaries(integration_dir: Path) -> None:
    """The HA layer: lifecycle, config flow, coordinator, and entities.

    Each may import homeassistant — the pure layers may not — but sockets
    and HTTP stay forbidden, and none of them may reach past the client
    boundary into the frame parser. config_flow.py must reuse the existing
    passive client rather than opening sockets of its own, so the
    socket-creating asyncio stream APIs are additionally banned by name
    across the whole HA layer.
    """
    ha_layer = (
        "__init__.py",
        "config_flow.py",
        "coordinator.py",
        "entity.py",
        "sensor.py",
        "binary_sensor.py",
    )
    banned_calls = {"open_connection", "create_connection", "start_server"}
    for module_file in ha_layer:
        path = integration_dir / module_file
        imported = _top_level_imports(path)
        assert "homeassistant" in imported, f"{module_file} is the HA layer"
        assert not imported & {"socket", "aiohttp"}, module_file
        assert "protocol" not in _relative_import_targets(path), module_file
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        overlap = calls & banned_calls
        assert not overlap, f"{module_file} opens sockets itself: {overlap}"


def test_no_module_calls_outbound_write_apis(integration_dir: Path) -> None:
    """No integration module may call a socket/stream write-style API.

    Phase 1 is passive. test_tcp_client locks client.py specifically; this
    repo-wide sweep extends the same lock to every integration module,
    including coordinator.py and anything added in later milestones.
    """
    banned = {"write", "writelines", "drain", "send", "sendall", "sendto"}
    for module_file in sorted(integration_dir.glob("*.py")):
        tree = ast.parse(module_file.read_text(encoding="utf-8"))
        attribute_calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        overlap = attribute_calls & banned
        assert not overlap, f"{module_file.name} calls banned APIs: {overlap}"


ENTITY_LAYER_MODULES = ("entity.py", "sensor.py", "binary_sensor.py")


def test_entity_modules_touch_client_enum_only(integration_dir: Path) -> None:
    """Entity modules may import only ConnectionState from the client layer.

    Entities read everything through the coordinator. The single permitted
    exception is the pure ``ConnectionState`` enum (the connectivity
    binary sensor compares against it); constructing or managing a client
    from an entity module is forbidden.
    """
    for module_file in ENTITY_LAYER_MODULES:
        tree = ast.parse((integration_dir / module_file).read_text("utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.level >= 1
                and (node.module or "").split(".")[0] == "client"
            ):
                names = {alias.name for alias in node.names}
                assert names <= {"ConnectionState"}, (
                    f"{module_file} imports {names} from the client layer"
                )
        referenced = {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        }
        assert "RinnaiTcpClient" not in referenced, module_file


def test_no_module_calls_refresh_or_service_apis(integration_dir: Path) -> None:
    """No module triggers coordinator refreshes or registers services.

    The read-only entity layer must never start refresh machinery, and no
    Phase 1 module may register a Home Assistant service.
    ``async_set_updated_data`` is the coordinator's approved push
    publication mechanism (coordinator.py module docstring) and is
    permitted there alone; every other listed API is banned everywhere.
    """
    banned = {
        "async_request_refresh",
        "async_refresh",
        "async_config_entry_first_refresh",
        "async_set_updated_data",
        "async_register",
        "async_register_entity_service",
    }
    for module_file in sorted(integration_dir.glob("*.py")):
        allowed = (
            {"async_set_updated_data"}
            if module_file.name == "coordinator.py"
            else set[str]()
        )
        tree = ast.parse(module_file.read_text(encoding="utf-8"))
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        overlap = calls & (banned - allowed)
        assert not overlap, f"{module_file.name} calls banned APIs: {overlap}"


def test_strings_and_translations_are_identical(integration_dir: Path) -> None:
    """strings.json and translations/en.json carry the same content.

    Home Assistant reads a custom integration's runtime texts from
    translations/en.json while strings.json remains the source document;
    the two must never drift apart.
    """
    strings = json.loads((integration_dir / "strings.json").read_text("utf-8"))
    translations = json.loads(
        (integration_dir / "translations" / "en.json").read_text("utf-8")
    )
    assert strings == translations


def test_entity_translations_cover_the_approved_inventory(
    integration_dir: Path,
) -> None:
    """Every approved entity key has a name translation, and nothing more."""
    strings = json.loads((integration_dir / "strings.json").read_text("utf-8"))
    entity_section = strings["entity"]
    assert set(entity_section) == {"binary_sensor", "sensor"}
    assert set(entity_section["binary_sensor"]) == {
        "connectivity",
        "fault_active",
    }
    assert set(entity_section["sensor"]) == {
        "data_freshness",
        "last_valid_status",
        "operating_mode",
        "controller_state",
    }


def test_client_logging_is_address_and_error_sanitised(
    integration_dir: Path,
) -> None:
    """client.py logger calls may never carry addresses or raw error text.

    Rejected inside any ``_LOGGER.*`` call argument:
    ``self._host`` / ``self._port`` (any ``_host``/``_port`` attribute),
    bare ``host``/``port`` names, ``event.error`` (ConnectionEvent text may
    embed OS detail and is stored, never logged), and ``str()``/``repr()``
    of a caught exception (``error``/``err``/``exc``) — OS exception
    messages can embed the remote address. Failures must be logged only as
    fixed classification labels, exception class names, and integer errnos.
    """
    tree = ast.parse((integration_dir / "client.py").read_text("utf-8"))
    banned_attributes = {"_host", "_port"}
    banned_names = {"host", "port"}
    logger_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "_LOGGER"
    ]
    assert logger_calls, "client.py is expected to log forensics"
    for call in logger_calls:
        arguments = [*call.args, *(keyword.value for keyword in call.keywords)]
        for argument in arguments:
            for sub in ast.walk(argument):
                if isinstance(sub, ast.Attribute):
                    assert sub.attr not in banned_attributes, (
                        f"logger argument references {sub.attr}"
                    )
                    event_error = (
                        sub.attr == "error"
                        and isinstance(sub.value, ast.Name)
                        and sub.value.id == "event"
                    )
                    assert not event_error, "event.error must never be logged"
                if isinstance(sub, ast.Name):
                    assert sub.id not in banned_names, (
                        f"logger argument references name {sub.id!r}"
                    )
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Name)
                    and sub.func.id in {"str", "repr"}
                ):
                    for inner in sub.args:
                        assert not (
                            isinstance(inner, ast.Name)
                            and inner.id in {"error", "err", "exc"}
                        ), "str()/repr() of an exception must never be logged"


def test_coordinator_defines_no_command_or_keepalive_api(
    integration_dir: Path,
) -> None:
    banned = ("command", "send", "write", "keepalive", "hvac", "setpoint")
    source = (integration_dir / "coordinator.py").read_text(encoding="utf-8")
    names = [
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    for name in names:
        lowered = name.lower()
        assert not any(word in lowered for word in banned), name


LOOPBACK_OPT_IN_MODULES = frozenset(
    {
        "test_capture_fixtures.py",
        "test_config_flow.py",
        "test_coordinator.py",
        "test_init.py",
        "test_rinnai_probe.py",
        "test_tcp_client.py",
    }
)


def _module_usefixtures(path: Path) -> set[str]:
    """Fixture names referenced by a module-level ``pytestmark`` assignment."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "pytestmark" not in targets:
            continue
        for call in ast.walk(node.value):
            if isinstance(call, ast.Call):
                names |= {
                    arg.value
                    for arg in call.args
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                }
    return names


def test_loopback_socket_opt_in_is_narrow_and_loopback_only(
    repo_root: Path,
) -> None:
    """The pytest-socket loopback opt-in stays exactly as narrow as approved.

    Exactly the approved modules that run in-process loopback servers opt
    in to ``loopback_socket_enabled`` (defined in tests/conftest.py), and
    the intentional networking in those modules uses only the literal
    IPv4 loopback host — no other address literal may appear in an
    opted-in module. tests/test_entities.py must never join this list:
    the entity layer is proven passive by running fully socket-blocked.
    """
    tests_dir = repo_root / "tests"
    opted_in = {
        path.name
        for path in tests_dir.glob("test_*.py")
        if "loopback_socket_enabled" in _module_usefixtures(path)
    }
    assert opted_in == LOOPBACK_OPT_IN_MODULES
    ipv4_pattern = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
    for module_name in sorted(LOOPBACK_OPT_IN_MODULES):
        tree = ast.parse((tests_dir / module_name).read_text(encoding="utf-8"))
        string_values = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]
        assert "127.0.0.1" in string_values, module_name
        addresses = {
            match
            for value in string_values
            for match in ipv4_pattern.findall(value)
        }
        assert addresses <= {"127.0.0.1"}, f"{module_name}: {addresses}"


def test_package_import_creates_no_sockets(monkeypatch) -> None:
    # __init__.py imports Home Assistant for the config-entry lifecycle
    # (approved decision D5), so this import check needs HA present; the
    # base non-HA environment skips exactly this one test.
    pytest.importorskip("homeassistant")

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("socket created during package import")

    monkeypatch.setattr(socket, "socket", _forbidden)
    package = _fresh_import("custom_components.rinnai_touch")
    const = _fresh_import("custom_components.rinnai_touch.const")
    assert package.__doc__ is not None
    assert const.DOMAIN == "rinnai_touch"
