"""Offline tests for the rolling TCP frame parser.

All payloads are synthetic and fictional: no captures, addresses,
credentials, identifiers, or home-specific data. Tests run with no network
access and never import Home Assistant.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from custom_components.rinnai_touch.protocol import (
    MAX_BUFFER_BYTES,
    ParsedFrame,
    RinnaiFrameParser,
)

# --- synthetic frame construction helpers ----------------------------------

SYST_GROUP: dict[str, object] = {"SYST": {"CFG": {"MTSP": "N", "TU": "C"}}}
HGOM_GROUP: dict[str, object] = {"HGOM": {"ZAS": {"MT": "215"}}}
UNICODE_GROUP: dict[str, object] = {"SYST": {"CFG": {"ZA": "Zöne Ä"}}}


def encode_payload(payload: list[dict[str, object]]) -> str:
    """Serialise a payload compactly, keeping non-ASCII characters raw."""
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def encode_frame(sequence: int, payload: list[dict[str, object]]) -> bytes:
    """Build one wire frame: N + six-digit sequence + JSON array."""
    return f"N{sequence:06d}{encode_payload(payload)}".encode()


def feed_all(parser: RinnaiFrameParser, *chunks: bytes) -> list[ParsedFrame]:
    """Feed chunks in order and collect every frame produced."""
    frames: list[ParsedFrame] = []
    for chunk in chunks:
        frames.extend(parser.feed(chunk))
    return frames


@pytest.fixture
def parser() -> RinnaiFrameParser:
    return RinnaiFrameParser()


# --- 1-2: complete frames and chunk splits ---------------------------------


def test_one_complete_frame(parser: RinnaiFrameParser) -> None:
    frame_bytes = encode_frame(123, [SYST_GROUP])
    frames = parser.feed(frame_bytes)
    assert len(frames) == 1
    frame = frames[0]
    assert frame.sequence == 123
    assert frame.payload == [SYST_GROUP]
    assert frame.raw_frame == frame_bytes.decode()
    assert frame.raw_payload == encode_payload([SYST_GROUP])
    assert parser.buffered_byte_count == 0


def test_frame_split_across_two_chunks(parser: RinnaiFrameParser) -> None:
    frame_bytes = encode_frame(7, [SYST_GROUP])
    middle = len(frame_bytes) // 2
    assert parser.feed(frame_bytes[:middle]) == []
    frames = parser.feed(frame_bytes[middle:])
    assert [frame.sequence for frame in frames] == [7]


# --- 3-5: splits inside header, string, and multibyte character ------------


def test_split_inside_sequence_header(parser: RinnaiFrameParser) -> None:
    frame_bytes = encode_frame(42, [SYST_GROUP])
    assert parser.feed(frame_bytes[:3]) == []  # b"N00" — mid-sequence
    assert parser.buffered_byte_count == 3
    frames = parser.feed(frame_bytes[3:])
    assert [frame.sequence for frame in frames] == [42]


def test_split_inside_json_string(parser: RinnaiFrameParser) -> None:
    frame_bytes = encode_frame(9, [SYST_GROUP])
    split = frame_bytes.index(b"SYST") + 2  # between SY and ST, in-string
    assert parser.feed(frame_bytes[:split]) == []
    frames = parser.feed(frame_bytes[split:])
    assert [frame.payload for frame in frames] == [[SYST_GROUP]]


def test_split_inside_multibyte_utf8_character(parser: RinnaiFrameParser) -> None:
    frame_bytes = encode_frame(11, [UNICODE_GROUP])
    first_multibyte = next(i for i, b in enumerate(frame_bytes) if b >= 0x80)
    split = first_multibyte + 1  # between the bytes of one UTF-8 character
    assert parser.feed(frame_bytes[:split]) == []
    frames = parser.feed(frame_bytes[split:])
    assert frames[0].payload == [UNICODE_GROUP]
    assert "Zöne Ä" in frames[0].raw_frame


def test_split_immediately_after_escape_backslash(
    parser: RinnaiFrameParser,
) -> None:
    payload: list[dict[str, object]] = [{"SYST": {"CFG": {"ZA": 'Zone "A"'}}}]
    frame_bytes = encode_frame(31, payload)
    split = frame_bytes.index(b"\\") + 1  # chunk 1 ends with the backslash
    assert parser.feed(frame_bytes[:split]) == []
    frames = parser.feed(frame_bytes[split:])
    assert len(frames) == 1
    assert frames[0].payload == payload


# --- 6-7: concatenation and trailing partials ------------------------------


def test_multiple_frames_in_one_chunk_all_preserved_in_order(
    parser: RinnaiFrameParser,
) -> None:
    # The upstream reference keeps only the last frame of a read; this
    # parser must return every frame, oldest first.
    chunk = encode_frame(1, [SYST_GROUP]) + encode_frame(2, [HGOM_GROUP])
    frames = parser.feed(chunk)
    assert [frame.sequence for frame in frames] == [1, 2]
    assert [frame.payload for frame in frames] == [[SYST_GROUP], [HGOM_GROUP]]


def test_full_frame_plus_partial_second_frame(parser: RinnaiFrameParser) -> None:
    second = encode_frame(6, [HGOM_GROUP])
    chunk = encode_frame(5, [SYST_GROUP]) + second[:10]
    frames = parser.feed(chunk)
    assert [frame.sequence for frame in frames] == [5]
    assert parser.buffered_byte_count == 10
    frames = parser.feed(second[10:])
    assert [frame.sequence for frame in frames] == [6]


# --- 8-9: garbage tolerance -------------------------------------------------


def test_garbage_before_valid_frame(parser: RinnaiFrameParser) -> None:
    garbage = b"\x00\xff@@ ...line noise... @@"
    frames = parser.feed(garbage + encode_frame(3, [SYST_GROUP]))
    assert [frame.sequence for frame in frames] == [3]
    assert parser.discarded_byte_count == len(garbage)


def test_garbage_between_valid_frames(parser: RinnaiFrameParser) -> None:
    garbage = b"##static##"  # no capital N, so it is pure garbage
    chunk = (
        encode_frame(1, [SYST_GROUP]) + garbage + encode_frame(2, [HGOM_GROUP])
    )
    frames = parser.feed(chunk)
    assert [frame.sequence for frame in frames] == [1, 2]
    assert parser.discarded_byte_count == len(garbage)


# --- 10-13: sequence zero, repeats, payload shapes --------------------------


def test_sequence_zero_is_accepted(parser: RinnaiFrameParser) -> None:
    frames = parser.feed(encode_frame(0, [SYST_GROUP]))
    assert [frame.sequence for frame in frames] == [0]


def test_repeated_identical_frames_are_both_returned(
    parser: RinnaiFrameParser,
) -> None:
    frame_bytes = encode_frame(8, [SYST_GROUP])
    frames = parser.feed(frame_bytes + frame_bytes)
    assert len(frames) == 2
    assert frames[0] == frames[1]  # deduplication belongs to a later layer


def test_single_top_level_status_object(parser: RinnaiFrameParser) -> None:
    frames = parser.feed(encode_frame(20, [SYST_GROUP]))
    assert frames[0].payload == [SYST_GROUP]


def test_multiple_top_level_status_objects(parser: RinnaiFrameParser) -> None:
    frames = parser.feed(encode_frame(21, [SYST_GROUP, HGOM_GROUP]))
    assert frames[0].payload == [SYST_GROUP, HGOM_GROUP]


# --- 14-18: malformed candidates and recovery -------------------------------


def test_invalid_json_then_valid_frame(parser: RinnaiFrameParser) -> None:
    bad = b'N000001[{"SYST":}]'  # balanced brackets, invalid JSON
    frames = parser.feed(bad + encode_frame(2, [SYST_GROUP]))
    assert [frame.sequence for frame in frames] == [2]
    assert parser.invalid_candidate_count >= 1


def test_valid_json_that_is_not_an_array_is_rejected(
    parser: RinnaiFrameParser,
) -> None:
    not_an_array = b'N000001{"SYST":{"CFG":{}}}'
    frames = parser.feed(not_an_array + encode_frame(2, [HGOM_GROUP]))
    assert [frame.sequence for frame in frames] == [2]
    assert parser.invalid_candidate_count >= 1


def test_array_with_non_object_item_is_rejected(
    parser: RinnaiFrameParser,
) -> None:
    bad = b"N000001[1,2]"
    frames = parser.feed(bad + encode_frame(2, [SYST_GROUP]))
    assert [frame.sequence for frame in frames] == [2]
    assert parser.invalid_candidate_count >= 1


def test_object_with_two_top_level_groups_is_rejected(
    parser: RinnaiFrameParser,
) -> None:
    bad = b'N000001[{"SYST":{},"HGOM":{}}]'
    frames = parser.feed(bad + encode_frame(2, [SYST_GROUP]))
    assert [frame.sequence for frame in frames] == [2]
    assert parser.invalid_candidate_count >= 1


def test_non_digit_sequence_then_valid_frame(parser: RinnaiFrameParser) -> None:
    bad = b"N00A123[]"
    frames = parser.feed(bad + encode_frame(4, [SYST_GROUP]))
    assert [frame.sequence for frame in frames] == [4]
    assert parser.invalid_candidate_count >= 1


def test_mismatched_bracket_does_not_swallow_next_frame(
    parser: RinnaiFrameParser,
) -> None:
    # A structurally impossible closer must fail the candidate immediately
    # instead of absorbing the valid frame that follows it.
    bad = b'N000001[{"SYST":]'
    frames = parser.feed(bad + encode_frame(2, [HGOM_GROUP]))
    assert [frame.sequence for frame in frames] == [2]
    assert parser.invalid_candidate_count >= 1


def test_empty_array_payload_is_accepted(parser: RinnaiFrameParser) -> None:
    # An empty status array satisfies the documented shape rules vacuously.
    frames = parser.feed(b"N000030[]")
    assert frames[0].payload == []


# --- incomplete-candidate resynchronisation ----------------------------------


def test_unterminated_string_then_valid_frame_resynchronises(
    parser: RinnaiFrameParser,
) -> None:
    # The unterminated string would otherwise absorb every later byte; the
    # parser must abandon it once an independently valid frame exists,
    # without waiting for buffer-cap overflow.
    bad = b'N000001[{"SYST":{"name":"unterminated'
    assert parser.feed(bad) == []  # alone, it is ordinary incomplete input
    frames = parser.feed(encode_frame(2, [SYST_GROUP]))
    assert [frame.sequence for frame in frames] == [2]
    assert parser.invalid_candidate_count == 1  # the abandoned candidate
    assert parser.discarded_byte_count == len(bad)
    assert parser.buffered_byte_count == 0


def test_unterminated_escaped_string_then_valid_frame_resynchronises(
    parser: RinnaiFrameParser,
) -> None:
    bad = b'N000001[{"SYST":{"name":"trailing\\'  # ends inside an escape
    assert parser.feed(bad) == []
    frames = parser.feed(encode_frame(2, [HGOM_GROUP]))
    assert [frame.sequence for frame in frames] == [2]
    assert parser.invalid_candidate_count >= 1
    assert parser.buffered_byte_count == 0


def test_ordinary_incomplete_frame_is_not_resynchronised_away(
    parser: RinnaiFrameParser,
) -> None:
    # A slow but healthy frame must never be abandoned: with no later valid
    # frame present, retention behaviour is unchanged.
    frame_bytes = encode_frame(12, [SYST_GROUP, HGOM_GROUP])
    for i in range(0, len(frame_bytes) - 1):
        assert parser.feed(frame_bytes[i : i + 1]) == []
        assert parser.invalid_candidate_count == 0
    frames = parser.feed(frame_bytes[-1:])
    assert [frame.sequence for frame in frames] == [12]
    assert parser.invalid_candidate_count == 0
    assert parser.discarded_byte_count == 0


# --- 19: bounded buffer ------------------------------------------------------


def test_buffer_remains_bounded_under_large_garbage_input(
    parser: RinnaiFrameParser,
) -> None:
    # A never-closing candidate forces maximum retention: header + array
    # opener, then filler with no closing bracket and no new prefix.
    parser.feed(b"N000001[")
    filler = b"x" * 8192
    for _ in range(40):  # ~320 KiB, five times the cap
        parser.feed(filler)
        assert parser.buffered_byte_count <= MAX_BUFFER_BYTES
    assert parser.discarded_byte_count > 0
    # The parser still recovers and parses a later valid frame.
    frames = parser.feed(encode_frame(2, [SYST_GROUP]))
    assert [frame.sequence for frame in frames] == [2]


def test_buffer_cap_is_configurable_and_counted() -> None:
    small = RinnaiFrameParser(max_buffer_bytes=32)
    small.feed(b"N000001[" + b"y" * 40)  # 48 bytes of never-closing frame
    assert small.buffered_byte_count == 32
    assert small.discarded_byte_count == 16


def test_constructor_rejects_cap_below_minimal_frame_length() -> None:
    # N000000[] is nine bytes; a smaller cap could never hold a valid frame.
    with pytest.raises(ValueError, match="max_buffer_bytes"):
        RinnaiFrameParser(max_buffer_bytes=8)
    RinnaiFrameParser(max_buffer_bytes=9)  # the minimum is accepted


# --- 20: import hygiene ------------------------------------------------------


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    return imported


def test_parser_imports_no_networking_or_home_assistant_modules() -> None:
    protocol_path = (
        Path(__file__).resolve().parent.parent
        / "custom_components"
        / "rinnai_touch"
        / "protocol.py"
    )
    imported = _top_level_imports(protocol_path)
    assert not imported & {"socket", "aiohttp", "homeassistant"}


# --- additional behaviour locks ---------------------------------------------


def test_empty_feed_is_a_no_op(parser: RinnaiFrameParser) -> None:
    assert parser.feed(b"") == []
    assert parser.buffered_byte_count == 0
    assert parser.discarded_byte_count == 0


def test_counters_track_a_mixed_stream(parser: RinnaiFrameParser) -> None:
    frames = feed_all(
        parser,
        b"noise-",
        encode_frame(1, [SYST_GROUP]),
        b"N00A!!!",
        encode_frame(2, [HGOM_GROUP]),
    )
    assert [frame.sequence for frame in frames] == [1, 2]
    assert parser.frames_parsed_count == 2
    assert parser.invalid_candidate_count == 1  # the N00A!!! candidate
    assert parser.discarded_byte_count == len(b"noise-") + len(b"N00A!!!")
    assert parser.buffered_byte_count == 0
