"""Verify cache checksums and summarize observations without imputing prices."""
from pathlib import Path
import hashlib
import json
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT/'data'/'raw'

def main():
    candidates = pd.read_csv(RAW/'candidate_contracts.csv').set_index('ric')
    frames, details, checks, older_field_groups, empty_groups = [], [], [], [], []
    for path in sorted(RAW.glob('calls_*.csv')):
        meta = json.loads(path.with_suffix('.json').read_text())
        assert hashlib.sha256(path.read_bytes()).hexdigest() == meta['sha256'], path
        if not {'DELTA','IMP_VOLT'}.issubset(meta['request'].get('fields',[])):
            older_field_groups.append(path.name)
        if meta['rows'] == 0:
            checks.append({'file':path.name,'sha256':meta['sha256'],'rows':0})
            empty_groups.append(path.name)
            continue
        df = pd.read_csv(path,header=[0,1],index_col=0,parse_dates=True)
        assert not df.index.duplicated().any(), path
        checks.append({'file':path.name,'sha256':meta['sha256'],'rows':len(df)})
        for ric in df.columns.get_level_values(0).unique():
            block = df[ric].apply(pd.to_numeric,errors='coerce')
            block = block.dropna(how='all').copy()
            if block.empty:
                continue
            assert ric in candidates.index, ric
            block.index.name = 'date'
            block = block.reset_index()
            info = candidates.loc[ric]
            block['ric'] = ric
            block['expiry'] = info.expiry
            block['strike'] = info.strike
            block['right'] = 'C'
            block['positive_two_sided_quote'] = (block.BID>0)&(block.ASK>=block.BID)
            block['crossed_quote'] = (block.BID>block.ASK)
            block['valid_vendor_delta'] = block.get('DELTA', pd.Series(index=block.index, dtype=float)).between(0,1)
            block['positive_vendor_iv'] = block.get('IMP_VOLT', pd.Series(index=block.index, dtype=float)).gt(0)
            assert (block.date <= pd.Timestamp(info.expiry)).all(), ric
            details.append({'ric':ric,'expiry':info.expiry,'strike':int(info.strike),
                            'rows':len(block),'positive_two_sided_quotes':int(block.positive_two_sided_quote.sum()),
                            'rows_with_valid_delta':int(block.valid_vendor_delta.sum()),
                            'first_date':str(block.date.min().date()),'last_date':str(block.date.max().date())})
            frames.append(block)
    if not frames:
        raise ValueError('No cached option observations')
    all_data = pd.concat(frames,ignore_index=True)
    assert not all_data.duplicated(['date','ric']).any()
    all_data = all_data.sort_values(['date','ric'],kind='stable').reset_index(drop=True)
    all_data.to_csv(RAW/'options_normalized.csv.gz',index=False,compression={'method':'gzip','mtime':0})
    pd.DataFrame(details).to_csv(RAW/'contract_coverage.csv',index=False)
    observed_rics = {r['ric'] for r in details}
    candidates.loc[~candidates.index.isin(observed_rics)].to_csv(RAW/'candidates_without_observations.csv')
    stock_path = RAW/'amzn_stock_2022_2025.csv'
    stock_meta = json.loads(stock_path.with_suffix('.json').read_text())
    assert hashlib.sha256(stock_path.read_bytes()).hexdigest()==stock_meta['sha256']
    stock = pd.read_csv(stock_path,index_col=0,parse_dates=True)
    in_period = all_data.loc[all_data.date.between('2023-01-01','2025-12-31')]
    usable = in_period.loc[in_period.positive_two_sided_quote].copy()
    usable['dte'] = (pd.to_datetime(usable.expiry)-usable.date).dt.days
    dates = stock.index[(stock.index>='2023-01-01')&(stock.index<='2025-12-31')]
    coverage = pd.DataFrame(index=dates)
    for label, low, high in [('short_dte_30_45',30,45),('long_dte_365_540',365,540)]:
        coverage[label]=usable.loc[usable.dte.between(low,high)].groupby('date').size().reindex(dates,fill_value=0)
    for label, low, high, dlo, dhi in [('short_delta_eligible',30,45,0.20,0.30),('long_delta_eligible',365,540,0.75,0.85)]:
        selection = usable.loc[usable.dte.between(low,high) & usable.get('DELTA',pd.Series(index=usable.index,dtype=float)).between(dlo,dhi)]
        coverage[label] = selection.groupby('date').size().reindex(dates,fill_value=0)
    coverage.to_csv(RAW/'daily_maturity_coverage.csv')
    summary = {'candidate_contracts':len(candidates),'downloaded_expiry_groups':len(checks),
               'expiry_groups_without_greek_request':older_field_groups,
               'expiry_groups_with_observations':len(checks)-len(empty_groups),
               'expiry_groups_returning_no_observations':empty_groups,
               'contracts_with_any_observation':len(details),'option_daily_rows':len(all_data),
               'backtest_period_option_rows':len(in_period),
               'backtest_period_positive_two_sided_quotes':int(in_period.positive_two_sided_quote.sum()),
               'backtest_period_rows_with_valid_delta':int(in_period.valid_vendor_delta.sum()),
               'backtest_period_rows_with_positive_iv':int(in_period.positive_vendor_iv.sum()),
               'days_with_both_delta_windows':int(((coverage.short_delta_eligible>0)&(coverage.long_delta_eligible>0)).sum()),
               'crossed_quotes':int(all_data.crossed_quote.sum()),'stock_rows':len(stock),
               'stock_backtest_period_rows':len(dates),
               'days_with_short_maturity_quotes':int((coverage.short_dte_30_45>0).sum()),
               'days_with_long_maturity_quotes':int((coverage.long_dte_365_540>0).sum()),
               'raw_files_checksum_verified':len(checks)+1,
               'data_start':str(all_data.date.min().date()),'data_end':str(all_data.date.max().date()),
               'limitations':['Fixed $40–$300 strikes in $5 increments; monthly calls only, not a full chain.',
                              'Daily summary quotes do not establish intraday quote freshness or executable fills.',
                              'Vendor DELTA and IMP_VOLT are cached where available; their calculation and timestamp conventions need verification. Dividends, deliverables and corporate actions not yet validated.',
                              'Constructed RIC candidates with no data are not assumed to have been listed.',
                              'A positive bid and ask check is not proof of liquidity or contract suitability.']}
    (ROOT/'data'/'cache_summary.json').write_text(json.dumps(summary,indent=2))
    report = ["# Cached LSEG data: AMZN", "", "This report audits the cached input data. Strategy results and execution assumptions are documented in the website and research write-up.", "", "| Check | Result |", "|---|---:|"]
    for label, key in [("Cached expiration responses", "downloaded_expiry_groups"), ("Expirations with observations", "expiry_groups_with_observations"), ("Candidate contracts", "candidate_contracts"), ("Contracts with observations", "contracts_with_any_observation"), ("Option contract-day records", "option_daily_rows"), ("2023–2025 stock observations", "stock_backtest_period_rows"), ("2023–2025 positive two-sided option quotes", "backtest_period_positive_two_sided_quotes"), ("2023–2025 option records with valid delta", "backtest_period_rows_with_valid_delta"), ("2023–2025 days with both proposed delta/maturity windows", "days_with_both_delta_windows"), ("Crossed quotes", "crossed_quotes"), ("Raw response checksums verified", "raw_files_checksum_verified")]:
        report.append(f"| {label} | {summary[key]:,} |")
    report += ["", "## Coverage limits", ""] + [f"- {x}" for x in summary["limitations"]]
    report += ["", "The count of days with both delta/maturity windows ignores the strike ordering, debit, cash, spread-width and execution checks. It measures data availability, not trade eligibility. Monthly rolls do not require a fresh eligible long call every day.", "", "The fixed universe can omit suitable contracts; no claim is made that it reconstructs the full historical chain. Missing values are preserved. See `data/raw/contract_coverage.csv`, `daily_maturity_coverage.csv` and `candidates_without_observations.csv` for local details.", "", "Raw data remain local and are excluded from Git. Each raw request has a JSON manifest with its parameters, timestamp and checksum. See README.md for reproduction.", ""]
    if empty_groups:
        report += ['Empty responses (no observations returned for the requested period): ' + ', '.join(empty_groups), '']
    if older_field_groups:
        report += ["Some batches still use the earlier quote-only fields: " + ", ".join(older_field_groups), ""]
    (ROOT / "DATA_REPORT.md").write_text("\n".join(report))
    print(json.dumps(summary,indent=2))

if __name__=='__main__':
    main()
