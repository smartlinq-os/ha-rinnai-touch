"""Shared test configuration.

Every test in this repository is offline: no network access, no Home
Assistant instance, and no connection to any Rinnai or Brivis hardware.

This conftest makes the repository root importable so that
``custom_components.rinnai_touch`` resolves as a namespace package during
tests, and hosts the shared offline test doubles: the fake clocks and the
socket-free fake client (used by test_coordinator.py and test_entities.py),
the loopback-socket opt-in fixture, and the minimal :class:`LoopbackServer`
helper for the modules that run in-process 127.0.0.1 servers. There is
deliberately no ``tests/__init__.py``: pytest discovers these tests by
path, and keeping ``tests`` out of the import namespace avoids shadowing
anything.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# custom_components resolves only after the sys.path insert above, so this
# import cannot sit in the top import block. The client layer is pure
# Python (no Home Assistant), so importing it never needs the ha-test group.
from custom_components.rinnai_touch.client import RinnaiTcpClient  # noqa: E402


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


class FakeMonotonic:
    """Injected monotonic clock under full test control."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeWallClock:
    """Injected UTC wall clock, fully independent of the monotonic clock."""

    def __init__(self) -> None:
        self.now = datetime(2026, 7, 4, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class FakeRinnaiClient(RinnaiTcpClient):
    """Client double: records lifecycle calls, never touches a socket.

    Construction of the real client is side-effect-free, so the real
    constructor is reused; only the lifecycle entry points are replaced.
    Tests drive the coordinator through its handler methods, exactly as
    the real client's dispatcher would (synchronous, event-loop context).
    """

    def __init__(self, host: str, port: int, **kwargs: Any) -> None:
        super().__init__(host, port, **kwargs)
        self.start_calls = 0
        self.stop_calls = 0

    async def start(self) -> None:
        self.start_calls += 1

    async def stop(self) -> None:
        self.stop_calls += 1


class LoopbackServer:
    """Minimal in-process 127.0.0.1 TCP server for loopback-only tests.

    Deliberately dumb — no protocol parser, no command API, no fake-device
    state model. It binds only the literal IPv4 loopback address, counts
    accepted connections, records every inbound byte (so passive behaviour
    can be asserted), can push raw bytes to the most recent connection
    like a module's unsolicited status stream, and closes deterministically.
    """

    def __init__(self) -> None:
        self._server: asyncio.Server | None = None
        self._writers: list[asyncio.StreamWriter] = []
        self._accepted = asyncio.Event()
        self.connection_count = 0
        self.open_connections = 0
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
        self._writers.append(writer)
        self._accepted.set()
        try:
            while chunk := await reader.read(1024):
                self.received.extend(chunk)
        except OSError:
            pass
        finally:
            self.open_connections -= 1
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()

    async def wait_for_connection(
        self, count: int = 1, timeout: float = 5.0
    ) -> None:
        async with asyncio.timeout(timeout):
            while self.connection_count < count:
                self._accepted.clear()
                await self._accepted.wait()

    async def send(self, data: bytes) -> None:
        """Push raw bytes to the most recent connection, unsolicited."""
        assert self._writers, "no connection accepted yet"
        writer = self._writers[-1]
        writer.write(data)
        await writer.drain()

    async def drop_current(self) -> None:
        """Deterministically close the most recent connection."""
        assert self._writers, "no connection accepted yet"
        writer = self._writers[-1]
        writer.close()
        with suppress(OSError):
            await writer.wait_closed()

    async def wait_all_closed(self, timeout: float = 5.0) -> None:
        async with asyncio.timeout(timeout):
            while self.open_connections:
                await asyncio.sleep(0.001)

    async def stop(self) -> None:
        """Close every connection and the listener; safe to call twice."""
        for writer in self._writers:
            writer.close()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None


@pytest.fixture
async def loopback_server() -> AsyncIterator[LoopbackServer]:
    """One started LoopbackServer on an ephemeral 127.0.0.1 port."""
    server = LoopbackServer()
    await server.start()
    yield server
    await server.stop()
