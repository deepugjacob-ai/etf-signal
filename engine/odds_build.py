"""Builds docs/odds.json: how ETFs in a similar position did afterwards. Offline; not used by the live engine.

Version 2 (October 2026), after independent review:
- Point-in-time universe. Every ASX ETF EODHD knows about, including ones delisted since, counts in a week if it
  traded over $1M a day (60-day median, as the strategy requires) at that time. Funds unlike anything the strategy
  holds are left out: geared and inverse funds, cash funds, pure currency funds, crypto and hedge funds.
  An ETF that closed during the forward period counts at its last traded price, as a holder would have been paid out.
- Split by market regime (ASX 200 uptrend / sideways / downtrend, the same test the strategy uses), plus all regimes.
- Confidence ranges by moving-block bootstrap over calendar weeks: whole weeks (all ETFs together, since they move
  together) are resampled in runs as long as the forecast horizon (4, 13 or 52 weeks), so overlapping forward
  periods and shared market moves are both allowed for.
- Distribution-adjusted prices, with provider errors repaired (see research.fix_adjustments).

Usage: EODHD_API_KEY=... python -m engine.odds_build [--cache DIR] [--out docs/odds.json]"""
import argparse, datetime as dt, json, os, re
import numpy as np
import pandas as pd
from . import config as C
from .indicators import clean_prices
from .research import exchange_etfs, fetch, frames, fix_adjustments

MOM_BINS = [[-9, 0, "falling (below 0%)"], [0, 0.1, "gentle (0–10%)"], [0.1, 0.2, "solid (10–20%)"],
            [0.2, 0.35, "strong (20–35%)"], [0.35, 9, "very strong (over 35%)"]]
TREND_BINS = [[-9, -0.02, "below its trend line"], [-0.02, 0.05, "near its trend line"],
              [0.05, 0.15, "above its trend line"], [0.15, 9, "well above its trend line"]]
HORIZONS = {"1m": 21, "3m": 63, "1y": 252}
BLOCK_WEEKS = {"1m": 4, "3m": 13, "1y": 52}
MIN_N, MIN_WEEKS = 150, 26
EXCLUDE = re.compile(r"\bgeared\b|\bultra\b|\bstrong\b|\bbear\b|\bcash\b|money market|bitcoin|ethereum|hedge fund", re.I)
EXCLUDE_CODES = {"USD", "EEU", "POU", "ZUSD", "YANK", C.CASH}
START, FIRST_SNAPSHOT = "2010-01-01", "2012-01-01"


def bootstrap(up_w, n_w, block, reps=2000, seed=7):
    """95% range for sum(up)/sum(n) when whole weeks are resampled in circular blocks of `block` weeks."""
    W = len(n_w)
    if n_w.sum() == 0:
        return None
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(W / block))
    starts = rng.integers(0, W, size=(reps, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(reps, -1)[:, :W] % W
    u, n = up_w[idx].sum(1), n_w[idx].sum(1)
    ok = n > 0
    p = u[ok] / n[ok]
    return [float(np.quantile(p, 0.025)), float(np.quantile(p, 0.975))]


def summarise(df, weeks, h):
    """df: rows of one group with columns week, fwd. Returns {up, median, bad, n, weeks, lo, hi} or None."""
    d = df.dropna(subset=[h])
    n, nw = len(d), d["week"].nunique()
    if n < MIN_N or nw < MIN_WEEKS:
        return None
    up = (d[h] > 0).astype(float)
    up_w = up.groupby(d["week"]).sum().reindex(weeks, fill_value=0).to_numpy()
    n_w = d.groupby("week").size().reindex(weeks, fill_value=0).to_numpy().astype(float)
    ci = bootstrap(up_w, n_w, BLOCK_WEEKS[h])
    return {"up": round(float(up.mean()), 4), "median": round(float(d[h].median()), 4),
            "bad": round(float(d[h].quantile(0.1)), 4), "n": int(n), "weeks": int(nw),
            "lo": round(ci[0], 4), "hi": round(ci[1], 4)}


def table(S, weeks):
    out = {"any": {}, "by_momentum": {}, "cells": {}}
    for h in HORIZONS:
        out["any"][h] = summarise(S, weeks, h)
    for i in range(len(MOM_BINS)):
        g = S[S["mi"] == i]
        out["by_momentum"][str(i)] = {h: summarise(g, weeks, h) for h in HORIZONS}
        for j in range(len(TREND_BINS)):
            gg = g[g["ti"] == j]
            out["cells"][f"{i},{j}"] = {h: summarise(gg, weeks, h) for h in HORIZONS}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.expanduser("~/.etf-signal-cache"))
    ap.add_argument("--out", default="docs/odds.json")
    a = ap.parse_args(argv)
    key = os.environ.get("EODHD_API_KEY", "")
    etfs = [e for e in exchange_etfs(key, a.cache) if e["code"] not in EXCLUDE_CODES and not EXCLUDE.search(e["name"])]
    data = fetch(key, [e["code"] for e in etfs] + [C.INDEX], a.cache, soft=True)
    adj, close, turnover = frames(data)
    adj = fix_adjustments(adj, close, key, a.cache)
    idx = adj[C.INDEX].dropna()
    tickers = [e["code"] for e in etfs if e["code"] in adj.columns]
    P = clean_prices(adj[tickers]).loc[START:]
    gone = {e["code"] for e in etfs if e["delisted"]}
    ends = {k: P[k].last_valid_index() for k in tickers}
    data_end = P.index[-1]
    # regime, exactly as the strategy measures it
    s200, s50 = idx.rolling(200).mean(), idx.rolling(50).mean()
    regime = pd.Series(np.where((idx > s200) & (s50 > s200), "bull", np.where((idx < s200) & (s50 < s200), "bear", "sideways")),
                       index=idx.index).where(s200.notna())
    score = sum(P / P.shift(l) - 1 for l in C.B_LOOKBACKS) / len(C.B_LOOKBACKS)
    trend = P / P.rolling(C.B_MA, min_periods=C.B_MA).mean() - 1
    liq = turnover.reindex(columns=tickers).reindex(P.index).rolling(60, min_periods=40).median().shift(1)
    # forward returns; an ETF that closed inside the window counts at its last price
    fwd = {}
    for h, n in HORIZONS.items():
        f = P.shift(-n) / P - 1
        for k, e in ends.items():
            if k in gone and e is not None and e < data_end - pd.Timedelta(days=14):        # delisted
                pos = P.index.get_loc(e)
                last = P[k].loc[e]
                rows = P.index[max(0, pos - n + 1): pos + 1]
                f.loc[rows, k] = last / P[k].loc[rows] - 1
        fwd[h] = f
    snaps = pd.Series(P.index, index=P.index).loc[FIRST_SNAPSHOT:].groupby(P.loc[FIRST_SNAPSHOT:].index.to_period("W")).last()
    T = pd.DatetimeIndex(snaps.values)
    def long(df, name):
        return df.reindex(T).rename_axis(index="t", columns="k").stack().rename(name)
    S = pd.concat([long(score, "score"), long(trend, "trend"), long(liq, "liq"),
                   long(fwd["1m"], "1m"), long(fwd["3m"], "3m"), long(fwd["1y"], "1y")], axis=1).reset_index()
    S = S[S["score"].notna() & S["trend"].notna() & (S["liq"] > C.LIQ_MIN)].copy()
    S["week"] = S["t"].map({t: w for w, t in enumerate(T)})
    S["regime"] = S["t"].map(regime.reindex(T, method="ffill"))
    S["mi"] = np.searchsorted([b[1] for b in MOM_BINS][:-1], S["score"], side="right")
    S["ti"] = np.searchsorted([b[1] for b in TREND_BINS][:-1], S["trend"], side="right")
    weeks = np.arange(len(snaps))
    out = {"built": dt.date.today().isoformat(), "version": 2,
           "source": f"Weekly samples of every liquid ASX ETF at the time (over $1M a day), including {sum(1 for k in set(S['k']) if k in gone)} since delisted; "
                     f"{snaps.iloc[0]:%b %Y} to {snaps.iloc[-1]:%b %Y}, distributions included. Geared, inverse, cash, currency, crypto and hedge funds left out.",
           "ci_method": "95% range by moving-block bootstrap over calendar weeks (blocks of 4, 13 and 52 weeks)",
           "momentum_bins": MOM_BINS, "trend_bins": TREND_BINS, "etfs": int(S["k"].nunique()), "samples": int(len(S)),
           **table(S, weeks), "regimes": {}}
    for r in ("bull", "sideways", "bear"):
        g = S[S["regime"] == r]
        out["regimes"][r] = {"samples": int(len(g)), "weeks": int(g["week"].nunique()), **table(g, weeks)}
    json.dump(out, open(a.out, "w"), ensure_ascii=False, separators=(",", ":"))
    print(out["source"])
    print(f"{out['samples']:,} samples from {out['etfs']} ETFs. Regimes: " +
          ", ".join(f"{r} {v['samples']:,} ({v['weeks']} weeks)" for r, v in out["regimes"].items()))
    for h in HORIZONS:
        x = out["any"][h]
        print(f"Any ETF, {h}: {x['up']*100:.0f}% higher, 95% range {x['lo']*100:.0f}–{x['hi']*100:.0f}%, n={x['n']:,}")
    return out


if __name__ == "__main__":
    main()
