"""Daily event replay of one-lot AMZN call diagonals, covered calls and stock.
Selection at session t; conditional bid/ask fills at session t+1 close.
Historical summary quotes are execution proxies, not verified executable NBBOs.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
from collections import Counter
import hashlib
import json
import math
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

@dataclass
class Config:
    start: str = '2023-01-03'
    end: str = '2025-12-31'
    initial_cash: float = 50000
    contracts: int = 1
    multiplier: int = 100
    long_delta_target: float = .80
    long_delta_min: float = .75
    long_delta_max: float = .85
    long_dte_min: int = 365
    long_dte_max: int = 540
    long_dte_target: int = 450
    short_delta_target: float = .25
    short_delta_min: float = .20
    short_delta_max: float = .30
    short_dte_min: int = 30
    short_dte_max: int = 45
    short_dte_target: int = 35
    short_close_dte: int = 7
    long_close_dte: int = 180
    max_relative_spread: float = .20
    max_absolute_spread: float = 2.
    minimum_signal_day_volume: int = 1
    option_fee: float = .65
    stock_fee: float = 0.
    extra_spread_fraction: float = 0.
    cash_interest: float = 0.
    max_carried_mark_sessions: int = 2
    early_assignment_stress: bool = False
    assignment_extrinsic_threshold: float = .05

class Market:
    def __init__(self, stock, options):
        self.stock = stock.sort_index()
        self.options = options.copy()
        self.options['date'] = pd.to_datetime(self.options.date)
        self.options['expiry'] = pd.to_datetime(self.options.expiry)
        if self.options.duplicated(['date','ric']).any():
            raise ValueError('Duplicate contract/date observations')
        self.chains = {d:g.set_index('ric',drop=False) for d,g in self.options.groupby('date')}
        self.empty = self.options.iloc[:0].set_index('ric',drop=False)
        self.contracts = self.options[['ric','expiry','strike']].drop_duplicates().set_index('ric')
        if self.contracts.index.duplicated().any():
            raise ValueError('Conflicting contract metadata')

    @classmethod
    def load(cls):
        return cls(pd.read_csv(ROOT/'data/raw/amzn_stock_2022_2025.csv',index_col=0,parse_dates=True),
                   pd.read_csv(ROOT/'data/raw/options_normalized.csv.gz',parse_dates=['date','expiry']))

    def chain(self, date):
        return self.chains.get(date,self.empty)

    def quote(self, date, ric):
        chain = self.chain(date)
        return chain.loc[ric] if ric in chain.index else None

    def candidates(self, date, leg, cfg):
        x = self.chain(date).copy()
        x['dte'] = (x.expiry-date).dt.days
        prefix = 'long' if leg == 'long' else 'short'
        spot = float(self.stock.loc[date,'TRDPRC_1'])
        width = x.ASK-x.BID
        mask = (x.BID>0)&(x.ASK>=x.BID)&(width<=cfg.max_absolute_spread)&(width/((x.ASK+x.BID)/2)<=cfg.max_relative_spread)
        mask &= x.DELTA.between(getattr(cfg,prefix+'_delta_min'),getattr(cfg,prefix+'_delta_max'))
        mask &= x.dte.between(getattr(cfg,prefix+'_dte_min'),getattr(cfg,prefix+'_dte_max'))
        mask &= x.ACVOL_UNS.ge(cfg.minimum_signal_day_volume)
        mask &= x.strike.lt(spot) if leg=='long' else x.strike.gt(spot)
        x = x.loc[mask].copy()
        x['delta_distance'] = abs(x.DELTA-getattr(cfg,prefix+'_delta_target'))
        x['expiry_distance'] = abs(x.dte-getattr(cfg,prefix+'_dte_target'))
        # A stable total ordering makes ties reproducible.
        x['ric_tie'] = x.ric
        return x.sort_values(['delta_distance','expiry_distance','strike','ric_tie'],ascending=[True,True,leg=='long',True])

def valid_quote(q):
    return q is not None and pd.notna(q.BID) and pd.notna(q.ASK) and q.BID>=0 and q.ASK>=q.BID and q.ASK>0

def entry_quote(q,cfg):
    return valid_quote(q) and q.BID>0 and q.ASK-q.BID<=cfg.max_absolute_spread and (q.ASK-q.BID)/((q.ASK+q.BID)/2)<=cfg.max_relative_spread

def valid_side(q,buy):
    if q is None:
        return False
    side=q.ASK if buy else q.BID
    if pd.isna(side) or side<0 or (buy and side==0):
        return False
    return not (pd.notna(q.ASK) and pd.notna(q.BID) and q.BID>q.ASK)

def fill_price(q, buy, cfg):
    if not valid_side(q,buy):
        raise ValueError('Cannot fill without an observed same-session quote on the execution side')
    # If the opposite quote is absent, use at least one cent for the stress spread.
    width=float(q.ASK-q.BID) if valid_quote(q) else max(.01,float(q.ASK if buy else q.BID)*.20)
    penalty = cfg.extra_spread_fraction*width
    return float(q.ASK+penalty if buy else max(0,q.BID-penalty))

class Engine:
    def __init__(self, market, strategy, cfg):
        self.m, self.strategy, self.c = market,strategy,cfg
        if cfg.contracts!=1 or cfg.multiplier!=100 or cfg.cash_interest!=0:
            raise ValueError('This experiment supports one standard 100-share contract and zero cash interest')
        self.cash=cfg.initial_cash
        self.shares=0
        self.long=None
        self.short=None
        self.ledger=[]
        self.decisions=[]
        self.daily=[]
        self.skips=Counter()
        self.last_marks={}
        self.close_long_pending=False
        self.close_short_pending=False
        self.assign_next=False
        self.initial_gross_capital=None
        self.initial_net_capital=None
        self.date=None
        self.signal=None

    def skip(self,reason):
        self.skips[reason]+=1
        self.decisions.append({'date':str(self.date.date()),'signal_date':str(self.signal.date()),'strategy':self.strategy,'reason':reason})

    def event(self, action, instrument, qty, price, fee, reason, cashflow=None):
        multiplier=self.c.multiplier if instrument!='AMZN.O' else 1
        cashflow = -qty*price*multiplier-fee if cashflow is None else cashflow
        self.cash += cashflow
        if self.cash < -1e-7:
            raise AssertionError(f'Negative cash: {self.date}, {action}, {self.cash}')
        row={'date':str(self.date.date()),'signal_date':str(self.signal.date()),'strategy':self.strategy,
             'action':action,'instrument':instrument,'quantity':qty,'price':float(price),
             'multiplier':multiplier,'fee':float(fee),'cashflow':float(cashflow),'cash_after':float(self.cash),'reason':reason}
        if instrument in self.m.contracts.index:
            info=self.m.contracts.loc[instrument]
            row.update(strike=float(info.strike),expiry=str(info.expiry.date()))
            signal_q=self.m.quote(self.signal,instrument)
            row['signal_delta']=float(signal_q.DELTA) if signal_q is not None and pd.notna(signal_q.DELTA) else None
        self.ledger.append(row)

    def stock_trade(self, qty, reason):
        q=self.m.stock.loc[self.date]
        price=fill_price(q,qty>0,self.c)
        self.event('BUY_STOCK' if qty>0 else 'SELL_STOCK','AMZN.O',qty,price,self.c.stock_fee,reason)
        self.shares+=qty
        return price

    def option_trade(self, ric, qty, reason):
        q=self.m.quote(self.date,ric)
        if not valid_side(q,qty>0):
            self.skip('close_missing_quote')
            return False
        self.event('BUY_CALL' if qty>0 else 'SELL_CALL',ric,qty,fill_price(q,qty>0,self.c),self.c.option_fee,reason)
        return True

    def close_short(self, reason):
        if not self.short:
            return True
        if self.option_trade(self.short,1,reason):
            self.short=None
            self.close_short_pending=False
            return True
        return False

    def close_long(self, reason):
        if self.short:
            raise AssertionError('Must close short before selling long collateral')
        if not self.long:
            return True
        if self.option_trade(self.long,-1,reason):
            self.long=None
            self.close_long_pending=False
            return True
        return False

    def assign(self, reason):
        ric=self.short
        strike=float(self.m.contracts.loc[ric,'strike'])
        # Physical settlement: the short option disappears; 100 shares are delivered
        # at strike. In PMCC this creates -100 shares; the long call is unchanged.
        self.event('ASSIGNED',ric,1,0,0,reason,cashflow=0)
        self.event('DELIVER_SHARES','AMZN.O',-100,strike,0,reason)
        self.shares-=100
        self.short=None
        self.close_short_pending=False

    def expire_short(self):
        if not self.short:
            return
        if self.m.contracts.loc[self.short,'expiry']>self.date:
            return
        spot=float(self.m.stock.loc[self.date,'TRDPRC_1'])
        if spot-float(self.m.contracts.loc[self.short,'strike'])>=.01:
            self.assign('expiry_assignment')
        else:
            self.event('EXPIRED',self.short,1,0,0,'expiry_otm',cashflow=0)
            self.short=None
            self.close_short_pending=False

    def open_pair(self):
        longs=self.m.candidates(self.signal,'long',self.c)
        shorts=self.m.candidates(self.signal,'short',self.c)
        selection=None
        for _,l in longs.iterrows():
            for _,s in shorts.iterrows():
                if s.strike<=l.strike:
                    continue
                if (l.ASK-s.BID)*100+2*self.c.option_fee >= (s.strike-l.strike)*100:
                    continue
                selection=(l,s)
                break
            if selection is not None:
                break
        if selection is None:
            self.skip('no_signal_pair')
            return
        l,s=selection
        lq,sq=self.m.quote(self.date,l.ric),self.m.quote(self.date,s.ric)
        # Do not select a different contract using today's information. A failed
        # conditional execution cancels the pair and the next signal tries anew.
        if not (entry_quote(lq,self.c) and entry_quote(sq,self.c)):
            self.skip('pair_execution_quote_rejected')
            return
        debit=(fill_price(lq,True,self.c)-fill_price(sq,False,self.c))*100+2*self.c.option_fee
        if debit >= (s.strike-l.strike)*100:
            self.skip('pair_execution_debit_rejected')
            return
        gross=fill_price(lq,True,self.c)*100+self.c.option_fee
        if gross>self.cash:
            self.skip('insufficient_cash')
            return
        self.option_trade(l.ric,1,'open_diagonal_long')
        self.long=l.ric
        self.option_trade(s.ric,-1,'open_diagonal_short')
        self.short=s.ric
        if self.initial_gross_capital is None:
            self.initial_gross_capital=gross
            self.initial_net_capital=debit

    def open_short(self):
        if self.strategy=='pmcc' and not self.long:
            raise AssertionError('Uncovered option sale')
        if self.strategy=='covered_call' and self.shares<100:
            raise AssertionError('Insufficient stock collateral')
        shorts=self.m.candidates(self.signal,'short',self.c)
        if self.long:
            shorts=shorts.loc[shorts.strike>float(self.m.contracts.loc[self.long,'strike'])]
        if shorts.empty:
            self.skip('no_signal_short')
            return
        ric=shorts.iloc[0].ric
        q=self.m.quote(self.date,ric)
        if not entry_quote(q,self.c):
            self.skip('short_execution_quote_rejected')
            return
        self.option_trade(ric,-1,'open_short_against_existing_collateral')
        self.short=ric

    def mark(self, ric, long, step):
        q=self.m.quote(self.date,ric)
        if valid_side(q,not long):
            value=float(q.BID if long else q.ASK)
            self.last_marks[ric]=(value,step)
            return value,False
        if ric not in self.last_marks:
            raise ValueError(f'No initial mark for {ric} on {self.date}')
        value,last_step=self.last_marks[ric]
        if step-last_step>self.c.max_carried_mark_sessions:
            raise ValueError(f'Unresolved valuation gap: {ric} on {self.date}')
        return value,True

    def run(self):
        all_dates=self.m.stock.index
        dates=all_dates[(all_dates>=self.c.start)&(all_dates<=self.c.end)]
        if len(dates)<2:
            raise ValueError('Insufficient stock history')
        for step,date in enumerate(dates):
            self.date=date
            ix=all_dates.get_loc(date)
            if ix==0:
                raise ValueError('Prior-session signal data required')
            self.signal=all_dates[ix-1]
            ending=step==len(dates)-1
            assert self.signal<self.date
            if self.assign_next:
                if self.short:
                    self.assign('early_assignment_stress_prior_close')
                self.assign_next=False
            # Any overnight short stock from assignment is covered at today's ask.
            if self.shares<0:
                self.stock_trade(-self.shares,'cover_assignment_stock')
            if self.strategy in ('stock','covered_call') and self.shares==0 and not ending:
                price=self.stock_trade(100,'initial_stock' if not self.ledger else 'restore_stock_after_assignment')
                if self.initial_gross_capital is None:
                    self.initial_gross_capital=price*100+self.c.stock_fee
                    self.initial_net_capital=self.initial_gross_capital

            if self.long and (self.m.contracts.loc[self.long,'expiry']-self.signal).days<=self.c.long_close_dte:
                self.close_long_pending=True
            if self.short and (self.m.contracts.loc[self.short,'expiry']-self.signal).days<=self.c.short_close_dte:
                self.close_short_pending=True
            if ending or self.close_long_pending or self.close_short_pending:
                self.close_short('terminal_liquidation' if ending else 'scheduled_roll')
            if ending or self.close_long_pending:
                if not self.short:
                    self.close_long('terminal_liquidation' if ending else 'long_roll')
            if ending:
                if self.long or self.short:
                    raise ValueError('Terminal quote missing: cannot liquidate honestly')
                if self.shares:
                    self.stock_trade(-self.shares,'terminal_liquidation')
            elif not self.close_long_pending and not self.close_short_pending:
                if self.strategy=='pmcc' and not self.long:
                    self.open_pair()
                elif self.strategy!='stock' and not self.short:
                    self.open_short()
            self.expire_short()
            if self.long and self.m.contracts.loc[self.long,'expiry']<=self.date:
                raise ValueError('Long call reached expiration before a supported close')
            if self.short:
                assert self.long is not None if self.strategy=='pmcc' else self.shares>=100
                if self.c.early_assignment_stress:
                    q=self.m.quote(self.date,self.short)
                    k=float(self.m.contracts.loc[self.short,'strike'])
                    spot=float(self.m.stock.loc[self.date,'TRDPRC_1'])
                    # Deliberately conservative scenario, not a probability model.
                    if valid_quote(q) and spot>k and float(q.BID)-max(spot-k,0)<=self.c.assignment_extrinsic_threshold:
                        self.assign_next=True
            lv,ls=(self.mark(self.long,True,step) if self.long else (0,False))
            sv,ss=(self.mark(self.short,False,step) if self.short else (0,False))
            stockq=self.m.stock.loc[self.date]
            stockvalue=self.shares*float(stockq.BID if self.shares>=0 else stockq.ASK)
            equity=self.cash+stockvalue+100*lv-100*sv
            lq=self.m.quote(self.date,self.long) if self.long else None
            sq=self.m.quote(self.date,self.short) if self.short else None
            net_delta=self.shares + (100*float(lq.DELTA) if lq is not None and pd.notna(lq.DELTA) else 0) - (100*float(sq.DELTA) if sq is not None and pd.notna(sq.DELTA) else 0)
            if (self.long and (lq is None or pd.isna(lq.DELTA))) or (self.short and (sq is None or pd.isna(sq.DELTA))):
                net_delta=None
            self.daily.append({'date':str(date.date()),'equity':equity,'cash':self.cash,'shares':self.shares,
                               'long_ric':self.long or '', 'short_ric':self.short or '',
                               'long_value':100*lv,'short_liability':100*sv,'stock_value':stockvalue,
                               'gross_long_asset_value':max(stockvalue,0)+100*lv,
                               'carried_mark':int(ls or ss),'net_delta_shares':net_delta})
        daily=pd.DataFrame(self.daily)
        ledger=pd.DataFrame(self.ledger)
        assert not self.long and not self.short and self.shares==0
        assert math.isclose(self.c.initial_cash+ledger.cashflow.sum(),self.cash,abs_tol=1e-6)
        assert daily.cash.min()>=0
        return daily,ledger,self.statistics(daily,ledger)

    def statistics(self,d,l):
        equity=d.equity.to_numpy()
        previous=np.r_[self.c.initial_cash,equity[:-1]]
        returns=equity/previous-1
        peaks=np.maximum.accumulate(np.r_[self.c.initial_cash,equity])[1:]
        drawdown=equity/peaks-1
        years=((pd.Timestamp(self.c.end)-pd.Timestamp(self.c.start)).days+1)/365.25
        fees=float(l.fee.sum())
        is_option=l.instrument!='AMZN.O'
        short_open=l.action.eq('SELL_CALL') & l.reason.isin(['open_diagonal_short','open_short_against_existing_collateral'])
        short_close=l.action.eq('BUY_CALL') & l.reason.isin(['scheduled_roll','terminal_liquidation'])
        d['daily_return']=returns
        d['drawdown']=drawdown
        yearly={}
        last=self.c.initial_cash
        for year,g in d.groupby(pd.to_datetime(d.date).dt.year):
            yearly[str(year)]=float(g.equity.iloc[-1]/last-1)
            last=float(g.equity.iloc[-1])
        return {'strategy':self.strategy,'ending_equity':float(equity[-1]),'net_profit':float(equity[-1]-self.c.initial_cash),
                'total_return':float(equity[-1]/self.c.initial_cash-1),'cagr':float((equity[-1]/self.c.initial_cash)**(1/years)-1),
                'max_drawdown':float(drawdown.min()),'annualized_volatility':float(np.std(returns,ddof=1)*np.sqrt(252)),
                'sharpe_zero_rf':float(np.mean(returns)/np.std(returns,ddof=1)*np.sqrt(252)),
                'initial_gross_capital':self.initial_gross_capital,'initial_net_capital':self.initial_net_capital,
                'average_gross_long_asset_value':float(d.gross_long_asset_value.mean()),
                'option_leg_fills':int((is_option&l.action.isin(['BUY_CALL','SELL_CALL'])).sum()),
                'stock_fills':int(l.action.isin(['BUY_STOCK','SELL_STOCK']).sum()),
                'short_calls_opened':int(short_open.sum()),'short_premiums_collected':float((-l.loc[short_open,'quantity']*l.loc[short_open,'price']*100).sum()),
                'short_buyback_cost':float((l.loc[short_close,'quantity']*l.loc[short_close,'price']*100).sum()),
                'assignments':int(l.action.eq('ASSIGNED').sum()),'fees':fees,'carried_mark_days':int(d.carried_mark.sum()),
                'short_exposure_days':int(d.short_ric.ne('').sum()),'long_exposure_days':int(d.long_ric.ne('').sum()),
                'skipped_decisions':dict(self.skips),'annual_returns':yearly}

def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--end',default=None)
    parser.add_argument('--output',default='docs/results')
    args=parser.parse_args()
    cfg=Config(**json.loads((ROOT/'config.json').read_text()))
    if args.end: cfg.end=args.end
    market=Market.load()
    out=ROOT/args.output
    out.mkdir(parents=True,exist_ok=True)
    results=[]
    for strategy in ['pmcc','covered_call','stock']:
        engine=Engine(market,strategy,cfg)
        d,l,s=engine.run()
        pd.DataFrame(engine.decisions,columns=['date','signal_date','strategy','reason']).to_csv(out/(strategy+'_skips.csv'),index=False)
        d.to_csv(out/(strategy+'_daily.csv'),index=False)
        l.to_csv(out/(strategy+'_trades.csv'),index=False)
        results.append(s)
        print(json.dumps(s,indent=2))
    manifest={'config':asdict(cfg),'source_hashes':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'src/backtest.py',ROOT/'config.json',ROOT/'data/raw/options_normalized.csv.gz',ROOT/'data/raw/amzn_stock_2022_2025.csv']}}
    (out/'run_manifest.json').write_text(json.dumps(manifest,indent=2))
    (out/'summary.json').write_text(json.dumps(results,indent=2,allow_nan=False))

if __name__=='__main__': main()
