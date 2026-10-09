"""Predeclared execution and assignment sensitivities; baseline is not optimized."""
from dataclasses import replace,asdict
import json
from backtest import Config,Market,Engine,ROOT

def main():
    cfg=Config(**json.loads((ROOT/'config.json').read_text()))
    market=Market.load()
    cases=[('baseline',cfg),('double_fees',replace(cfg,option_fee=1.30)),
           ('extra_quarter_spread',replace(cfg,extra_spread_fraction=.25)),
           ('early_assignment_stress',replace(cfg,early_assignment_stress=True))]
    rows=[]
    for name,c in cases:
        for strategy in ['pmcc','covered_call','stock']:
            d,l,s=Engine(market,strategy,c).run()
            rows.append({'scenario':name,**s,'config':asdict(c)})
            if name=='early_assignment_stress':
                l.to_csv(ROOT/'docs/results'/f'{strategy}_assignment_stress_trades.csv',index=False)
            print(name,strategy,round(s['total_return']*100,4),'assignments',s['assignments'],flush=True)
    (ROOT/'docs/results/robustness.json').write_text(json.dumps(rows,indent=2,allow_nan=False))

if __name__=='__main__':main()
