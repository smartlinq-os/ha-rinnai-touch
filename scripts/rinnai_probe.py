"""Passive Rinnai Touch protocol capture probe (user-run only).

Gathers private local evidence for the validation ledger in
docs/protocol_assumptions.md: status-frame cadence (A1), passive
idle-disconnect timing (A2), framing behaviour (A3), received sequence
behaviour (A4), zone/temperature field shape (A6), and the evidence base
for the future transport-keepalive decision (A11).

Safety model
------------
- This tool never runs automatically: it is not part of the integration
  runtime, and importing this module performs no connection or I/O.
- A TCP connection is attempted only when the user supplies an explicit
  host, the explicit ``--confirm-passive-capture`` acknowledgement flag,
  and a capture duration (default 360 seconds — the minimum recommended
  first capture; shorter runs additionally require
  ``--allow-short-capture`` and are intended for local testing only).
- The probe is strictly passive: it has no outbound protocol write path,
  no keepalive, no command generation, and no transmit toggle of any
  kind. It opens one connection, receives bytes, and closes gracefully.
  The only ``write`` calls in this file target the local raw capture
  file.
- Raw output goes to the git-ignored ``reference_data/raw/`` directory
  (or ``--output-dir``; a directory outside this repository is supported
  for cases like encrypted volumes, but prints an additional warning
  because the repository's Git ignore rules cannot protect it). Raw
  captures may contain private household data and must never be
  committed; the generated notes file carries the redaction checklist to
  follow before anything is turned into a fixture.
- Stdout never shows raw payloads, zone names, fault details, or JSON
  content — only counts, timing, and file locations.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

_REPO_ROOT: Final = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from custom_components.rinnai_touch.const import (  # noqa: E402
    CONNECT_TIMEOUT_SECONDS,
    DEFAULT_TCP_PORT,
)
from custom_components.rinnai_touch.models import (  # noqa: E402
    RinnaiStatusModel,
    StatusSnapshot,
)
from custom_components.rinnai_touch.protocol import RinnaiFrameParser  # noqa: E402

MIN_FIRST_CAPTURE_SECONDS: Final = 360.0
DEFAULT_OUTPUT_DIR: Final = _REPO_ROOT / "reference_data" / "raw"
_READ_CHUNK_BYTES: Final = 4096

_WARNING: Final = """\
============================= PASSIVE CAPTURE WARNING =========================
- The WiFi module may permit only ONE active local TCP client at a time.
- Stop Homebridge and any other local integration BEFORE capturing.
- The local Rinnai/Brivis app may conflict with this capture while it runs.
- This probe is PASSIVE: it transmits no bytes to the module.
- Raw capture output may contain PRIVATE household data.
- Raw files are written to a git-ignored directory and must NEVER be
  committed to Git.
- Abort now (Ctrl+C) if you are not ready to temporarily occupy the local
  module connection.
================================================================================
"""

_OUTSIDE_REPO_WARNING: Final = """\
--------------------------- OUTPUT LOCATION WARNING ---------------------------
- The chosen output directory is OUTSIDE this Git repository.
- The repository's Git ignore rules do NOT apply there.
- Capture files may contain PRIVATE household data.
- Avoid cloud-synced or shared locations unless that is intentional.
- Never commit, upload, or share these files without sanitisation.
--------------------------------------------------------------------------------
"""

_NOTES_TEXT: Final = """\
Rinnai Touch passive capture — PRIVATE raw data
===============================================

This directory contains a raw, unredacted local protocol capture. It may
reveal private household information. Keep it local. Never commit it to
Git: reference_data/raw/ is ignored by design.

Purpose: evidence for the validation ledger in docs/protocol_assumptions.md
(items A1 cadence, A2 idle disconnect, A3 framing, A4 sequences, A6 zone and
temperature field shape, A11 keepalive decision basis).

Redaction checklist — complete EVERY item before moving any part of this
capture into tests/fixtures/ or reference_data/anonymised/:

  [ ] Remove or anonymise IP addresses and hostnames
  [ ] Remove MAC addresses
  [ ] Remove WPA keys and any credentials
  [ ] Remove serial numbers and controller IDs
  [ ] Replace zone/room names with generic names (Zone A, Living, ...)
  [ ] Remove household timestamps where they are not needed
  [ ] Remove occupancy-related information
  [ ] Remove raw payload fragments that could identify the home

See reference_data/README.md for the full sanitisation rules. Update the
ledger status column in docs/protocol_assumptions.md in the same change
that adds any sanitised fixture.
"""


@dataclass(frozen=True, slots=True)
class ProbeConfig:
    """Validated probe settings; construction implies the gates passed."""

    host: str
    port: int
    duration_seconds: float
    output_dir: Path
    verbose_summary: bool


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI. There is deliberately no transmit-related option."""
    parser = argparse.ArgumentParser(
        prog="rinnai_probe",
        description=(
            "Passive Rinnai Touch protocol capture. Receives unsolicited "
            "status bytes from a local module and records them privately. "
            "Transmits nothing."
        ),
    )
    parser.add_argument(
        "--host",
        required=True,
        help="Module host/IP on the local network (never recorded publicly).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_TCP_PORT,
        help=f"Module TCP port (default {DEFAULT_TCP_PORT}).",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=MIN_FIRST_CAPTURE_SECONDS,
        help=(
            "Capture duration in seconds (default and recommended first-"
            f"capture minimum: {MIN_FIRST_CAPTURE_SECONDS:.0f})."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Private output directory (default reference_data/raw, "
        "git-ignored).",
    )
    parser.add_argument(
        "--confirm-passive-capture",
        action="store_true",
        help=(
            "Required acknowledgement that you have read the capture "
            "warnings and accept temporarily occupying the module's single "
            "local TCP connection."
        ),
    )
    parser.add_argument(
        "--allow-short-capture",
        action="store_true",
        help=(
            "Permit a duration below the recommended 360-second minimum. "
            "For controlled local testing/debugging only; the first real-"
            "device capture must remain at least six minutes."
        ),
    )
    parser.add_argument(
        "--verbose-summary",
        action="store_true",
        help="Include per-frame timing and top-level group keys in the "
        "private summary (still no raw values or names).",
    )
    return parser


def parse_config(argv: list[str] | None) -> tuple[int | None, ProbeConfig | None]:
    """Parse and gate CLI arguments; returns (exit_code, None) on refusal."""
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as err:
        return (0 if err.code in (0, None) else 1), None
    if not args.confirm_passive_capture:
        print(
            "Refusing to run: pass --confirm-passive-capture after reading "
            "the capture warnings. No connection was attempted."
        )
        return 1, None
    if args.duration <= 0:
        print("Refusing to run: --duration must be a positive number of "
              "seconds.")
        return 1, None
    if args.duration < MIN_FIRST_CAPTURE_SECONDS and not args.allow_short_capture:
        print(
            f"Refusing to run: the first capture should be at least "
            f"{MIN_FIRST_CAPTURE_SECONDS:.0f} seconds (six minutes) so idle-"
            "disconnect behaviour can be observed. Pass "
            "--allow-short-capture only for controlled local testing."
        )
        return 1, None
    return None, ProbeConfig(
        host=args.host,
        port=args.port,
        duration_seconds=args.duration,
        output_dir=args.output_dir,
        verbose_summary=args.verbose_summary,
    )


def _output_dir_within_repo(output_dir: Path) -> bool:
    """True when the output directory resolves inside this repository."""
    try:
        return output_dir.resolve().is_relative_to(_REPO_ROOT)
    except OSError:
        return False


def _create_capture_dir(output_dir: Path) -> Path:
    """Create a collision-free private capture directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    capture_dir = output_dir / f"capture_{stamp}_{secrets.token_hex(3)}"
    capture_dir.mkdir()
    return capture_dir


def _model_overview(snapshot: StatusSnapshot | None) -> dict[str, Any]:
    """Shape-only model facts for A6: letters and presence, never names."""
    if snapshot is None:
        return {"frames_applied": False}
    return {
        "frames_applied": True,
        "operating_mode": snapshot.operating_mode,
        "controller_state": snapshot.controller_state,
        "active_mode_group": snapshot.active_mode_group,
        "fault_active": snapshot.fault.active,
        "capabilities": {
            "heater_observed": snapshot.capabilities.heater_observed,
            "cooler_observed": snapshot.capabilities.cooler_observed,
            "evaporative_observed": snapshot.capabilities.evaporative_observed,
            "multi_setpoint_observed": (
                snapshot.capabilities.multi_setpoint_observed
            ),
            "temperature_unit": snapshot.capabilities.temperature_unit,
        },
        "zones": [
            {
                "letter": zone.letter,
                "installed_observed": zone.installed_observed,
                "has_current_status": zone.current is not None,
                "has_measured_temperature": (
                    zone.current is not None
                    and zone.current.measured_temperature is not None
                ),
            }
            for zone in snapshot.zones.values()
        ],
    }


def _write_outputs(capture_dir: Path, summary: dict[str, Any]) -> None:
    """Write the private summary and the redaction-checklist notes."""
    summary_path = capture_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    (capture_dir / "capture_notes.txt").write_text(_NOTES_TEXT, encoding="utf-8")


async def run_capture(config: ProbeConfig) -> int:
    """Run one passive capture; returns the process exit code.

    0: capture ended cleanly with data and the summary written.
    1: output-directory failure.
    2: connection failed, or the session ended before any data arrived.
    3: cancelled/interrupted after output was finalised.
    """
    print(_WARNING)
    if not _output_dir_within_repo(config.output_dir):
        # Emitted before the capture directory exists and before any
        # connection attempt. Outside directories stay supported (for
        # example encrypted volumes), but git-ignore protection is lost.
        print(_OUTSIDE_REPO_WARNING)
    try:
        capture_dir = _create_capture_dir(config.output_dir)
    except OSError as err:
        print(f"Output directory error: {type(err).__name__}")
        return 1
    started_local = datetime.now().astimezone().isoformat(timespec="seconds")
    summary: dict[str, Any] = {
        "tool": "rinnai_probe",
        "purpose": "passive capture evidence for ledger items "
        "A1/A2/A3/A4/A6/A11",
        "started_local_time": started_local,
        "port": config.port,
        "requested_duration_seconds": config.duration_seconds,
    }

    print("Connecting for passive capture (no bytes will be transmitted)...")
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT_SECONDS):
            reader, writer = await asyncio.open_connection(
                config.host, config.port
            )
    except (OSError, TimeoutError) as err:
        # Only the error type is recorded: exception text can echo the host.
        summary["outcome"] = "connection_failed"
        summary["error_type"] = type(err).__name__
        _write_outputs(capture_dir, summary)
        print(f"Connection failed ({type(err).__name__}). "
              f"Summary written to: {capture_dir}")
        return 2

    start = time.monotonic()
    parser = RinnaiFrameParser()
    model = RinnaiStatusModel()
    last_snapshot: StatusSnapshot | None = None
    chunks: list[dict[str, Any]] = []
    sequences: list[int] = []
    frame_events: list[dict[str, Any]] = []
    total_bytes = 0
    frame_count = 0
    outcome = "duration_elapsed"
    eof_offset: float | None = None
    print("Connected. Capturing passively...")
    try:
        with (capture_dir / "raw_bytes.bin").open("wb") as raw_output:
            while True:
                remaining = config.duration_seconds - (time.monotonic() - start)
                if remaining <= 0:
                    break
                try:
                    chunk = await asyncio.wait_for(
                        reader.read(_READ_CHUNK_BYTES), timeout=remaining
                    )
                except TimeoutError:
                    break
                offset = round(time.monotonic() - start, 3)
                if not chunk:
                    outcome = "eof_before_duration"
                    eof_offset = offset
                    break
                raw_output.write(chunk)
                total_bytes += len(chunk)
                chunks.append(
                    {"offset_seconds": offset, "byte_count": len(chunk)}
                )
                for frame in parser.feed(chunk):
                    frame_count += 1
                    sequences.append(frame.sequence)
                    last_snapshot = model.apply(frame)
                    if config.verbose_summary:
                        frame_events.append(
                            {
                                "offset_seconds": offset,
                                "sequence": frame.sequence,
                                "group_keys": sorted(
                                    key
                                    for item in frame.payload
                                    for key in item
                                ),
                            }
                        )
    except asyncio.CancelledError:
        # Finalise what we have; the exit code reports the interruption.
        outcome = "cancelled"
    finally:
        writer.close()
        with suppress(OSError):
            await writer.wait_closed()

    close_offset = round(time.monotonic() - start, 3)
    summary.update(
        {
            "outcome": outcome,
            "connection_open_offset_seconds": 0.0,
            "connection_close_offset_seconds": close_offset,
            "elapsed_seconds": close_offset,
            "eof_offset_seconds": eof_offset,
            "first_data_offset_seconds": (
                chunks[0]["offset_seconds"] if chunks else None
            ),
            "last_data_offset_seconds": (
                chunks[-1]["offset_seconds"] if chunks else None
            ),
            "chunk_count": len(chunks),
            "chunks": chunks,
            "total_bytes": total_bytes,
            "frame_count": frame_count,
            "sequences": sequences,
            "parser_invalid_candidate_count": parser.invalid_candidate_count,
            "parser_discarded_byte_count": parser.discarded_byte_count,
            "parser_buffered_byte_count_final": parser.buffered_byte_count,
            "model_overview": _model_overview(last_snapshot),
        }
    )
    if config.verbose_summary:
        summary["frame_events"] = frame_events
    try:
        _write_outputs(capture_dir, summary)
    except OSError as err:
        print(f"Failed writing outputs: {type(err).__name__}")
        return 1

    print(
        f"Capture finished: outcome={outcome}, bytes={total_bytes}, "
        f"frames={frame_count}, "
        f"invalid_candidates={parser.invalid_candidate_count}"
    )
    print(f"Private output written to: {capture_dir}")
    print("Raw capture may contain household data. Never commit it. Follow "
          "capture_notes.txt before creating fixtures.")
    if outcome == "cancelled":
        return 3
    if total_bytes == 0:
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; connects only after every safety gate passes."""
    exit_code, config = parse_config(argv)
    if config is None:
        return exit_code if exit_code is not None else 1
    try:
        return asyncio.run(run_capture(config))
    except KeyboardInterrupt:
        print("\nCapture interrupted.")
        return 3


if __name__ == "__main__":
    sys.exit(main())
