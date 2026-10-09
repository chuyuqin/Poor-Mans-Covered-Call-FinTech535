"""Render the GitHub Pages site from completed backtest results (no market requests)."""
from pathlib import Path
import json
import shutil
import html
import zipfile
import pandas as pd
from backtest import ROOT

DOCS=ROOT/'docs'
R=DOCS/'results'
NAMES={'pmcc':'Poor man’s covered call','covered_call':'Covered call','stock':'100 shares + cash'}
COLORS={'pmcc':'#183b56','covered_call':'#9a7134','stock':'#78888f'}

def money(v):return f'${v:,.2f}'
def pct(v):return f'{v:.2%}'
def table(headers,rows,primary=False):
    return '<div class="table-wrap"><table><thead><tr>'+''.join(f'<th scope="col">{h}</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr'+(' class="primary"' if primary and i==0 else '')+'>'+''.join(f'<td>{v}</td>' for v in row)+'</tr>' for i,row in enumerate(rows))+'</tbody></table></div>'
def head(title):
    return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="AMZN poor man’s covered call: investment research, historical results and implementation assumptions, 2023–2025."><title>{title}</title><link rel="stylesheet" href="assets/style.css"></head><body><a class="skip-link" href="#main">Skip to content</a>'
def nav(report=False):
    base='index.html' if report else ''
    return '<header class="topbar"><div class="bar"><a class="brand" href="index.html">QIN <span>/</span> INVESTMENT RESEARCH</a><nav aria-label="Main navigation">'+''.join(f'<a href="{base}#{target}">{label}</a>' for target,label in [('overview','Overview'),('design','Study design'),('results','Results'),('rules','Rules'),('blotter','Blotter'),('ledger','Ledger')])+'<a href="report.html">Research memo</a><a href="downloads/pmcc-source.zip">Source ZIP</a></nav></div></header>'
def section(id,num,title,extra=''):
    return f'<section id="{id}"><div class="section-heading"><h2><span class="section-num">{num}</span>{title}</h2>{extra}</div>'
def footer():
    return '<footer>FINTECH 535 · Assignment 1.3 · AMZN · 2023–2025<br>Historical-data backtest with simulated execution. Built from cached LSEG observations; no live trades. <a href="https://chuyuqin.github.io/Covered-Call-FinTech535/">Previous covered-call assignment</a>.</footer>'

def main():
    summaries=json.loads((R/'summary.json').read_text())
    stats={x['strategy']:x for x in summaries}
    pm,cc,bh=[stats[x] for x in ['pmcc','covered_call','stock']]
    robustness=json.loads((R/'robustness.json').read_text())
    cache=json.loads((ROOT/'data/cache_summary.json').read_text())
    data={'stats':stats,'robustness':robustness,'daily':{},'trades':{},'skips':{}}
    for strategy in NAMES:
        for key,suffix in [('daily','daily'),('trades','trades'),('skips','skips')]:
            frame=pd.read_csv(R/f'{strategy}_{suffix}.csv')
            data[key][strategy]=json.loads(frame.to_json(orient='records',double_precision=10))
    first=data['trades']['pmcc'][0]
    first_short=data['trades']['pmcc'][1]
    stock=pd.read_csv(ROOT/'data/raw/amzn_stock_2022_2025.csv',index_col=0)
    equivalent_stock=float(stock.loc[first['date'],'ASK'])*100
    saving=1-pm['initial_gross_capital']/equivalent_stock
    short_net=pm['short_premiums_collected']-pm['short_buyback_cost']-pm['short_calls_opened']*2*.65
    long_net=pm['net_profit']-short_net
    data['capital']={'same_day_stock':equivalent_stock,'saving':saving,'first_trade':first,'first_short':first_short,'short_net_profit':short_net,'long_net_profit':long_net}
    (DOCS/'assets/data.js').write_text('window.PMCC_DATA='+json.dumps(data,ensure_ascii=False,allow_nan=False).replace('<','\\u003c')+';\n')
    resulttable=table(['Strategy','Final account','Total return','CAGR','Max drawdown','Volatility','Commissions'],[[NAMES[s],money(stats[s]['ending_equity']),pct(stats[s]['total_return']),pct(stats[s]['cagr']),pct(stats[s]['max_drawdown']),pct(stats[s]['annualized_volatility']),money(stats[s]['fees'])] for s in NAMES],True)
    annualtable=table(['Strategy','2023','2024','2025'],[[NAMES[s]]+[pct(stats[s]['annual_returns'][y]) for y in ['2023','2024','2025']] for s in NAMES],True)
    sensitivity=table(['PMCC scenario','Return','Max drawdown','Assignments'],[[{'baseline':'Bid/ask + $0.65 per leg','double_fees':'Double commissions ($1.30)','extra_quarter_spread':'Extra ¼ spread beyond bid/ask','early_assignment_stress':'Low-extrinsic early assignment'}[s['scenario']],pct(s['total_return']),pct(s['max_drawdown']),s['assignments']] for s in robustness if s['strategy']=='pmcc'])
    legend='<div class="legend">'+''.join(f'<span><i class="dot" style="background:{COLORS[k]}"></i>{NAMES[k]}</span>' for k in NAMES)+'</div>'
    s=head('FINTECH 535 — Poor Man’s Covered Call')+nav()+'<main id="main">'
    s+=f'''<div class="hero" id="overview"><p class="eyebrow">Investment memorandum · October 9, 2026</p><h1>Poor man’s covered call<br><span class="subtle">AMZN research study</span></h1><p class="lead">I tested whether replacing 100 shares with a long-dated call reduces the cash needed for a covered-call strategy without materially weakening the result. The PMCC required less cash initially, but it did not outperform the conventional covered call.</p><span class="badge">AMZN · 3 JAN 2023 – 31 DEC 2025 · THREE YEARS</span><p class="meta">$50,000 starting account per strategy · No borrowing · Idle cash earns 0% · All positions closed by year-end 2025</p></div>
    <div class="metrics"><div class="metric"><label>PMCC account return</label><strong>{pct(pm['total_return'])}</strong><small>{money(pm['ending_equity'])} ending account value</small></div><div class="metric"><label>Initial long-call outlay</label><strong>${pm['initial_gross_capital']:,.0f}</strong><small>{saving:.1%} below 100 shares on the same date</small></div><div class="metric"><label>PMCC max drawdown</label><strong>{pct(pm['max_drawdown'])}</strong><small>100 shares + cash: {pct(bh['max_drawdown'])}</small></div><div class="metric"><label>Short calls written</label><strong>{pm['short_calls_opened']}</strong><small>{pm['option_leg_fills']} option-leg fills · {money(pm['fees'])} commissions</small></div></div>
    <div class="note"><strong>Assessment.</strong> PMCC is a workable substitute when reducing the initial cash commitment is the objective. This test does not support choosing it for higher returns: most of its profit came from the long calls, while selling short calls added only $635.20 after commissions. I would require a broader sample and broker-specific assignment checks before deploying it.</div>'''
    s+=section('design','01','Study design')
    s+='<p class="intro">The choices below define a manageable single-stock case study. They were not selected by comparing strategy returns across stocks or searching for the best parameter combination.</p>'
    s+=table(['Decision','Reason','What it leaves unresolved'],[
        ['AMZN','Listed calls, no cash dividends, and a test window after its June 2022 split simplify the stock-replacement comparison.','One surviving growth stock; no evidence of performance across other names.'],
        ['2023–2025 · three full years','A completed calendar-year sample permits repeated monthly trades and long-call replacements; it excludes partial-year 2026.','A strong rising-stock sample. Starting in 2023 omits the preceding decline; the window is not a full market-cycle test.'],
        ['0.80 long / 0.25 short delta','The long provides substantial stock exposure; the short leaves room for a rise before its strike is reached.','Judgment-based targets, not estimated optima. Delta does not eliminate loss or assignment risk.'],
        ['One contract · $50,000 per account','Equal starting cash and one 100-share contract unit make the cash flows directly comparable without borrowing.','Different delta and invested capital. Account returns depend on the deliberately idle cash balance.'],
        ['Monthly calls · fixed strike grid','A bounded, reproducible expired-contract universe keeps the historical download and selection process tractable.','Weeklies and intermediate strikes are omitted; this is not the full historical chain.']])
    s+='<p class="smallprint">The memo explains the maturity ranges, roll dates and execution filters. These choices are practical assumptions; the cost and assignment scenarios do not validate the parameter choices.</p></section>'
    s+=section('results','02','Account performance','<a href="results/summary.json" download>Download metrics ↗</a>')
    s+='<p class="intro">One diagonal, one covered call, or 100 shares. Each account starts with $50,000 and retains unused cash. All returns include modeled entry, roll and exit costs.</p>'+legend+'<div class="panel"><div id="equity-chart" class="chart" role="img" aria-label="Daily account equity for PMCC, covered call and stock"></div><div class="chart-caption">Daily liquidation-side marks: long assets at bid, short liabilities at ask. Hover to inspect values; drag to zoom; double-click to reset.</div></div><div style="height:18px"></div><div class="panel">'+resulttable+'</div><p class="smallprint">Volatility uses daily account returns × √252. CAGR uses elapsed calendar days. Drawdown includes the initial $50,000. Commissions are shown separately; quoted spreads are already embedded in returns.</p><div class="grid2"><div class="panel"><div id="drawdown-chart" class="chart small" role="img" aria-label="Account drawdowns"></div></div><div class="panel pad"><h3>Calendar-year returns</h3>'+annualtable+'<p class="smallprint">Continuous accounts, not annual resets. These are retrospective chronological slices, not an untouched out-of-sample experiment.</p></div></div></section>'
    s+=section('rules','03','Trading rules')
    s+='''<div class="grid2"><div class="panel pad"><h3>Build a one-to-one call diagonal</h3><div class="numberline"><span>1</span><p>Buy one in-the-money call: <strong>0.75–0.85 delta</strong>, <strong>365–540 days</strong> to expiration. Target 0.80 delta.</p></div><div class="numberline"><span>2</span><p>Sell one out-of-the-money call: <strong>0.20–0.30 delta</strong>, <strong>30–45 days</strong> to expiration. Target 0.25 delta; its strike must exceed the long strike.</p></div><div class="numberline"><span>3</span><p>Close the short after the prior session reaches <strong>7 days</strong> remaining. Replace the long after it reaches <strong>180 days</strong>, closing the short first.</p></div></div><div class="panel pad"><h3>Signal and execution timing</h3><div class="numberline"><span>t</span><p>Rank contracts using the <strong>previous session’s</strong> delta, quotes, volume and remaining maturity.</p></div><div class="numberline"><span>t+1</span><p>Use the selected contracts at the <strong>next session’s ask to buy and bid to sell</strong>. Reject failed entry checks; do not replace the contract using future Greeks.</p></div><p class="smallprint">Entries require positive two-sided quotes, spread ≤ $2 and ≤ 20% of midpoint, and at least one signal-day trade. New-pair debit plus fees must be below strike width × 100. Long purchase must be funded before short proceeds arrive.</p></div></div>'''
    s+=f'''<div class="note"><strong>The first simulated entry · {first['date']}:</strong> buy the ${first['strike']:g} call expiring {first['expiry']} for ${first['price']:.2f} per share; sell the ${first_short['strike']:g} call expiring {first_short['expiry']} for ${first_short['price']:.2f}. Net cash paid including both fees: <strong>{money(pm['initial_net_capital'])}</strong>. The long leg alone costs {money(pm['initial_gross_capital'])}; 100 shares at that day’s ask cost {money(equivalent_stock)}.</div><p class="smallprint">The first PMCC entry occurs one session after the stock benchmark starts. The capital comparison above uses the same date. Standard 100-share contracts are assumed; AMZN had no stock split or cash dividend during the test period. This is a cash-funded model, not a broker-specific margin calculation.</p></section>'''
    s+=section('risk','04','Execution & assignment sensitivity')+ '<div class="panel">'+sensitivity+'</div><p class="intro">The early-assignment scenario forces assignment when an in-the-money short call’s bid is within $0.05 of intrinsic value at the prior close. Shares are delivered at strike; a PMCC short-stock position is bought back at the next session’s ask. The long call is retained. This tests an adverse event path, not its probability.</p><p class="smallprint">Baseline early assignment is not modeled. Scheduled pre-expiry closes produced zero expiration assignments. AMZN paid no dividends, but American-call early exercise is still possible. Daily data do not establish synchronized or fresh executable quotes, depth, or atomic multi-leg fills.</p></section>'
    s+=section('blotter','05','Simulated trade blotter','<a id="trades-download" href="results/pmcc_trades.csv" download>Download trades CSV ↗</a>')
    choices=''.join(f'<option value="{k}">{v}</option>' for k,v in NAMES.items())
    s+=f'''<p class="intro">Every booked simulation event includes its signal date, execution date, cash effect and rule. These are model fills, not live executions.</p><div class="panel"><div class="toolbar"><div class="controls"><label for="trade-strategy">Strategy</label><select id="trade-strategy">{choices}</select></div><label>Find a date or contract <input id="trade-search" type="search" placeholder="e.g. 2024-06 or AMZNF"></label></div><div class="table-wrap"><table><thead><tr><th>Fill date / signal date</th><th>Contract / action</th><th>Qty</th><th>Fill</th><th>Fee</th><th>Cash flow</th><th>Rule</th></tr></thead><tbody id="trade-body"></tbody></table></div><div class="pagination"><button id="trade-prev" aria-label="Previous trades">← Previous</button><span id="trade-page" aria-live="polite"></span><button id="trade-next" aria-label="Next trades">Next →</button></div></div></section>'''
    s+=section('ledger','06','Daily account ledger','<a id="ledger-download" href="results/pmcc_daily.csv" download>Download daily CSV ↗</a>')
    s+=f'''<p class="intro">Account value = cash + stock value + long-call value − short-call liability. Premium receipts remain cash flows until the offsetting liabilities and closing trades are accounted for.</p><div class="panel"><div class="toolbar"><div class="controls"><label for="ledger-strategy">Strategy</label><select id="ledger-strategy">{choices}</select></div><label>Filter date <input id="ledger-search" type="search" placeholder="e.g. 2025-04"></label></div><div class="table-wrap"><table><thead><tr><th>Date</th><th>Cash</th><th>Stock value</th><th>Long call</th><th>Short liability</th><th>Account value</th><th>Net delta, shares</th></tr></thead><tbody id="ledger-body"></tbody></table></div><div class="pagination"><button id="ledger-prev" aria-label="Previous ledger rows">← Previous</button><span id="ledger-page" aria-live="polite"></span><button id="ledger-next" aria-label="Next ledger rows">Next →</button></div></div></section>'''
    s+=section('writeup','07','Interpretation','<a href="report.html">Read the research memo ↗</a>')
    s+=f'''<div class="grid2"><div class="analysis-text"><h3>Lower initial outlay; no return advantage.</h3><p>The PMCC produced {money(pm['net_profit'])} of net profit on a $50,000 account. The initial long-call purchase required less cash than 100 shares. The covered-call account finished {money(cc['ending_equity']-pm['ending_equity'])} ahead. I would treat the cash saving as a funding choice, not evidence of higher expected returns.</p><p>The long call adds expiration, time-decay and volatility exposure. The short call gives up part of a rally. AMZN’s strong rise over this sample makes this a favorable setting for bullish exposure; one stock and three years cannot establish robustness across market regimes.</p></div><div class="panel pad"><h3>Short-call profit contribution</h3>{table(['PMCC contribution','Amount'],[['Short premiums received',money(pm['short_premiums_collected'])],['Short calls bought back','−'+money(pm['short_buyback_cost'])],['Short-leg commissions','−'+money(pm['short_calls_opened']*2*.65)],['Short-leg net profit',money(short_net)],['Long-leg net profit',money(long_net)]])}<p class="smallprint">The long-call P&amp;L supplied most of the strategy’s profit. Short-call proceeds alone would overstate the benefit of selling options.</p></div></div></section>'''
    s+=section('data','08','Data & reproducibility')
    s+=f'''<div class="grid2"><div class="panel pad"><h3>{cache['backtest_period_option_rows']:,} option-day records</h3><p class="intro">LSEG Workspace history, cached October 6, 2026. A fixed grid of monthly calls: $40–$300 strikes in $5 steps. {cache['contracts_with_any_observation']:,} contracts have observations; this is a subset of the historical chain.</p><p class="smallprint">752 stock sessions in 2023–2025; December 2022 warmup. 47 expiration groups contain history. October and November 2026 expirations returned no observations for the requested dates. Raw vendor data remain local.</p></div><div class="panel pad"><h3>Audit trail</h3><p class="intro">All 50 cached response checksums passed. Seven engine tests cover cash conservation, collateral, signal lag, missing-price handling and physical assignment. The baseline used zero carried marks.</p><div class="downloads"><a class="button-link" href="results/run_manifest.json" download>Run manifest</a><a class="button-link" href="results/pmcc_skips.csv" download>Skipped decisions</a><a class="button-link" href="results/cache_summary.json" download>Coverage</a><a class="button-link" href="downloads/pmcc-source.zip" download>Source ZIP</a></div></div></div><details><summary>Reproduce the study</summary><p class="intro">The complete source bundle includes configuration, fetcher, engine, tests, site generator and cached derived results. Rebuilding the analysis requires an entitled LSEG Workspace account or the same local raw cache.</p><pre>python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python src/fetch_lseg.py
.venv/bin/python src/audit_cache.py
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python src/backtest.py
.venv/bin/python src/robustness.py
.venv/bin/python src/build_site.py</pre><p class="smallprint">Serve the <code>docs/</code> directory with GitHub Pages. The published site is static and does not require access to LSEG.</p></details></section></main>'''
    s+=footer()+'<script src="assets/plotly.min.js"></script><script src="assets/data.js"></script><script src="assets/app.js"></script></body></html>'
    (DOCS/'index.html').write_text(s)
    report=f'''# Poor man’s covered call: AMZN

To: Investment Strategy Team · From: Chuyu Qin · Date: October 9, 2026

Historical period: January 3, 2023–December 31, 2025 · Three calendar years

## Assessment

I tested a poor man’s covered call (PMCC) against a conventional covered call and a 100-share stock position. Each account started with $50,000 and held unused cash. After modeled spreads and commissions, PMCC returned {pct(pm['total_return'])}, compared with {pct(cc['total_return'])} for the covered call and {pct(bh['total_return'])} for stock plus cash.

The PMCC reduced the initial cash required for the long position by {saving:.1%}: {money(pm['initial_gross_capital'])} for the call versus {money(equivalent_stock)} for 100 shares on the same date. It did not improve returns. I would consider it when the objective is to commit less cash to a bullish position, but this study is not enough to recommend live deployment. The next test should cover a sustained decline, another stock, and the broker’s assignment and margin procedures.

## Why AMZN and why these dates

I chose AMZN before comparing strategy returns. It has listed options, pays no cash dividend, and completed its latest split in June 2022, before the sample. This keeps dividend-related exercise incentives and a split out of the main experiment. Historical quote availability was checked in LSEG; a large-cap name alone is not a guarantee of executable option quotes.

The period is three years, not two: 2023, 2024 and 2025. Three complete calendar years provide repeated short-call trades and long-call replacements while avoiding a partial 2026 year. This is a practical scope choice, not a statistically optimal sample length. Starting in 2023 also excludes the preceding decline. AMZN rose strongly during the test, so the results mainly describe the strategy in a favorable period for bullish exposure. Choosing a successful surviving company in 2026 adds selection bias even though I did not choose it by backtest return. Neither choice establishes performance across a full market cycle.

## What the strategy is intended to do

The PMCC buys an in-the-money, long-dated call instead of 100 shares and sells a shorter-dated call against it. The short premium offsets part of the long call’s cost, at the expense of some upside. Unlike stock, the long call expires and is exposed to time decay and changes in implied volatility. It can lose its entire purchase price. A short-call assignment does not automatically exercise the long call.

I use a long delta target of 0.80 to retain substantial stock exposure while reducing the cash outlay. The 0.25 short target leaves room for a price increase before the short strike is reached. Eligible ranges are 0.75–0.85 and 0.20–0.30. These are judgment-based starting rules, not parameters fitted to maximize returns. They also mean the PMCC starts with less directional exposure than 100 shares; it is not an equal-delta comparison.

The long must have 365–540 calendar days remaining. That allows several monthly short-call trades before replacement. The short must have 30–45 days remaining, giving a repeatable monthly cycle. I close the short after the prior session reaches seven days to expiry and replace the long after it reaches 180 days, closing the short first. These buffers limit reliance on near-expiry positions but do not prevent early assignment. Their exact thresholds have not been validated by a parameter sensitivity study.

## Portfolio and contract selection

Each strategy trades one 100-share unit in a $50,000 cash account, without borrowing. The covered call owns 100 shares and uses the same short-call rules; the stock benchmark owns 100 shares with no options. Holding the contract count fixed makes the cash flows comparable and prevents the PMCC’s cash saving from being reinvested as additional leverage. The $50,000 balance is an accounting convention, not a minimum funding requirement. Account returns and drawdowns depend on that cash balance. Idle cash earns zero interest, so the study does not measure the benefit of investing the released cash elsewhere.

The candidate universe contains monthly calls at $40–$300 strikes in $5 increments. This bounds the historical download and makes the universe reproducible. It omits weeklies, intermediate strikes and contracts outside the grid. Contracts are ranked by distance from the target delta, then from 450 days for the long or 35 for the short, then strike (lower long, higher short), then RIC. The long strike must be below spot; the short strike must be above spot and the long strike. New-pair debit including fees must be less than strike width × 100.

Entries require positive bid and ask quotes, a spread no greater than both $2 and 20% of midpoint, and at least one trade on the signal day. The absolute and relative caps screen out visibly wide quotes; one trade is only a minimum activity check. These thresholds do not prove liquidity or executable size. If the selected entry fails, the engine waits rather than choosing a different contract using that day’s Greeks. With no eligible pair it holds cash; with no eligible short it retains the long call or stock alone.

## Data and execution

LSEG supplied {cache['backtest_period_option_rows']:,} option-day observations for 2023–2025, plus December 2022 warmup. The cache includes expired contracts and historical bid, ask, delta and volatility fields. It was downloaded in October 2026. Vendor corrections and the exact timing and model conventions of the Greeks were not independently checked.

Signals use the previous stock session. The selected contracts trade at the next session’s ask for purchases and bid for sales, subject to quote and funding checks. These are daily execution proxies. I do not assume midpoint fills. Option commissions are $0.65 per contract per transaction; stock commissions are zero. Both entry quotes must qualify before a pair is booked, and cash must fund the long before the short premium is credited. This assumes paired execution that daily data cannot verify.

The first PMCC entry was {first['date']}: buy the $70 June 2024 call and sell the $100 February 2023 call, for a net debit of {money(pm['initial_net_capital'])} including fees. The stock accounts began one session earlier. The initial capital comparison uses the PMCC entry date for both instruments.

Daily account value is cash plus stock and long-call value at bid, less short-call liability at ask. Closing trades require an observed price on the execution side. Valuation can carry a missing mark for at most two sessions, explicitly flagged; the baseline needed none. All final positions are liquidated with costs included. The PMCC closed its last long in the scheduled December 2025 roll and remained in cash because no replacement qualified.

## Results and assignment risk

PMCC earned {money(pm['net_profit'])}. The short calls collected {money(pm['short_premiums_collected'])}, but cost {money(pm['short_buyback_cost'])} to close. After short-leg commissions, they contributed {money(short_net)}; the long calls contributed {money(long_net)}. The result was driven mainly by bullish long-call exposure. This attribution does not measure the opportunity cost against holding the long calls alone.

Maximum account drawdown was {pct(pm['max_drawdown'])}, versus {pct(bh['max_drawdown'])} for stock plus cash. That difference partly reflects different exposure and cash holdings. It should not be read as evidence that the option position itself carries less risk.

Doubling commissions reduced the PMCC return to 28.84%. Charging an additional quarter-spread beyond bid/ask reduced it to 28.35%. If the opposite quote is absent on a closing trade, that stress uses a spread estimate of 20% of the execution-side price, with a $0.01 floor. These scenarios address execution costs, not the robustness of the chosen stock, dates or delta targets.

The baseline assumes no early assignment; scheduled pre-expiry closes produced no expiry assignments. A separate scenario assigns an in-the-money short when its prior-close bid has no more than $0.05 of extrinsic value. It delivers shares at strike, retains the long call, and covers the resulting PMCC short-stock position at the next session’s ask. One assignment occurred and the PMCC returned 28.55%. This tests a specified adverse path, not assignment probability. Borrow availability, overnight financing, broker intervention and margin requirements remain outside the model.

## Review and reproduction

The website includes daily accounts, trade records, skipped decisions, configuration and source code. Seven tests check accounting, prior-session selection, collateral, missing prices and physical assignment. Ending cash reconciles to the trade records. Reproduction uses Python 3.12, pinned dependencies and either the retained raw cache or an entitled LSEG session; raw vendor data remain outside the public source bundle.

Daily observations cannot verify quote age, synchronization, market depth or actual multi-leg fills. Standard 100-share deliverables are assumed; individual adjustment notices were not independently audited. Taxes and interest are excluded. The engine was checked across the full sample, so the annual results are not an untouched holdout. The conclusion is limited to this implementation and sample: less initial cash was required, with no observed return advantage over the conventional covered call.

## References

- [Amazon investor FAQ: dividends and stock splits](https://ir.aboutamazon.com/faqs/default.aspx)
- [Options Industry Council: strategy FAQ](https://www.optionseducation.org/referencelibrary/faq/strategies)
- [Options Industry Council: assignment and exercise risk](https://www.optionseducation.org/videolibrary/assignment-and-exercise-risk)
- [LSEG: Python desktop session](https://developers.lseg.com/en/api-catalog/lseg-data-platform/lseg-data-library-for-python/quick-start)
- [LSEG: option RIC construction](https://developers.lseg.com/en/article-catalog/article/functions-to-find-option-rics-traded-on-different-exchanges)
'''
    (ROOT/'REPORT.md').write_text(report)
    # Minimal deterministic Markdown renderer for this controlled report source.
    import re
    parts=[]
    for block in report.strip().split('\n\n'):
        if block.startswith('# '): parts.append('<h1>'+html.escape(block[2:])+'</h1>')
        elif block.startswith('## '): parts.append('<h2>'+html.escape(block[3:])+'</h2>')
        elif block.startswith('- '):
            links=[]
            for line in block.splitlines():
                label,url=re.match(r'- \[(.*?)\]\((.*?)\)',line).groups()
                links.append(f'<li><a href="{html.escape(url)}">{html.escape(label)}</a></li>')
            parts.append('<ul>'+''.join(links)+'</ul>')
        else: parts.append('<p>'+html.escape(block)+'</p>')
    report_html=head('AMZN PMCC — Investment memorandum')+nav(True)+'<main id="main" class="report"><div class="hero"><p class="eyebrow">Chuyu Qin · Investment research</p><div class="downloads no-print"><a class="button-link" href="index.html">← Back to results</a><button onclick="window.print()">Print / save PDF</button><a class="button-link" href="downloads/REPORT.md" download>Download Markdown</a></div></div>'+''.join(parts[:6])+'<div class="panel">'+resulttable+'</div>'+''.join(parts[6:])+'</main>'+footer()+'</body></html>'
    (DOCS/'report.html').write_text(report_html)
    (DOCS/'downloads').mkdir(exist_ok=True)
    shutil.copy2(ROOT/'REPORT.md',DOCS/'downloads/REPORT.md')
    shutil.copy2(ROOT/'data/cache_summary.json',R/'cache_summary.json')
    shutil.copy2(ROOT/'config.json',R/'config.json')
    with zipfile.ZipFile(DOCS/'downloads/pmcc-source.zip','w',zipfile.ZIP_DEFLATED) as z:
        for path in sorted(ROOT.rglob('*')):
            rel=path.relative_to(ROOT)
            if not path.is_file() or any(x in rel.parts for x in ['raw','development','__pycache__','.git','.venv']) or path.suffix=='.zip':continue
            z.write(path,rel)
    print('Generated docs/index.html, docs/report.html, REPORT.md, data.js and source ZIP')

if __name__=='__main__':main()
