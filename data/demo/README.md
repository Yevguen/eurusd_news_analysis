# data/demo/ - public demonstration data

| File | Origin | Notes |
|---|---|---|
| `synthetic_releases.jsonl` | **SYNTHETIC** | Five invented release records dated January 2030 with placeholder values. Not real publications. |
| `SYNTHETIC_eurusd_h1_mt5_format.csv` | **SYNTHETIC** | Invented EUR/USD-like H1 candles (2-12 January 2024, weekdays) in MT5 export layout. Starts at 1.00000; pure noise with no injected event effect. Not market data. |
| `official_releases_allowlist.jsonl` | AUTHENTIC | One reviewed record from the U.S. Bureau of Labor Statistics (public domain): the CPI release for December 2023, published 2024-01-11 08:30 ET. Source: U.S. Bureau of Labor Statistics. |
| `demo_manifest.yaml` | - | Declares origin and source for every data file here; enforced by `scripts/check_publication_safety.py`. |

Regenerate the synthetic files with `python scripts/generate_synthetic_demo_data.py`
(`--check` verifies they are current).
