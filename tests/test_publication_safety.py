"""Tests for the publication-safety guard.

Several tests build credential-like strings and paths at runtime so that this
file itself never contains them literally (the guard scans test files too).
"""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from src.data_governance.publication_guard import (
    check_code_for_restricted_urls,
    check_demo_directory,
    check_publishable_paths,
    check_release_file,
    check_source_audit,
    list_publishable_files,
    run_publication_checks,
    scan_text_files,
)
from src.data_governance.source_registry import load_source_registry

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = PROJECT_ROOT / "config" / "data_sources.yaml"
AUDIT_PATH = (
    PROJECT_ROOT
    / "config"
    / "historical_release_audits"
    / "january_2024_source_audit.yaml"
)
ALLOWLIST_PATH = PROJECT_ROOT / "data" / "demo" / "official_releases_allowlist.jsonl"
SYNTHETIC_PRICES = PROJECT_ROOT / "data" / "demo" / "SYNTHETIC_eurusd_h1_mt5_format.csv"

requires_git = pytest.mark.skipif(
    shutil.which("git") is None, reason="git not installed"
)


@pytest.fixture(scope="module")
def registry():
    return load_source_registry(REGISTRY_PATH)


def bls_record(**overrides: object) -> dict[str, Any]:
    record = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8").splitlines()[0])
    record.update(overrides)
    return record


def write_jsonl(path: Path, *records: dict[str, object]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The repository's own public content
# ---------------------------------------------------------------------------


def test_repository_demo_directory_passes(registry) -> None:
    assert check_demo_directory(PROJECT_ROOT, registry) == []


def test_repository_source_audit_passes(registry) -> None:
    assert check_source_audit(AUDIT_PATH, registry) == []


@requires_git
def test_full_publication_check_passes_for_this_checkout() -> None:
    report = run_publication_checks(PROJECT_ROOT)

    assert report.passed, "\n".join(
        f"[{f.check}] {f.path}: {f.message}" for f in report.findings
    )


# ---------------------------------------------------------------------------
# Release records
# ---------------------------------------------------------------------------


def test_restricted_source_record_is_rejected(tmp_path: Path, registry) -> None:
    ism = bls_record(
        release_id="us_ism_manufacturing_pmi_2024_01_03",
        event_key="us_ism_manufacturing_pmi",
        official_source_name="Institute for Supply Management",
        official_source_url="https://www.ismworld.org/some-report/",
        components=[],
        release_summary="Test.",
    )
    path = write_jsonl(tmp_path / "r.jsonl", ism)

    messages = [
        f.message
        for f in check_release_file(
            path, registry, declared_origin="authentic", declared_source_keys=["bls"]
        )
    ]

    assert any("'ism'" in m and "restricted" in m for m in messages)
    assert any("not classified as reusable" in m for m in messages)


def test_undeclared_origin_is_rejected(tmp_path: Path, registry) -> None:
    record = bls_record()
    record.pop("data_origin")
    path = write_jsonl(tmp_path / "r.jsonl", record)

    findings = check_release_file(
        path, registry, declared_origin="authentic", declared_source_keys=["bls"]
    )

    assert [f.message for f in findings] == [
        "data_origin is not declared (synthetic/authentic)."
    ]


def test_synthetic_record_pointing_at_real_source_is_rejected(
    tmp_path: Path, registry
) -> None:
    record = bls_record(
        release_id="synthetic_us_cpi_2030_01_15",
        data_origin="synthetic",
        official_source_name="SYNTHETIC source",
    )
    path = write_jsonl(tmp_path / "r.jsonl", record)

    findings = check_release_file(
        path,
        registry,
        declared_origin="synthetic",
        declared_source_keys=["project_synthetic"],
    )

    assert any("'bls' is not declared" in f.message for f in findings)


def test_forecasts_from_restricted_vendor_are_rejected(
    tmp_path: Path, registry
) -> None:
    record = bls_record(
        forecast_source_name="Vendor",
        forecast_source_url="https://www.investing.com/economic-calendar/cpi",
    )
    record["components"][0]["forecast"] = 0.2
    path = write_jsonl(tmp_path / "r.jsonl", record)

    findings = check_release_file(
        path, registry, declared_origin="authentic", declared_source_keys=["bls"]
    )

    assert any("secondary_media" in f.message for f in findings)


def test_restricted_url_inside_text_is_rejected(tmp_path: Path, registry) -> None:
    record = bls_record(notes="Copied from https://www.zew.de/en/some-release")
    path = write_jsonl(tmp_path / "r.jsonl", record)

    findings = check_release_file(
        path, registry, declared_origin="authentic", declared_source_keys=["bls"]
    )

    assert any("'zew'" in f.message for f in findings)


def test_reviewed_bls_record_passes(tmp_path: Path, registry) -> None:
    path = write_jsonl(tmp_path / "r.jsonl", bls_record())

    assert (
        check_release_file(
            path, registry, declared_origin="authentic", declared_source_keys=["bls"]
        )
        == []
    )


# ---------------------------------------------------------------------------
# Demo manifest and price series
# ---------------------------------------------------------------------------


def make_demo_project(tmp_path: Path, files: list[dict[str, object]]) -> Path:
    demo = tmp_path / "data" / "demo"
    demo.mkdir(parents=True)
    shutil.copy(SYNTHETIC_PRICES, demo / SYNTHETIC_PRICES.name)
    (demo / "demo_manifest.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "files": files}), encoding="utf-8"
    )
    return tmp_path


def price_entry(**overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "path": f"data/demo/{SYNTHETIC_PRICES.name}",
        "kind": "price_series",
        "data_origin": "synthetic",
        "source_keys": ["project_synthetic"],
        "description": "test",
    }
    entry.update(overrides)
    return entry


def test_demo_price_file_declared_synthetic_passes(tmp_path: Path, registry) -> None:
    root = make_demo_project(tmp_path, [price_entry()])

    assert check_demo_directory(root, registry) == []


def test_private_price_data_cannot_be_published(tmp_path: Path, registry) -> None:
    root = make_demo_project(
        tmp_path,
        [
            price_entry(
                data_origin="authentic_private", source_keys=["mt5_broker_price_data"]
            )
        ],
    )

    messages = [f.message for f in check_demo_directory(root, registry)]

    assert any("must not be published" in m for m in messages)
    assert any("mt5_broker_price_data" in m for m in messages)


def test_unlisted_demo_data_file_is_rejected(tmp_path: Path, registry) -> None:
    root = make_demo_project(tmp_path, [price_entry()])
    (root / "data" / "demo" / "extra.jsonl").write_text("{}\n", encoding="utf-8")

    findings = check_demo_directory(root, registry)

    assert [f.path for f in findings] == ["data/demo/extra.jsonl"]


# ---------------------------------------------------------------------------
# Source audit
# ---------------------------------------------------------------------------


def write_audit(path: Path, entries: list[dict[str, object]]) -> Path:
    path.write_text(yaml.safe_dump({"release_audits": entries}), encoding="utf-8")
    return path


def test_audit_values_for_restricted_source_are_rejected(
    tmp_path: Path, registry
) -> None:
    path = write_audit(
        tmp_path / "audit.yaml",
        [
            {
                "release_id": "r1",
                "event_key": "us_ism_manufacturing_pmi",
                "components": [
                    {"component_key": "headline_index", "stored_actual": 50.0}
                ],
            },
            {
                "release_id": "r2",
                "event_key": "eur_germany_state_cpi",
                "evidence": "The release confirms 2.5 percent annual inflation.",
            },
        ],
    )

    findings = check_source_audit(path, registry)

    assert {f.message.split(":")[0] for f in findings} == {"r1", "r2"}


def test_withheld_markers_and_reusable_sources_pass(tmp_path: Path, registry) -> None:
    path = write_audit(
        tmp_path / "audit.yaml",
        [
            {
                "release_id": "r1",
                "event_key": "us_ism_manufacturing_pmi",
                "components": [
                    {"component_key": "x", "corrected_text": "withheld (x)"}
                ],
            },
            {
                "release_id": "r2",
                "event_key": "us_jolts_job_openings",
                "components": [{"component_key": "job_openings", "stored_actual": 1.0}],
                "comment": "Rate of 3.5 percent from BLS.",
            },
        ],
    )

    assert check_source_audit(path, registry) == []


# ---------------------------------------------------------------------------
# Paths, text scan and code URLs
# ---------------------------------------------------------------------------


def test_path_policy() -> None:
    files = [
        "README.md",
        "data/raw/.gitkeep",
        f"data/demo/{SYNTHETIC_PRICES.name}",
        "data/historical_releases/raw/releases.jsonl",
        "exports/EURUSD_H1_MT5_2024.csv",
        ".env",
        "src/__pycache__/module.cpython-312.pyc",
    ]

    flagged = {f.path for f in check_publishable_paths(files)}

    assert flagged == {
        "data/historical_releases/raw/releases.jsonl",
        "exports/EURUSD_H1_MT5_2024.csv",
        ".env",
        "src/__pycache__/module.cpython-312.pyc",
    }


def test_text_scan_detects_credentials_paths_and_emails(tmp_path: Path) -> None:
    drive_path = "C" + ":" + "\\" + "Users" + "\\" + "someone" + "\\" + "data.csv"
    aws_key = "AKIA" + "ABCDEFGHIJKLMNOP"
    email = "person" + "@" + "mail-provider.org"
    posix_home = "/" + "home" + "/someone/project"
    (tmp_path / "notes.md").write_text(
        f"path {drive_path}\nkey {aws_key}\ncontact {email}\nrun {posix_home}\n",
        encoding="utf-8",
    )

    labels = {f.message for f in scan_text_files(tmp_path, ["notes.md"])}

    assert labels == {
        "Possible Windows absolute path.",
        "Possible AWS access key id.",
        "Possible e-mail address.",
        "Possible personal home-directory path.",
    }


def test_text_scan_ignores_urls_and_example_addresses(tmp_path: Path) -> None:
    (tmp_path / "ok.md").write_text(
        "See https://www.ecb.europa.eu/home/disclaimer/html/index.en.html "
        "and write to demo" + "@" + "example.com. Result:\\n done.\n",
        encoding="utf-8",
    )

    assert scan_text_files(tmp_path, ["ok.md"]) == []


def test_code_referencing_restricted_urls_is_flagged(tmp_path: Path, registry) -> None:
    (tmp_path / "embedded.py").write_text(
        'URL = "https://www.ismworld.org/report/"\nOK = "https://www.bls.gov/cpi/"\n',
        encoding="utf-8",
    )

    findings = check_code_for_restricted_urls(tmp_path, ["embedded.py"], registry)

    assert [f.path for f in findings] == ["embedded.py:1"]


# ---------------------------------------------------------------------------
# .gitignore behaviour (what `git add .` would publish)
# ---------------------------------------------------------------------------


@requires_git
def test_gitignore_keeps_private_data_out_of_git_add(tmp_path: Path) -> None:
    shutil.copy(PROJECT_ROOT / ".gitignore", tmp_path / ".gitignore")

    candidates = [
        "src/module.py",
        "data/raw/.gitkeep",
        "data/processed/.gitkeep",
        "data/reports/.gitkeep",
        "data/demo/SYNTHETIC_prices.csv",
        "data/demo/synthetic_releases.jsonl",
        "data/historical_releases/raw/releases.jsonl",
        "data/historical_releases/processed/release_components.parquet",
        "data/private/anything.txt",
        "data/new_private_dataset/values.txt",
        "data/raw/EURUSD_H1_MT5.csv",
        "data/reports/authentic_private/report.md",
        "scripts/dump.jsonl",
        "EURUSD_H1_MT5_export.csv",
        "backup.zip",
        ".env",
    ]

    for relative in candidates:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n", encoding="utf-8")

    files, method = list_publishable_files(tmp_path)

    assert "simulated" in method
    assert set(files) == {
        ".gitignore",
        "src/module.py",
        "data/raw/.gitkeep",
        "data/processed/.gitkeep",
        "data/reports/.gitkeep",
        "data/demo/SYNTHETIC_prices.csv",
        "data/demo/synthetic_releases.jsonl",
    }
