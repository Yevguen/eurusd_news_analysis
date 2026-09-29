"""Tests for report outputs and the generate_eurusd_report.py command line."""

import json
import shutil
from pathlib import Path

import pytest

from scripts.generate_eurusd_report import main as report_main

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = PROJECT_ROOT / "data" / "demo"
EXAMPLE_OUTPUT_DIR = PROJECT_ROOT / "docs" / "example_output"
ALLOWLIST = DEMO_DIR / "official_releases_allowlist.jsonl"
SYNTHETIC_PRICES = DEMO_DIR / "SYNTHETIC_eurusd_h1_mt5_format.csv"
STEM = "us_cpi_2024_01_11__synthetic_prices"


def run_demo(output_dir: Path) -> int:
    return report_main(["--demo", "--output-dir", str(output_dir)])


def test_demo_report_writes_json_markdown_and_chart(tmp_path: Path) -> None:
    assert run_demo(tmp_path) == 0

    payload = json.loads((tmp_path / f"{STEM}.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / f"{STEM}.md").read_text(encoding="utf-8")
    chart = (tmp_path / f"{STEM}.png").read_bytes()

    assert payload["market_data"]["data_origin"] == "synthetic"
    assert payload["event"]["release_data_origin"] == "authentic"
    assert payload["event"]["source_attribution"] == (
        "Source: U.S. Bureau of Labor Statistics"
    )
    assert payload["alignment"]["minutes_into_event_candle"] == 30
    assert payload["consensus"]["available"] is False
    assert len(payload["candles"]) == 6 + 24 + 6 + 2
    assert "SYNTHETIC demonstration prices" in markdown
    assert "## Limitations" in markdown
    assert chart.startswith(b"\x89PNG") and len(chart) > 20_000


def test_report_output_is_deterministic(tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"

    assert run_demo(first) == 0
    assert run_demo(second) == 0

    for suffix in (".json", ".md"):
        assert (first / f"{STEM}{suffix}").read_bytes() == (
            second / f"{STEM}{suffix}"
        ).read_bytes()


def test_committed_example_output_is_current(tmp_path: Path) -> None:
    assert run_demo(tmp_path) == 0

    for suffix in (".json", ".md"):
        committed = (EXAMPLE_OUTPUT_DIR / f"{STEM}{suffix}").read_text(encoding="utf-8")
        fresh = (tmp_path / f"{STEM}{suffix}").read_text(encoding="utf-8")

        assert committed.replace("\r\n", "\n") == fresh, suffix


def test_cli_requires_explicit_price_origin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = report_main(
        [
            "--releases",
            str(ALLOWLIST),
            "--release-id",
            "us_cpi_2024_01_11",
            "--prices",
            str(SYNTHETIC_PRICES),
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert exit_code == 2
    assert "--price-data-origin" in capsys.readouterr().err


def test_cli_reports_missing_price_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = report_main(
        [
            "--demo",
            "--prices",
            str(tmp_path / "absent.csv"),
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert exit_code == 2
    assert "Price file not found" in capsys.readouterr().err


def test_cli_reports_unknown_release(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = report_main(
        ["--demo", "--release-id", "does_not_exist", "--output-dir", str(tmp_path)]
    )

    assert exit_code == 2
    assert "not found" in capsys.readouterr().err


def test_cli_refuses_to_relabel_synthetic_prices(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = report_main(
        [
            "--demo",
            "--price-data-origin",
            "authentic_redistributable",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert exit_code == 2
    assert "declared as 'synthetic'" in capsys.readouterr().err


def test_private_price_reports_cannot_target_publishable_folders(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    private_copy = tmp_path / "EURUSD_H1_private_export.csv"
    shutil.copy(SYNTHETIC_PRICES, private_copy)
    forbidden_dir = PROJECT_ROOT / "docs" / "_should_not_exist"

    exit_code = report_main(
        [
            "--releases",
            str(ALLOWLIST),
            "--release-id",
            "us_cpi_2024_01_11",
            "--prices",
            str(private_copy),
            "--price-data-origin",
            "authentic_private",
            "--output-dir",
            str(forbidden_dir),
        ]
    )

    assert exit_code == 2
    assert "data/reports/" in capsys.readouterr().err
    assert not forbidden_dir.exists()


def test_private_price_reports_may_be_written_outside_the_repository(
    tmp_path: Path,
) -> None:
    private_copy = tmp_path / "EURUSD_H1_private_export.csv"
    shutil.copy(SYNTHETIC_PRICES, private_copy)

    exit_code = report_main(
        [
            "--releases",
            str(ALLOWLIST),
            "--release-id",
            "us_cpi_2024_01_11",
            "--prices",
            str(private_copy),
            "--price-data-origin",
            "authentic_private",
            "--output-dir",
            str(tmp_path / "private_reports"),
        ]
    )

    assert exit_code == 0
    assert (
        tmp_path / "private_reports" / "us_cpi_2024_01_11__authentic_private_prices.md"
    ).is_file()
