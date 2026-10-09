import sys
import unittest
from pathlib import Path
from dataclasses import replace
import pandas as pd
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from backtest import Config,Market,Engine,fill_price,entry_quote,ROOT


def fixture():
    dates=pd.to_datetime(['2023-01-03','2023-01-04','2023-01-05','2023-01-06'])
    stock=pd.DataFrame({'BID':[100,100,115,115], 'ASK':[100.1,100.1,115.1,115.1], 'TRDPRC_1':[100,100,115,115]},index=dates)
    rows=[]
    for d in dates:
        for ric,expiry,k,b,a,delta in [('L','2024-04-19',80,24,24.2,.8),('S','2023-02-17',110,1,1.1,.25)]:
            rows.append(dict(date=d,ric=ric,expiry=expiry,strike=k,BID=b,ASK=a,DELTA=delta,ACVOL_UNS=10))
    return Market(stock,pd.DataFrame(rows))

class EngineTests(unittest.TestCase):
    def test_entry_uses_prior_session_delta(self):
        m=fixture()
        c=Config(start='2023-01-04',end='2023-01-06')
        d,l,s=Engine(m,'pmcc',c).run()
        changed=m.options.copy()
        changed.loc[changed.date>=pd.Timestamp('2023-01-04'),'DELTA']=.50
        d2,l2,s2=Engine(Market(m.stock,changed),'pmcc',c).run()
        first=l.loc[l.date.eq('2023-01-04')].reset_index(drop=True)
        second=l2.loc[l2.date.eq('2023-01-04')].reset_index(drop=True)
        pd.testing.assert_frame_equal(first,second)
        self.assertEqual(first.action.tolist(),['BUY_CALL','SELL_CALL'])
        self.assertTrue((pd.to_datetime(l.signal_date)<pd.to_datetime(l.date)).all())

    def test_assignment_creates_stock_liability_without_exercising_long(self):
        m=fixture(); e=Engine(m,'pmcc',Config())
        e.date=pd.Timestamp('2023-01-05');e.signal=pd.Timestamp('2023-01-04')
        e.cash=40000;e.long='L';e.short='S'
        e.assign('test')
        self.assertEqual(e.shares,-100)
        self.assertEqual(e.cash,51000)
        self.assertEqual(e.long,'L')
        self.assertIsNone(e.short)
        e.stock_trade(100,'cover_assignment_stock')
        self.assertAlmostEqual(e.cash,39490)
        self.assertEqual(e.shares,0)

    def test_missing_bid_does_not_block_observed_ask_buyback(self):
        q=pd.Series(dict(BID=np.nan,ASK=.02))
        self.assertFalse(entry_quote(q,Config()))
        self.assertEqual(fill_price(q,True,Config()),.02)
        with self.assertRaises(ValueError):fill_price(q,False,Config())

    def test_no_uncovered_sale(self):
        e=Engine(fixture(),'pmcc',Config())
        with self.assertRaises(AssertionError):e.open_short()

    def test_no_future_price_for_missing_mark(self):
        e=Engine(fixture(),'pmcc',Config())
        e.date=pd.Timestamp('2023-01-09')
        with self.assertRaises(ValueError):e.mark('L',True,0)
        e.last_marks['L']=(24,0)
        self.assertEqual(e.mark('L',True,2),(24,True))
        with self.assertRaises(ValueError):e.mark('L',True,3)

    def test_cash_conservation_and_final_flat(self):
        d,l,s=Engine(fixture(),'pmcc',Config(start='2023-01-04',end='2023-01-06')).run()
        self.assertAlmostEqual(50000+l.cashflow.sum(),d.equity.iloc[-1])
        self.assertAlmostEqual(d.equity.iloc[-1],d.cash.iloc[-1])
        self.assertEqual(d.long_ric.iloc[-1],'')
        self.assertEqual(d.short_ric.iloc[-1],'')
        self.assertGreaterEqual(d.cash.min(),0)

    @unittest.skipUnless((ROOT/'data/raw/options_normalized.csv.gz').exists(),'Private LSEG cache required')
    def test_historical_accounting_and_lag(self):
        m=Market.load()
        for strategy in ['pmcc','covered_call','stock']:
            d,l,s=Engine(m,strategy,Config()).run()
            expected=d.cash+d.stock_value+d.long_value-d.short_liability
            np.testing.assert_allclose(d.equity,expected)
            np.testing.assert_allclose(50000+l.cashflow.cumsum(),l.cash_after)
            self.assertTrue((pd.to_datetime(l.signal_date)<pd.to_datetime(l.date)).all())
            self.assertEqual(len(d),752)
            self.assertEqual(s['carried_mark_days'],0)
            if strategy=='pmcc':self.assertTrue((d.short_ric.eq('')|d.long_ric.ne('')).all())
            if strategy=='covered_call':self.assertTrue((d.short_ric.eq('')|d.shares.ge(100)).all())

if __name__=='__main__':unittest.main()
