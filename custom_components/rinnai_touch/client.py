"""Async TCP client for the Rinnai Touch status stream (passive only).

This is Phase 1 *passive observation mode* (docs/protocol_assumptions.md,
"Phase 1 Operating Modes"): the client opens one TCP connection, receives
unsolicited status bytes, feeds them through :class:`RinnaiFrameParser`,
folds frames into one :class:`RinnaiStatusModel`, and publishes immutable
:class:`StatusSnapshot` values in stream order. It transmits nothing.

No outbound write path exists
    The client never writes to the socket: no HVAC commands, no outgoing
    sequence arithmetic, and no transport keepalive. The stream writer is
    held only so it can be closed gracefully. The transport keepalive
    defined in AGENT_SCOPE.md ("Transport Keepalive Policy") remains
    prohibited here until (1) passive probe evidence validates the module's
    idle-disconnect behaviour in docs/protocol_assumptions.md (ledger items
    A2/A11), and (2) a future explicit milestone approves sending it. No
    placeholder write hook is provided, deliberately, so no code path can
    transmit bytes.

Lifecycle
    Construction has no side effects; connections happen only after an
    explicit ``await start()`` (Config Flow Connection Policy: live
    connections require an explicit action). ``start()`` is *idempotent*:
    calling it while the client is already starting or running returns
    without opening another socket. ``await stop()`` cancels the supervisor
    task, closes the writer gracefully (``wait_closed``), prevents any
    further reconnect, and is safe to call repeatedly. A stopped client may
    be started again. ``stop()`` may also be awaited *re-entrantly* from a
    snapshot or state callback: an explicit guard detects the call coming
    from the supervisor task itself and shuts down without self-cancelling
    or self-awaiting; the read loop exits as soon as the callback returns.

One connection, by construction
    A single supervisor task owns the whole lifecycle and runs strictly
    sequentially: connect, read until the stream ends, back off, repeat.
    There is no separate reconnect task to duplicate and no path that can
    hold two open sockets at once. Each connection gets a fresh parser;
    the status model is shared across connections so cumulative
    observations survive reconnects.

Connection state
    ``ConnectionState.CONNECTED`` means the TCP connection is established —
    it is *not* a claim that valid status data is flowing. Per
    AGENT_SCOPE.md, availability must be based on recent valid status
    data, so a future coordinator layer must derive availability from
    snapshot arrival, not from this socket-level state. States move
    STOPPED -> CONNECTING -> CONNECTED, then on failure or EOF
    CONNECTION_FAILED -> RECONNECTING -> CONNECTING, and any state ->
    STOPPED via ``stop()``.

Reconnect policy
    Backoff follows the approved schedule (2, 5, 10, 30, then 60 seconds
    maximum, from ``const.RECONNECT_BACKOFF_SCHEDULE_SECONDS``) and resets
    to the first delay only after a *valid session* — a connection that
    produced at least one successfully parsed frame with a **non-empty**
    payload. An empty ``N…[]`` frame is valid framing but carries no status
    update and does not reset backoff; malformed data never does. A
    non-empty status array counts even if its top-level groups are
    unfamiliar. This way a module that accepts and immediately drops
    connections, or emits only empty frames, still escalates instead of
    being hammered (the upstream reference reports the module dislikes
    rapid reconnects). The sleep function is injectable so tests control
    time completely.

Callbacks
    Snapshot and connection-event callbacks may be sync or async. They are
    awaited in order; exceptions they raise are contained and counted,
    never crashing the read loop or triggering reconnects.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum
from typing import Final

from .const import (
    CONNECT_TIMEOUT_SECONDS,
    DEFAULT_TCP_PORT,
    RECONNECT_BACKOFF_SCHEDULE_SECONDS,
)
from .models import RinnaiStatusModel, StatusSnapshot
from .protocol import RinnaiFrameParser

_LOGGER: Final = logging.getLogger(__name__)

_READ_CHUNK_BYTES: Final = 4096


class ConnectionState(Enum):
    """Socket-level lifecycle state of the client."""

    STOPPED = "stopped"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    CONNECTION_FAILED = "connection_failed"


@dataclass(frozen=True, slots=True)
class ConnectionEvent:
    """One connection-state transition, published to the state callback.

    ``error`` carries a short description when the transition was caused
    by a failure (refused connection, reset, unexpected EOF), else None.
    """

    state: ConnectionState
    error: str | None = None


type SnapshotCallback = Callable[[StatusSnapshot], Awaitable[None] | None]
type ConnectionEventCallback = Callable[[ConnectionEvent], Awaitable[None] | None]
type SleepFunction = Callable[[float], Awaitable[None]]


class RinnaiTcpClient:
    """Passive, receive-only TCP client for one Rinnai Touch module.

    See the module docstring for lifecycle, state, reconnect, and
    no-outbound-write guarantees. All constructor arguments are read-only
    configuration; nothing connects until ``await start()``.
    """

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_TCP_PORT,
        *,
        on_snapshot: SnapshotCallback | None = None,
        on_connection_event: ConnectionEventCallback | None = None,
        reconnect_delays: Sequence[float] = RECONNECT_BACKOFF_SCHEDULE_SECONDS,
        connect_timeout: float = CONNECT_TIMEOUT_SECONDS,
        sleep: SleepFunction = asyncio.sleep,
    ) -> None:
        if not reconnect_delays:
            raise ValueError("reconnect_delays must contain at least one delay")
        self._host = host
        self._port = port
        self._on_snapshot = on_snapshot
        self._on_connection_event = on_connection_event
        self._delays: tuple[float, ...] = tuple(reconnect_delays)
        self._connect_timeout = connect_timeout
        self._sleep = sleep
        self._model = RinnaiStatusModel()
        self._state = ConnectionState.STOPPED
        self._stopping = False
        self._run_task: asyncio.Task[None] | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._frames_received = 0
        self._non_empty_frames = 0
        self._callback_errors = 0
        self._last_error: str | None = None
        self._last_snapshot: StatusSnapshot | None = None

    # --- read-only diagnostics ----------------------------------------------

    @property
    def host(self) -> str:
        """Configured module host (as given; never resolved or probed)."""
        return self._host

    @property
    def port(self) -> int:
        """Configured module TCP port."""
        return self._port

    @property
    def state(self) -> ConnectionState:
        """Current socket-level connection state."""
        return self._state

    @property
    def connected(self) -> bool:
        """True while a TCP connection is established (socket-level only)."""
        return self._state is ConnectionState.CONNECTED

    @property
    def frames_received(self) -> int:
        """Total valid frames parsed and applied since construction."""
        return self._frames_received

    @property
    def callback_error_count(self) -> int:
        """Exceptions contained from snapshot/state callbacks."""
        return self._callback_errors

    @property
    def last_error(self) -> str | None:
        """Most recent connection error description, if any."""
        return self._last_error

    @property
    def last_snapshot(self) -> StatusSnapshot | None:
        """Most recently published immutable snapshot, if any."""
        return self._last_snapshot

    # --- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Begin connecting; idempotent by documented policy.

        If the client is already starting or running, this returns without
        side effects and without opening another socket. After a re-entrant
        ``stop()`` the old supervisor may still be winding down briefly;
        ``start()`` then waits for it to finish before launching a new one,
        so sessions can never overlap. A client that was stopped may be
        started again; cumulative model observations are retained across
        restarts. Calling ``start()`` from inside a client callback is not
        supported and is a no-op while the supervisor is unwinding.
        """
        task = self._run_task
        if task is not None and not task.done():
            if not self._stopping:
                return  # already starting or running
            if task is asyncio.current_task():
                return  # re-entrant restart from a callback: unsupported
            with suppress(asyncio.CancelledError):
                await task  # let the winding-down supervisor finish
        self._stopping = False
        self._run_task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stop permanently until the next ``start()``; safe to repeat.

        Prevents further reconnect attempts, closes the writer gracefully,
        and leaves the client in the STOPPED state. May be called
        externally or *re-entrantly from a snapshot/state callback*: when
        the caller is the supervisor task itself it is neither cancelled
        nor awaited (no self-await path exists); the stopping flag makes
        the read loop exit as soon as the callback returns, and the
        supervisor deregisters itself on exit.
        """
        self._stopping = True
        task = self._run_task
        if task is not None and task is not asyncio.current_task():
            self._run_task = None
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        await self._close_writer()
        await self._set_state(ConnectionState.STOPPED)

    # --- supervisor ----------------------------------------------------------

    async def _run(self) -> None:
        """Connect, read, back off, repeat — strictly sequentially.

        Being the only task, it can never overlap connections or duplicate
        reconnect timers. It exits only via ``stop()`` cancellation (or the
        stopping flag observed after a sleep).
        """
        try:
            delay_index = 0
            while not self._stopping:
                await self._set_state(ConnectionState.CONNECTING)
                try:
                    async with asyncio.timeout(self._connect_timeout):
                        reader, writer = await asyncio.open_connection(
                            self._host, self._port
                        )
                except (OSError, TimeoutError) as err:
                    error = f"connect failed: {err}"
                else:
                    self._writer = writer
                    await self._set_state(ConnectionState.CONNECTED)
                    status_frames_before = self._non_empty_frames
                    error = await self._read_session(reader)
                    await self._close_writer()
                    if self._non_empty_frames > status_frames_before:
                        # A valid session carried at least one non-empty
                        # status frame: reset backoff (documented policy;
                        # empty N…[] frames and malformed data never reset).
                        delay_index = 0
                if self._stopping:
                    break
                self._last_error = error
                await self._set_state(ConnectionState.CONNECTION_FAILED, error)
                await self._set_state(ConnectionState.RECONNECTING)
                delay = self._delays[min(delay_index, len(self._delays) - 1)]
                delay_index += 1
                await self._sleep(delay)
        finally:
            # Self-deregistration: after a re-entrant stop() this task keeps
            # winding down briefly with its registration intact, keeping
            # start() guarded; it hands the slot back only on exit.
            if self._run_task is asyncio.current_task():
                self._run_task = None

    async def _read_session(self, reader: asyncio.StreamReader) -> str:
        """Receive until the stream ends; return a short failure reason.

        Wire bytes can never raise (the parser contains malformed input),
        and callback exceptions are contained by the dispatchers, so only
        transport errors end a session. The broad handler is a supervisor
        safety net: an unexpected internal error is recorded and treated
        like a transport failure instead of silently killing the task.
        """
        parser = RinnaiFrameParser()  # fresh framing state per connection
        try:
            while not self._stopping:
                chunk = await reader.read(_READ_CHUNK_BYTES)
                if not chunk:
                    return "connection closed by remote end"
                for frame in parser.feed(chunk):
                    self._frames_received += 1
                    if frame.payload:
                        self._non_empty_frames += 1
                    snapshot = self._model.apply(frame)
                    self._last_snapshot = snapshot
                    await self._dispatch_snapshot(snapshot)
            return "stopped"
        except asyncio.CancelledError:
            raise
        except Exception as err:  # supervisor safety net, see docstring
            return f"read failed: {err}"

    async def _close_writer(self) -> None:
        """Close the connection gracefully; never raises."""
        writer, self._writer = self._writer, None
        if writer is None:
            return
        try:
            writer.close()
            await writer.wait_closed()
        except OSError:
            pass  # already broken; closing is best effort

    # --- callback dispatch ----------------------------------------------------

    async def _set_state(
        self, state: ConnectionState, error: str | None = None
    ) -> None:
        """Record a state transition and publish it; no-op if unchanged."""
        if state is self._state:
            return
        self._state = state
        if self._on_connection_event is None:
            return
        event = ConnectionEvent(state=state, error=error)
        try:
            result = self._on_connection_event(event)
            if result is not None and inspect.isawaitable(result):
                await result
        except Exception as err:  # containment is the callback contract
            self._callback_errors += 1
            _LOGGER.debug("Connection-event callback failed: %r", err)

    async def _dispatch_snapshot(self, snapshot: StatusSnapshot) -> None:
        """Publish one snapshot; callback failures are contained."""
        if self._on_snapshot is None:
            return
        try:
            result = self._on_snapshot(snapshot)
            if result is not None and inspect.isawaitable(result):
                await result
        except Exception as err:  # containment is the callback contract
            self._callback_errors += 1
            _LOGGER.debug("Snapshot callback failed: %r", err)
