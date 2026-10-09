"""Fetch a fixed AMZN monthly-call research universe through Workspace.

Raw vendor data stays local. This file never saves session credentials.
Requires a running, signed-in Workspace desktop and lseg-data.
"""
import argparse
import calendar
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import time
import lseg.data as ld
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'raw'
FIELDS = ['BID', 'ASK', 'TRDPRC_1', 'OPEN_PRC', 'ACVOL_UNS', 'OPINT_1', 'DELTA', 'IMP_VOLT']

def save_request(name, request):
    csv = RAW / (name + '.csv')
    manifest = csv.with_suffix('.json')
    if csv.exists() and manifest.exists():
        meta = json.loads(manifest.read_text())
        if meta.get('request') == request and meta.get('sha256') == hashlib.sha256(csv.read_bytes()).hexdigest():
            return meta
    df = ld.get_history(**request)
    if df is None:
        raise ValueError('No response dataframe returned')
    # Retain the provider's column headers, including both levels for batched RICs.
    tmp = csv.with_suffix('.tmp')
    df.to_csv(tmp)
    tmp.replace(csv)
    meta = {'request': request, 'retrieved_utc': datetime.now(timezone.utc).isoformat(),
            'status': 'no_observations' if df.empty else 'observations',
            'rows': len(df), 'columns': [list(x) if isinstance(x, tuple) else str(x) for x in df.columns],
            'non_null_cells': int(df.notna().sum().sum()),
            'first_observation': str(df.index.min()), 'last_observation': str(df.index.max()),
            'sha256': hashlib.sha256(csv.read_bytes()).hexdigest(), 'library_version': ld.__version__}
    manifest.write_text(json.dumps(meta, indent=2))
    return meta

def contracts():
    # Fixed strike grid chosen before observing strategy results. This intentionally
    # excludes weeklies and non-$5 strikes and is not a complete historical chain.
    rows = []
    today = date.today()
    for year in range(2023, 2028):
        for month in range(1, 13):
            if (year, month) > (2027, 1):
                continue
            day = next(w[calendar.FRIDAY] for w in calendar.monthcalendar(year, month)
                       if 15 <= w[calendar.FRIDAY] <= 21)
            expiry = date(year, month, day)
            # Good Friday 2025: the monthly contract expires Thursday April 17.
            if expiry == date(2025, 4, 18):
                expiry = date(2025, 4, 17)
            # Juneteenth 2026 also shifts the standard expiration to Thursday.
            if expiry == date(2026, 6, 19):
                expiry = date(2026, 6, 18)
            for strike in range(40, 301, 5):
                monthcode = 'ABCDEFGHIJKL'[month-1]
                ric = f'AMZN{monthcode}{expiry.day}{year%100:02d}{strike*100:05d}.U'
                if expiry < today:
                    ric += f'^{monthcode}{year%100:02d}'
                rows.append({'ric': ric, 'expiry': expiry.isoformat(), 'strike': strike,
                             'right': 'C', 'underlying': 'AMZN.O', 'status': 'candidate_not_verified'})
    return pd.DataFrame(rows)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--max-groups', type=int, default=None)
    parser.add_argument('--start-group', type=int, default=0, help='Zero-based first expiry group to fetch')
    args = parser.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    universe = contracts()
    universe.to_csv(RAW/'candidate_contracts.csv', index=False)
    ld.open_session()
    failures = []
    try:
        meta = save_request('amzn_stock_2022_2025', dict(universe='AMZN.O', fields=['OPEN_PRC','HIGH_1','LOW_1','TRDPRC_1','BID','ASK','ACVOL_UNS'], start='2022-12-01', end='2025-12-31', interval='1D', adjustments='unadjusted', count=2000))
        print(f"Stock cached: {meta['rows']} daily rows", flush=True)
        for i, (expiry, frame) in enumerate(universe.groupby('expiry')):
            if i < args.start_group:
                continue
            if args.max_groups is not None and i >= args.start_group + args.max_groups:
                break
            # Cover up to 600 days before expiration, plus warmup prior to 2023.
            start = max(date(2022,12,1),date.fromisoformat(expiry)-timedelta(days=600))
            end = min(date(2025,12,31),date.fromisoformat(expiry))
            req = dict(universe=frame.ric.tolist(),fields=FIELDS,start=start.isoformat(),end=end.isoformat(),interval='1D',adjustments='unadjusted',count=2000)
            name = 'calls_' + expiry
            try:
                meta = save_request(name, req)
                print(f"{i+1}/49 {expiry}: {meta['rows']} dates, {meta['non_null_cells']} populated cells", flush=True)
            except Exception as exc:
                failures.append({'expiry':expiry,'error':str(exc)[:1500], 'request':req})
                print(f'{expiry}: request failed ({type(exc).__name__})',flush=True)
            time.sleep(0.3)
    finally:
        ld.close_session()
        (RAW/('failures.json' if args.start_group == 0 else f'failures_from_{args.start_group}.json')).write_text(json.dumps(failures,indent=2))
    print(f'Finished; failed groups: {len(failures)}',flush=True)

if __name__ == '__main__':
    main()
