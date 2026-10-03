"""Replays the live rules day by day over history using the exact same code as the live engine.
Usage: python -m engine.backtest  (needs EODHD_API_KEY)"""
import pandas as pd
from . import config as C
from .indicators import compute
from .strategies import decide_b, b_new_weights, decide_a_exits, decide_a_entries
from . import portfolio as PF


def replay(px, turnover, start="2013-01-01"):
    ind = compute(px, turnover)
    idx = px.loc[start:].index
    week_last = set(pd.Series(idx, index=idx).groupby(idx.to_period("W")).last())
    pB = PF.new_portfolio(px[C.CASH].loc[idx[0]]); pA = PF.new_portfolio(px[C.CASH].loc[idx[0]])
    a_days = {}
    eqB, eqA, maxinv = [], [], 0.0
    for t in idx:
        prices = px.loc[t].to_dict()
        # positions that no longer have a price (delisted) are valued at their last price
        if t in week_last:
            held = list(pB["units"])
            keep, _, _ = decide_b(ind, t, held)
            if set(keep) != set(held):
                new = [k for k in keep if k not in held]
                PF.rebalance_b(pB, keep, b_new_weights(ind, t, keep, new), prices)
        for k in a_days: a_days[k] += 1
        for k in decide_a_exits(ind, t, a_days):
            PF.sell_all(pA, k, prices); a_days.pop(k)
        for k in decide_a_entries(ind, t, list(a_days)):
            PF.buy_value(pA, k, PF.value(pA, prices) / C.A_MAX_POS, prices); a_days[k] = 0
        eqB.append(PF.value(pB, prices)); eqA.append(PF.value(pA, prices))
        maxinv = max(maxinv, 1 - pB["cash_units"] * prices[C.CASH] / eqB[-1])
    return pd.Series(eqB, index=idx), pd.Series(eqA, index=idx), maxinv


def _stats(eq):
    r = eq.pct_change().fillna(0)
    yrs = len(r) / 252
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    dd = (eq / eq.cummax() - 1).min()
    return f"{cagr*100:5.1f}% a year | worst fall {dd*100:6.1f}% | $10k -> ${eq.iloc[-1]/eq.iloc[0]*1e4:,.0f}"


if __name__ == "__main__":
    import os, datetime as dt
    from .data import history
    from .indicators import clean_prices
    adj, close, turnover = history(os.environ["EODHD_API_KEY"], dt.date.today(), days=365 * 16)
    px = clean_prices(adj).loc["2011-01-01":]
    eqB, eqA, maxinv = replay(px, turnover.reindex(px.index))
    R = px[list(C.BENCH_MIX)].pct_change(fill_method=None).loc[eqB.index].fillna(0)
    cur, vals, m = pd.Series(C.BENCH_MIX), [], None
    for t, row in R.iterrows():
        if m is not None and t.month != m:
            cur = pd.Series(C.BENCH_MIX)
        vals.append((cur * row).sum()); cur = cur * (1 + row); cur = cur / cur.sum(); m = t.month
    mix = (1 + pd.Series(vals, index=R.index)).cumprod()
    print(f"Period {eqB.index[0].date()} to {eqB.index[-1].date()}")
    print("Strategy B   ", _stats(eqB))
    print("Strategy A   ", _stats(eqA))
    print("Hold 40/40/20", _stats(mix))
    print(f"Max invested (B): {maxinv*100:.1f}%")
