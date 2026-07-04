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

Transport forensics
    The client logs a sanitised forensic trail so field logs can explain
    *when* and *how* sessions end, without changing any transport
    behaviour: per-client and per-session identifiers (process-lifetime
    counters, never addresses), connect/first-byte/first-frame timings
    from an injectable monotonic clock, a split-safe observational check
    for the module's 7-byte greeting banner (log-only; parser input and
    outcomes are untouched), and exactly one summary record for every
    finished connect attempt. Log lines never contain host, port, entry
    title, frame or payload content, or raw OS exception text — failures
    are reduced to a fixed classification label, the exception class
    name, and the integer errno. One WARNING marks the start of an outage
    (a session ending without any valid frame) or a change of failure
    classification during one; repeats stay at DEBUG, and the escalation
    clears only when a valid frame arrives. ``ConnectionEvent`` payloads
    are byte-identical to before and are never logged.
"""

from __future__ import annotations

import asyncio
import errno as errno_codes
import inspect
import itertools
import logging
import time
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar, Final

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
type MonotonicFunction = Callable[[], float]

# The module's observed 7-byte greeting. Detection is observational only:
# the bytes still flow to the parser unchanged (which discards them as
# pre-frame garbage), and only a boolean is ever logged.
_BANNER: Final = b"*HELLO*"

# Fixed classification labels for transport failures. Only these labels,
# the exception class name, and the integer errno may reach a log line:
# OS-generated exception *messages* can embed the remote address and are
# therefore never logged (see the no-address structural lock).
_ERRNO_LABELS: Final = {
    errno_codes.ECONNREFUSED: "refused",
    errno_codes.ECONNRESET: "reset",
    errno_codes.ECONNABORTED: "aborted",
    errno_codes.EHOSTUNREACH: "host-unreachable",
    errno_codes.ENETUNREACH: "network-unreachable",
    errno_codes.EPIPE: "broken-pipe",
    errno_codes.ETIMEDOUT: "timeout",
}


def _classify_error(err: BaseException) -> tuple[str, str, int | None]:
    """Reduce an exception to (label, class name, errno) — never message text."""
    code = getattr(err, "errno", None)
    code = code if isinstance(code, int) else None
    if isinstance(err, TimeoutError):
        label = "timeout"
    elif code is not None and code in _ERRNO_LABELS:
        label = _ERRNO_LABELS[code]
    elif isinstance(err, ConnectionResetError):
        label = "reset"
    elif isinstance(err, ConnectionRefusedError):
        label = "refused"
    elif isinstance(err, ConnectionAbortedError):
        label = "aborted"
    elif isinstance(err, BrokenPipeError):
        label = "broken-pipe"
    elif isinstance(err, OSError):
        label = "os-error"
    else:
        label = "internal-error"
    return label, type(err).__name__, code


def _elapsed_ms(start: float, end: float) -> int:
    """Whole milliseconds between two monotonic readings, never negative."""
    return max(0, round((end - start) * 1000))


def _fmt_ms(value: int | None) -> str:
    """Render an optional millisecond value for a log line."""
    return f"{value}ms" if value is not None else "never"


@dataclass(slots=True)
class _OpenSession:
    """Mutable tracker for the connect attempt currently in flight.

    Internal forensic bookkeeping only; holds counters, monotonic marks,
    and the split-safe banner prefix. Never contains addresses, frame
    content, or OS error text.
    """

    number: int
    started: float
    connected_at: float | None = None
    bytes_received: int = 0
    chunks_received: int = 0
    frames: int = 0
    non_empty_frames: int = 0
    banner_seen: bool = False
    banner_prefix: bytearray = field(default_factory=bytearray)
    first_bytes_at: float | None = None
    first_frame_at: float | None = None
    parser: RinnaiFrameParser | None = None
    reason: str | None = None
    error_class: str | None = None
    error_errno: int | None = None


@dataclass(frozen=True, slots=True)
class _SessionForensics:
    """Sanitised summary of one finished connect attempt.

    Private/internal record: it backs the per-session summary log line and
    lets offline tests assert forensic fields directly. It is not a public
    client API. All values are counters, timings, booleans, and fixed
    labels — never addresses, payload content, or OS error text.
    """

    client_number: int
    session_number: int
    phase: str
    reason: str
    error_class: str | None
    error_errno: int | None
    duration_ms: int
    connect_ms: int | None
    bytes_received: int
    chunks_received: int
    frames_received: int
    non_empty_frames: int
    parser_discarded_bytes: int
    parser_invalid_candidates: int
    banner_seen: bool
    first_bytes_ms: int | None
    first_frame_ms: int | None


class RinnaiTcpClient:
    """Passive, receive-only TCP client for one Rinnai Touch module.

    See the module docstring for lifecycle, state, reconnect, and
    no-outbound-write guarantees. All constructor arguments are read-only
    configuration; nothing connects until ``await start()``.
    """

    # Process-lifetime client numbering for log identity: carries no
    # address or entry information and resets naturally on restart.
    _instance_counter: ClassVar[Iterator[int]] = itertools.count(1)

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
        monotonic: MonotonicFunction = time.monotonic,
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
        self._monotonic = monotonic
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
        # --- forensic bookkeeping (logging only; no behaviour input) ------
        self._client_number = next(RinnaiTcpClient._instance_counter)
        self._session_number = 0
        self._sessions_without_frame = 0
        self._warned_classification: str | None = None
        self._open_session: _OpenSession | None = None
        self._last_session_forensics: _SessionForensics | None = None

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
                _LOGGER.debug(
                    "client #%d: start ignored; supervisor already active",
                    self._client_number,
                )
                return  # already starting or running
            if task is asyncio.current_task():
                _LOGGER.debug(
                    "client #%d: start ignored; called from supervisor callback",
                    self._client_number,
                )
                return  # re-entrant restart from a callback: unsupported
            _LOGGER.debug(
                "client #%d: start waiting for winding-down supervisor",
                self._client_number,
            )
            with suppress(asyncio.CancelledError):
                await task  # let the winding-down supervisor finish
        self._stopping = False
        _LOGGER.debug("client #%d: supervisor starting", self._client_number)
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
        _LOGGER.debug(
            "client #%d: stop requested (state=%s)",
            self._client_number,
            self._state.value,
        )
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
        _LOGGER.debug("client #%d: stopped", self._client_number)

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
                session = self._begin_session(delay_index)
                error: str
                try:
                    await self._set_state(ConnectionState.CONNECTING)
                    try:
                        async with asyncio.timeout(self._connect_timeout):
                            reader, writer = await asyncio.open_connection(
                                self._host, self._port
                            )
                    except (OSError, TimeoutError) as err:
                        error = f"connect failed: {err}"
                        self._finish_session("connect-failed", exc=err)
                    else:
                        session.connected_at = self._monotonic()
                        _LOGGER.debug(
                            "client #%d session #%d: TCP established in %d ms",
                            self._client_number,
                            session.number,
                            _elapsed_ms(session.started, session.connected_at),
                        )
                        self._writer = writer
                        await self._set_state(ConnectionState.CONNECTED)
                        status_frames_before = self._non_empty_frames
                        error = await self._read_session(reader, session)
                        await self._close_writer()
                        if self._non_empty_frames > status_frames_before:
                            # A valid session carried at least one non-empty
                            # status frame: reset backoff (documented policy;
                            # empty N…[] frames and malformed data never reset).
                            delay_index = 0
                        self._finish_session(
                            "stopped"
                            if self._stopping
                            else "established-then-closed"
                        )
                finally:
                    # Cancellation guard (stop() mid-connect or mid-read):
                    # every begun attempt still gets exactly one summary.
                    # A no-op when the session was already finished above.
                    self._finish_session("stopped")
                if self._stopping:
                    break
                self._last_error = error
                await self._set_state(ConnectionState.CONNECTION_FAILED, error)
                await self._set_state(ConnectionState.RECONNECTING)
                step_index = min(delay_index, len(self._delays) - 1)
                delay = self._delays[step_index]
                delay_index += 1
                _LOGGER.debug(
                    "client #%d: retrying in %.0f s (backoff step %d/%d)",
                    self._client_number,
                    delay,
                    step_index + 1,
                    len(self._delays),
                )
                await self._sleep(delay)
        finally:
            _LOGGER.debug(
                "client #%d: supervisor exited", self._client_number
            )
            # Self-deregistration: after a re-entrant stop() this task keeps
            # winding down briefly with its registration intact, keeping
            # start() guarded; it hands the slot back only on exit.
            if self._run_task is asyncio.current_task():
                self._run_task = None

    async def _read_session(
        self, reader: asyncio.StreamReader, session: _OpenSession
    ) -> str:
        """Receive until the stream ends; return a short failure reason.

        Wire bytes can never raise (the parser contains malformed input),
        and callback exceptions are contained by the dispatchers, so only
        transport errors end a session. The broad handler is a supervisor
        safety net: an unexpected internal error is recorded and treated
        like a transport failure instead of silently killing the task.
        The ``session`` tracker collects forensic counters and timings as
        a pure observer: parser input and outcomes are untouched.
        """
        parser = RinnaiFrameParser()  # fresh framing state per connection
        session.parser = parser
        try:
            while not self._stopping:
                chunk = await reader.read(_READ_CHUNK_BYTES)
                if not chunk:
                    session.reason = "remote-eof"
                    return "connection closed by remote end"
                self._track_chunk(session, chunk)
                for frame in parser.feed(chunk):
                    self._frames_received += 1
                    session.frames += 1
                    if session.first_frame_at is None:
                        session.first_frame_at = self._monotonic()
                        self._note_first_valid_frame(session)
                    if frame.payload:
                        self._non_empty_frames += 1
                        session.non_empty_frames += 1
                        if session.non_empty_frames == 1:
                            _LOGGER.debug(
                                "client #%d session #%d: first non-empty"
                                " status frame (+%d ms)",
                                self._client_number,
                                session.number,
                                _elapsed_ms(
                                    session.connected_at or session.started,
                                    self._monotonic(),
                                ),
                            )
                    snapshot = self._model.apply(frame)
                    self._last_snapshot = snapshot
                    await self._dispatch_snapshot(snapshot)
            session.reason = "stopped"
            return "stopped"
        except asyncio.CancelledError:
            raise
        except Exception as err:  # supervisor safety net, see docstring
            label, error_class, error_errno = _classify_error(err)
            session.reason = label
            session.error_class = error_class
            session.error_errno = error_errno
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

    # --- transport forensics (logging only; never a behaviour input) -----------

    def _begin_session(self, delay_index: int) -> _OpenSession:
        """Open the forensic tracker for the next connect attempt."""
        self._session_number += 1
        step_index = min(delay_index, len(self._delays) - 1)
        _LOGGER.debug(
            "client #%d session #%d: connecting (backoff step %d/%d;"
            " %d prior session(s) without a valid frame)",
            self._client_number,
            self._session_number,
            step_index + 1,
            len(self._delays),
            self._sessions_without_frame,
        )
        session = _OpenSession(self._session_number, self._monotonic())
        self._open_session = session
        return session

    def _track_chunk(self, session: _OpenSession, chunk: bytes) -> None:
        """Record received-byte forensics; purely observational.

        The chunk is only inspected, never modified or withheld: the exact
        same bytes reach the parser. The banner check copies at most the
        first 7 bytes of the session (split-safe) and logs a boolean.
        """
        now = self._monotonic()
        base = session.connected_at or session.started
        first_chunk = session.first_bytes_at is None
        if first_chunk:
            session.first_bytes_at = now
        session.bytes_received += len(chunk)
        session.chunks_received += 1
        banner_newly_seen = False
        if not session.banner_seen and len(session.banner_prefix) < len(_BANNER):
            session.banner_prefix.extend(
                chunk[: len(_BANNER) - len(session.banner_prefix)]
            )
            if (
                len(session.banner_prefix) == len(_BANNER)
                and bytes(session.banner_prefix) == _BANNER
            ):
                session.banner_seen = True
                banner_newly_seen = True
        if first_chunk:
            banner_state = (
                "yes"
                if session.banner_seen
                else "pending"
                if len(session.banner_prefix) < len(_BANNER)
                else "no"
            )
            _LOGGER.debug(
                "client #%d session #%d: first bytes received"
                " (%d byte(s), +%d ms, banner=%s)",
                self._client_number,
                session.number,
                len(chunk),
                _elapsed_ms(base, now),
                banner_state,
            )
        if banner_newly_seen:
            _LOGGER.debug(
                "client #%d session #%d: HELLO banner observed (+%d ms)",
                self._client_number,
                session.number,
                _elapsed_ms(base, now),
            )

    def _note_first_valid_frame(self, session: _OpenSession) -> None:
        """Log session health and clear the outage escalation state."""
        first_frame_at = session.first_frame_at
        if first_frame_at is None:  # caller sets it just before calling
            return
        _LOGGER.info(
            "client #%d session #%d: first valid frame received (+%d ms)",
            self._client_number,
            session.number,
            _elapsed_ms(session.connected_at or session.started, first_frame_at),
        )
        if self._sessions_without_frame:
            _LOGGER.info(
                "client #%d session #%d: valid status restored after %d"
                " session(s) without a valid frame",
                self._client_number,
                session.number,
                self._sessions_without_frame,
            )
        self._sessions_without_frame = 0
        self._warned_classification = None

    def _finish_session(
        self, phase: str, exc: BaseException | None = None
    ) -> None:
        """Emit exactly one sanitised summary for the open attempt.

        Idempotent per session: the cancellation guard in ``_run`` calls
        this again after the normal paths and becomes a no-op. Also
        maintains the once-per-outage warning escalation, which fires on
        the first frameless session or on a failure-classification change
        and clears only when a valid frame arrives.
        """
        session = self._open_session
        if session is None:
            return
        self._open_session = None
        now = self._monotonic()
        if exc is not None:
            label, error_class, error_errno = _classify_error(exc)
            session.reason = label
            session.error_class = error_class
            session.error_errno = error_errno
        reason = session.reason or ("stopped" if phase == "stopped" else "unknown")
        duration_ms = _elapsed_ms(session.started, now)
        connect_ms = (
            _elapsed_ms(session.started, session.connected_at)
            if session.connected_at is not None
            else None
        )
        base = session.connected_at or session.started
        first_bytes_ms = (
            _elapsed_ms(base, session.first_bytes_at)
            if session.first_bytes_at is not None
            else None
        )
        first_frame_ms = (
            _elapsed_ms(base, session.first_frame_at)
            if session.first_frame_at is not None
            else None
        )
        parser = session.parser
        self._last_session_forensics = _SessionForensics(
            client_number=self._client_number,
            session_number=session.number,
            phase=phase,
            reason=reason,
            error_class=session.error_class,
            error_errno=session.error_errno,
            duration_ms=duration_ms,
            connect_ms=connect_ms,
            bytes_received=session.bytes_received,
            chunks_received=session.chunks_received,
            frames_received=session.frames,
            non_empty_frames=session.non_empty_frames,
            parser_discarded_bytes=(
                parser.discarded_byte_count if parser is not None else 0
            ),
            parser_invalid_candidates=(
                parser.invalid_candidate_count if parser is not None else 0
            ),
            banner_seen=session.banner_seen,
            first_bytes_ms=first_bytes_ms,
            first_frame_ms=first_frame_ms,
        )
        _LOGGER.debug(
            "client #%d session #%d: session end (phase=%s, reason=%s,"
            " error=%s, errno=%s, duration=%d ms, connect=%s, bytes=%d,"
            " chunks=%d, frames=%d, non_empty=%d, discarded=%d,"
            " invalid_candidates=%d, banner=%s, first_bytes=%s,"
            " first_frame=%s)",
            self._client_number,
            session.number,
            phase,
            reason,
            session.error_class,
            session.error_errno,
            duration_ms,
            _fmt_ms(connect_ms),
            session.bytes_received,
            session.chunks_received,
            session.frames,
            session.non_empty_frames,
            self._last_session_forensics.parser_discarded_bytes,
            self._last_session_forensics.parser_invalid_candidates,
            session.banner_seen,
            _fmt_ms(first_bytes_ms),
            _fmt_ms(first_frame_ms),
        )
        if session.frames == 0 and phase != "stopped":
            self._sessions_without_frame += 1
            if self._warned_classification != reason:
                self._warned_classification = reason
                _LOGGER.warning(
                    "client #%d session #%d: transport session ended without"
                    " a valid frame (phase=%s, reason=%s, error=%s, errno=%s,"
                    " duration=%d ms, bytes=%d)",
                    self._client_number,
                    session.number,
                    phase,
                    reason,
                    session.error_class,
                    session.error_errno,
                    duration_ms,
                    session.bytes_received,
                )

    # --- callback dispatch ----------------------------------------------------

    async def _set_state(
        self, state: ConnectionState, error: str | None = None
    ) -> None:
        """Record a state transition and publish it; no-op if unchanged.

        The transition log carries the state value only: the event's
        ``error`` text may embed OS-generated detail and is never logged.
        """
        if state is self._state:
            return
        self._state = state
        _LOGGER.debug(
            "client #%d: connection state -> %s",
            self._client_number,
            state.value,
        )
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
