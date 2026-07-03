"""Direct safety tests for the capture sanitiser.

Every input here is a tiny fully synthetic capture created inside pytest's
tmp_path. Nothing reads real captures or any private location, and nothing
writes outside pytest temporary directories except where a refusal is being
proven (in which case the test asserts nothing was created).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from scripts import sanitise_rinnai_capture as sanitiser
from scripts.sanitise_rinnai_capture import (
    SanitisationError,
    SanitiseStats,
    sanitise_payload,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SANITISER_PATH = REPO_ROOT / "scripts" / "sanitise_rinnai_capture.py"

SAFE_PAYLOAD: list[dict[str, object]] = [
    {
        "SYST": {
            "CFG": {"MTSP": "Y", "TU": "C", "ZA": "Real Room Name"},
            "AVM": {"HG": "Y", "CG": "N"},
            "OSS": {"MD": "H", "ST": "N", "TM": "07:15", "DY": "FRI"},
            "FLT": {"AV": "N"},
        }
    },
    {
        "HGOM": {
            "CFG": {"ZAIS": "Y", "ZBIS": "N"},
            "ZAO": {"OP": "M", "SP": "19", "AO": "N"},
            "ZAS": {"AE": "N", "MT": "237", "AT": "W"},
        }
    },
]


def encode_frame(sequence: int, payload: list[dict[str, object]]) -> bytes:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return f"N{sequence:06d}{body}".encode()


def write_capture(
    tmp_path: Path, payload: list[dict[str, object]]
) -> Path:
    capture = tmp_path / "synthetic_input.bin"
    capture.write_bytes(encode_frame(7, payload))
    return capture


def run_main(
    tmp_path: Path,
    payload: list[dict[str, object]],
    *,
    fixture_dir: Path | None = None,
    report_dir: Path | None = None,
) -> tuple[int, Path, Path]:
    capture = write_capture(tmp_path, payload)
    fixtures = fixture_dir if fixture_dir is not None else tmp_path / "fx"
    report = report_dir if report_dir is not None else tmp_path / "report"
    exit_code = sanitiser.main(
        [
            "--input",
            str(capture),
            "--fixture-dir",
            str(fixtures),
            "--report-dir",
            str(report),
        ]
    )
    return exit_code, fixtures, report


# --- 1-4: allow-list behaviour ---------------------------------------------------


def test_approved_protocol_enums_are_preserved() -> None:
    stats = SanitiseStats()
    result = sanitise_payload(SAFE_PAYLOAD, stats)
    syst = result[0]["SYST"]
    hgom = result[1]["HGOM"]
    assert syst["OSS"]["MD"] == "H"
    assert syst["OSS"]["ST"] == "N"
    assert syst["CFG"]["TU"] == "C"
    assert syst["CFG"]["MTSP"] == "Y"
    assert syst["AVM"] == {"HG": "Y", "CG": "N"}
    assert hgom["ZAO"]["OP"] == "M"
    assert hgom["ZAO"]["AO"] == "N"
    assert hgom["ZAS"]["AT"] == "W"
    assert stats.protocol_symbols_preserved > 0


@pytest.mark.parametrize(
    ("key", "value"),
    [("MD", "Q"), ("TU", "K"), ("OP", "X"), ("QQ", "J")],
)
def test_unknown_single_letter_symbols_fail_closed(
    key: str, value: str
) -> None:
    payload: list[dict[str, object]] = [{"SYST": {"OSS": {key: value}}}]
    with pytest.raises(SanitisationError):
        sanitise_payload(payload, SanitiseStats())


def test_oop_state_symbol_is_rejected_at_controller_state_path() -> None:
    # "F" is a valid HGOM.OOP.ST power state but not a valid SYST.OSS.ST
    # controller state: path-aware approval must not transfer it.
    ok = sanitise_payload([{"HGOM": {"OOP": {"ST": "F"}}}], SanitiseStats())
    assert ok[0]["HGOM"]["OOP"]["ST"] == "F"
    with pytest.raises(SanitisationError):
        sanitise_payload([{"SYST": {"OSS": {"ST": "F"}}}], SanitiseStats())
    with pytest.raises(SanitisationError):
        sanitise_payload([{"SYST": {"OSS": {"ST": "Z"}}}], SanitiseStats())


def test_zone_schedule_symbol_is_rejected_at_unrelated_at_path() -> None:
    # "W"/"L" are valid at the zone-sensed schedule-period path but not at
    # an unrelated AT location such as SYST.OSS.AT.
    ok = sanitise_payload([{"HGOM": {"ZAS": {"AT": "L"}}}], SanitiseStats())
    assert ok[0]["HGOM"]["ZAS"]["AT"] == "L"
    with pytest.raises(SanitisationError):
        sanitise_payload([{"SYST": {"OSS": {"AT": "W"}}}], SanitiseStats())


def test_fixture_equivalent_paths_still_sanitise() -> None:
    # Both ST paths, both AT usages, and the fixture-only symbols together.
    payload: list[dict[str, object]] = [
        {"SYST": {"OSS": {"ST": "N", "MD": "H", "AT": "16"}}},
        {
            "HGOM": {
                "OOP": {"ST": "N", "DT": "E"},
                "CFG": {"DG": "W"},
                "ZCO": {"OP": "M", "AO": "N"},
                "ZBS": {"AT": "W", "AZ": "W"},
            }
        },
    ]
    result = sanitise_payload(payload, SanitiseStats())
    assert result[0]["SYST"]["OSS"]["ST"] == "N"
    assert result[1]["HGOM"]["OOP"]["ST"] == "N"
    assert result[1]["HGOM"]["OOP"]["DT"] == "E"
    assert result[1]["HGOM"]["CFG"]["DG"] == "W"
    assert result[1]["HGOM"]["ZCO"]["OP"] == "M"
    assert result[1]["HGOM"]["ZBS"]["AT"] == "W"
    assert result[1]["HGOM"]["ZBS"]["AZ"] == "W"


def test_path_aware_failure_creates_no_output(tmp_path: Path) -> None:
    bad_payload: list[dict[str, object]] = [{"SYST": {"OSS": {"ST": "F"}}}]
    exit_code, fixtures, report = run_main(tmp_path, bad_payload)
    assert exit_code == 2
    assert not fixtures.exists()
    assert not report.exists()


def test_arbitrary_source_strings_fail_closed() -> None:
    payload: list[dict[str, object]] = [
        {"SYST": {"CFG": {"XX": "Living Room West"}}}
    ]
    with pytest.raises(SanitisationError):
        sanitise_payload(payload, SanitiseStats())


def test_zone_names_and_numerics_are_replaced() -> None:
    stats = SanitiseStats()
    result = sanitise_payload(SAFE_PAYLOAD, stats)
    syst = result[0]["SYST"]
    hgom = result[1]["HGOM"]
    assert syst["CFG"]["ZA"] == "Synthetic Zone A"  # never the source name
    assert hgom["ZAS"]["MT"] == "216"  # deterministic synthetic, not 237
    assert hgom["ZAO"]["SP"] == "21"  # deterministic synthetic, not 19
    assert syst["OSS"]["TM"] == "12:34"
    assert syst["OSS"]["DY"] == "MON"
    assert stats.strings_replaced > 0
    assert stats.numerics_replaced > 0


# --- 5-6: destination refusals ----------------------------------------------------


def test_fixture_dir_under_reference_data_raw_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    forbidden = REPO_ROOT / "reference_data" / "raw" / "fixtures"
    exit_code, _, report = run_main(
        tmp_path, SAFE_PAYLOAD, fixture_dir=forbidden
    )
    assert exit_code == 1
    assert not (REPO_ROOT / "reference_data" / "raw").exists()
    assert not report.exists()  # refused before any output was written
    assert "Refusing" in capsys.readouterr().out


def test_report_dir_inside_repository_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inside = REPO_ROOT / "tmp_refused_report_dir"
    exit_code, fixtures, _ = run_main(
        tmp_path, SAFE_PAYLOAD, report_dir=inside
    )
    assert exit_code == 1
    assert not inside.exists()
    assert not fixtures.exists()  # refused before any output was written
    assert "Refusing" in capsys.readouterr().out


# --- failure-before-write ----------------------------------------------------------


def test_sanitisation_failure_writes_no_fixture_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad_payload: list[dict[str, object]] = [{"SYST": {"OSS": {"MD": "Q"}}}]
    exit_code, fixtures, report = run_main(tmp_path, bad_payload)
    assert exit_code == 2
    assert not fixtures.exists()
    assert not report.exists()
    out = capsys.readouterr().out
    assert "Cannot sanitise" in out
    assert "Q" not in out.split("Cannot sanitise")[-1]  # never echo values


def test_empty_capture_fails_cleanly_without_output(tmp_path: Path) -> None:
    capture = tmp_path / "empty.bin"
    capture.write_bytes(b"")
    fixtures = tmp_path / "fx"
    report = tmp_path / "report"
    exit_code = sanitiser.main(
        [
            "--input",
            str(capture),
            "--fixture-dir",
            str(fixtures),
            "--report-dir",
            str(report),
        ]
    )
    assert exit_code == 2
    assert not fixtures.exists()
    assert not report.exists()


# --- 7: stdout never contains absolute paths ---------------------------------------


def test_stdout_contains_no_absolute_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, fixtures, report = run_main(tmp_path, SAFE_PAYLOAD)
    assert exit_code == 0
    assert (fixtures / sanitiser.FIXTURE_STREAM_NAME).is_file()
    assert (fixtures / sanitiser.FIXTURE_METADATA_NAME).is_file()
    out = capsys.readouterr().out
    assert str(tmp_path) not in out  # covers input, fixture, report paths
    assert str(tmp_path.resolve()) not in out
    assert str(report) not in out
    # Fixture output is filename-only when outside the repository.
    assert sanitiser.FIXTURE_STREAM_NAME in out
    assert sanitiser.FIXTURE_METADATA_NAME in out


# --- 8: import hygiene and no transmit surface --------------------------------------


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    return imported


def test_sanitiser_has_no_network_or_transmit_surface() -> None:
    imported = _top_level_imports(SANITISER_PATH)
    assert not imported & {"socket", "aiohttp", "homeassistant", "asyncio"}
    source = SANITISER_PATH.read_text(encoding="utf-8")
    assert "open_connection" not in source
    tree = ast.parse(source)
    banned_calls = {"write", "writelines", "drain", "send", "sendall", "sendto"}
    attribute_calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not attribute_calls & banned_calls, attribute_calls & banned_calls
