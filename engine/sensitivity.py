"""Offline robustness check (not used by the live engine, never changes the live rules).

Replays Strategy B with the live decision code over 2013-now, then again with nearby settings, to see whether its
result against the 40/40/20 index mix is a feature of the strategy or of one lucky or unlucky setting.
Grid: buy line 100/101/102% and sell line 97/98/99% of the 200-day average, and 3 to 7 holdings.

Usage: EODHD_API_KEY=... python -m engine.sensitivity [--cache DIR] [--out docs/sensitivity.json]

How to read it: look at the spread, not the best row. Picking the best-looking setting from a grid is overfitting.

Percentile vs absolute momentum: the ranking is the same either way (a percentile rank keeps the order), so it
can't change which ETFs are bought; it only matters for the odds table's bins. It is not in the grid for that reason."""
import argparse, contextlib, itertools, json, os, datetime as dt
import numpy as np
import pandas as pd
from . import config as C
from .indicators import clean_prices, compute
from .backtest import replay, bench, with_cash_history
from .research import fetch, frames, fix_adjustments

START = "2013-01-01"


@contextlib.contextmanager
def settings(**kw):
    old = {k: getattr(C, k) for k in kw}
    try:
        for k, v in kw.items():
            setattr(C, k, v)
        yield
    finally:
        for k, v in old.items():
            setattr(C, k, v)


def with_lines(ind, buy, sell):
    ind = dict(ind)
    ind["above_in"] = ind["P"] > ind["sma"] * buy
    ind["above_hold"] = ind["P"] > ind["sma"] * sell
    return ind


def stats(eq: pd.Series, mix: pd.Series, invested: float) -> dict:
    r = eq.pct_change().fillna(0)
    yrs = len(r) / 252
    wk = eq.resample("W-FRI").last().pct_change().dropna()
    wm = mix.resample("W-FRI").last().pct_change().dropna()
    # each calendar year's return measured from the previous year's last close
    ye = eq.resample("YE").last()
    yearly = {str(d.year): float(v) for d, v in (ye / ye.shift(1).fillna(eq.iloc[0]) - 1).items()}
    return {"cagr": float((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1), "max_dd": float((eq / eq.cummax() - 1).min()),
            "vol": float(r.std() * np.sqrt(252)), "invested": invested,
            "weeks_beaten": float((wk > wm.reindex(wk.index)).mean()), "yearly": yearly,
            "end_10k": float(1e4 * eq.iloc[-1] / eq.iloc[0])}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.expanduser("~/.etf-signal-cache"))
    ap.add_argument("--out", default="docs/sensitivity.json")
    a = ap.parse_args(argv)
    key = os.environ["EODHD_API_KEY"]
    data = fetch(key, C.UNIVERSE + [C.CASH, C.INDEX], a.cache)
    adj, close, turnover = frames(data)
    adj = fix_adjustments(adj, close, key, a.cache)
    px = with_cash_history(clean_prices(adj).loc["2011-01-01":])
    turnover = turnover.reindex(px.index)
    base_ind = compute(px, turnover)
    mix = bench(px, START)
    ye = mix.resample("YE").last()
    mix_stats = {"cagr": float((mix.iloc[-1] / mix.iloc[0]) ** (252 / len(mix)) - 1), "max_dd": float((mix / mix.cummax() - 1).min()),
                 "vol": float(mix.pct_change().std() * np.sqrt(252)),
                 "yearly": {str(d.year): float(v) for d, v in (ye / ye.shift(1).fillna(mix.iloc[0]) - 1).items()},
                 "end_10k": float(1e4 * mix.iloc[-1] / mix.iloc[0])}
    live = (1 + C.B_BAND / 2, 1 - C.B_BAND, C.B_N)
    rows = []
    for buy, sell, n in itertools.product((1.00, 1.01, 1.02), (0.97, 0.98, 0.99), (3, 4, 5, 6, 7)):
        if sell >= buy:
            continue
        with settings(B_N=n, B_BEAR_N=min(C.B_BEAR_N, n)):
            eq, _, st = replay(px, turnover, START, ind=with_lines(base_ind, buy, sell))
        row = {"buy": buy, "sell": sell, "n": n, "live": (round(buy, 4), round(sell, 4), n) == tuple(round(x, 4) for x in live[:2]) + (live[2],),
               **stats(eq, mix.reindex(eq.index), st["invested"])}
        rows.append(row)
        print(f"buy {buy:.2f} sell {sell:.2f} holdings {n}: {row['cagr']*100:5.1f}% a year, worst fall {row['max_dd']*100:6.1f}%"
              f"{'  <- live rules' if row['live'] else ''}")
    c = np.array([r["cagr"] for r in rows])
    out = {"built": dt.date.today().isoformat(), "start": str(px.loc[START:].index[0].date()), "end": str(px.index[-1].date()),
           "rules_version": C.RULES_VERSION, "fills": "next day's close, 0.15% cost per trade",
           "mix": mix_stats, "rows": rows,
           "summary": {"runs": len(rows), "cagr_min": float(c.min()), "cagr_median": float(np.median(c)), "cagr_max": float(c.max()),
                       "beat_mix": int((c > mix_stats["cagr"]).sum()),
                       "dd_better_than_mix": int(sum(r["max_dd"] > mix_stats["max_dd"] for r in rows))}}
    json.dump(out, open(a.out, "w"), indent=1)
    s = out["summary"]
    print(f"\n{s['runs']} settings: {s['cagr_min']*100:.1f}% to {s['cagr_max']*100:.1f}% a year (median {s['cagr_median']*100:.1f}%). "
          f"Index mix {mix_stats['cagr']*100:.1f}%. Beat the mix: {s['beat_mix']} of {s['runs']}. "
          f"Smaller worst fall than the mix: {s['dd_better_than_mix']} of {s['runs']}.")


if __name__ == "__main__":
    main()
