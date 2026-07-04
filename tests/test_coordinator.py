"""Offline tests for the push-based Rinnai Touch coordinator.

These are the first tests that need Home Assistant test fixtures. They are
skipped as a whole when the ``ha-test`` dependency group
(``pytest-homeassistant-custom-component``) is not installed, so the base
suite stays runnable without Home Assistant.

Everything here is in-process or loopback-only: fake clocks drive every
freshness decision (the stale rule is monotonic-elapsed only, per the
approved design), coordinator handlers are invoked directly exactly as the
client's synchronous callback dispatcher would invoke them, and the single
end-to-end test speaks to an in-process 127.0.0.1 server. No real hardware,
no real addresses, no internet. The event loop is used only to validate
listener delivery and cancellation — never to define freshness timing.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest

pytest.importorskip(
    "pytest_homeassistant_custom_component",
    reason="ha-test dependency group is not installed",
)

from conftest import FakeMonotonic, FakeRinnaiClient, FakeWallClock
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
)

from custom_components.rinnai_touch import coordinator as coordinator_module
from custom_components.rinnai_touch.client import (
    ConnectionEvent,
    ConnectionState,
)
from custom_components.rinnai_touch.coordinator import (
    Freshness,
    RinnaiTouchCoordinator,
)
from custom_components.rinnai_touch.models import (
    Capabilities,
    FaultRecord,
    StatusSnapshot,
)

# In-process 127.0.0.1 servers only; opt-in fixture defined in tests/conftest.py.
pytestmark = pytest.mark.usefixtures("loopback_socket_enabled")

STALE_AFTER = 180.0  # matches const.STALE_STATUS_THRESHOLD_SECONDS
COORDINATOR_LOGGER = "custom_components.rinnai_touch.coordinator"


# --- fakes and helpers --------------------------------------------------------

# FakeMonotonic, FakeWallClock, and FakeRinnaiClient live in tests/conftest.py
# and are shared with test_entities.py.


def make_snapshot(sequence: int = 1) -> StatusSnapshot:
    """Build a minimal frozen snapshot; the coordinator treats it opaquely."""
    return StatusSnapshot(
        sequence=sequence,
        raw_groups={},
        capabilities=Capabilities(),
        zones={},
        operating_mode=None,
        controller_state=None,
        active_mode_group=None,
        fault=FaultRecord(),
    )


@dataclass
class Harness:
    """One coordinator wired to fake clocks, a fake client, and a listener."""

    coordinator: RinnaiTouchCoordinator
    client: FakeRinnaiClient
    monotonic: FakeMonotonic
    wall: FakeWallClock
    notifications: list[int]

    @property
    def notify_count(self) -> int:
        return len(self.notifications)


@pytest.fixture
async def harness(hass: HomeAssistant) -> AsyncIterator[Harness]:
    monotonic = FakeMonotonic()
    wall = FakeWallClock()
    clients: list[FakeRinnaiClient] = []

    def _factory(host: str, port: int, **kwargs: Any) -> FakeRinnaiClient:
        client = FakeRinnaiClient(host, port, **kwargs)
        clients.append(client)
        return client

    coordinator = RinnaiTouchCoordinator(
        hass,
        host="127.0.0.1",
        port=0,
        client_factory=_factory,
        wall_clock=wall,
        monotonic_clock=monotonic,
    )
    notifications: list[int] = []
    coordinator.async_add_listener(lambda: notifications.append(1))
    fixture = Harness(coordinator, clients[0], monotonic, wall, notifications)
    yield fixture
    await coordinator.async_shutdown()


class TimerSpy:
    """Observes every arm/cancel of the stale timer via async_call_later.

    Wraps the real scheduler rather than replacing it: real loop timers
    are still created and still fire, so event-loop behaviour is
    untouched; the spy only records the delay of each arm and the order
    of cancellations. A fired callback's own entry housekeeping also
    records a cancellation (a harmless no-op on the underlying handle).
    """

    def __init__(self) -> None:
        self.armed_delays: list[float] = []
        self.cancellations: list[int] = []

    @property
    def live_count(self) -> int:
        """Arms not yet cancelled (valid while no spied timer has fired)."""
        return len(self.armed_delays) - len(self.cancellations)


@pytest.fixture
def timer_spy(monkeypatch: pytest.MonkeyPatch) -> TimerSpy:
    """Narrowly scoped scheduling spy on the coordinator's timer arming."""
    spy = TimerSpy()
    real_call_later = coordinator_module.async_call_later

    def _spying_call_later(hass: HomeAssistant, delay: float, action: Any) -> Any:
        index = len(spy.armed_delays)
        spy.armed_delays.append(float(delay))
        real_cancel = real_call_later(hass, delay, action)

        def _record_cancel() -> None:
            spy.cancellations.append(index)
            real_cancel()

        return _record_cancel

    monkeypatch.setattr(coordinator_module, "async_call_later", _spying_call_later)
    return spy


# --- construction and start -----------------------------------------------------


async def test_construction_is_side_effect_free(harness: Harness) -> None:
    assert harness.client.start_calls == 0  # nothing connects on construction
    assert harness.coordinator.data is None
    assert harness.coordinator.freshness is Freshness.NO_DATA
    assert harness.coordinator.last_valid_frame_at is None
    assert harness.coordinator.last_valid_frame_monotonic is None
    assert not harness.coordinator.stale_timer_armed
    assert harness.coordinator.connection_state is ConnectionState.STOPPED
    assert harness.coordinator.reconnect_count == 0
    assert harness.notify_count == 0
    # A direct stale-check call in NO_DATA is a documented no-op.
    harness.coordinator._async_check_stale()
    assert harness.notify_count == 0
    assert not harness.coordinator.stale_timer_armed


async def test_async_start_delegates_to_client(harness: Harness) -> None:
    await harness.coordinator.async_start()
    assert harness.client.start_calls == 1


async def test_stale_after_must_be_positive(hass: HomeAssistant) -> None:
    with pytest.raises(ValueError, match="stale_after"):
        RinnaiTouchCoordinator(hass, host="127.0.0.1", port=0, stale_after=0)


# --- snapshot arrival and freshness timestamps -----------------------------------


async def test_first_snapshot_marks_fresh_and_notifies(harness: Harness) -> None:
    harness.monotonic.advance(5)
    harness.wall.advance(5)
    snapshot = make_snapshot(1)
    harness.coordinator._handle_snapshot(snapshot)
    assert harness.coordinator.data is snapshot
    assert harness.coordinator.freshness is Freshness.FRESH
    assert harness.coordinator.last_valid_frame_at == harness.wall.now
    assert harness.coordinator.last_valid_frame_monotonic == harness.monotonic.now
    assert harness.coordinator.stale_timer_armed
    assert harness.notify_count == 1


async def test_repeated_identical_snapshot_still_notifies_and_refreshes(
    harness: Harness,
) -> None:
    # The module re-sends identical payloads, and a valid empty N…[] frame
    # produces a snapshot equal to its predecessor. Either way the frame is
    # valid and must refresh both timestamps and reach listeners
    # (always_update=True is pinned by this test).
    snapshot = make_snapshot(1)
    harness.coordinator._handle_snapshot(snapshot)
    first_wall = harness.coordinator.last_valid_frame_at
    harness.monotonic.advance(30)
    harness.wall.advance(30)
    harness.coordinator._handle_snapshot(snapshot)  # the very same object
    assert harness.notify_count == 2
    assert harness.coordinator.last_valid_frame_at == harness.wall.now
    assert harness.coordinator.last_valid_frame_at != first_wall
    assert harness.coordinator.last_valid_frame_monotonic == harness.monotonic.now
    assert harness.coordinator.freshness is Freshness.FRESH


async def test_expiry_uses_monotonic_time_only(harness: Harness) -> None:
    harness.coordinator._handle_snapshot(make_snapshot(1))
    # A wall-clock jump must not age the data...
    harness.wall.advance(10_000)
    assert harness.coordinator.freshness is Freshness.FRESH
    # ...and the boundary is strict: elapsed == threshold is still FRESH.
    harness.monotonic.advance(STALE_AFTER)
    assert harness.coordinator.freshness is Freshness.FRESH
    # Strictly beyond the threshold the property reads STALE on its own,
    # with no timer involvement and no wall-clock movement required.
    harness.monotonic.advance(0.1)
    assert harness.coordinator.freshness is Freshness.STALE


# --- stale-check callback: direct invocation (monotonic authority) ---------------


async def test_early_stale_check_rearms_without_announcing(
    harness: Harness,
) -> None:
    harness.coordinator._handle_snapshot(make_snapshot(1))
    base = harness.notify_count
    harness.monotonic.advance(100)
    harness.coordinator._async_check_stale()
    assert harness.notify_count == base  # no announcement
    assert harness.coordinator.freshness is Freshness.FRESH
    assert harness.coordinator.stale_timer_armed  # re-armed for the remainder


async def test_stale_check_at_exact_threshold_rearms(harness: Harness) -> None:
    harness.coordinator._handle_snapshot(make_snapshot(1))
    base = harness.notify_count
    harness.monotonic.advance(STALE_AFTER)  # exactly the boundary: still FRESH
    harness.coordinator._async_check_stale()
    assert harness.notify_count == base
    assert harness.coordinator.freshness is Freshness.FRESH
    assert harness.coordinator.stale_timer_armed


async def test_due_stale_check_announces_exactly_once(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=COORDINATOR_LOGGER)
    # Silent-but-connected session: the socket stays CONNECTED throughout.
    harness.coordinator._handle_connection_event(
        ConnectionEvent(ConnectionState.CONNECTING)
    )
    harness.coordinator._handle_connection_event(
        ConnectionEvent(ConnectionState.CONNECTED)
    )
    harness.coordinator._handle_snapshot(make_snapshot(1))
    base = harness.notify_count
    harness.monotonic.advance(STALE_AFTER + 0.1)
    harness.coordinator._async_check_stale()
    assert harness.notify_count == base + 1  # exactly one announcement
    assert harness.coordinator.freshness is Freshness.STALE
    assert harness.coordinator.connection_state is ConnectionState.CONNECTED
    assert not harness.coordinator.stale_timer_armed  # nothing left to expire
    # A stray second invocation must not announce again.
    harness.coordinator._async_check_stale()
    assert harness.notify_count == base + 1
    stale_logs = [
        record
        for record in caplog.records
        if record.name == COORDINATOR_LOGGER and "stale" in record.getMessage()
    ]
    assert len(stale_logs) == 1


async def test_stale_does_not_fabricate_update_failure(harness: Harness) -> None:
    harness.coordinator._handle_snapshot(make_snapshot(1))
    harness.monotonic.advance(STALE_AFTER + 1)
    harness.coordinator._async_check_stale()
    assert harness.coordinator.freshness is Freshness.STALE
    # last_update_success is not this integration's availability contract
    # and staleness must not manufacture an update failure: the base class
    # value stays wherever async_set_updated_data left it.
    assert harness.coordinator.last_update_success is True
    assert harness.coordinator.last_exception is None


async def test_recovery_after_stale_and_second_cycle(harness: Harness) -> None:
    harness.coordinator._handle_snapshot(make_snapshot(1))
    harness.monotonic.advance(STALE_AFTER + 1)
    harness.coordinator._async_check_stale()
    base = harness.notify_count
    # The next valid frame recovers STALE -> FRESH and notifies via the
    # normal data path, re-arming the announcement for a new fresh period.
    harness.coordinator._handle_snapshot(make_snapshot(2))
    assert harness.coordinator.freshness is Freshness.FRESH
    assert harness.coordinator.stale_timer_armed
    assert harness.notify_count == base + 1
    harness.monotonic.advance(STALE_AFTER + 1)
    harness.coordinator._async_check_stale()
    assert harness.coordinator.freshness is Freshness.STALE
    assert harness.notify_count == base + 2  # announced once per fresh period


# --- stale-deadline reset on every valid frame ------------------------------------


async def test_second_frame_resets_stale_deadline(
    harness: Harness, timer_spy: TimerSpy
) -> None:
    harness.coordinator._handle_snapshot(make_snapshot(1))
    assert timer_spy.armed_delays == [STALE_AFTER]
    assert timer_spy.cancellations == []
    harness.monotonic.advance(100)
    harness.coordinator._handle_snapshot(make_snapshot(2))
    # The frame-1 timer was cancelled and a full fresh threshold was armed
    # anchored to frame 2 — not a remainder of the old deadline.
    assert timer_spy.armed_delays == [STALE_AFTER, STALE_AFTER]
    assert timer_spy.cancellations == [0]
    assert harness.coordinator.stale_timer_armed
    # Freshness measures from frame 2: just past frame 1's would-be
    # deadline the data is still FRESH...
    harness.monotonic.advance(STALE_AFTER - 100 + 1)
    assert harness.coordinator.freshness is Freshness.FRESH
    # ...and it turns STALE only strictly beyond frame 2's deadline.
    harness.monotonic.advance(100)
    assert harness.coordinator.freshness is Freshness.STALE


async def test_frame_stream_leaves_no_old_timer_active(
    harness: Harness, timer_spy: TimerSpy
) -> None:
    for sequence in range(1, 11):  # ten frames, one second apart
        harness.coordinator._handle_snapshot(make_snapshot(sequence))
        harness.monotonic.advance(1)
    # Ten arms of the full threshold; the previous timer was cancelled on
    # every arrival, in order, leaving exactly the newest one live.
    assert timer_spy.armed_delays == [STALE_AFTER] * 10
    assert timer_spy.cancellations == list(range(9))
    assert timer_spy.live_count == 1
    assert harness.coordinator.stale_timer_armed


async def test_newest_frame_timer_delivers_the_stale_announcement(
    hass: HomeAssistant, harness: Harness, timer_spy: TimerSpy
) -> None:
    harness.coordinator._handle_snapshot(make_snapshot(1))
    harness.monotonic.advance(100)
    harness.coordinator._handle_snapshot(make_snapshot(2))
    base = harness.notify_count
    # Only frame 2's timer is live; frame 1's was cancelled and can never
    # run, so the announcement below can only come from the newest timer.
    assert timer_spy.cancellations == [0]
    assert timer_spy.live_count == 1
    harness.monotonic.advance(STALE_AFTER + 1)
    # Fire a window wide enough to cover both frames' deadlines: the
    # cancelled frame-1 timer stays silent; frame 2's timer announces.
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=2 * STALE_AFTER + 200)
    )
    await hass.async_block_till_done()
    assert harness.notify_count == base + 1
    assert harness.coordinator.freshness is Freshness.STALE
    assert not harness.coordinator.stale_timer_armed
    # No re-arm happened after the announcement; the only cancellations
    # are frame 1's reset and the fired callback's own entry housekeeping.
    assert timer_spy.armed_delays == [STALE_AFTER, STALE_AFTER]
    assert timer_spy.cancellations == [0, 1]


async def test_no_duplicate_stale_notification_after_deadline_reset(
    harness: Harness,
) -> None:
    harness.coordinator._handle_snapshot(make_snapshot(1))
    harness.monotonic.advance(100)
    harness.coordinator._handle_snapshot(make_snapshot(2))  # deadline reset
    base = harness.notify_count
    harness.monotonic.advance(STALE_AFTER + 1)
    harness.coordinator._async_check_stale()  # due for frame 2's fresh period
    assert harness.notify_count == base + 1
    # Stray repeats after the reset-deadline announcement stay silent.
    harness.coordinator._async_check_stale()
    harness.coordinator._async_check_stale()
    assert harness.notify_count == base + 1
    assert harness.coordinator.freshness is Freshness.STALE


# --- connection state is separate from freshness ---------------------------------


async def test_disconnect_within_fresh_window_stays_fresh(
    harness: Harness,
) -> None:
    harness.coordinator._handle_snapshot(make_snapshot(1))
    monotonic_at_frame = harness.coordinator.last_valid_frame_monotonic
    harness.monotonic.advance(60)
    base = harness.notify_count
    harness.coordinator._handle_connection_event(
        ConnectionEvent(
            ConnectionState.CONNECTION_FAILED,
            "connection closed by remote end",
        )
    )
    harness.coordinator._handle_connection_event(
        ConnectionEvent(ConnectionState.RECONNECTING)
    )
    # Each event notified listeners, surfaced socket state and error, and
    # left freshness timing completely untouched: 60-second-old data is
    # still FRESH while the socket is down.
    assert harness.notify_count == base + 2
    assert harness.coordinator.freshness is Freshness.FRESH
    assert harness.coordinator.connection_state is ConnectionState.RECONNECTING
    assert harness.coordinator.last_connection_error == (
        "connection closed by remote end"
    )
    assert harness.coordinator.reconnect_count == 1
    assert harness.coordinator.last_valid_frame_monotonic == monotonic_at_frame


# --- lifecycle and event-loop delivery --------------------------------------------


async def test_shutdown_stops_client_and_cancels_timer(harness: Harness) -> None:
    harness.coordinator._handle_snapshot(make_snapshot(1))
    assert harness.coordinator.stale_timer_armed
    await harness.coordinator.async_shutdown()
    assert harness.client.stop_calls == 1
    assert not harness.coordinator.stale_timer_armed
    # Repeating shutdown stays safe (idempotent behaviour preserved); the
    # client's own stop() is documented safe to call again.
    await harness.coordinator.async_shutdown()
    assert harness.client.stop_calls == 2
    assert not harness.coordinator.stale_timer_armed


async def test_handlers_are_noops_after_shutdown(harness: Harness) -> None:
    snapshot = make_snapshot(1)
    harness.coordinator._handle_snapshot(snapshot)
    wall_before = harness.coordinator.last_valid_frame_at
    monotonic_before = harness.coordinator.last_valid_frame_monotonic
    await harness.coordinator.async_shutdown()
    base = harness.notify_count
    harness.monotonic.advance(10)
    harness.wall.advance(10)
    # Every handler must be a no-op once shutdown has begun.
    harness.coordinator._handle_snapshot(make_snapshot(2))
    harness.coordinator._handle_connection_event(
        ConnectionEvent(ConnectionState.RECONNECTING)
    )
    # Elapsed is only 10 s here, so an unguarded stale check would re-arm
    # the timer...
    harness.coordinator._async_check_stale()
    assert not harness.coordinator.stale_timer_armed
    # ...and once well past the threshold it would announce STALE.
    harness.monotonic.advance(STALE_AFTER + 200)
    harness.coordinator._async_check_stale()
    assert harness.notify_count == base
    assert harness.coordinator.data is snapshot
    assert harness.coordinator.last_valid_frame_at == wall_before
    assert harness.coordinator.last_valid_frame_monotonic == monotonic_before
    assert harness.coordinator.connection_state is ConnectionState.STOPPED
    assert harness.coordinator.reconnect_count == 0
    assert not harness.coordinator.stale_timer_armed


class LateCallbackClient(FakeRinnaiClient):
    """stop() yields control once, then fires late callbacks into the
    coordinator before returning.

    Models the shutdown race: the coordinator has begun shutting down and
    is awaiting ``stop()`` while the client still delivers a final
    snapshot and connection event. The shutdown guard must make both
    permanent no-ops.
    """

    async def stop(self) -> None:
        self.stop_calls += 1
        await asyncio.sleep(0)  # yield control once, mid-shutdown
        snapshot_callback = self._on_snapshot
        event_callback = self._on_connection_event
        assert snapshot_callback is not None
        assert event_callback is not None
        snapshot_callback(make_snapshot(99))
        event_callback(
            ConnectionEvent(ConnectionState.RECONNECTING, "late error")
        )


async def test_late_client_callbacks_during_stop_are_ignored(
    hass: HomeAssistant,
) -> None:
    monotonic = FakeMonotonic()
    wall = FakeWallClock()
    clients: list[LateCallbackClient] = []

    def _factory(host: str, port: int, **kwargs: Any) -> LateCallbackClient:
        client = LateCallbackClient(host, port, **kwargs)
        clients.append(client)
        return client

    coordinator = RinnaiTouchCoordinator(
        hass,
        host="127.0.0.1",
        port=0,
        client_factory=_factory,
        wall_clock=wall,
        monotonic_clock=monotonic,
    )
    notifications: list[int] = []
    coordinator.async_add_listener(lambda: notifications.append(1))

    coordinator._handle_connection_event(
        ConnectionEvent(ConnectionState.CONNECTED)
    )
    snapshot = make_snapshot(1)
    coordinator._handle_snapshot(snapshot)
    wall_before = coordinator.last_valid_frame_at
    monotonic_before = coordinator.last_valid_frame_monotonic
    notify_before = len(notifications)
    # Advance both clocks so a late (unguarded) snapshot would stamp new,
    # detectably different timestamp values.
    monotonic.advance(10)
    wall.advance(10)

    await coordinator.async_shutdown()

    assert clients[0].stop_calls == 1  # the late callbacks fired inside stop()
    assert len(notifications) == notify_before  # nothing notified afterwards
    assert not coordinator.stale_timer_armed
    assert coordinator.data is snapshot  # late snapshot 99 was ignored
    assert coordinator.last_valid_frame_at == wall_before
    assert coordinator.last_valid_frame_monotonic == monotonic_before
    assert coordinator.freshness is Freshness.FRESH  # timing untouched
    assert coordinator.connection_state is ConnectionState.CONNECTED
    assert coordinator.last_connection_error is None  # "late error" ignored
    assert coordinator.reconnect_count == 0


async def test_scheduled_stale_check_fires_via_event_loop(
    hass: HomeAssistant, harness: Harness
) -> None:
    # The event loop only *delivers* the callback; the STALE decision it
    # makes still comes from the injected monotonic clock, which is
    # advanced here independently of the scheduler's wall-based firing.
    harness.coordinator._handle_snapshot(make_snapshot(1))
    base = harness.notify_count
    harness.monotonic.advance(STALE_AFTER + 20)
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=STALE_AFTER + 20)
    )
    await hass.async_block_till_done()
    assert harness.notify_count == base + 1
    assert harness.coordinator.freshness is Freshness.STALE


# --- end to end over loopback ------------------------------------------------------


class LoopbackModule:
    """Minimal in-process stand-in for a module: unsolicited send only.

    Mirrors the fake-server pattern of test_tcp_client.py, trimmed to what
    this single end-to-end test needs. Records every inbound byte so the
    passive guarantee can be re-asserted at the coordinator level.
    """

    def __init__(self) -> None:
        self._server: asyncio.Server | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected = asyncio.Event()
        self.received = bytearray()

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)

    @property
    def port(self) -> int:
        assert self._server is not None
        return int(self._server.sockets[0].getsockname()[1])

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._writer = writer
        self._connected.set()
        try:
            while chunk := await reader.read(1024):
                self.received.extend(chunk)
        except OSError:
            pass
        finally:
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()

    async def wait_for_connection(self, timeout: float = 5.0) -> None:
        async with asyncio.timeout(timeout):
            await self._connected.wait()

    async def send(self, data: bytes) -> None:
        assert self._writer is not None
        self._writer.write(data)
        await self._writer.drain()

    async def stop(self) -> None:
        if self._writer is not None:
            self._writer.close()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None


def encode_frame(sequence: int, payload: list[dict[str, object]]) -> bytes:
    """Build one wire frame: N + six-digit sequence + JSON array."""
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return f"N{sequence:06d}{body}".encode()


async def test_end_to_end_loopback_stream(hass: HomeAssistant) -> None:
    server = LoopbackModule()
    await server.start()
    coordinator = RinnaiTouchCoordinator(
        hass, host="127.0.0.1", port=server.port
    )
    updated = asyncio.Event()

    def _on_update() -> None:
        if coordinator.data is not None:
            updated.set()

    coordinator.async_add_listener(_on_update)
    try:
        await coordinator.async_start()
        await server.wait_for_connection()
        await server.send(
            encode_frame(1, [{"SYST": {"OSS": {"MD": "H", "ST": "N"}}}])
        )
        async with asyncio.timeout(5.0):
            await updated.wait()
        assert coordinator.data is not None
        assert coordinator.data.operating_mode == "H"
        assert coordinator.freshness is Freshness.FRESH
        assert coordinator.connection_state is ConnectionState.CONNECTED
        assert coordinator.last_valid_frame_at is not None
        assert coordinator.frames_received == 1
    finally:
        await coordinator.async_shutdown()
        await server.stop()
    assert bytes(server.received) == b""  # the coordinator path is passive too
