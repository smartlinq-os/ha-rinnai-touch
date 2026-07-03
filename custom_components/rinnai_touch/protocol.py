"""Rolling TCP frame parser for the Rinnai Touch status stream.

Frame shape (AGENT_SCOPE.md "TCP Transport", docs/protocol_assumptions.md):

    N + six ASCII decimal digits + JSON array

for example ``N000123[{"SYST":{"CFG":{"TU":"C"}}}]``. There is no delimiter
between frames and no guarantee that one TCP read equals one frame, so this
module implements a rolling parser: arbitrary byte chunks go in, every
complete valid frame comes out, in stream order.

Design notes
------------

Framing strategy
    The buffer is scanned as *bytes*. Every structural character the parser
    cares about (``N``, decimal digits, ``[``, ``]``, ``{``, ``}``, ``"`` and
    ``\\``) is single-byte ASCII, and UTF-8 continuation bytes are always
    ``>= 0x80``, so byte-level scanning can never mistake part of a multibyte
    character (for example in a zone name) for frame structure. The end of a
    candidate frame's JSON array is located with a small state machine that
    tracks bracket nesting, string state, and escape state; only then is the
    complete extent decoded as UTF-8 and parsed with :func:`json.loads`.

Incomplete input
    Ending mid-prefix, mid-sequence, mid-string, mid-escape, or mid-UTF-8
    character is ordinary TCP behaviour: the parser retains the bytes from
    the candidate frame start and returns no partial frame. Because decoding
    is deferred until a full extent exists, a chunk boundary inside a
    multibyte character is indistinguishable from any other incomplete frame.

Malformed input and recovery
    A failed candidate (non-digit sequence, payload not starting with ``[``,
    mismatched brackets, invalid UTF-8, invalid JSON, or wrong payload shape)
    never raises. The parser discards exactly one byte (the candidate's
    ``N``) and rescans, so a later valid frame is always found, and bytes
    before the next plausible header are dropped only once proven unusable.
    Mismatched closing brackets are detected structurally, which stops a
    malformed candidate from swallowing the frames that follow it.

Incomplete-candidate resynchronisation
    A corrupt candidate can be structurally *incomplete* forever — for
    example an unterminated JSON string absorbs every later byte, including
    the next valid frame. Whenever the head candidate is incomplete, the
    parser therefore trial-scans the rest of the retained buffer for a later
    candidate that passes full validation (``N`` prefix, six digits,
    complete array extent, valid UTF-8, valid JSON, single-key-object
    members). Only if one exists is the head candidate abandoned: it is
    counted as one invalid candidate, every byte up to the later frame is
    counted as discarded, and parsing resumes at that frame in stream order.
    If no such frame exists the head candidate is retained unchanged, so
    ordinary in-flight frames are never affected. This is a deliberate
    corrupted-stream trade-off: a frame-looking byte sequence inside
    legitimate status text could theoretically trigger a false
    resynchronisation after corruption, but permanent loss of recovery is
    strictly worse. Trial scanning advances monotonically and is bounded by
    the buffer cap, so it cannot loop or grow without bound.

Bounded-buffer policy
    Real status frames observed upstream are on the order of a few hundred
    bytes to a few kilobytes. :data:`MAX_BUFFER_BYTES` (64 KiB) is a
    conservative ceiling far above any plausible local HVAC payload. If
    retained bytes exceed it (a garbage flood, or a "frame" that never
    closes), the oldest bytes are discarded and counted; a genuine frame
    larger than the cap is treated as pathological input by policy.

The parser performs no I/O, keeps no sockets, and must stay independent of
Home Assistant so it can be tested and reused (client.py, probe) unchanged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final, cast

from .const import MESSAGE_PREFIX, SEQUENCE_DIGITS

MAX_BUFFER_BYTES: Final = 65536
"""Default retained-byte ceiling; see the bounded-buffer policy above."""

_PREFIX: Final = MESSAGE_PREFIX.encode("ascii")
_HEADER_LEN: Final = 1 + SEQUENCE_DIGITS
_DIGITS: Final = frozenset(b"0123456789")
_ARRAY_OPEN: Final = ord("[")
_QUOTE: Final = ord('"')
_BACKSLASH: Final = ord("\\")
_OPEN_TO_CLOSE: Final = {ord("["): ord("]"), ord("{"): ord("}")}
_CLOSERS: Final = frozenset((ord("]"), ord("}")))

# _scan_array_end() sentinel results (any value >= 0 is an end offset).
_SCAN_INCOMPLETE: Final = -1
_SCAN_INVALID: Final = -2

# Length of the minimal valid frame, N000000[] — header plus an empty array.
_MIN_FRAME_BYTES: Final = _HEADER_LEN + 2


@dataclass(frozen=True, slots=True)
class ParsedFrame:
    """One complete, validated frame from the module's status stream.

    ``payload`` is the parsed JSON array: a list of single-key objects, one
    per top-level status group. Unknown groups and fields are preserved as
    decoded JSON data, without dropping or interpreting them. ``raw_frame``
    is the decoded frame text including the header, kept for future
    duplicate detection and diagnostics.
    """

    sequence: int
    payload: list[dict[str, Any]]
    raw_frame: str

    @property
    def raw_payload(self) -> str:
        """Frame text without the header (a stable duplicate-detection key)."""
        return self.raw_frame[_HEADER_LEN:]


def _scan_array_end(buf: bytearray, start: int) -> int:
    """Locate the end of the JSON array starting at ``buf[start]``.

    Returns the offset one past the matching closing bracket,
    :data:`_SCAN_INCOMPLETE` if the data ends first, or
    :data:`_SCAN_INVALID` on a structurally impossible bracket mismatch.
    ``buf[start]`` must be ``[``. Operates purely on bytes; see the module
    docstring for why this is safe across UTF-8 chunk boundaries.
    """
    stack: list[int] = []
    in_string = False
    escaped = False
    i = start
    n = len(buf)
    while i < n:
        byte = buf[i]
        if in_string:
            if escaped:
                escaped = False
            elif byte == _BACKSLASH:
                escaped = True
            elif byte == _QUOTE:
                in_string = False
        elif byte == _QUOTE:
            in_string = True
        elif byte in _OPEN_TO_CLOSE:
            stack.append(_OPEN_TO_CLOSE[byte])
        elif byte in _CLOSERS:
            if not stack or byte != stack.pop():
                return _SCAN_INVALID
            if not stack:
                return i + 1
        i += 1
    return _SCAN_INCOMPLETE


def _validate_payload(payload: object) -> list[dict[str, Any]] | None:
    """Return the payload if it is a list of single-key objects, else None."""
    if not isinstance(payload, list):
        return None
    for item in payload:
        if not isinstance(item, dict) or len(item) != 1:
            return None
    return cast("list[dict[str, Any]]", payload)


class RinnaiFrameParser:
    """Rolling frame parser: feed byte chunks, receive complete frames.

    The parser is synchronous, deterministic, and offline. It never raises
    on wire data: incomplete input is retained (unless a later, fully valid
    frame proves the head candidate dead — see the resynchronisation policy
    in the module docstring), malformed input is counted and skipped per the
    recovery rules. Sequence values (including 0) are surfaced as received;
    deduplication and ordering policy belong to the future client/state
    layer.
    """

    def __init__(self, *, max_buffer_bytes: int = MAX_BUFFER_BYTES) -> None:
        if max_buffer_bytes < _MIN_FRAME_BYTES:
            raise ValueError(
                f"max_buffer_bytes must be at least {_MIN_FRAME_BYTES} bytes,"
                " the length of the minimal valid frame 'N000000[]'"
            )
        self._buffer = bytearray()
        self._max_buffer_bytes = max_buffer_bytes
        self._frames_parsed = 0
        self._invalid_candidates = 0
        self._discarded_bytes = 0

    @property
    def buffered_byte_count(self) -> int:
        """Bytes currently retained while waiting for a complete frame."""
        return len(self._buffer)

    @property
    def frames_parsed_count(self) -> int:
        """Total valid frames returned since construction."""
        return self._frames_parsed

    @property
    def invalid_candidate_count(self) -> int:
        """Candidate headers rejected as malformed since construction."""
        return self._invalid_candidates

    @property
    def discarded_byte_count(self) -> int:
        """Bytes dropped as garbage or by the buffer cap since construction."""
        return self._discarded_bytes

    def feed(self, data: bytes) -> list[ParsedFrame]:
        """Consume a chunk and return every frame completed by it, in order.

        Earlier valid frames are always returned alongside later ones found
        in the same chunk; nothing is replaced or dropped because more data
        arrived (unlike the upstream reference, which keeps only the last
        frame in a read).
        """
        self._buffer.extend(data)
        frames = self._extract_frames()
        self._enforce_buffer_cap()
        return frames

    def _extract_frames(self) -> list[ParsedFrame]:
        frames: list[ParsedFrame] = []
        buf = self._buffer
        pos = 0
        while True:
            n = len(buf)
            idx = buf.find(_PREFIX, pos)
            if idx < 0:
                # No possible frame start anywhere: everything is garbage.
                self._discarded_bytes += n - pos
                pos = n
                break
            if idx > pos:
                # Bytes before a prefix can never begin a frame.
                self._discarded_bytes += idx - pos
                pos = idx
            end, frame = self._try_candidate(pos)
            if frame is not None:
                frames.append(frame)
                self._frames_parsed += 1
                pos = end
                continue
            if end == _SCAN_INVALID:
                pos = self._reject_candidate(pos)
                continue
            # Head candidate is incomplete. Abandon it only if a later,
            # independently valid frame already exists in the buffer
            # (resynchronisation policy, module docstring); otherwise this
            # is ordinary in-flight input and is retained from pos.
            resync = self._find_resync_frame(pos + 1)
            if resync is None:
                break
            frame, start, end = resync
            self._invalid_candidates += 1  # the abandoned head candidate
            self._discarded_bytes += start - pos
            frames.append(frame)
            self._frames_parsed += 1
            pos = end
        if pos:
            del buf[:pos]
        return frames

    def _try_candidate(self, pos: int) -> tuple[int, ParsedFrame | None]:
        """Evaluate the candidate whose ``N`` prefix sits at ``pos``.

        Returns ``(end, frame)`` when fully valid, ``(_SCAN_INCOMPLETE,
        None)`` when more bytes could still complete it, or
        ``(_SCAN_INVALID, None)`` when it can never become valid. Has no
        side effects, so it is safe to use for resynchronisation trials.
        """
        buf = self._buffer
        n = len(buf)
        sequence_bytes = buf[pos + 1 : pos + 1 + SEQUENCE_DIGITS]
        if any(byte not in _DIGITS for byte in sequence_bytes):
            return _SCAN_INVALID, None
        if len(sequence_bytes) < SEQUENCE_DIGITS:
            return _SCAN_INCOMPLETE, None  # header still arriving
        payload_start = pos + _HEADER_LEN
        if payload_start >= n:
            return _SCAN_INCOMPLETE, None  # payload not yet arrived
        if buf[payload_start] != _ARRAY_OPEN:
            # Covers valid JSON that is not an array as well as any other
            # non-array payload byte.
            return _SCAN_INVALID, None
        end = _scan_array_end(buf, payload_start)
        if end < 0:
            return end, None  # _SCAN_INCOMPLETE or _SCAN_INVALID
        frame = self._decode_frame(bytes(buf[pos:end]))
        if frame is None:
            return _SCAN_INVALID, None
        return end, frame

    def _find_resync_frame(
        self, search_start: int
    ) -> tuple[ParsedFrame, int, int] | None:
        """Find the first fully valid frame at or after ``search_start``.

        Used only when the head candidate is incomplete. Trial candidates
        that fail are skipped without touching any counter: if a valid frame
        is found, the whole abandoned span is accounted for by the caller as
        one invalid candidate plus its discarded bytes; if none is found,
        the buffer must remain exactly as it was. Search positions strictly
        increase, so the scan terminates within the (capped) buffer.
        """
        buf = self._buffer
        search = search_start
        while True:
            idx = buf.find(_PREFIX, search)
            if idx < 0:
                return None
            end, frame = self._try_candidate(idx)
            if frame is not None:
                return frame, idx, end
            search = idx + 1

    def _reject_candidate(self, pos: int) -> int:
        """Count a failed candidate and discard exactly its prefix byte."""
        self._invalid_candidates += 1
        self._discarded_bytes += 1
        return pos + 1

    def _decode_frame(self, frame: bytes) -> ParsedFrame | None:
        """Decode and validate one complete candidate extent."""
        try:
            text = frame.decode("utf-8")
        except UnicodeDecodeError:
            return None
        try:
            payload = json.loads(text[_HEADER_LEN:])
        except json.JSONDecodeError:
            return None
        validated = _validate_payload(payload)
        if validated is None:
            return None
        return ParsedFrame(
            sequence=int(text[1:_HEADER_LEN]),
            payload=validated,
            raw_frame=text,
        )

    def _enforce_buffer_cap(self) -> None:
        overflow = len(self._buffer) - self._max_buffer_bytes
        if overflow > 0:
            del self._buffer[:overflow]
            self._discarded_bytes += overflow
