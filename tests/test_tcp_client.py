"""Offline tests for the passive async TCP client.

Every test runs against an in-process asyncio fake server bound to
127.0.0.1 with an ephemeral port. No real hardware, no real addresses, no
internet, no Home Assistant. Reconnect timing is fully controlled through
an injected fake sleep, so no test waits for real backoff periods.
"""

from __future__ import annotations

import ast
import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from pathlib import Path

import pytest

from custom_components.rinnai_touch.client import (
    ConnectionEvent,
    ConnectionState,
    RinnaiTcpClient,
)
from custom_components.rinnai_touch.models import StatusSnapshot

# --- synthetic payloads -------------------------------------------------------

SYST_FULL: dict[str, object] = {
    "SYST": {"AVM": {"HG": "Y"}, "OSS": {"MD": "H", "ST": "N"}}
}
SYST_PARTIAL: dict[str, object] = {"SYST": {"OSS": {"MD": "H"}}}
HGOM_GROUP: dict[str, object] = {"HGOM": {"ZUS": {"MT": "223", "AE": "Y"}}}


def encode_frame(sequence: int, payload: list[dict[str, object]]) -> bytes:
    """Build one wire frame: N + six-digit sequence + JSON array."""
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return f"N{sequence:06d}{body}".encode()


# --- in-process fake server and test doubles ---------------------------------


class FakeRinnaiServer:
    """Loopback TCP server that speaks like a module: it only sends.

    Records every inbound byte (there must never be any), counts
    connections, and tracks the maximum number of simultaneously open
    connections so overlap can be asserted.
    """

    def __init__(self) -> None:
        self._server: asyncio.Server | None = None
        self._writers: list[asyncio.StreamWriter] = []
        self._accepted = asyncio.Event()
        self.connection_count = 0
        self.open_connections = 0
        self.max_open_connections = 0
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
        self.connection_count += 1
        self.open_connections += 1
        self.max_open_connections = max(
            self.max_open_connections, self.open_connections
        )
        self._writers.append(writer)
        self._accepted.set()
        try:
            while True:
                data = await reader.read(1024)
                if not data:
                    break
                self.received.extend(data)
        except (OSError, asyncio.IncompleteReadError):
            pass
        finally:
            self.open_connections -= 1
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()

    async def wait_for_connections(self, count: int, timeout: float = 2.0) -> None:
        async with asyncio.timeout(timeout):
            while self.connection_count < count:
                self._accepted.clear()
                await self._accepted.wait()

    async def send(self, data: bytes) -> None:
        """Send bytes to the most recent connection, like an unsolicited push."""
        writer = self._writers[-1]
        writer.write(data)
        await writer.drain()

    async def drop_current(self) -> None:
        """Close the current connection, producing EOF on the client side."""
        writer = self._writers[-1]
        writer.close()
        with suppress(OSError):
            await writer.wait_closed()

    async def stop(self) -> None:
        for writer in self._writers:
            writer.close()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None


class SnapshotCollector:
    """Synchronous snapshot callback that records and signals arrivals."""

    def __init__(self) -> None:
        self.snapshots: list[StatusSnapshot] = []
        self._arrived = asyncio.Event()

    def __call__(self, snapshot: StatusSnapshot) -> None:
        self.snapshots.append(snapshot)
        self._arrived.set()

    async def wait_for(self, count: int, timeout: float = 2.0) -> None:
        async with asyncio.timeout(timeout):
            while len(self.snapshots) < count:
                self._arrived.clear()
                await self._arrived.wait()


class EventCollector:
    """Synchronous connection-event callback that records transitions."""

    def __init__(self) -> None:
        self.events: list[ConnectionEvent] = []
        self._arrived = asyncio.Event()

    def __call__(self, event: ConnectionEvent) -> None:
        self.events.append(event)
        self._arrived.set()

    @property
    def states(self) -> list[ConnectionState]:
        return [event.state for event in self.events]

    async def wait_for_state(
        self, state: ConnectionState, timeout: float = 2.0
    ) -> None:
        async with asyncio.timeout(timeout):
            while state not in self.states:
                self._arrived.clear()
                await self._arrived.wait()


class FakeSleep:
    """Injected sleep: records requested delays and returns immediately.

    With ``block_after`` set, later calls block forever (until cancelled by
    ``stop()``), which freezes a reconnect loop deterministically once the
    delays under test have been observed.
    """

    def __init__(self, block_after: int | None = None) -> None:
        self.delays: list[float] = []
        self._block_after = block_after
        self._recorded = asyncio.Event()

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        self._recorded.set()
        if self._block_after is not None and len(self.delays) >= self._block_after:
            await asyncio.Event().wait()  # block until cancelled
        await asyncio.sleep(0)

    async def wait_for_delays(self, count: int, timeout: float = 2.0) -> None:
        async with asyncio.timeout(timeout):
            while len(self.delays) < count:
                self._recorded.clear()
                await self._recorded.wait()


async def wait_until(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    """Poll a condition with a hard timeout; keeps tests deterministic."""
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.001)


@pytest.fixture
async def server() -> AsyncIterator[FakeRinnaiServer]:
    fake = FakeRinnaiServer()
    await fake.start()
    yield fake
    await fake.stop()


def new_client(
    port: int,
    *,
    snapshots: SnapshotCollector | None = None,
    events: EventCollector | None = None,
    sleeper: FakeSleep | None = None,
) -> RinnaiTcpClient:
    return RinnaiTcpClient(
        "127.0.0.1",
        port,
        on_snapshot=snapshots,
        on_connection_event=events,
        sleep=sleeper if sleeper is not None else FakeSleep(),
    )


# --- 1-2: construction and start ----------------------------------------------


async def test_construction_does_not_connect(server: FakeRinnaiServer) -> None:
    client = new_client(server.port)
    for _ in range(5):
        await asyncio.sleep(0)
    assert server.connection_count == 0
    assert client.state is ConnectionState.STOPPED
    await client.stop()  # safe even though never started


async def test_start_opens_one_connection(server: FakeRinnaiServer) -> None:
    events = EventCollector()
    client = new_client(server.port, events=events)
    try:
        await client.start()
        await server.wait_for_connections(1)
        await events.wait_for_state(ConnectionState.CONNECTED)
        assert server.connection_count == 1
        # CONNECTED is never reported before a socket exists.
        assert events.states[:2] == [
            ConnectionState.CONNECTING,
            ConnectionState.CONNECTED,
        ]
    finally:
        await client.stop()


# --- 3-6: read loop, splits, concatenation, malformed bytes --------------------


async def test_unsolicited_frame_reaches_snapshot_callback(
    server: FakeRinnaiServer,
) -> None:
    snapshots = SnapshotCollector()
    client = new_client(server.port, snapshots=snapshots)
    try:
        await client.start()
        await server.wait_for_connections(1)
        await server.send(encode_frame(1, [SYST_FULL]))
        await snapshots.wait_for(1)
        snapshot = snapshots.snapshots[0]
        assert snapshot.sequence == 1
        assert snapshot.operating_mode == "H"
        assert client.frames_received == 1
        assert client.last_snapshot is snapshot
    finally:
        await client.stop()


async def test_frame_split_across_multiple_writes(
    server: FakeRinnaiServer,
) -> None:
    snapshots = SnapshotCollector()
    client = new_client(server.port, snapshots=snapshots)
    try:
        await client.start()
        await server.wait_for_connections(1)
        frame = encode_frame(7, [SYST_FULL, HGOM_GROUP])
        third = len(frame) // 3
        await server.send(frame[:third])
        await server.send(frame[third : 2 * third])
        await server.send(frame[2 * third :])
        await snapshots.wait_for(1)
        snapshot = snapshots.snapshots[0]
        assert snapshot.sequence == 7
        zone_u = snapshot.zones["U"]
        assert zone_u.current is not None
        assert zone_u.current.measured_temperature == 22.3
    finally:
        await client.stop()


async def test_concatenated_frames_publish_ordered_snapshots(
    server: FakeRinnaiServer,
) -> None:
    snapshots = SnapshotCollector()
    client = new_client(server.port, snapshots=snapshots)
    try:
        await client.start()
        await server.wait_for_connections(1)
        await server.send(
            encode_frame(1, [SYST_FULL]) + encode_frame(2, [HGOM_GROUP])
        )
        await snapshots.wait_for(2)
        assert [s.sequence for s in snapshots.snapshots] == [1, 2]
    finally:
        await client.stop()


async def test_malformed_bytes_then_valid_frame(
    server: FakeRinnaiServer,
) -> None:
    snapshots = SnapshotCollector()
    client = new_client(server.port, snapshots=snapshots)
    try:
        await client.start()
        await server.wait_for_connections(1)
        await server.send(b'N000001[{"SYST":}]@@garbage@@')
        await server.send(encode_frame(2, [SYST_FULL]))
        await snapshots.wait_for(1)
        assert snapshots.snapshots[0].sequence == 2
        assert client.state is ConnectionState.CONNECTED
        assert server.connection_count == 1  # no reconnect was triggered
    finally:
        await client.stop()


# --- 7: shared parser/model semantics across frames ----------------------------


async def test_model_state_is_shared_across_frames(
    server: FakeRinnaiServer,
) -> None:
    snapshots = SnapshotCollector()
    client = new_client(server.port, snapshots=snapshots)
    try:
        await client.start()
        await server.wait_for_connections(1)
        await server.send(encode_frame(1, [SYST_FULL, HGOM_GROUP]))
        await snapshots.wait_for(1)
        await server.send(encode_frame(2, [SYST_PARTIAL]))
        await snapshots.wait_for(2)
        second = snapshots.snapshots[1]
        # Raw SYST is exactly the replacement; cumulative facts survive.
        assert second.raw_groups["SYST"] == {"OSS": {"MD": "H"}}
        assert second.capabilities.heater_observed is True
        zone_u = second.zones["U"]
        assert zone_u.current is not None  # retained HGOM is still active
        assert zone_u.current.measured_temperature == 22.3
    finally:
        await client.stop()


# --- 8: callback exception containment ------------------------------------------


class FlakySnapshotCollector(SnapshotCollector):
    """Raises on the first call, records normally afterwards."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def __call__(self, snapshot: StatusSnapshot) -> None:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("synthetic callback failure")
        super().__call__(snapshot)


async def test_callback_exception_does_not_stop_delivery(
    server: FakeRinnaiServer,
) -> None:
    snapshots = FlakySnapshotCollector()
    client = new_client(server.port, snapshots=snapshots)
    try:
        await client.start()
        await server.wait_for_connections(1)
        await server.send(encode_frame(1, [SYST_FULL]))
        await server.send(encode_frame(2, [HGOM_GROUP]))
        await snapshots.wait_for(1)
        assert snapshots.snapshots[0].sequence == 2  # first was consumed by error
        assert client.callback_error_count == 1
        assert client.state is ConnectionState.CONNECTED  # no reconnect
        assert client.frames_received == 2  # parsing never stopped
    finally:
        await client.stop()


class FailingOnConnectedEvents(EventCollector):
    """Raises exactly when the CONNECTING -> CONNECTED transition arrives."""

    def __call__(self, event: ConnectionEvent) -> None:
        super().__call__(event)
        if event.state is ConnectionState.CONNECTED:
            raise RuntimeError("synthetic state callback failure")


async def test_state_callback_exception_during_connected_transition(
    server: FakeRinnaiServer,
) -> None:
    events = FailingOnConnectedEvents()
    snapshots = SnapshotCollector()
    client = new_client(server.port, snapshots=snapshots, events=events)
    try:
        await client.start()
        await server.wait_for_connections(1)
        await events.wait_for_state(ConnectionState.CONNECTED)
        assert client.callback_error_count == 1
        # The socket stayed usable and the read loop proceeded normally.
        await server.send(encode_frame(1, [SYST_FULL]))
        await snapshots.wait_for(1)
        assert snapshots.snapshots[0].sequence == 1
        assert client.state is ConnectionState.CONNECTED
        assert server.connection_count == 1  # no unnecessary reconnect
    finally:
        await client.stop()
    assert client.state is ConnectionState.STOPPED  # still stops cleanly


async def test_reentrant_stop_from_snapshot_callback(
    server: FakeRinnaiServer,
) -> None:
    stop_returned: list[str] = []
    client: RinnaiTcpClient | None = None

    async def stopping_callback(snapshot: StatusSnapshot) -> None:
        assert client is not None
        await client.stop()  # re-entrant: must not deadlock or raise
        stop_returned.append("returned")

    client = RinnaiTcpClient(
        "127.0.0.1",
        server.port,
        on_snapshot=stopping_callback,
        sleep=FakeSleep(),
    )
    await client.start()
    await server.wait_for_connections(1)
    await server.send(encode_frame(1, [SYST_FULL]))
    await wait_until(lambda: stop_returned == ["returned"])  # no deadlock
    # stop() completed without raising: had it raised inside the callback,
    # the dispatcher would have contained and counted it.
    assert client.callback_error_count == 0
    assert client.state is ConnectionState.STOPPED
    await wait_until(lambda: server.open_connections == 0)  # connection closed
    for _ in range(10):
        await asyncio.sleep(0.001)
    assert server.connection_count == 1  # no reconnect occurred

    # The client can be restarted through the normal explicit path;
    # start() waits out any remaining supervisor winddown first.
    await client.start()
    await server.wait_for_connections(2)
    await wait_until(lambda: client.connected)
    await client.stop()
    assert client.state is ConnectionState.STOPPED


async def test_async_callbacks_are_supported(server: FakeRinnaiServer) -> None:
    received: list[int] = []
    states: list[ConnectionState] = []
    arrived = asyncio.Event()

    async def on_snapshot(snapshot: StatusSnapshot) -> None:
        received.append(snapshot.sequence)
        arrived.set()

    async def on_event(event: ConnectionEvent) -> None:
        states.append(event.state)

    client = RinnaiTcpClient(
        "127.0.0.1",
        server.port,
        on_snapshot=on_snapshot,
        on_connection_event=on_event,
        sleep=FakeSleep(),
    )
    try:
        await client.start()
        await server.wait_for_connections(1)
        await server.send(encode_frame(5, [SYST_FULL]))
        async with asyncio.timeout(2.0):
            await arrived.wait()
        assert received == [5]
        assert ConnectionState.CONNECTED in states
    finally:
        await client.stop()


# --- 9-11: idempotent start, idempotent stop, stop prevents reconnect -----------


async def test_repeated_start_does_not_open_second_connection(
    server: FakeRinnaiServer,
) -> None:
    client = new_client(server.port)
    try:
        await client.start()
        await client.start()  # while connecting
        await server.wait_for_connections(1)
        await client.start()  # while connected
        for _ in range(10):
            await asyncio.sleep(0.001)
        assert server.connection_count == 1
        assert server.max_open_connections == 1
    finally:
        await client.stop()


async def test_stop_is_idempotent(server: FakeRinnaiServer) -> None:
    client = new_client(server.port)
    await client.start()
    await server.wait_for_connections(1)
    await client.stop()
    await client.stop()  # second stop must be safe
    assert client.state is ConnectionState.STOPPED


async def test_stop_closes_connection_and_prevents_reconnect(
    server: FakeRinnaiServer,
) -> None:
    sleeper = FakeSleep()
    client = new_client(server.port, sleeper=sleeper)
    await client.start()
    await server.wait_for_connections(1)
    await client.stop()
    await wait_until(lambda: server.open_connections == 0)
    for _ in range(10):
        await asyncio.sleep(0.001)
    assert server.connection_count == 1  # never reconnected
    assert sleeper.delays == []  # no backoff was ever scheduled
    assert client.state is ConnectionState.STOPPED


# --- 12-16: EOF, refusal, backoff, reset, no overlap -----------------------------


async def test_unexpected_eof_triggers_controlled_reconnect(
    server: FakeRinnaiServer,
) -> None:
    events = EventCollector()
    sleeper = FakeSleep()
    client = new_client(server.port, events=events, sleeper=sleeper)
    try:
        await client.start()
        await server.wait_for_connections(1)
        await server.drop_current()
        await server.wait_for_connections(2)  # controlled reconnect happened
        await events.wait_for_state(ConnectionState.CONNECTION_FAILED)
        assert ConnectionState.RECONNECTING in events.states
        assert sleeper.delays == [2]  # first approved backoff step
        assert server.max_open_connections == 1
    finally:
        await client.stop()


async def test_connection_refused_backoff_follows_approved_schedule() -> None:
    # Acquire a loopback port that refuses connections: bind, note, close.
    throwaway = FakeRinnaiServer()
    await throwaway.start()
    refused_port = throwaway.port
    await throwaway.stop()

    events = EventCollector()
    sleeper = FakeSleep(block_after=6)
    client = new_client(refused_port, events=events, sleeper=sleeper)
    try:
        await client.start()
        await sleeper.wait_for_delays(6)
        assert sleeper.delays == [2, 5, 10, 30, 60, 60]  # approved schedule
        assert ConnectionState.CONNECTION_FAILED in events.states
        assert ConnectionState.CONNECTED not in events.states
    finally:
        await client.stop()  # must promptly cancel the blocked sleep
    assert client.state is ConnectionState.STOPPED


async def test_valid_session_resets_backoff(server: FakeRinnaiServer) -> None:
    snapshots = SnapshotCollector()
    sleeper = FakeSleep()
    client = new_client(server.port, snapshots=snapshots, sleeper=sleeper)
    try:
        await client.start()
        await server.wait_for_connections(1)
        await server.send(encode_frame(1, [SYST_FULL]))
        await snapshots.wait_for(1)
        await server.drop_current()

        await server.wait_for_connections(2)
        await server.send(encode_frame(2, [SYST_FULL]))
        await snapshots.wait_for(2)
        await server.drop_current()

        await server.wait_for_connections(3)
        # Each drop followed a session with a valid frame, so the backoff
        # restarted from the first approved delay both times.
        assert sleeper.delays == [2, 2]
    finally:
        await client.stop()


async def test_empty_payload_session_does_not_reset_backoff(
    server: FakeRinnaiServer,
) -> None:
    snapshots = SnapshotCollector()
    sleeper = FakeSleep()
    client = new_client(server.port, snapshots=snapshots, sleeper=sleeper)
    try:
        await client.start()
        await server.wait_for_connections(1)
        await server.drop_current()  # frameless session: escalate

        await server.wait_for_connections(2)
        await server.send(encode_frame(1, []))  # valid framing, no status
        await snapshots.wait_for(1)  # the empty frame was fully processed
        await server.drop_current()

        await server.wait_for_connections(3)
        # An empty-payload-only session must not reset the backoff: the
        # second delay escalated instead of returning to the first step.
        assert sleeper.delays == [2, 5]
    finally:
        await client.stop()


async def test_unfamiliar_non_empty_frame_resets_backoff(
    server: FakeRinnaiServer,
) -> None:
    snapshots = SnapshotCollector()
    sleeper = FakeSleep()
    client = new_client(server.port, snapshots=snapshots, sleeper=sleeper)
    try:
        await client.start()
        await server.wait_for_connections(1)
        await server.drop_current()  # frameless session: escalate

        await server.wait_for_connections(2)
        # Non-empty status array with an unknown future top-level group.
        await server.send(encode_frame(1, [{"XGOM": {"Q": {"V": "1"}}}]))
        await snapshots.wait_for(1)
        await server.drop_current()

        await server.wait_for_connections(3)
        # The unfamiliar-but-valid non-empty frame reset the backoff.
        assert sleeper.delays == [2, 2]
    finally:
        await client.stop()


async def test_no_overlapping_connections_across_cycles(
    server: FakeRinnaiServer,
) -> None:
    client = new_client(server.port)
    try:
        await client.start()
        await server.wait_for_connections(1)
        for expected in (2, 3):
            await server.drop_current()
            await server.wait_for_connections(expected)
        assert server.connection_count == 3
        assert server.max_open_connections == 1  # never two sockets at once
    finally:
        await client.stop()


# --- 17-18: nothing is ever transmitted -----------------------------------------


async def test_client_sends_no_bytes(server: FakeRinnaiServer) -> None:
    snapshots = SnapshotCollector()
    client = new_client(server.port, snapshots=snapshots)
    await client.start()
    await server.wait_for_connections(1)
    await server.send(encode_frame(1, [SYST_FULL, HGOM_GROUP]))
    await snapshots.wait_for(1)
    await client.stop()
    await wait_until(lambda: server.open_connections == 0)
    assert bytes(server.received) == b""  # passive monitored mode only


CLIENT_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "rinnai_touch"
    / "client.py"
)


def test_no_outbound_write_call_path_exists() -> None:
    # The only permitted writer interactions are close() and wait_closed().
    tree = ast.parse(CLIENT_PATH.read_text(encoding="utf-8"))
    banned = {"write", "writelines", "drain", "send", "sendall", "sendto"}
    attribute_calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not attribute_calls & banned, attribute_calls & banned


# --- 19-20: import hygiene and API surface ---------------------------------------


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    return imported


def test_client_imports_no_forbidden_modules() -> None:
    imported = _top_level_imports(CLIENT_PATH)
    assert not imported & {"socket", "aiohttp", "homeassistant"}


def test_client_exposes_no_command_or_keepalive_api() -> None:
    banned = ("command", "send", "write", "keepalive", "hvac", "setpoint")
    public = [name for name in dir(RinnaiTcpClient) if not name.startswith("_")]
    for name in public:
        lowered = name.lower()
        assert not any(word in lowered for word in banned), name


# --- additional lifecycle locks ---------------------------------------------------


async def test_restart_after_stop_keeps_cumulative_model(
    server: FakeRinnaiServer,
) -> None:
    snapshots = SnapshotCollector()
    client = new_client(server.port, snapshots=snapshots)
    await client.start()
    await server.wait_for_connections(1)
    await server.send(encode_frame(1, [SYST_FULL]))  # latches heater_observed
    await snapshots.wait_for(1)
    await client.stop()
    assert client.state is ConnectionState.STOPPED

    await client.start()  # restart is supported after stop
    try:
        await server.wait_for_connections(2)
        await server.send(encode_frame(2, [SYST_PARTIAL]))
        await snapshots.wait_for(2)
        # Cumulative observations survive the restart (shared model).
        assert snapshots.snapshots[1].capabilities.heater_observed is True
    finally:
        await client.stop()
