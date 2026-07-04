"""Config flow for the Rinnai Touch integration (manual entry only).

One ``user`` step: the user types the module's host/IP and an optional TCP
port. There is no discovery of any kind — no UDP, mDNS, SSDP, Zeroconf,
DHCP, or hostname probing — and nothing connects until the user submits
the form (Config Flow Connection Policy, AGENT_SCOPE.md).

Validation
    Submitting the form triggers exactly one deliberate, bounded, passive
    connection to the entered address using the existing
    :class:`~.client.RinnaiTcpClient`; this module contains no second
    socket or protocol implementation. Validation succeeds only after the
    client publishes at least one valid :class:`~.models.StatusSnapshot` —
    a connected-but-silent socket, malformed traffic, or TCP connectivity
    alone never creates an entry. The first terminal ``CONNECTION_FAILED``
    event fails fast, the whole wait is bounded by
    ``CONFIG_VALIDATION_TIMEOUT_SECONDS``, a single oversized backoff entry
    keeps the client's supervisor from ever starting a second attempt, and
    ``client.stop()`` always runs in ``finally`` — validation never leaves
    a connection behind, on success or failure.

Duplicates and identity
    Duplicate prevention runs *before* any socket is opened, by exact
    normalized (trimmed, lowercased) host+port entry-data matching via
    ``_async_abort_entries_match``. No unique ID is created or inferred:
    the protocol exposes no validated device serial yet, and an IP address
    must never be used as one.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Final

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.exceptions import HomeAssistantError

from .client import ConnectionEvent, ConnectionState, RinnaiTcpClient
from .const import (
    CONF_HOST,
    CONF_PORT,
    CONFIG_VALIDATION_TIMEOUT_SECONDS,
    DEFAULT_TCP_PORT,
    DOMAIN,
)
from .models import StatusSnapshot

_LOGGER: Final = logging.getLogger(__name__)

# One oversized pseudo-delay keeps the client's supervisor from ever
# starting a second connection attempt inside the validation window;
# stop() in the finally block cancels it long before it could elapse.
_NO_RETRY_BACKOFF: Final = (CONFIG_VALIDATION_TIMEOUT_SECONDS * 4.0,)

STEP_USER_DATA_SCHEMA: Final = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_TCP_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
    }
)


class CannotConnect(HomeAssistantError):
    """The single deliberate connection attempt failed."""


class NoStatusReceived(HomeAssistantError):
    """No valid status frame arrived within the validation deadline."""


async def _async_validate_input(host: str, port: int) -> None:
    """Make one deliberate, bounded, passive validation connection.

    Waits for the first of: a valid snapshot (success), a terminal
    ``CONNECTION_FAILED`` event (:class:`CannotConnect`), or the overall
    deadline (:class:`NoStatusReceived`). The client is always stopped in
    the ``finally`` block, so no connection or task survives validation.
    """
    snapshot_received = asyncio.Event()
    connection_failed = asyncio.Event()
    failure_reason: list[str] = []

    def _on_snapshot(_snapshot: StatusSnapshot) -> None:
        snapshot_received.set()

    def _on_connection_event(event: ConnectionEvent) -> None:
        if event.state is ConnectionState.CONNECTION_FAILED:
            if event.error is not None:
                failure_reason.append(event.error)
            connection_failed.set()

    client = RinnaiTcpClient(
        host,
        port,
        on_snapshot=_on_snapshot,
        on_connection_event=_on_connection_event,
        reconnect_delays=_NO_RETRY_BACKOFF,
    )
    snapshot_waiter = asyncio.create_task(snapshot_received.wait())
    failure_waiter = asyncio.create_task(connection_failed.wait())
    try:
        await client.start()
        try:
            async with asyncio.timeout(CONFIG_VALIDATION_TIMEOUT_SECONDS):
                await asyncio.wait(
                    (snapshot_waiter, failure_waiter),
                    return_when=asyncio.FIRST_COMPLETED,
                )
        except TimeoutError as err:
            raise NoStatusReceived("no valid status frame in time") from err
        if snapshot_received.is_set():
            return  # at least one valid StatusSnapshot: validated
        raise CannotConnect(
            failure_reason[0] if failure_reason else "connection failed"
        )
    finally:
        snapshot_waiter.cancel()
        failure_waiter.cancel()
        await asyncio.gather(
            snapshot_waiter, failure_waiter, return_exceptions=True
        )
        await client.stop()


class RinnaiTouchConfigFlow(ConfigFlow, domain=DOMAIN):
    """Manual host/port flow; no discovery, options, reconfigure, or reauth."""

    VERSION = 1
    MINOR_VERSION = 0

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form; on submit, deduplicate first, then validate once."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = str(user_input[CONF_HOST]).strip().lower()
            port = int(user_input[CONF_PORT])
            if not host:
                errors[CONF_HOST] = "invalid_host"
            else:
                # Duplicate detection must run before any socket is opened.
                self._async_abort_entries_match(
                    {CONF_HOST: host, CONF_PORT: port}
                )
                try:
                    await _async_validate_input(host, port)
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                except NoStatusReceived:
                    errors["base"] = "no_status_received"
                except Exception:
                    _LOGGER.exception(
                        "Unexpected error validating the Rinnai Touch module"
                    )
                    errors["base"] = "unknown"
                else:
                    return self.async_create_entry(
                        title=f"Rinnai Touch ({host})",
                        data={CONF_HOST: host, CONF_PORT: port},
                    )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input
            ),
            errors=errors,
        )
