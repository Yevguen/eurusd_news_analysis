"""Tests for data-file-driven catalogue seeding."""

from pathlib import Path

import pytest

from scripts.seed_initial_historical_releases import main as seed_main
from src.economic_calendar.historical_models import HistoricalRelease
from src.economic_calendar.historical_seed import (
    MixedDataOriginError,
    SeedInputError,
    load_seed_records,
    seed_storage,
)
from src.economic_calendar.historical_storage import HistoricalReleaseStorage

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_RELEASES = PROJECT_ROOT / "data" / "demo" / "synthetic_releases.jsonl"
OFFICIAL_ALLOWLIST = (
    PROJECT_ROOT / "data" / "demo" / "official_releases_allowlist.jsonl"
)
SEED_SCRIPT = PROJECT_ROOT / "scripts" / "seed_initial_historical_releases.py"


def test_load_seed_records_reads_demo_file() -> None:
    records = load_seed_records(SYNTHETIC_RELEASES)

    assert len(records) == 5
    assert all(isinstance(record, HistoricalRelease) for record in records)


def test_load_seed_records_rejects_duplicate_release_keys(tmp_path: Path) -> None:
    line = SYNTHETIC_RELEASES.read_text(encoding="utf-8").splitlines()[0]
    duplicate_file = tmp_path / "duplicate.jsonl"
    duplicate_file.write_text(f"{line}\n{line}\n", encoding="utf-8")

    with pytest.raises(SeedInputError, match="repeats release keys"):
        load_seed_records(duplicate_file)


def test_load_seed_records_reports_invalid_line(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad.jsonl"
    bad_file.write_text('\n{"release_id": "x"}\n', encoding="utf-8")

    with pytest.raises(SeedInputError, match="at line 2"):
        load_seed_records(bad_file)


def test_load_seed_records_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SeedInputError, match="not found"):
        load_seed_records(tmp_path / "absent.jsonl")


def test_seed_storage_is_idempotent(tmp_path: Path) -> None:
    storage = HistoricalReleaseStorage(tmp_path / "releases.jsonl")
    records = load_seed_records(SYNTHETIC_RELEASES)

    first = seed_storage(records, storage)
    second = seed_storage(records, storage)

    assert (first.appended_count, first.skipped_existing_count) == (5, 0)
    assert (second.appended_count, second.skipped_existing_count) == (0, 5)
    assert storage.count() == 5


def test_seed_storage_refuses_to_mix_synthetic_and_authentic(tmp_path: Path) -> None:
    storage = HistoricalReleaseStorage(tmp_path / "releases.jsonl")
    seed_storage(load_seed_records(OFFICIAL_ALLOWLIST), storage)

    with pytest.raises(MixedDataOriginError):
        seed_storage(load_seed_records(SYNTHETIC_RELEASES), storage)

    assert storage.count() == 1


def test_seed_cli_writes_validated_catalogue(tmp_path: Path) -> None:
    output = tmp_path / "catalogue" / "releases.jsonl"

    exit_code = seed_main(["--input", str(SYNTHETIC_RELEASES), "--output", str(output)])

    assert exit_code == 0
    assert HistoricalReleaseStorage(output).count() == 5


def test_seed_cli_fails_clearly_for_missing_input(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = seed_main(
        [
            "--input",
            str(tmp_path / "absent.jsonl"),
            "--output",
            str(tmp_path / "o.jsonl"),
        ]
    )

    assert exit_code == 2
    assert "Seed input file not found" in capsys.readouterr().err


def test_seed_script_embeds_no_release_values() -> None:
    """The seed script must stay free of embedded catalogue content."""

    text = SEED_SCRIPT.read_text(encoding="utf-8")

    assert "HistoricalReleaseComponent(" not in text
    assert "https://" not in text
