# Cached LSEG data: AMZN

This report audits the cached input data. Strategy results and execution assumptions are documented in the website and research write-up.

| Check | Result |
|---|---:|
| Cached expiration responses | 49 |
| Expirations with observations | 47 |
| Candidate contracts | 2,597 |
| Contracts with observations | 1,958 |
| Option contract-day records | 370,406 |
| 2023–2025 stock observations | 752 |
| 2023–2025 positive two-sided option quotes | 352,201 |
| 2023–2025 option records with valid delta | 361,812 |
| 2023–2025 days with both proposed delta/maturity windows | 382 |
| Crossed quotes | 0 |
| Raw response checksums verified | 50 |

## Coverage limits

- Fixed $40–$300 strikes in $5 increments; monthly calls only, not a full chain.
- Daily summary quotes do not establish intraday quote freshness or executable fills.
- Vendor DELTA and IMP_VOLT are cached where available; their calculation and timestamp conventions need verification. Dividends, deliverables and corporate actions not yet validated.
- Constructed RIC candidates with no data are not assumed to have been listed.
- A positive bid and ask check is not proof of liquidity or contract suitability.

The count of days with both delta/maturity windows ignores the strike ordering, debit, cash, spread-width and execution checks. It measures data availability, not trade eligibility. Monthly rolls do not require a fresh eligible long call every day.

The fixed universe can omit suitable contracts; no claim is made that it reconstructs the full historical chain. Missing values are preserved. See `data/raw/contract_coverage.csv`, `daily_maturity_coverage.csv` and `candidates_without_observations.csv` for local details.

Raw data remain local and are excluded from Git. Each raw request has a JSON manifest with its parameters, timestamp and checksum. See README.md for reproduction.

Empty responses (no observations returned for the requested period): calls_2026-10-16.csv, calls_2026-11-20.csv
