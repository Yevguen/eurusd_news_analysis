"""Tests for the data-source registry (config/data_sources.yaml)."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from src.data_governance.source_registry import (
    DataSource,
    RedistributionStatus,
    load_source_registry,
)
from src.economic_calendar.rule_models import load_event_rule_catalogue

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = PROJECT_ROOT / "config" / "data_sources.yaml"
EVENT_RULES_PATH = PROJECT_ROOT / "config" / "event_rules.yaml"
DATA_SOURCES_DOC = PROJECT_ROOT / "DATA_SOURCES.md"

PERMITTED = RedistributionStatus.PERMITTED_WITH_ATTRIBUTION

EXPECTED_CLASSIFICATION = {
    "bls": PERMITTED,
    "bea": PERMITTED,
    "census": PERMITTED,
    "federal_reserve_board": PERMITTED,
    "eurostat": PERMITTED,
    "ecb": PERMITTED,
    "destatis": PERMITTED,
    "sp_global_pmi": RedistributionStatus.RESTRICTED,
    "ism": RedistributionStatus.RESTRICTED,
    "zew": RedistributionStatus.RESTRICTED,
    "ifo": RedistributionStatus.RESTRICTED,
    "adp": RedistributionStatus.RESTRICTED,
    "pr_newswire": RedistributionStatus.RESTRICTED,
    "university_of_michigan": RedistributionStatus.UNRESOLVED,
    "german_state_statistical_offices": RedistributionStatus.UNRESOLVED,
    "mt5_broker_price_data": RedistributionStatus.RESTRICTED,
}


def test_registry_loads() -> None:
    registry = load_source_registry(REGISTRY_PATH)

    assert registry.schema_version == 1
    assert len(registry.sources) >= len(EXPECTED_CLASSIFICATION)


def test_required_source_classifications() -> None:
    registry = load_source_registry(REGISTRY_PATH)

    for source_key, status in EXPECTED_CLASSIFICATION.items():
        assert registry.get(source_key).redistribution_status == status, source_key


def test_every_event_rule_is_mapped_to_a_source() -> None:
    registry = load_source_registry(REGISTRY_PATH)
    catalogue = load_event_rule_catalogue(EVENT_RULES_PATH)

    unmapped = [
        rule.event_key
        for rule in catalogue.event_rules
        if not registry.sources_for_event_key(rule.event_key)
    ]

    assert not unmapped, f"Event rules without a data source: {unmapped!r}"


def test_restricted_event_families_are_not_publishable() -> None:
    registry = load_source_registry(REGISTRY_PATH)

    for event_key in (
        "us_ism_manufacturing_pmi",
        "us_adp_employment",
        "us_michigan_preliminary",
        "eur_zew_sentiment",
        "eur_germany_ifo_business_climate",
        "eur_eurozone_flash_pmi",
        "eur_germany_state_cpi",
    ):
        assert not registry.event_key_is_publishable(event_key), event_key

    assert registry.event_key_is_publishable("us_cpi")


@pytest.mark.parametrize(
    ("url", "expected_key"),
    [
        ("https://www.bls.gov/news.release/archives/cpi_01112024.htm", "bls"),
        ("https://ec.europa.eu/eurostat/web/products-euro-indicators/w/x", "eurostat"),
        ("https://www.pmi.spglobal.com/Public/Home/PressRelease/abc", "sp_global_pmi"),
        ("https://mediacenter.adp.com/2024-01-04-report", "adp"),
        (
            "https://data.sca.isr.umich.edu/fetchdoc.php?docid=1",
            "university_of_michigan",
        ),
        ("https://www.prnewswire.com/news-releases/x.html", "pr_newswire"),
        ("https://www.it.nrw/nrw-inflationsrate", "german_state_statistical_offices"),
        ("https://example.com/synthetic/x", "project_synthetic"),
    ],
)
def test_url_mapping(url: str, expected_key: str) -> None:
    source = load_source_registry(REGISTRY_PATH).source_for_url(url)

    assert source is not None
    assert source.source_key == expected_key


@pytest.mark.parametrize(
    "url",
    [
        "https://ec.europa.eu/info/other-commission-page",
        "https://notbls.gov/page",
        "https://unknown.example-vendor.io/data",
    ],
)
def test_unregistered_urls_map_to_no_source(url: str) -> None:
    assert load_source_registry(REGISTRY_PATH).source_for_url(url) is None


def test_reusable_source_requires_terms_and_attribution() -> None:
    with pytest.raises(ValidationError, match="has no terms_url"):
        DataSource(
            source_key="x",
            publisher="X",
            category="official_statistics",
            redistribution_status=PERMITTED,
            attribution="Source: X",
            modification_notice_required=False,
            repository_treatment="test",
        )


def test_duplicate_url_patterns_are_rejected(tmp_path: Path) -> None:
    raw = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    raw["sources"][1]["url_patterns"] = list(raw["sources"][0]["url_patterns"])
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(ValidationError, match="url_pattern"):
        load_source_registry(path)


def test_data_sources_document_covers_every_registry_entry() -> None:
    """DATA_SOURCES.md must not drift from the machine-readable registry."""

    document = DATA_SOURCES_DOC.read_text(encoding="utf-8")

    for source in load_source_registry(REGISTRY_PATH).sources:
        assert f"`{source.source_key}`" in document, source.source_key
