"""Consensus-surprise (actual minus forecast) with a data-rights gate.

Consensus forecasts are typically compiled by commercial data vendors. The
project does not scrape or copy them to make the analysis look complete, so a
surprise is computed only when:

1. at least one numeric component has a recorded forecast, and
2. the release names a forecast source whose URL maps to a source classified
   as publishable in ``config/data_sources.yaml`` (synthetic demonstration
   sources count as publishable, and their output is labelled synthetic).

Otherwise the status explains why the surprise is unavailable.
"""

from __future__ import annotations

from src.data_governance.source_registry import SourceRegistry
from src.economic_calendar.historical_models import (
    ComponentValueType,
    DataOrigin,
    HistoricalRelease,
)

from .event_study import ConsensusStatus, ConsensusSurprise


def evaluate_consensus(
    release: HistoricalRelease,
    registry: SourceRegistry,
) -> ConsensusStatus:
    """Return the consensus-surprise status for one release."""

    numeric_with_forecast = [
        component
        for component in release.components
        if component.value_type == ComponentValueType.NUMERIC
        and component.forecast is not None
    ]

    if not numeric_with_forecast:
        return ConsensusStatus(
            available=False,
            reason=(
                "no forecast/consensus values are recorded for this release, and "
                "no rights-cleared consensus source is available to the project."
            ),
        )

    if not release.forecast_source_url:
        return ConsensusStatus(
            available=False,
            reason="forecast values have no documented source URL.",
        )

    source = registry.source_for_url(release.forecast_source_url)

    if source is None or not source.is_publishable:
        status = (
            "unregistered" if source is None else source.redistribution_status.value
        )
        return ConsensusStatus(
            available=False,
            reason=(
                f"the forecast source is {status}; consensus values are not used "
                "unless their reuse terms are cleared."
            ),
        )

    surprises: list[ConsensusSurprise] = []

    for component in numeric_with_forecast:
        actual, forecast = component.actual, component.forecast

        # Numeric components are validated as numbers; this narrows the type.
        if isinstance(actual, str) or forecast is None or isinstance(forecast, str):
            continue

        surprises.append(
            ConsensusSurprise(
                component_key=component.component_key,
                actual=float(actual),
                forecast=float(forecast),
                surprise=float(actual) - float(forecast),
                unit=component.unit,
            )
        )

    origin_note = (
        "SYNTHETIC forecasts (demonstration only)"
        if release.data_origin == DataOrigin.SYNTHETIC
        else f"forecasts from {source.publisher}"
    )

    return ConsensusStatus(
        available=True,
        reason=f"computed from {origin_note}.",
        surprises=surprises,
    )
