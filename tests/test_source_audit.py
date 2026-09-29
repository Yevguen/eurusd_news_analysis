"""Consistency tests for the January 2024 source audit and its public redaction."""

from pathlib import Path
from typing import Any

import yaml

from src.data_governance.source_registry import load_source_registry

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUDIT_DIR = PROJECT_ROOT / "config" / "historical_release_audits"
AUDIT_PATH = AUDIT_DIR / "january_2024_source_audit.yaml"
MANIFEST_PATH = AUDIT_DIR / "january_2024.yaml"
REGISTRY_PATH = PROJECT_ROOT / "config" / "data_sources.yaml"


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_audit_entries_belong_to_the_manifest() -> None:
    audit = load_yaml(AUDIT_PATH)
    manifest = load_yaml(MANIFEST_PATH)

    manifest_ids = {entry["release_id"] for entry in manifest["expected_releases"]}
    audited_ids = [entry["release_id"] for entry in audit["release_audits"]]

    assert len(audited_ids) == len(set(audited_ids))
    assert set(audited_ids) <= manifest_ids
    assert audit["audit"]["expected_release_count"] == len(manifest_ids)


def test_audit_statuses_are_permitted() -> None:
    audit = load_yaml(AUDIT_PATH)
    permitted = set(audit["audit"]["permitted_statuses"])

    for entry in audit["release_audits"]:
        assert entry["verification_status"] in permitted, entry["release_id"]


def test_redaction_block_lists_exactly_the_non_reusable_entries() -> None:
    audit = load_yaml(AUDIT_PATH)
    registry = load_source_registry(REGISTRY_PATH)

    non_reusable = {
        entry["release_id"]
        for entry in audit["release_audits"]
        if not registry.event_key_is_publishable(entry["event_key"])
    }
    declared = set(
        audit["audit"]["public_repository_redaction"]["affected_release_ids"]
    )

    assert declared == non_reusable
