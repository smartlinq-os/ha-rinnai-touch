"""Offline tests for the passive capture probe.

Every connection in this file goes to an in-process asyncio fake server on
127.0.0.1 with an ephemeral port. No real hardware, no real addresses, no
internet. Payloads are synthetic and fictional. Output is written only to
pytest-provided temporary directories.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import json
import socket
import sys
from collections.abc import AsyncIterator
from contextlib import suppress
from pathlib import Path

import pytest

from scripts import rinnai_probe as probe

REPO_ROOT = Path(__file__).resolve().parent.parent
PROBE_PATH = REPO_ROOT / "scripts" / "rinnai_probe.py"

SYST_FULL: dict[str, object] = {
    "SYST": {
        "AVM": {"HG": "Y"},
        "OSS": {"MD": "H", "ST": "N"},
        "CFG": {"ZA": "MARKER_DO_NOT_PRINT"},
    }
}
HGOM_GROUP: dict[str, object] = {"HGOM": {"ZAS": {"MT": "223", "AE": "Y"}}}


def encode_frame(sequence: int, payload: list[dict[str, object]]) -> bytes:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return f"N{sequence:06d}{body}".encode()


class FakeModuleServer:
    """Loopback server standing in for a module: sends only, records inbound."""

    def __init__(self) -> None:
        self._server: asyncio.Server | None = None
        self._writers: list[asyncio.StreamWriter] = []
        self._accepted = asyncio.Event()
        self.connection_count = 0
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
        self._writers.append(writer)
        self._accepted.set()
        try:
            while True:
                data = await reader.read(1024)
                if not data:
                    break
                self.received.extend(data)
        except OSError:
            pass
        finally:
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()

    async def wait_for_connection(self, timeout: float = 2.0) -> None:
        async with asyncio.timeout(timeout):
            await self._accepted.wait()

    async def send(self, data: bytes) -> None:
        writer = self._writers[-1]
        writer.write(data)
        await writer.drain()

    async def drop_current(self) -> None:
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


@pytest.fixture
async def server() -> AsyncIterator[FakeModuleServer]:
    fake = FakeModuleServer()
    await fake.start()
    yield fake
    await fake.stop()


def make_config(
    port: int, tmp_path: Path, duration: float = 0.4
) -> probe.ProbeConfig:
    """Build a gated config through the real CLI parsing path."""
    exit_code, config = probe.parse_config(
        [
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--duration",
            str(duration),
            "--allow-short-capture",
            "--confirm-passive-capture",
            "--output-dir",
            str(tmp_path),
        ]
    )
    assert exit_code is None
    assert config is not None
    return config


def capture_dir_of(tmp_path: Path) -> Path:
    entries = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert len(entries) == 1
    return entries[0]


def read_summary(tmp_path: Path) -> dict[str, object]:
    summary_path = capture_dir_of(tmp_path) / "summary.json"
    return json.loads(summary_path.read_text(encoding="utf-8"))


# --- 1: importing performs no connection or socket use -------------------------


def test_import_creates_no_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("socket created during probe import")

    monkeypatch.setattr(socket, "socket", _forbidden)
    for name in [m for m in sys.modules if m.startswith("scripts")]:
        sys.modules.pop(name)
    module = importlib.import_module("scripts.rinnai_probe")
    assert module.MIN_FIRST_CAPTURE_SECONDS == 360.0


# --- 2-6: CLI safety gates -------------------------------------------------------


async def test_missing_confirmation_refuses_before_connecting(
    server: FakeModuleServer, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = probe.main(
        [
            "--host",
            "127.0.0.1",
            "--port",
            str(server.port),
            "--duration",
            "1",
            "--allow-short-capture",
            "--output-dir",
            str(tmp_path),
        ]
    )
    assert exit_code == 1
    assert server.connection_count == 0  # refused before any connection
    assert "--confirm-passive-capture" in capsys.readouterr().out


def test_missing_host_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = probe.main(["--confirm-passive-capture"])
    assert exit_code == 1
    assert "--host" in capsys.readouterr().err


def test_default_duration_is_six_minutes() -> None:
    args = probe.build_parser().parse_args(
        ["--host", "127.0.0.1", "--confirm-passive-capture"]
    )
    assert args.duration == 360.0


def test_short_duration_rejected_without_override(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code, config = probe.parse_config(
        ["--host", "127.0.0.1", "--confirm-passive-capture", "--duration", "5"]
    )
    assert exit_code == 1
    assert config is None
    assert "six minutes" in capsys.readouterr().out


def test_short_duration_accepted_with_override(tmp_path: Path) -> None:
    config = make_config(port=27847, tmp_path=tmp_path, duration=5)
    assert config.duration_seconds == 5.0
    assert config.port == 27847


# --- 7-13: capture behaviour against the loopback fake --------------------------


async def test_capture_writes_raw_bytes_and_summary(
    server: FakeModuleServer, tmp_path: Path
) -> None:
    frame = encode_frame(1, [SYST_FULL])
    config = make_config(server.port, tmp_path)
    task = asyncio.create_task(probe.run_capture(config))
    await server.wait_for_connection()
    await server.send(frame)
    exit_code = await task
    assert exit_code == 0
    capture_dir = capture_dir_of(tmp_path)
    assert (capture_dir / "raw_bytes.bin").read_bytes() == frame
    assert (capture_dir / "capture_notes.txt").exists()
    summary = read_summary(tmp_path)
    assert summary["frame_count"] == 1
    assert summary["sequences"] == [1]
    assert summary["total_bytes"] == len(frame)


async def test_split_frame_is_parsed(
    server: FakeModuleServer, tmp_path: Path
) -> None:
    frame = encode_frame(9, [SYST_FULL, HGOM_GROUP])
    config = make_config(server.port, tmp_path)
    task = asyncio.create_task(probe.run_capture(config))
    await server.wait_for_connection()
    await server.send(frame[:11])
    await asyncio.sleep(0.05)
    await server.send(frame[11:])
    exit_code = await task
    assert exit_code == 0
    summary = read_summary(tmp_path)
    assert summary["frame_count"] == 1
    assert summary["sequences"] == [9]
    assert summary["chunk_count"] == 2


async def test_multiple_frames_recorded_with_sequences(
    server: FakeModuleServer, tmp_path: Path
) -> None:
    config = make_config(server.port, tmp_path)
    task = asyncio.create_task(probe.run_capture(config))
    await server.wait_for_connection()
    await server.send(encode_frame(1, [SYST_FULL]) + encode_frame(2, [HGOM_GROUP]))
    exit_code = await task
    assert exit_code == 0
    summary = read_summary(tmp_path)
    assert summary["frame_count"] == 2
    assert summary["sequences"] == [1, 2]
    overview = summary["model_overview"]
    assert isinstance(overview, dict)
    assert overview["operating_mode"] == "H"


async def test_malformed_bytes_do_not_crash_capture(
    server: FakeModuleServer, tmp_path: Path
) -> None:
    config = make_config(server.port, tmp_path)
    task = asyncio.create_task(probe.run_capture(config))
    await server.wait_for_connection()
    await server.send(b'N000001[{"SYST":}]@@garbage@@')
    await server.send(encode_frame(2, [SYST_FULL]))
    exit_code = await task
    assert exit_code == 0
    summary = read_summary(tmp_path)
    assert summary["frame_count"] == 1
    assert summary["sequences"] == [2]
    invalid = summary["parser_invalid_candidate_count"]
    assert isinstance(invalid, int) and invalid >= 1


async def test_probe_transmits_no_bytes(
    server: FakeModuleServer, tmp_path: Path
) -> None:
    config = make_config(server.port, tmp_path)
    task = asyncio.create_task(probe.run_capture(config))
    await server.wait_for_connection()
    await server.send(encode_frame(1, [SYST_FULL]))
    assert await task == 0
    assert bytes(server.received) == b""  # strictly passive


async def test_eof_is_recorded_cleanly(
    server: FakeModuleServer, tmp_path: Path
) -> None:
    config = make_config(server.port, tmp_path, duration=5)
    task = asyncio.create_task(probe.run_capture(config))
    await server.wait_for_connection()
    await server.send(encode_frame(1, [SYST_FULL]))
    await asyncio.sleep(0.05)
    await server.drop_current()
    exit_code = await task  # returns early, well before the 5s duration
    assert exit_code == 0
    summary = read_summary(tmp_path)
    assert summary["outcome"] == "eof_before_duration"
    assert summary["eof_offset_seconds"] is not None
    assert summary["frame_count"] == 1


# --- 14-15: refusal and output placement -----------------------------------------


async def test_connection_refused_exit_code_and_no_raw_file(
    tmp_path: Path,
) -> None:
    throwaway = FakeModuleServer()
    await throwaway.start()
    refused_port = throwaway.port
    await throwaway.stop()

    config = make_config(refused_port, tmp_path)
    exit_code = await probe.run_capture(config)
    assert exit_code == 2
    capture_dir = capture_dir_of(tmp_path)
    assert not (capture_dir / "raw_bytes.bin").exists()  # no false capture
    summary = read_summary(tmp_path)
    assert summary["outcome"] == "connection_failed"
    assert "sequences" not in summary  # nothing was captured


async def test_outputs_only_under_requested_directory(
    server: FakeModuleServer, tmp_path: Path
) -> None:
    default_dir = REPO_ROOT / "reference_data" / "raw"
    existed_before = default_dir.exists()
    entries_before = set(default_dir.iterdir()) if existed_before else set()

    config = make_config(server.port, tmp_path)
    task = asyncio.create_task(probe.run_capture(config))
    await server.wait_for_connection()
    await server.send(encode_frame(1, [SYST_FULL]))
    assert await task == 0

    capture_dir = capture_dir_of(tmp_path)
    assert capture_dir.parent == tmp_path
    if existed_before:
        assert set(default_dir.iterdir()) == entries_before
    else:
        assert not default_dir.exists()


# --- 16-17: stdout privacy and summary diagnostics --------------------------------


async def test_raw_payload_not_printed_to_stdout(
    server: FakeModuleServer,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = make_config(server.port, tmp_path)
    task = asyncio.create_task(probe.run_capture(config))
    await server.wait_for_connection()
    await server.send(encode_frame(1, [SYST_FULL]))
    assert await task == 0
    output = capsys.readouterr()
    assert "MARKER_DO_NOT_PRINT" not in output.out
    assert "MARKER_DO_NOT_PRINT" not in output.err
    assert "PASSIVE CAPTURE WARNING" in output.out  # warning was shown


async def test_summary_records_diagnostics_and_timing(
    server: FakeModuleServer, tmp_path: Path
) -> None:
    config = make_config(server.port, tmp_path)
    task = asyncio.create_task(probe.run_capture(config))
    await server.wait_for_connection()
    await server.send(encode_frame(1, [SYST_FULL]))
    assert await task == 0
    summary = read_summary(tmp_path)
    for key in (
        "elapsed_seconds",
        "connection_close_offset_seconds",
        "first_data_offset_seconds",
        "parser_invalid_candidate_count",
        "parser_discarded_byte_count",
        "parser_buffered_byte_count_final",
        "chunks",
    ):
        assert key in summary, key
    chunks = summary["chunks"]
    assert isinstance(chunks, list) and len(chunks) == 1
    assert chunks[0]["byte_count"] == len(encode_frame(1, [SYST_FULL]))
    elapsed = summary["elapsed_seconds"]
    assert isinstance(elapsed, float) and elapsed > 0


async def test_external_output_dir_warns_before_connection(
    server: FakeModuleServer,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # pytest tmp_path is outside the repository, so the location warning
    # must appear — and strictly before the connection attempt begins.
    config = make_config(server.port, tmp_path)
    task = asyncio.create_task(probe.run_capture(config))
    await server.wait_for_connection()
    await server.send(encode_frame(1, [SYST_FULL]))
    assert await task == 0
    out = capsys.readouterr().out
    assert "OUTPUT LOCATION WARNING" in out
    assert out.index("OUTPUT LOCATION WARNING") < out.index(
        "Connecting for passive capture"
    )
    assert out.index("Connecting for passive capture") < out.index("Connected.")


async def test_repo_internal_output_dir_does_not_warn(
    server: FakeModuleServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Pure predicate check against the real repository paths (no writes).
    assert probe._output_dir_within_repo(
        REPO_ROOT / "reference_data" / "raw"
    )
    assert not probe._output_dir_within_repo(tmp_path)
    # Full capture with the repo root patched over the temp tree, so an
    # "inside the repository" run needs no writes into the real repo.
    monkeypatch.setattr(probe, "_REPO_ROOT", tmp_path)
    config = make_config(server.port, tmp_path / "captures")
    task = asyncio.create_task(probe.run_capture(config))
    await server.wait_for_connection()
    await server.send(encode_frame(1, [SYST_FULL]))
    assert await task == 0
    assert "OUTPUT LOCATION WARNING" not in capsys.readouterr().out


# --- 18: cancellation finalises output --------------------------------------------


async def test_cancellation_finalises_output(
    server: FakeModuleServer, tmp_path: Path
) -> None:
    config = make_config(server.port, tmp_path, duration=30)
    task = asyncio.create_task(probe.run_capture(config))
    await server.wait_for_connection()
    await server.send(encode_frame(1, [SYST_FULL]))
    await asyncio.sleep(0.05)
    task.cancel()
    exit_code = await task  # the probe converts cancellation to exit code 3
    assert exit_code == 3
    summary = read_summary(tmp_path)
    assert summary["outcome"] == "cancelled"
    assert summary["frame_count"] == 1
    raw = capture_dir_of(tmp_path) / "raw_bytes.bin"
    assert raw.read_bytes() == encode_frame(1, [SYST_FULL])


# --- 19-20: import hygiene and CLI surface -----------------------------------------


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    return imported


def test_probe_imports_no_forbidden_modules() -> None:
    imported = _top_level_imports(PROBE_PATH)
    assert not imported & {"socket", "aiohttp", "homeassistant"}
    # The probe must not pull in the client (and its reconnect machinery),
    # only the pure parser/model/const modules.
    tree = ast.parse(PROBE_PATH.read_text(encoding="utf-8"))
    from_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any("client" in module for module in from_modules)


def test_probe_has_no_outbound_write_call_path() -> None:
    # File writes are permitted only on the raw capture handle; there must
    # be no stream/socket transmit call of any kind.
    tree = ast.parse(PROBE_PATH.read_text(encoding="utf-8"))
    banned = {"writelines", "drain", "send", "sendall", "sendto"}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        name = node.func.attr
        assert name not in banned, name
        if name == "write":
            receiver = node.func.value
            assert isinstance(receiver, ast.Name), ast.dump(node)
            assert receiver.id == "raw_output", receiver.id


def test_cli_exposes_no_control_or_transmit_options() -> None:
    banned = (
        "keepalive",
        "command",
        "send",
        "write",
        "hvac",
        "temperature",
        "mode",
        "fan",
        "pump",
        "schedule",
    )
    for action in probe.build_parser()._actions:
        for option in action.option_strings:
            lowered = option.lower()
            assert not any(word in lowered for word in banned), option
