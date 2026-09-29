# data/

Everything under `data/` is git-ignored by default (see `.gitignore`).
Only the entries below are part of the public repository.

| Path | Public? | Contents |
|---|---|---|
| `demo/` | yes | Documented demonstration data: synthetic releases, synthetic candles and one reviewed official record. Every file is declared in `demo/demo_manifest.yaml`. |
| `raw/`, `processed/`, `reports/` | placeholders only | Local working folders; generated outputs stay on your machine. |
| `historical_releases/` | **no** | Private research catalogue (January 2024 slice). Mixed-source data; not distributed. |
| anything else | **no** | Default-denied. |

See `DATA_SOURCES.md` for the data-rights policy and run
`python scripts/check_publication_safety.py` before publishing.
