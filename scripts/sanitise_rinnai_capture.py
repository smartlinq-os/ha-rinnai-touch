"""Local-only sanitiser: private Rinnai capture -> synthetic fixtures.

Reads a private raw capture (never committed, never printed), parses it
with the project frame parser, and generates small, fully synthetic,
human-reviewable fixtures under a chosen fixture directory. Only protocol
*structure* survives: envelope shape, top-level group names, nested field
keys, value types, and an explicit fail-closed allow-list of protocol
symbols (Y/N flags plus a small set of documented letters approved
per full nesting path, and the 999 no-reading sentinel). Every other
value — names, numbers, times, sequences — is replaced with
deterministic synthetic values. Any symbol or shape outside the
allow-list raises an error and produces no fixture output; the
allow-list is never broadened based on source values, and a symbol
permitted at one path is not thereby permitted at another.

Safety rules enforced here:

- No network I/O of any kind; this is pure local file processing.
- Never prints raw frames, payloads, zone names, host data, sequence
  values, or any absolute path (input, verify, fixture, or report).
  Stdout carries counts, check results, and repository-relative fixture
  paths (filename-only when the fixture directory is outside the repo).
  Failure messages name key paths (protocol vocabulary), never values.
- Refuses to write fixtures beneath ``reference_data/raw/`` (private raw
  captures and committed fixtures must never share a directory).
- The redaction report is written *outside* the repository and contains
  only counts and check results — no source values, paths, hashes, or
  excerpts. The input paths appear in the report as placeholders.
- An optional second capture can be supplied purely to verify structural
  consistency; its content is never used for fixture generation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

_REPO_ROOT: Final = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from custom_components.rinnai_touch.protocol import (  # noqa: E402
    ParsedFrame,
    RinnaiFrameParser,
)

_READ_CHUNK_BYTES: Final = 4096

# Committed fixture names (must satisfy the fixture audit tests: no "/",
# no "capture_", no timestamps).
FIXTURE_STREAM_NAME: Final = "synthetic_multizone_status_stream.bin"
FIXTURE_METADATA_NAME: Final = "synthetic_multizone_status.json"

# Synthetic leading fragment: looks like the tail of an earlier frame but
# is invented here. It must contain no "N" so the parser discards it as
# plain garbage without even an invalid-candidate.
SYNTHETIC_LEADING_FRAGMENT: Final = b'"TU":"C"}}]'

# Synthetic sequences for the emitted frames (deliberately unremarkable).
SYNTHETIC_SEQUENCES: Final = (101, 102)

_KEY_PATTERN: Final = re.compile(r"^[A-Z0-9]{1,6}$")
_NUMERIC_PATTERN: Final = re.compile(r"^-?\d+$")
_TIME_PATTERN: Final = re.compile(r"^\d{1,2}:\d{2}$")
_DAY_NAMES: Final = frozenset({"SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"})
_SHORT_CODE_PATTERN: Final = re.compile(r"^[A-Z]{1,3}\d{0,2}$")
_ZONE_KEY_PATTERN: Final = re.compile(r"^Z([A-DU])(IS|S|O)?$")

_SYNTHETIC_ZONE_NAMES: Final = {
    "A": "Synthetic Zone A",
    "B": "Synthetic Zone B",
    "C": "Synthetic Zone C",
    "D": "Synthetic Zone D",
}
_SYNTHETIC_MT: Final = {"U": "221", "A": "216", "B": "224", "C": "219", "D": "229"}
_SYNTHETIC_SP: Final = {"U": "20", "A": "21", "B": "22", "C": "23", "D": "24"}
_MT_SENTINEL: Final = "999"

# Fail-closed protocol-symbol allow-list. Y/N flags are accepted for any
# field; every other symbol is approved per FULL nesting path, because a
# leaf key can carry different semantics at different locations (for
# example SYST.OSS.ST controller state versus HGOM.OOP.ST power state).
# A value permitted at one path is never thereby permitted at another.
# Sets contain only letters documented in docs/protocol_assumptions.md or
# strictly required by the current synthetic fixture; the list is never
# broadened from source data.
_GLOBAL_SYMBOLS: Final = frozenset({"Y", "N"})


def _zone_paths(
    template: str, symbols: frozenset[str]
) -> dict[str, frozenset[str]]:
    """Expand one per-zone path template across the five zone letters."""
    return {template.format(letter): symbols for letter in "UABCD"}


_PATH_SYMBOLS: Final[dict[str, frozenset[str]]] = {
    # Documented SYST paths.
    "SYST.OSS.MD": frozenset({"H", "C", "E", "R", "N"}),  # operating modes
    "SYST.OSS.ST": frozenset({"N", "C", "P", "U"}),  # controller states only
    "SYST.CFG.TU": frozenset({"C", "F"}),  # temperature units
    "SYST.FLT.GP": frozenset({"H", "C", "E", "R", "N"}),  # fault appliance
    "SYST.FLT.TP": frozenset({"M", "B", "L"}),  # fault severity
    # HGOM paths present in the current fixture.
    "HGOM.OOP.ST": frozenset({"N", "F", "Z"}),  # OOP power/fan states only
    "HGOM.OOP.DT": frozenset({"E"}),  # undocumented: fixture symbol only
    "HGOM.CFG.DG": frozenset({"W"}),  # undocumented: fixture symbol only
    **_zone_paths("HGOM.Z{}O.OP", frozenset({"M", "A"})),  # control modes
    **_zone_paths("HGOM.Z{}O.AO", frozenset({"N", "A", "O"})),  # override
    **_zone_paths(
        "HGOM.Z{}S.AT", frozenset({"W", "L", "R", "P", "S"})
    ),  # documented schedule periods, zone-sensed path only
    **_zone_paths("HGOM.Z{}S.AZ", frozenset({"W"})),  # fixture symbol only
}


class SanitisationError(Exception):
    """Raised when a value cannot be safely replaced (never echoes values)."""


@dataclass
class SanitiseStats:
    """Counters for the private report; counts only, never values."""

    keys_audited: int = 0
    protocol_symbols_preserved: int = 0
    strings_replaced: int = 0
    numerics_replaced: int = 0
    generic_numeric_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CaptureStructure:
    """Structure-only view of a parsed capture (protocol vocabulary only)."""

    frame_count: int
    unique_payload_count: int
    unique_sequence_count: int
    invalid_candidates: int
    leading_discarded_bytes: int
    trailing_discarded_bytes: int
    group_names: frozenset[str]
    key_paths: frozenset[str]
    zone_letters: frozenset[str]
    best_payload: list[dict[str, Any]]


def _iter_frames(path: Path) -> tuple[list[ParsedFrame], RinnaiFrameParser]:
    parser = RinnaiFrameParser()
    frames: list[ParsedFrame] = []
    leading_marker: int | None = None
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_READ_CHUNK_BYTES)
            if not chunk:
                break
            frames.extend(parser.feed(chunk))
            if frames and leading_marker is None:
                leading_marker = parser.discarded_byte_count
    return frames, parser


def _collect_key_paths(
    node: Any, prefix: str, paths: set[str], zones: set[str]
) -> None:
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if not isinstance(key, str) or not _KEY_PATTERN.match(key):
            raise SanitisationError(f"unsafe key shape at {prefix or '<root>'}")
        zone_match = _ZONE_KEY_PATTERN.match(key)
        if zone_match:
            zones.add(zone_match.group(1))
        path = f"{prefix}.{key}" if prefix else key
        paths.add(path)
        _collect_key_paths(value, path, paths, zones)


def analyse_capture(path: Path) -> CaptureStructure:
    """Parse a private capture and reduce it to structure and counts."""
    frames, parser = _iter_frames(path)
    if not frames:
        raise SanitisationError("no valid frames found in input")
    unique_payloads: dict[str, ParsedFrame] = {}
    for frame in frames:
        unique_payloads.setdefault(frame.raw_payload, frame)
    leading = 0
    # Discarded bytes before the first frame versus after: parser counters
    # are cumulative, so re-derive by replaying the first feed boundary.
    # (A single leading fragment is the observed real-world case.)
    replay = RinnaiFrameParser()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_READ_CHUNK_BYTES)
            if not chunk:
                break
            if replay.feed(chunk):
                leading = replay.discarded_byte_count
                break
    key_paths: set[str] = set()
    zones: set[str] = set()
    groups: set[str] = set()
    for frame in unique_payloads.values():
        for item in frame.payload:
            for group_name, group_value in item.items():
                groups.add(group_name)
                _collect_key_paths(
                    group_value, group_name, key_paths, zones
                )
    best = max(
        unique_payloads.values(),
        key=lambda f: (len(f.payload), len(f.raw_payload)),
    )
    return CaptureStructure(
        frame_count=len(frames),
        unique_payload_count=len(unique_payloads),
        unique_sequence_count=len({frame.sequence for frame in frames}),
        invalid_candidates=parser.invalid_candidate_count,
        leading_discarded_bytes=leading,
        trailing_discarded_bytes=parser.discarded_byte_count - leading,
        group_names=frozenset(groups),
        key_paths=frozenset(key_paths),
        zone_letters=frozenset(zones),
        best_payload=best.payload,
    )


def _zone_letter_for(key: str, path: list[str]) -> str | None:
    match = _ZONE_KEY_PATTERN.match(key)
    if match:
        return match.group(1)
    for part in reversed(path):
        match = _ZONE_KEY_PATTERN.match(part)
        if match:
            return match.group(1)
    return None


def _sanitise_value(
    key: str, value: Any, path: list[str], stats: SanitiseStats
) -> Any:
    location = ".".join([*path, key])
    if isinstance(value, dict):
        return _sanitise_mapping(value, [*path, key], stats)
    if isinstance(value, bool) or value is None or isinstance(value, float):
        raise SanitisationError(f"unclassified value type at {location}")
    if isinstance(value, int):
        stats.numerics_replaced += 1
        return 21  # synthetic; integer values are not expected on the wire
    if not isinstance(value, str):
        raise SanitisationError(f"unclassified value type at {location}")
    letter = _zone_letter_for(key, path)
    if len(value) == 1 and value.isalpha() and value.isupper():
        allowed = _GLOBAL_SYMBOLS | _PATH_SYMBOLS.get(location, frozenset())
        if value in allowed:
            stats.protocol_symbols_preserved += 1
            return value
        # Fail closed: a symbol is approved for its exact path or not at
        # all — approval at another path with the same leaf key does not
        # transfer here.
        raise SanitisationError(f"unapproved protocol symbol at {location}")
    if value == "":
        stats.protocol_symbols_preserved += 1
        return value
    if _NUMERIC_PATTERN.match(value):
        stats.numerics_replaced += 1
        if key == "MT":
            if value == _MT_SENTINEL:
                stats.numerics_replaced -= 1
                stats.protocol_symbols_preserved += 1
                return _MT_SENTINEL  # protocol no-reading sentinel
            return _SYNTHETIC_MT.get(letter or "", "225")
        if key == "SP":
            return _SYNTHETIC_SP.get(letter or "", "22")
        if key not in stats.generic_numeric_keys:
            stats.generic_numeric_keys.append(key)
        return str(11 + stats.generic_numeric_keys.index(key))
    if _TIME_PATTERN.match(value):
        stats.strings_replaced += 1
        return "12:34"
    if value in _DAY_NAMES:
        stats.strings_replaced += 1
        return "MON"
    if len(path) >= 1 and path[-1] == "CFG" and _ZONE_KEY_PATTERN.match(key):
        stats.strings_replaced += 1
        return _SYNTHETIC_ZONE_NAMES.get(letter or "", "Synthetic Zone X")
    if _SHORT_CODE_PATTERN.match(value):
        stats.strings_replaced += 1
        return "Z9"
    raise SanitisationError(f"unclassified string shape at {location}")


def _sanitise_mapping(
    mapping: dict[str, Any], path: list[str], stats: SanitiseStats
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in mapping.items():
        if not isinstance(key, str) or not _KEY_PATTERN.match(key):
            raise SanitisationError(
                f"unsafe key shape at {'.'.join(path) or '<root>'}"
            )
        stats.keys_audited += 1
        result[key] = _sanitise_value(key, value, path, stats)
    return result


def sanitise_payload(
    payload: list[dict[str, Any]], stats: SanitiseStats
) -> list[dict[str, Any]]:
    """Replace every non-protocol value in a payload, structure-preserving."""
    synthetic: list[dict[str, Any]] = []
    for item in payload:
        synthetic_item: dict[str, Any] = {}
        for group_name, group_value in item.items():
            if not _KEY_PATTERN.match(group_name):
                raise SanitisationError("unsafe top-level group name shape")
            stats.keys_audited += 1
            if not isinstance(group_value, dict):
                raise SanitisationError(
                    f"unclassified group value type at {group_name}"
                )
            synthetic_item[group_name] = _sanitise_mapping(
                group_value, [group_name], stats
            )
        synthetic.append(synthetic_item)
    return synthetic


def _encode_frame(sequence: int, payload: list[dict[str, Any]]) -> bytes:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return f"N{sequence:06d}{body}".encode()


def build_fixture_files(
    synthetic_payload: list[dict[str, Any]], structure: CaptureStructure
) -> tuple[bytes, dict[str, Any]]:
    """Build the wire-stream fixture bytes and the metadata document."""
    frames = [
        _encode_frame(sequence, synthetic_payload)
        for sequence in SYNTHETIC_SEQUENCES
    ]
    stream = SYNTHETIC_LEADING_FRAGMENT + b"".join(frames)
    zones_meta: dict[str, Any] = {}
    for letter in sorted(structure.zone_letters):
        zones_meta[letter] = {
            "installed_expected": _installed_for_meta(
                synthetic_payload, letter
            ),
            "synthetic_measured_temperature": _synthetic_mt_for_meta(
                synthetic_payload, letter
            ),
        }
    metadata: dict[str, Any] = {
        "synthetic": True,
        "description": (
            "Fully synthetic multi-zone heat-cool status stream. Structure "
            "derived from private local passive observations; every value "
            "was replaced with synthetic data by "
            "scripts.sanitise_rinnai_capture. Safe to commit."
        ),
        "stream_fixture": FIXTURE_STREAM_NAME,
        "leading_fragment_byte_count": len(SYNTHETIC_LEADING_FRAGMENT),
        "frame_count": len(frames),
        "sequences": list(SYNTHETIC_SEQUENCES),
        "repeated_payload": True,
        "top_level_groups": sorted(structure.group_names),
        "zone_letters": sorted(structure.zone_letters),
        "zones": zones_meta,
    }
    return stream, metadata


def _installed_for_meta(payload: list[dict[str, Any]], letter: str) -> bool:
    """Installed means an explicit Z?IS == "Y" (a preserved protocol flag)."""
    for item in payload:
        for group_value in item.values():
            if isinstance(group_value, dict):
                cfg = group_value.get("CFG")
                if isinstance(cfg, dict) and cfg.get(f"Z{letter}IS") == "Y":
                    return True
    return False


def _synthetic_mt_for_meta(
    payload: list[dict[str, Any]], letter: str
) -> float | None:
    for item in payload:
        for group_value in item.values():
            sensed = group_value.get(f"Z{letter}S")
            if isinstance(sensed, dict):
                raw = sensed.get("MT")
                if isinstance(raw, str) and raw != _MT_SENTINEL:
                    return int(raw) / 10.0
    return None


def _display_path(path: Path) -> str:
    """Repo-relative display path, or filename-only outside the repo.

    Guarantees no absolute path (input, verify, fixture, or report) is
    ever echoed to stdout.
    """
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(_REPO_ROOT))
    except ValueError:
        return resolved.name


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sanitise_rinnai_capture",
        description=(
            "Generate small synthetic committed fixtures from a private "
            "local capture. Local file processing only; prints counts and "
            "checks, never values."
        ),
    )
    parser.add_argument("--input", type=Path, required=True,
                        help="Private raw capture file (kept private).")
    parser.add_argument("--verify-against", type=Path, default=None,
                        help="Second private capture for a structural "
                        "consistency check only.")
    parser.add_argument("--fixture-dir", type=Path, required=True,
                        help="Directory for the synthetic fixtures "
                        "(refused under reference_data/raw).")
    parser.add_argument("--report-dir", type=Path, required=True,
                        help="Directory for the private redaction report; "
                        "must be OUTSIDE this repository.")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_argument_parser().parse_args(argv)
    except SystemExit as err:
        return 0 if err.code in (0, None) else 1

    fixture_dir: Path = args.fixture_dir
    raw_dir = (_REPO_ROOT / "reference_data" / "raw").resolve()
    if fixture_dir.resolve().is_relative_to(raw_dir):
        print("Refusing: fixtures must not be written under "
              "reference_data/raw (that directory is for private captures).")
        return 1
    report_dir: Path = args.report_dir
    if report_dir.resolve().is_relative_to(_REPO_ROOT):
        print("Refusing: the private report must be written outside this "
              "repository.")
        return 1
    if not args.input.is_file():
        print("Refusing: input capture not found.")
        return 1

    try:
        structure = analyse_capture(args.input)
    except SanitisationError as err:
        print(f"Cannot sanitise input: {err}")
        return 2

    verify_result = "not_requested"
    verify_counts: dict[str, int] = {}
    if args.verify_against is not None:
        if not args.verify_against.is_file():
            print("Refusing: verify capture not found.")
            return 1
        try:
            other = analyse_capture(args.verify_against)
        except SanitisationError as err:
            print(f"Cannot analyse verify capture: {err}")
            return 2
        consistent = (
            other.group_names == structure.group_names
            and other.key_paths == structure.key_paths
            and other.zone_letters == structure.zone_letters
        )
        verify_result = "passed" if consistent else "FAILED"
        verify_counts = {
            "verify_frames_parsed": other.frame_count,
            "verify_unique_payloads": other.unique_payload_count,
            "verify_unique_sequences": other.unique_sequence_count,
            "verify_invalid_candidates": other.invalid_candidates,
        }
        if not consistent:
            print("Structural consistency check FAILED between the two "
                  "captures; no fixtures written.")
            return 3

    stats = SanitiseStats()
    try:
        synthetic_payload = sanitise_payload(structure.best_payload, stats)
    except SanitisationError as err:
        print(f"Cannot sanitise input: {err}")
        return 2

    stream, metadata = build_fixture_files(synthetic_payload, structure)

    fixture_dir.mkdir(parents=True, exist_ok=True)
    (fixture_dir / FIXTURE_STREAM_NAME).write_bytes(stream)
    (fixture_dir / FIXTURE_METADATA_NAME).write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "tool": "sanitise_rinnai_capture",
        "input": "<input>",
        "verify_against": (
            "<verify>" if args.verify_against is not None else None
        ),
        "frames_parsed": structure.frame_count,
        "unique_payloads": structure.unique_payload_count,
        "unique_sequences": structure.unique_sequence_count,
        "invalid_candidates": structure.invalid_candidates,
        "discarded_bytes_before_first_frame": (
            structure.leading_discarded_bytes
        ),
        "discarded_bytes_after_first_frame": (
            structure.trailing_discarded_bytes
        ),
        **verify_counts,
        "checks": {
            "structural_consistency_with_verify_capture": verify_result,
            "interframe_delimiters": (
                "none_observed"
                if structure.trailing_discarded_bytes == 0
                else "bytes_discarded_between_frames"
            ),
            "sequence_stability": (
                "constant"
                if structure.unique_sequence_count == 1
                else "varied"
            ),
            "keys_audited": stats.keys_audited,
            "protocol_symbols_preserved": stats.protocol_symbols_preserved,
            "strings_replaced": stats.strings_replaced,
            "numerics_replaced": stats.numerics_replaced,
            "fixture_values_synthetic": "by_construction",
        },
    }
    (report_dir / "sanitisation_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )

    print("Sanitisation complete (counts only; no values shown):")
    print(f"  input frames parsed: {structure.frame_count}")
    print(f"  unique payloads: {structure.unique_payload_count}")
    print(f"  unique sequences: {structure.unique_sequence_count}")
    print(f"  structural consistency with verify capture: {verify_result}")
    print(
        "  fixtures written: "
        f"{_display_path(fixture_dir / FIXTURE_STREAM_NAME)}"
    )
    print(
        "                    "
        f"{_display_path(fixture_dir / FIXTURE_METADATA_NAME)}"
    )
    print("  private report written outside the repository.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
