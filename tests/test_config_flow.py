"""Offline tests for the manual Rinnai Touch config flow.

Skipped as a whole without the ``ha-test`` dependency group. Everything is
in-process 127.0.0.1 loopback: no real hardware, no real addresses, no
internet, no discovery. The tests prove the Config Flow Connection Policy —
nothing connects before the user submits, duplicate detection runs before
any socket opens, validation makes exactly one deliberate passive
connection, requires at least one valid StatusSnapshot, and always stops
the client afterwards.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

pytest.importorskip(
    "pytest_homeassistant_custom_component",
    reason="ha-test dependency group is not installed",
)

from conftest import LoopbackServer
from homeassistant.config_entries import SOURCE_USER, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rinnai_touch import config_flow as config_flow_module
from custom_components.rinnai_touch.const import (
    CONF_HOST,
    CONF_PORT,
    DEFAULT_TCP_PORT,
    DOMAIN,
)

# In-process 127.0.0.1 servers only; opt-in fixture defined in tests/conftest.py.
pytestmark = pytest.mark.usefixtures(
    "enable_custom_integrations", "loopback_socket_enabled"
)

LOOPBACK_HOST = "127.0.0.1"


def encode_frame(sequence: int, payload: list[dict[str, object]]) -> bytes:
    """Build one wire frame: N + six-digit sequence + JSON array."""
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return f"N{sequence:06d}{body}".encode()


STATUS_FRAME = encode_frame(1, [{"SYST": {"OSS": {"MD": "H", "ST": "N"}}}])


async def _begin_user_flow(hass: HomeAssistant) -> ConfigFlowResult:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )


def _feed_one_frame(server: LoopbackServer) -> asyncio.Task[None]:
    """Background task: once a client connects, stream one valid frame."""

    async def _feed() -> None:
        await server.wait_for_connection()
        await server.send(STATUS_FRAME)

    return asyncio.create_task(_feed())


async def test_form_renders_without_connecting(
    hass: HomeAssistant, loopback_server: LoopbackServer
) -> None:
    result = await _begin_user_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}
    # Config Flow Connection Policy: rendering the form is not an explicit
    # connect action, so nothing may have touched the network.
    assert loopback_server.connection_count == 0


async def test_user_flow_validates_and_creates_entry(
    hass: HomeAssistant, loopback_server: LoopbackServer
) -> None:
    feeder = _feed_one_frame(loopback_server)
    result = await _begin_user_flow(hass)
    with patch(
        "custom_components.rinnai_touch.async_setup_entry", return_value=True
    ) as mock_setup_entry:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: LOOPBACK_HOST, CONF_PORT: loopback_server.port},
        )
        await hass.async_block_till_done()
    await feeder
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Rinnai Touch ({LOOPBACK_HOST})"
    assert result["data"] == {
        CONF_HOST: LOOPBACK_HOST,
        CONF_PORT: loopback_server.port,
    }
    assert len(mock_setup_entry.mock_calls) == 1
    # Exactly one deliberate, passive, always-stopped validation connection.
    await loopback_server.wait_all_closed()
    assert loopback_server.connection_count == 1
    assert bytes(loopback_server.received) == b""


async def test_host_is_normalized_before_storage(
    hass: HomeAssistant, loopback_server: LoopbackServer
) -> None:
    feeder = _feed_one_frame(loopback_server)
    result = await _begin_user_flow(hass)
    with patch(
        "custom_components.rinnai_touch.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: f"  {LOOPBACK_HOST}  ", CONF_PORT: loopback_server.port},
        )
        await hass.async_block_till_done()
    await feeder
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == LOOPBACK_HOST  # trimmed + lowercased


async def test_connection_refused_shows_cannot_connect(
    hass: HomeAssistant, loopback_server: LoopbackServer
) -> None:
    refused_port = loopback_server.port
    await loopback_server.stop()  # bound then closed: connects are refused
    result = await _begin_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: LOOPBACK_HOST, CONF_PORT: refused_port}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_dropped_connection_fails_without_second_attempt(
    hass: HomeAssistant, loopback_server: LoopbackServer
) -> None:
    async def _accept_then_drop() -> None:
        await loopback_server.wait_for_connection()
        await loopback_server.drop_current()

    dropper = asyncio.create_task(_accept_then_drop())
    result = await _begin_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: LOOPBACK_HOST, CONF_PORT: loopback_server.port},
    )
    await dropper
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    # Validation stopped the client on the first terminal failure: the
    # client's retry/backoff never produced a second connection attempt.
    for _ in range(20):
        await asyncio.sleep(0.001)
    assert loopback_server.connection_count == 1


async def test_silent_socket_never_validates(
    hass: HomeAssistant,
    loopback_server: LoopbackServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A connected-but-silent socket must never create an entry; shorten the
    # deadline (test-local) so the timeout path runs without real waiting.
    monkeypatch.setattr(
        config_flow_module, "CONFIG_VALIDATION_TIMEOUT_SECONDS", 0.3
    )
    result = await _begin_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: LOOPBACK_HOST, CONF_PORT: loopback_server.port},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_status_received"}
    await loopback_server.wait_all_closed()  # client was stopped regardless
    # Timeout cleanup stopped the validation client outright: even after
    # further event-loop turns there is no second connection attempt — the
    # client's configured retry delay never gets a chance to produce one.
    for _ in range(20):
        await asyncio.sleep(0.001)
    assert loopback_server.connection_count == 1
    assert bytes(loopback_server.received) == b""  # still fully passive


async def test_malformed_traffic_never_validates(
    hass: HomeAssistant,
    loopback_server: LoopbackServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        config_flow_module, "CONFIG_VALIDATION_TIMEOUT_SECONDS", 0.3
    )

    async def _feed_garbage() -> None:
        await loopback_server.wait_for_connection()
        await loopback_server.send(b'@@not-a-frame@@N000001[{"SYST":}]')

    feeder = asyncio.create_task(_feed_garbage())
    result = await _begin_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: LOOPBACK_HOST, CONF_PORT: loopback_server.port},
    )
    await feeder
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_status_received"}
    assert loopback_server.connection_count == 1


async def test_duplicate_aborts_before_any_connection(
    hass: HomeAssistant, loopback_server: LoopbackServer
) -> None:
    MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: LOOPBACK_HOST, CONF_PORT: loopback_server.port},
    ).add_to_hass(hass)
    result = await _begin_user_flow(hass)
    # Whitespace/case variants normalize to the same data and must abort
    # before validation opens any socket (mandatory rule 1).
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: f" {LOOPBACK_HOST} ", CONF_PORT: loopback_server.port},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert loopback_server.connection_count == 0


async def test_same_host_different_port_is_a_new_entry(
    hass: HomeAssistant, loopback_server: LoopbackServer
) -> None:
    MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: LOOPBACK_HOST, CONF_PORT: loopback_server.port + 1},
    ).add_to_hass(hass)
    feeder = _feed_one_frame(loopback_server)
    result = await _begin_user_flow(hass)
    with patch(
        "custom_components.rinnai_touch.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: LOOPBACK_HOST, CONF_PORT: loopback_server.port},
        )
        await hass.async_block_till_done()
    await feeder
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_blank_host_is_rejected_without_connecting(
    hass: HomeAssistant, loopback_server: LoopbackServer
) -> None:
    result = await _begin_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "   ", CONF_PORT: DEFAULT_TCP_PORT}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_HOST: "invalid_host"}
    assert loopback_server.connection_count == 0


async def test_unexpected_error_shows_unknown(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _boom(host: str, port: int) -> None:
        raise RuntimeError("synthetic validation failure")

    monkeypatch.setattr(config_flow_module, "_async_validate_input", _boom)
    result = await _begin_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: LOOPBACK_HOST, CONF_PORT: 27847}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}
