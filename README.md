# Poor Man’s Covered Call — FINTECH 535, Assignment 1.3

A static GitHub Pages website and research write-up for a one-contract AMZN PMCC, compared with a conventional covered call and 100 shares plus cash. Historical period: January 3, 2023–December 31, 2025. Each account starts with $50,000.

**Baseline result:** PMCC +28.94%, covered call +31.18%, stock plus cash +28.99%. PMCC's initial long call required $2,810.65 versus $8,515 for 100 shares on the same date. These are different exposures; a smaller cash outlay does not establish a superior leveraged investment.

- Website: [docs/index.html](docs/index.html)
- Full write-up: [REPORT.md](REPORT.md), or [printable HTML](docs/report.html)
- Data audit: [DATA_REPORT.md](DATA_REPORT.md)
- Configuration: [config.json](config.json)
- Derived daily equity, trades, skipped decisions and sensitivities: [docs/results](docs/results)

## Run locally

Python 3.12 was used. The running LSEG/Refinitiv Workspace desktop is needed only for fetching raw data. No password or app key is embedded in these scripts.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python src/fetch_lseg.py
.venv/bin/python src/audit_cache.py
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python src/backtest.py
.venv/bin/python src/robustness.py
.venv/bin/python src/build_site.py
.venv/bin/python -m http.server 8767 --bind 127.0.0.1 --directory docs
```

If the identical raw cache is already present, skip the fetch step. If you only want to view the saved results, serve `docs/` directly; no data subscription is required. Plotly is bundled locally, so charts do not rely on a CDN.

## Publish on GitHub Pages

Push this project to the intended GitHub repository. In **Settings → Pages**, choose **Deploy from a branch**, the main branch, and **/docs**. Submit the resulting Pages URL. The repository includes a `.nojekyll` file and requires no server-side runtime or build service. Keep the previous assignment separate unless intentionally adding this as a new subsection.

## Method

Select contracts using prior-session historical Greeks and quotes. Execute the selected contracts at the next session's bid/ask proxy. Entry filters, deterministic ranking, cash checks, roll rules and fees are fixed in `config.json`. This is a one-lot, cash-funded experiment with zero interest on idle cash. It is not a broker margin simulator.

The baseline assumes no early assignment; an explicit physical-assignment sensitivity is reported separately. Expiry assignment is supported in the engine. New PMCC pairs require both quotes before booking the long then short, which assumes conditional paired execution. Daily data cannot demonstrate that both legs could actually fill simultaneously.

Seven tests cover cash reconciliation, terminal liquidation, prior-session selection, collateral, missing quotes and physical assignment. The private-cache integration test runs when local data are present and is skipped otherwise. Tests use both small constructed accounting fixtures and the real historical dataset; fixtures never supply the published performance results.

No parameter sweep selected these results. The implementation was first checked on 2023 and then across the full sample; annual results are chronological slices rather than a claimed untouched holdout.

## Data cache

The initial cache contains 752 stock observations and 362,300 option contract-day records for 2023–2025, plus December 2022 warmup. The candidate universe has 49 monthly expirations, January 2023–January 2027, and $40–$300 strikes in $5 increments. 1,958 contracts across 47 expirations have observations. October and November 2026 expiration requests return no observations in the requested period.

`data/raw/` holds original responses, SHA-256 manifests, normalized data and coverage diagnostics. Every successful response, including an empty response, is cached. Requests with matching parameters and checksums are skipped on reruns. `failures.json` describes errors from the most recent complete fetch pass.

Quote history contains BID, ASK, TRDPRC_1, OPEN_PRC, ACVOL_UNS, OPINT_1, DELTA and IMP_VOLT where available. Delta is a fraction; implied volatility is reported in percent. Greeks' exact observation-time/model conventions are not independently verified. Open interest is cached but not used for selection. A current-day field is required on the side used to close/mark; no quote is invented from a missing opposite side.

Raw vendor data are ignored by Git. The public site contains derived simulation results and a small simulated trade ledger, not the full option-price dataset. Check the applicable LSEG redistribution terms before publishing any additional raw data. No brokerage trades are placed by this project.

## Files

- `src/fetch_lseg.py`: desktop-session downloads; holiday-aware RIC construction for this fixed grid.
- `src/audit_cache.py`: raw checksums, normalization and coverage report.
- `src/backtest.py`: event accounting and baseline comparison.
- `src/robustness.py`: commission, spread and early-assignment scenarios.
- `src/build_site.py`: static website, research note and source ZIP.
- `tests/test_engine.py`: accounting and timing tests.

The run manifest records configuration and hashes of the engine and normalized inputs. Historical vendor corrections can make a future download differ; retaining the original local cache gives the strongest reproducibility.
