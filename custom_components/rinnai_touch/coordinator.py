"""Push-based Home Assistant coordinator for the Rinnai Touch status stream.

First Home Assistant-aware layer of the integration: everything beneath it
(``protocol.py``, ``models.py``, ``client.py``) is pure Python that never
imports Home Assistant, and this module never parses wire bytes, opens
sockets, or touches the frame parser. The only values crossing the boundary
are the frozen :class:`~.models.StatusSnapshot` and
:class:`~.client.ConnectionEvent` objects the passive client already
publishes to its callbacks.

Push fan-out only
    ``DataUpdateCoordinator`` is used purely as a listener fan-out
    mechanism: ``update_interval`` is ``None``, no update method exists,
    and nothing ever polls. Every valid snapshot is published with
    ``async_set_updated_data``. ``always_update=True`` is passed
    explicitly: the module re-sends identical payloads, and a repeated
    frame must still refresh freshness timing and reach listeners.

Availability contract
    ``last_update_success`` is **not** this integration's availability
    signal. It is never read or written here (the base class sets it as a
    side effect of ``async_set_updated_data``), and no update failure is
    ever fabricated on staleness or disconnection. Future entity layers
    must derive availability from :attr:`RinnaiTouchCoordinator.freshness`
    — per AGENT_SCOPE.md, availability must be based on recent valid
    status data, not merely the existence of a socket object.

Freshness model
    Every valid parsed frame — including a valid empty ``N…[]`` frame —
    updates two timestamps: ``last_valid_frame_at`` (UTC wall clock, for
    diagnostics and the future last-valid-status sensor only) and
    ``last_valid_frame_monotonic`` (the sole input to expiry arithmetic).
    Freshness is computed on read from the injected monotonic clock:
    ``NO_DATA`` until the first valid frame of this runtime, ``FRESH``
    while the monotonic age is at most ``stale_after`` seconds (default
    ``STALE_STATUS_THRESHOLD_SECONDS``), ``STALE`` strictly beyond that,
    and back to ``FRESH`` on the next valid frame. Connection state is
    never an input: a disconnect inside the fresh window stays FRESH, and
    a silent-but-connected socket becomes STALE on time. Staleness is
    report-only — one debug log and one listener notification; no
    keepalive, no write, no reconnect-on-stale, no teardown, no command
    or sequence logic.

Stale timer
    A single ``async_call_later`` callback announces the FRESH -> STALE
    edge; it never defines freshness (the property stays correct even if
    the callback runs late). Every valid frame cancels the previous timer
    and arms a new one for exactly ``stale_after`` seconds from that
    frame's arrival, so the scheduled deadline always belongs to the most
    recent valid frame — never to an earlier frame or a housekeeping
    re-arm. The callback decides from the injected monotonic clock only
    and is deliberately safe to invoke directly in tests: called early it
    re-arms for the monotonic remainder without announcing; called when
    due it announces STALE exactly once per fresh period. The event loop
    merely delivers the callback.

Clocks
    Wall and monotonic clocks are injected callables (defaults:
    ``homeassistant.util.dt.utcnow`` and ``time.monotonic``), mirroring
    the client's injectable sleep, so tests control time completely.

Lifecycle
    Construction is side-effect-free and never connects (Config Flow
    Connection Policy: live connections require an explicit action). The
    client built here connects only on ``await async_start()``.
    ``async_shutdown()`` sets a shutdown guard before any await, cancels
    the stale timer, stops the client, then shuts down the base
    coordinator. Once the guard is set, the snapshot, connection-event,
    and stale-check callbacks are permanent no-ops: a late callback
    arriving while ``stop()`` is awaited can neither notify listeners nor
    re-arm the timer. Shutdown stays safe to call repeatedly.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .client import ConnectionEvent, ConnectionState, RinnaiTcpClient
from .const import DEFAULT_TCP_PORT, DOMAIN, STALE_STATUS_THRESHOLD_SECONDS
from .models import StatusSnapshot

_LOGGER: Final = logging.getLogger(__name__)

# Re-arm floor for an early-firing stale check. At the exact boundary
# (elapsed == stale_after is still FRESH) a zero-second re-arm would
# reschedule in a busy loop; one second is negligible against the
# 180-second threshold and keeps the callback consistent with the
# freshness property's strictly-beyond-threshold rule.
_STALE_RECHECK_FLOOR_SECONDS: Final = 1.0

type WallClock = Callable[[], datetime]
type MonotonicClock = Callable[[], float]
type RinnaiClientFactory = Callable[..., RinnaiTcpClient]


class Freshness(Enum):
    """Data-recency state, deliberately decoupled from socket state."""

    NO_DATA = "no_data"
    FRESH = "fresh"
    STALE = "stale"


class RinnaiTouchCoordinator(DataUpdateCoordinator[StatusSnapshot]):
    """Fan out passive-client snapshots and report monotonic freshness.

    See the module docstring for the full contract. All constructor
    arguments are plain configuration; nothing connects until
    ``await async_start()``.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        host: str,
        port: int = DEFAULT_TCP_PORT,
        config_entry: ConfigEntry | None = None,
        stale_after: float = STALE_STATUS_THRESHOLD_SECONDS,
        client_factory: RinnaiClientFactory = RinnaiTcpClient,
        wall_clock: WallClock = dt_util.utcnow,
        monotonic_clock: MonotonicClock = time.monotonic,
    ) -> None:
        if stale_after <= 0:
            raise ValueError("stale_after must be a positive number of seconds")
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=None,  # push only: nothing ever polls
            always_update=True,  # identical frames still refresh freshness
        )
        self._stale_after = float(stale_after)
        self._wall_clock = wall_clock
        self._monotonic_clock = monotonic_clock
        self._last_valid_frame_at: datetime | None = None
        self._last_valid_frame_monotonic: float | None = None
        self._announced_freshness = Freshness.NO_DATA
        self._stale_timer_cancel: CALLBACK_TYPE | None = None
        self._is_shutting_down = False
        self._connection_state = ConnectionState.STOPPED
        self._last_connection_error: str | None = None
        self._reconnect_count = 0
        self._client = client_factory(
            host,
            port,
            on_snapshot=self._handle_snapshot,
            on_connection_event=self._handle_connection_event,
        )

    # --- read-only surface for future entity and diagnostics layers ----------

    @property
    def freshness(self) -> Freshness:
        """Current data-recency state, computed from the monotonic clock."""
        last = self._last_valid_frame_monotonic
        if last is None:
            return Freshness.NO_DATA
        if self._monotonic_clock() - last <= self._stale_after:
            return Freshness.FRESH
        return Freshness.STALE

    @property
    def stale_after(self) -> float:
        """Seconds of monotonic frame silence after which data is stale."""
        return self._stale_after

    @property
    def last_valid_frame_at(self) -> datetime | None:
        """UTC wall-clock arrival of the last valid frame (diagnostics only)."""
        return self._last_valid_frame_at

    @property
    def last_valid_frame_monotonic(self) -> float | None:
        """Monotonic arrival of the last valid frame (expiry arithmetic)."""
        return self._last_valid_frame_monotonic

    @property
    def connection_state(self) -> ConnectionState:
        """Socket state from the latest connection event; never freshness."""
        return self._connection_state

    @property
    def last_connection_error(self) -> str | None:
        """Most recent error carried by a connection event, if any."""
        return self._last_connection_error

    @property
    def reconnect_count(self) -> int:
        """Reconnect attempts observed via connection events."""
        return self._reconnect_count

    @property
    def frames_received(self) -> int:
        """Total valid frames the client has parsed (pass-through)."""
        return self._client.frames_received

    @property
    def callback_error_count(self) -> int:
        """Callback exceptions the client has contained (pass-through)."""
        return self._client.callback_error_count

    @property
    def stale_timer_armed(self) -> bool:
        """True while a stale-check callback is scheduled."""
        return self._stale_timer_cancel is not None

    # --- lifecycle ------------------------------------------------------------

    async def async_start(self) -> None:
        """Start the passive client — the explicit connect action."""
        await self._client.start()

    async def async_shutdown(self) -> None:
        """Guard, cancel the timer, stop the client, shut down the base.

        The guard is set before any await and the timer is cancelled
        before ``stop()`` is awaited, so a callback arriving mid-shutdown
        finds every handler a no-op: no listener notification and no
        timer re-arm can happen once shutdown has begun. Safe to repeat.
        """
        self._is_shutting_down = True
        self._cancel_stale_timer()
        await self._client.stop()
        await super().async_shutdown()

    # --- client callbacks (synchronous, event-loop context) --------------------

    @callback
    def _handle_snapshot(self, snapshot: StatusSnapshot) -> None:
        """Record freshness timing and fan the snapshot out to listeners.

        Called by the client for every valid parsed frame, including a
        valid empty ``N…[]`` frame: any valid frame refreshes both
        timestamps, cancels the previous stale timer, and arms a new one
        for exactly ``stale_after`` seconds from this frame's arrival, so
        the stale deadline is always anchored to the newest valid frame.
        Publishing goes through ``async_set_updated_data``, which notifies
        every listener (``always_update=True``). No-op once shutdown has
        begun.
        """
        if self._is_shutting_down:
            return
        self._last_valid_frame_at = self._wall_clock()
        self._last_valid_frame_monotonic = self._monotonic_clock()
        self._announced_freshness = Freshness.FRESH
        self._cancel_stale_timer()
        self._arm_stale_timer(self._stale_after)
        self.async_set_updated_data(snapshot)

    @callback
    def _handle_connection_event(self, event: ConnectionEvent) -> None:
        """Track socket-level state and notify listeners.

        Connection state is surfaced for the future connectivity entity
        and diagnostics but is never an input to freshness, and no update
        failure is fabricated for a failed or reconnecting socket. No-op
        once shutdown has begun.
        """
        if self._is_shutting_down:
            return
        self._connection_state = event.state
        if event.error is not None:
            self._last_connection_error = event.error
        if event.state is ConnectionState.RECONNECTING:
            self._reconnect_count += 1
        self.async_update_listeners()

    # --- stale timer ------------------------------------------------------------

    def _arm_stale_timer(self, delay: float) -> None:
        self._stale_timer_cancel = async_call_later(
            self.hass, delay, self._async_check_stale
        )

    def _cancel_stale_timer(self) -> None:
        if self._stale_timer_cancel is not None:
            self._stale_timer_cancel()
            self._stale_timer_cancel = None

    @callback
    def _async_check_stale(self, _now: datetime | None = None) -> None:
        """Announce the FRESH -> STALE edge; decide from monotonic time only.

        Scheduled through the event loop but deliberately safe to invoke
        directly (tests advance the injected monotonic clock and call it).
        An early invocation re-arms for the monotonic remainder without
        announcing; a due invocation announces STALE exactly once per
        fresh period. The wall clock plays no part in the decision.
        No-op once shutdown has begun.
        """
        if self._is_shutting_down:
            return
        self._cancel_stale_timer()  # fired or superseded either way
        last = self._last_valid_frame_monotonic
        if last is None:
            return  # NO_DATA: never armed; a direct call is a no-op
        elapsed = self._monotonic_clock() - last
        if elapsed <= self._stale_after:
            self._arm_stale_timer(
                max(self._stale_after - elapsed, _STALE_RECHECK_FLOOR_SECONDS)
            )
            return
        if self._announced_freshness is not Freshness.STALE:
            self._announced_freshness = Freshness.STALE
            _LOGGER.debug(
                "Status is stale: no valid frame for %.1f s (threshold %.0f s);"
                " connection state is %s",
                elapsed,
                self._stale_after,
                self._connection_state.value,
            )
            self.async_update_listeners()
