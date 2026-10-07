"""Replays the live rules day by day over history, using the same decision and portfolio code as the live engine.
Trades are filled at the NEXT trading day's close after each decision (more conservative than live, which trades
the same afternoon). Usage: EODHD_API_KEY=... python -m engine.backtest"""
import numpy as np
import pandas as pd
from . import config as C
from .indicators import compute
from .strategies import decide_b, b_new_weights, decide_a_exits, decide_a_entries
from . import portfolio as PF

# Approximate RBA cash rate, used only for the cash hurdle before AAA listed in March 2012
RBA = [("2010-01", 3.75), ("2010-03", 4.0), ("2010-04", 4.25), ("2010-05", 4.5), ("2010-11", 4.75),
       ("2011-11", 4.5), ("2011-12", 4.25), ("2012-05", 3.75)]


def with_cash_history(px: pd.DataFrame) -> pd.DataFrame:
    px = px.copy()
    rate = pd.Series(np.nan, index=px.index)
    for m, r in RBA:
        rate[rate.index >= pd.Timestamp(m + "-01")] = r
    rate = rate.ffill().fillna(3.75) / 100
    syn = (1 + rate / 252).cumprod()
    first = px[C.CASH].first_valid_index()
    px.loc[:first, C.CASH] = (syn * px.at[first, C.CASH] / syn[first]).loc[:first]
    return px


def replay(px, turnover, start="2013-01-01", end=None, ind=None):
    ind = compute(px, turnover) if ind is None else ind     # the sensitivity grid passes adjusted indicators
    idx = px.loc[start:end].index
    week_last = set(pd.Series(idx, index=idx).groupby(idx.to_period("W")).last())
    pB = PF.new_portfolio(px[C.CASH].loc[idx[0]]); pA = PF.new_portfolio(px[C.CASH].loc[idx[0]])
    a_days, pendB, pendA = {}, None, None
    eqB, eqA, invB, stats = [], [], [], {"turnover": 0.0, "sells": [], "buy_date": {}}
    for t in idx:
        prices = px.loc[t].to_dict()
        if pendB is not None:                       # execute last decision at today's close
            keep, dt_ = pendB; pendB = None
            held = list(pB["units"])
            if set(keep) != set(held) or PF.needs_trim(pB, prices):
                new = [k for k in keep if k not in held]
                for tr in PF.rebalance_b(pB, keep, b_new_weights(ind, dt_, keep, new), prices):
                    stats["turnover"] += tr["value"]
                    if tr["side"] == "BUY":
                        stats["buy_date"][tr["ticker"]] = t
                    elif tr.get("whole"):
                        stats["sells"].append((t - stats["buy_date"].pop(tr["ticker"], t)).days)
        if pendA is not None:
            exits, entries = pendA; pendA = None
            for k in exits:
                PF.sell_all(pA, k, prices); a_days.pop(k, None)
            for k in entries:
                if PF.buy_value(pA, k, PF.value(pA, prices) / C.A_MAX_POS, prices) > 0:
                    a_days[k] = 0
        if t in week_last:
            pendB = (decide_b(ind, t, list(pB["units"]))[0], t)
        for k in a_days:
            a_days[k] += 1
        ex = decide_a_exits(ind, t, a_days)
        pendA = (ex, decide_a_entries(ind, t, [k for k in a_days if k not in ex]))
        eqB.append(PF.value(pB, prices)); eqA.append(PF.value(pA, prices))
        invB.append(1 - pB["cash_units"] * prices[C.CASH] / eqB[-1])
    stats["invested"] = float(np.mean(invB)); stats["max_invested"] = float(np.max(invB))
    return pd.Series(eqB, index=idx), pd.Series(eqA, index=idx), stats


def metrics(eq: pd.Series, cash: pd.Series, stats=None) -> dict:
    r = eq.pct_change().fillna(0)
    yrs = len(r) / 252
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    vol = r.std() * np.sqrt(252)
    ex = r - cash.pct_change(fill_method=None).reindex(r.index).fillna(0)
    dd = (eq / eq.cummax() - 1).min()
    out = {"CAGR": cagr, "Volatility": vol, "Sharpe": ex.mean() / r.std() * np.sqrt(252),
           "Sortino": ex.mean() * 252 / (r[r < 0].std() * np.sqrt(252)), "MaxDD": dd, "Calmar": cagr / abs(dd),
           "End value of $10k": 1e4 * eq.iloc[-1] / eq.iloc[0]}
    if stats:
        s = stats["sells"]
        out.update({"Turnover per year": stats["turnover"] / eq.mean() / yrs, "Sales per year": len(s) / yrs,
                    "Average days held": float(np.mean(s)) if s else float("nan"),
                    "Sales within 12 months": float(np.mean([x < 365 for x in s])) if s else float("nan"),
                    "Average invested": stats["invested"]})
    return out


def bench(px, start, mix=C.BENCH_MIX):
    R = px[list(mix)].pct_change(fill_method=None).loc[start:].fillna(0)
    w = pd.Series(mix); cur, vals, m = w.copy(), [], None
    for t, row in R.iterrows():
        cost = 0.0
        if m is not None and t.month != m:
            cost = (cur - w).abs().sum() * C.COST; cur = w.copy()
        vals.append((cur * row).sum() - cost); cur = cur * (1 + row); cur = cur / cur.sum(); m = t.month
    return (1 + pd.Series(vals, index=R.index)).cumprod()


def report(px, turnover, start="2013-01-01"):
    eqB, eqA, st = replay(px, turnover, start)
    mix = bench(px, start)
    cash = px[C.CASH]
    rows = {"Strategy B": metrics(eqB, cash, st), "Strategy A (paper)": metrics(eqA, cash),
            "Buy and hold 40/40/20": metrics(mix, cash)}
    for a, b in [("2013", "2019"), ("2020", None)]:
        rows["Strategy B"][f"CAGR {a}-{b or 'now'}"] = metrics(eqB.loc[a:b], cash)["CAGR"]
        rows["Buy and hold 40/40/20"][f"CAGR {a}-{b or 'now'}"] = metrics(mix.loc[a:b], cash)["CAGR"]
    return pd.DataFrame(rows), st


if __name__ == "__main__":
    import os, datetime as dt
    from .data import history
    from .indicators import clean_prices
    from .research import fix_adjustments
    adj, close, turnover = history(os.environ["EODHD_API_KEY"], dt.date.today(), days=365 * 16)
    adj = fix_adjustments(adj, close, os.environ["EODHD_API_KEY"], os.path.expanduser("~/.etf-signal-cache"))
    px = with_cash_history(clean_prices(adj).loc["2011-01-01":])
    df, st = report(px, turnover.reindex(px.index))
    pct = {"CAGR", "Volatility", "MaxDD", "Sales within 12 months", "Average invested", "CAGR 2013-2019", "CAGR 2020-now"}
    fmt = df.apply(lambda col: [("" if pd.isna(v) else f"{v*100:.1f}%" if i in pct else f"{v:,.0f}" if i == "End value of $10k" else f"{v:.2f}") for i, v in col.items()], result_type="expand")
    fmt.index = df.index
    print(f"Rules version {C.RULES_VERSION}, {px.loc['2013':].index[0].date()} to {px.index[-1].date()}, trades filled next day")
    print(fmt.to_string())
    print(f"Highest share ever invested (B): {st['max_invested']*100:.1f}%")
