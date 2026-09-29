# Event-study methodology

This page documents every analytical choice made by
`src/impact_analysis/event_study.py`. The same definitions are summarised in
each generated report. The study is **descriptive and single-event**: it
measures what EUR/USD did around one release; it does not estimate causal
effects or statistical significance across events.

## 1. Event timestamp

- **Definition.** The event instant is the publisher's embargo-lift time as
  recorded in the catalogue (`official_release_time`, with its UTC offset),
  converted to UTC (`utc_release_time`). The model rejects naive timestamps
  and requires all three stored timestamps to denote the same instant.
- **Provenance.** For the public demo event (U.S. CPI for December 2023), the
  BLS release header states "embargoed until 8:30 a.m. (ET) Thursday,
  January 11, 2024" → 13:30 UTC.

## 2. Price data and time basis

- Input: EUR/USD **H1** candles in the MetaTrader 5 export layout
  (`<DATE> <TIME> <OPEN> <HIGH> <LOW> <CLOSE> <TICKVOL> <VOL> <SPREAD>`).
- MT5 labels each candle by its **open** time in the **broker-server clock**.
- Server time is converted to UTC with **one fixed offset**: the UTC offset of
  the release's `mt5_server_time`, i.e. the catalogue's provisional MT5 rule
  (`+02:00` for northern-hemisphere winter releases). This is an assumption,
  not a verified broker fact.
- **DST guard.** If the full analysis window crosses a daylight-saving
  transition in `America/New_York` or `Europe/Berlin`, the study stops with
  `TimeBasisError`: a single fixed offset cannot be trusted across such a
  change. If the event itself falls in a DST period while the recorded offset
  is `+02:00`, the report adds a limitation (the common summer convention
  would be `+03:00`).
- **Offset diagnostic.** For candidate offsets UTC+0 … UTC+3 the report shows
  the tick volume of the candle that *would* contain the release, relative to
  the preceding candle. A verdict ("consistent with UTC+h") is given only when
  one candidate's jump ratio is ≥ 2 and at least twice the next best;
  otherwise "inconclusive". This is circumstantial evidence, never proof.

## 3. Candle alignment

Candle *k* covers `[open_k, open_k + 1 h)`.

- **Event candle (k = 0):** the candle whose interval contains the event
  instant, `open_0 = floor_to_hour(event_utc)`.
- **Release on the hour** (e.g. 14:00 UTC): the release coincides with the
  event candle's open.
- **Release between candle boundaries** (e.g. 13:30 UTC): the event candle
  contains 30 minutes of *pre-release* trading. The study does not hide this;
  it reports `minutes_into_event_candle` and adds a limitation. H1 data cannot
  isolate the first minutes after a release.

## 4. Windows (clock hours, contiguous)

| Window | Relative candles | Default length |
|---|---|---|
| Anchor (previous close only) | k = −(P + B + 1) | 1 |
| Baseline (estimation) | k = −(P + B) … −(P + 1) | B = 24 |
| Pre-event | k = −P … −1 | P = 6 |
| Event candle | k = 0 | 1 |
| Post-event | k = 1 … M | M = 6 |

The baseline ends before the pre-event window so that anticipation effects do
not inflate the volatility benchmark. Lengths are configurable
(`--pre-candles`, `--baseline-candles`, `--post-candles`; P, M ≥ 2, B ≥ 3).

## 5. Returns

- Candle log return (basis points): `r_k = 10,000 × ln(C_k / C_(k−1))`.
- Reference price: `P_ref = C_(−1)`, the close of the last complete candle
  before the event candle.
- Cumulative return to candle k: `10,000 × ln(C_k / P_ref)`.
- Price change in pips: `(C_k − P_ref) × 10,000` (one EUR/USD pip = 0.0001).
- Pre-event drift: `10,000 × ln(C_(−1) / O_(−P))`.

## 6. Volatility

- Baseline volatility `σ_base`: sample standard deviation (ddof = 1) of `r_k`
  over the baseline window.
- Standardised event move: `|r_0| / σ_base`.
- Range measures: event-candle high−low range (pips) and its ratio to the mean
  baseline high−low range.
- Pre- and post-event realised volatility: sample standard deviation of `r_k`
  over those windows.
- Tick-volume ratio: event-candle tick volume / median baseline tick volume.

## 7. Missing data

Every candle from the anchor to the last post-event candle must exist.
Missing candles — including weekend closures, which affect Monday-morning
events with long baselines — raise `MissingCandlesError` listing the missing
server-time opens. Nothing is forward-filled or interpolated. Price files are
validated on load (ascending unique on-the-hour timestamps, positive prices,
consistent OHLC).

## 8. Consensus surprise

`actual − forecast` is computed only when numeric forecasts exist **and** the
forecast source URL maps to a source classified as reusable in
`config/data_sources.yaml`. No such source is currently available for
historical consensus values, so authentic reports state that the surprise is
unavailable. The synthetic demo catalogue contains synthetic forecasts only to
exercise this code path.

## 9. Determinism

All computations are pure functions of their inputs. Reports embed no
wall-clock time, round floats to six decimals and sort JSON keys, so
re-running the same inputs produces byte-identical JSON and Markdown.
