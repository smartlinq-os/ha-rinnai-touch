"""Tests for the committed synthetic capture fixtures.

The fixtures under tests/fixtures/ are fully synthetic: structure was
derived from private local passive observations, and every value was
replaced by scripts/sanitise_rinnai_capture.py. These tests prove the
fixtures exercise the real-world stream conditions (leading fragment,
splits, concatenation, repeats, multi-zone heat/cool shape) and audit the
fixtures and test sources for private-source remnants.

Nothing here validates or authorises a transport keepalive.
"""

from __future__ import annotations

import asyncio
import json
import re
from contextlib import suppress
from pathlib import Path
from typing import Any

import pytest

from custom_components.rinnai_touch.client import ConnectionState, RinnaiTcpClient
from custom_components.rinnai_touch.models import RinnaiStatusModel
from custom_components.rinnai_touch.protocol import ParsedFrame, RinnaiFrameParser

# In-process 127.0.0.1 servers only; opt-in fixture defined in tests/conftest.py.
pytestmark = pytest.mark.usefixtures("loopback_socket_enabled")

TESTS_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = TESTS_DIR / "fixtures"
STREAM_PATH = FIXTURES_DIR / "synthetic_multizone_status_stream.bin"
METADATA_PATH = FIXTURES_DIR / "synthetic_multizone_status.json"


def load_stream() -> bytes:
    return STREAM_PATH.read_bytes()


def load_metadata() -> dict[str, Any]:
    return json.loads(METADATA_PATH.read_text(encoding="utf-8"))


def parse_all(data: bytes) -> tuple[list[ParsedFrame], RinnaiFrameParser]:
    parser = RinnaiFrameParser()
    return parser.feed(data), parser


# --- fixture parses cleanly with the documented stream conditions -------------


def test_stream_fixture_parses_without_invalid_candidates() -> None:
    metadata = load_metadata()
    frames, parser = parse_all(load_stream())
    assert len(frames) == metadata["frame_count"]
    assert parser.invalid_candidate_count == 0
    assert [frame.sequence for frame in frames] == metadata["sequences"]


def test_leading_fragment_is_discarded_without_blocking() -> None:
    metadata = load_metadata()
    stream = load_stream()
    fragment_length = metadata["leading_fragment_byte_count"]
    parser = RinnaiFrameParser()
    assert parser.feed(stream[:fragment_length]) == []  # fragment only
    frames = parser.feed(stream[fragment_length:])
    assert len(frames) == metadata["frame_count"]
    assert parser.discarded_byte_count == fragment_length
    assert parser.invalid_candidate_count == 0


def test_split_delivery_produces_expected_frames() -> None:
    metadata = load_metadata()
    stream = load_stream()
    parser = RinnaiFrameParser()
    frames: list[ParsedFrame] = []
    for start in range(0, len(stream), 7):  # deliberately awkward chunking
        frames.extend(parser.feed(stream[start : start + 7]))
    assert [frame.sequence for frame in frames] == metadata["sequences"]


def test_concatenated_frames_arrive_in_order() -> None:
    frames, _ = parse_all(load_stream())
    assert [frame.sequence for frame in frames] == [101, 102]


def test_repeated_status_payloads_are_both_parsed() -> None:
    frames, _ = parse_all(load_stream())
    assert len(frames) == 2
    assert frames[0].raw_payload == frames[1].raw_payload  # repeated payload
    assert frames[0].sequence != frames[1].sequence


# --- model observes the multi-zone heat/cool capability shape ------------------


def test_model_observes_multizone_heatcool_shape() -> None:
    metadata = load_metadata()
    frames, _ = parse_all(load_stream())
    model = RinnaiStatusModel()
    snapshot = None
    for frame in frames:
        snapshot = model.apply(frame)
    assert snapshot is not None
    assert snapshot.capabilities.heater_observed is True
    assert snapshot.capabilities.cooler_observed is True
    assert snapshot.capabilities.multi_setpoint_observed is True
    assert snapshot.capabilities.temperature_unit == "C"
    assert snapshot.operating_mode == "H"
    assert snapshot.active_mode_group == "HGOM"
    assert set(snapshot.zones) == set(metadata["zone_letters"])
    for letter, expected in metadata["zones"].items():
        zone = snapshot.zones[letter]
        assert zone.installed_observed is expected["installed_expected"]
        assert zone.current is not None
        assert (
            zone.current.measured_temperature
            == expected["synthetic_measured_temperature"]
        )
    # Main zone (U): observed with current data even though not installed.
    assert snapshot.zones["U"].installed_observed is False
    assert snapshot.zones["U"].current is not None
    assert snapshot.zones["A"].name == "Synthetic Zone A"


def test_sequence_is_not_a_freshness_or_ordering_source() -> None:
    frames, _ = parse_all(load_stream())
    payload_text = frames[0].raw_payload
    model = RinnaiStatusModel()

    def frame_with_sequence(sequence: int) -> ParsedFrame:
        parser = RinnaiFrameParser()
        produced = parser.feed(f"N{sequence:06d}{payload_text}".encode())
        assert len(produced) == 1
        return produced[0]

    first = model.apply(frame_with_sequence(150))
    second = model.apply(frame_with_sequence(120))  # lower, still accepted
    assert first.sequence == 150
    assert second.sequence == 120
    # The later frame wins regardless of its sequence value: raw state and
    # observations are unchanged in content, and nothing was rejected.
    assert dict(second.raw_groups) == dict(first.raw_groups)


async def test_socket_connected_is_distinct_from_fresh_status() -> None:
    # A server that accepts, holds the connection open, and stays silent:
    # the client reports a socket-level connection while no status frame
    # has ever been received.
    async def silent_handler(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            while True:
                data = await reader.read(1024)
                if not data:
                    break
        finally:
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()

    server = await asyncio.start_server(silent_handler, "127.0.0.1", 0)
    port = int(server.sockets[0].getsockname()[1])
    client = RinnaiTcpClient("127.0.0.1", port)
    try:
        await client.start()
        async with asyncio.timeout(2.0):
            while client.state is not ConnectionState.CONNECTED:
                await asyncio.sleep(0.001)
        for _ in range(20):  # the connection must remain quiet and stable
            await asyncio.sleep(0.001)
        assert client.connected is True
        assert client.frames_received == 0  # connected != fresh data
        assert client.last_snapshot is None
    finally:
        await client.stop()
        server.close()
        with suppress(OSError):
            await server.wait_closed()


# --- audits: no private-source remnants anywhere -------------------------------

# Constructed tokens so these audit tests never trip their own scans.
_PRIVATE_LOCATION_TOKENS = (
    "Down" + "loads",
    "private-" + "captures",
    "rinnai-" + "raw",
    "Path." + "home(",
)

_TIMESTAMP_PATTERNS = (
    re.compile(r"\d{4}-\d{2}-\d{2}"),
    re.compile(r"\d{8}_\d{6}"),
    re.compile(r"\d{2}:\d{2}:\d{2}"),
)
_IPV4_PATTERN = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
_IPV6_PATTERN = re.compile(r"\b(?:[0-9A-Fa-f]{1,4}:){2,}[0-9A-Fa-f]{1,4}\b")


def test_no_test_reads_private_capture_locations() -> None:
    for source in sorted(TESTS_DIR.glob("*.py")):
        text = source.read_text(encoding="utf-8")
        for token in _PRIVATE_LOCATION_TOKENS:
            assert token not in text, f"{source.name} references {token!r}"


def test_fixtures_contain_no_private_source_remnants() -> None:
    fixture_files = sorted(FIXTURES_DIR.iterdir())
    assert fixture_files, "fixtures are expected to exist"
    banned_literals = (
        "raw_bytes.bin",
        "capture_",
        "reference_data",
        *_PRIVATE_LOCATION_TOKENS[:3],
        "MARKER_DO_NOT" + "_PRINT",
    )
    for fixture in fixture_files:
        text = fixture.read_bytes().decode("latin-1")
        assert "/" not in text, f"{fixture.name} contains a filesystem path"
        assert not _IPV4_PATTERN.search(text), fixture.name
        assert not _IPV6_PATTERN.search(text), fixture.name
        for pattern in _TIMESTAMP_PATTERNS:
            assert not pattern.search(text), (
                f"{fixture.name} matches {pattern.pattern}"
            )
        for literal in banned_literals:
            assert literal not in text, f"{fixture.name} contains {literal!r}"


def test_metadata_fixture_is_valid_json_and_declares_synthetic() -> None:
    metadata = load_metadata()
    assert metadata["synthetic"] is True
    assert metadata["stream_fixture"] == STREAM_PATH.name
    assert metadata["top_level_groups"] == ["HGOM", "SYST"]
