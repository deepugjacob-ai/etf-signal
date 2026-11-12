"""Offline check of other rule ideas (not used by the live engine, never changes the live rules).

Question it answers: when Strategy B has a bad run, would a different rule have done better over the long history?
It replays the live rules and several commonly suggested alternatives over the same period, with the same fills and
costs as engine.backtest (decide at the week's last close, trade at the next day's close, 0.15% per trade):

- rank by momentum divided by volatility (less weight on the jumpiest funds)
- momentum that ignores the latest month
- a trailing stop: sell at the weekly check once a holding is 8/10/12/15% below its highest close since purchase
- broad funds only (no single-sector or thematic ETFs)
- a monthly check instead of weekly
- no new purchases more than 20% above the trend line
- the index mix, holding each part only while it is above its own 200-day trend line

Usage: EODHD_API_KEY=... python -m engine.variants [--cache DIR] [--out docs/variants.json]
       python -m engine.variants --csv DIR      (DIR holds TICKER.csv.gz daily files: date,open,high,low,close,adjusted_close,volume)

With --csv there is no index file, so the market trend test uses STW's price in place of the ASX 200.

How to read it: look at whether ANY row clearly beats the live rules and the index mix. Picking the best row from a
list like this and switching to it is overfitting. A change should only follow if an idea wins clearly, for a reason
that makes sense, and then survives its own paper period."""
import argparse, datetime as dt, json, os
import numpy as np
import pandas as pd
from . import config as C
from . import portfolio as PF
from .backtest import bench, with_cash_history
from .indicators import clean_prices, compute
from .strategies import b_new_weights, decide_b

START = "2014-01-01"      # after the 2013 IVV distribution errors in the provider's adjusted prices
NARROW = {"Technology", "Energy", "Gold", "Australian resources", "Australian banks", "Healthcare", "Japan", "Europe"}


def load_csv(folder: str):
    adj, close, vol = {}, {}, {}
    for k in C.UNIVERSE + [C.CASH]:
        df = pd.read_csv(os.path.join(folder, k + ".csv.gz"), parse_dates=["date"]).set_index("date").sort_index()
        adj[k], close[k], vol[k] = df["adjusted_close"].astype(float), df["close"].astype(float), df["volume"].astype(float)
    adj, close, vol = pd.DataFrame(adj).sort_index(), pd.DataFrame(close).sort_index(), pd.DataFrame(vol).sort_index()
    adj[C.INDEX] = close["STW"]
    close[C.INDEX] = close["STW"]
    return adj, close, close * vol


def run(px, ind, start=START, stop=None, every="W"):
    """Strategy B replayed with the live decision and portfolio code. stop: fraction below the highest close since
    purchase that makes a holding ineligible at the next check. every: 'W' weekly or 'M' monthly checks."""
    idx = px.loc[start:].index
    per = set(pd.Series(idx, index=idx).groupby(idx.to_period(every)).last())
    pf = PF.new_portfolio(px[C.CASH].loc[idx[0]])
    pend, eq, inv, peak, n = None, [], [], {}, 0
    for t in idx:
        prices = px.loc[t].to_dict()
        if pend is not None:
            keep, when = pend; pend = None
            held = list(pf["units"])
            if set(keep) != set(held) or PF.needs_trim(pf, prices):
                new = [k for k in keep if k not in held]
                n += len(PF.rebalance_b(pf, keep, b_new_weights(ind, when, keep, new), prices))
                for k in new:
                    peak[k] = prices[k]
        for k in pf["units"]:
            peak[k] = max(peak.get(k, 0.0), prices[k])
        if t in per:
            held = list(pf["units"])
            if stop:
                held = [k for k in held if prices[k] >= peak[k] * (1 - stop)]
            keep = decide_b(ind, t, held)[0]
            if stop:      # something just stopped out isn't bought straight back
                keep = [k for k in keep if k in held or k not in pf["units"]]
            pend = (keep, t)
        v = PF.value(pf, prices)
        eq.append(v); inv.append(1 - pf["cash_units"] * prices[C.CASH] / v)
    return pd.Series(eq, index=idx), float(np.mean(inv)), n


def trend_mix(px, start=START):
    """The 40/40/20 index mix, each part held only while above its own 200-day line (same 101%/98% lines), else cash."""
    idx = px.loc[start:].index
    per = set(pd.Series(idx, index=idx).groupby(idx.to_period("W")).last())
    w = pd.Series(C.BENCH_MIX)
    sma = px[list(w.index)].rolling(C.B_MA).mean()
    R = px[list(w.index) + [C.CASH]].pct_change(fill_method=None).fillna(0)
    hold = {k: True for k in w.index}
    cur, pend, val, out, n = None, None, 1.0, [], 0
    for t in idx:
        if cur is not None:
            val *= 1 + sum(cur[k] * R.at[t, k] for k in w.index) + (1 - sum(cur.values())) * R.at[t, C.CASH]
        if pend is not None:
            if cur is not None:
                val *= 1 - sum(abs(pend[k] - cur[k]) for k in w.index) * C.COST
                n += sum(pend[k] != cur[k] for k in w.index)
            cur, pend = pend, None
        if cur is None:
            cur = {k: float(w[k]) for k in w.index}
        if t in per:
            for k in w.index:
                p, s = px.at[t, k], sma.at[t, k]
                if hold[k] and p < s * (1 - C.B_BAND):
                    hold[k] = False
                elif not hold[k] and p > s * (1 + C.B_BAND / 2):
                    hold[k] = True
            pend = {k: (float(w[k]) if hold[k] else 0.0) for k in w.index}
        out.append(val)
    return pd.Series(out, index=idx), n


def stats(eq: pd.Series, cash: pd.Series) -> dict:
    r = eq.pct_change().fillna(0)
    ex = r - cash.pct_change(fill_method=None).reindex(r.index).fillna(0)

    def cagr(s):
        return float((s.iloc[-1] / s.iloc[0]) ** (252 / len(s)) - 1) if len(s) > 1 else None

    return {"cagr": cagr(eq), "max_dd": float((eq / eq.cummax() - 1).min()),
            "sharpe": float(ex.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else None,
            "cagr_first": cagr(eq.loc[:"2019"]), "cagr_second": cagr(eq.loc["2020":])}


def build(px, turnover) -> dict:
    cash = px[C.CASH]
    base = compute(px, turnover)
    P = base["P"]
    rows = []

    def add(name, kind, eq, invested=None, trades=None, note=""):
        rows.append({"name": name, "kind": kind, **stats(eq, cash), "invested": invested,
                     "trades_per_year": (trades / (len(eq) / 252)) if trades is not None else None, "note": note})
        r = rows[-1]
        print(f"{name:52s} {r['cagr']*100:5.1f}% a year, worst fall {r['max_dd']*100:6.1f}%")

    add("Index mix, bought and held", "index", bench(px, START), 1.0, None, "40% STW, 40% IVV, 20% VEU, rebalanced monthly")
    add("Live rules (version %d)" % C.RULES_VERSION, "live", *run(px, base))
    vol = P.pct_change(fill_method=None).rolling(126).std() * np.sqrt(252)
    ind = dict(base); ind["score"] = (base["score"] / vol).where(base["base"])
    add("Rank by momentum divided by volatility", "variant", *run(px, ind), note="Favours steadier funds over the jumpiest ones")
    skip = sum(P.shift(21) / P.shift(l + 21) - 1 for l in C.B_LOOKBACKS) / len(C.B_LOOKBACKS)
    ind = dict(base); ind["score"] = skip.where(base["base"])
    add("Momentum ignoring the latest month", "variant", *run(px, ind), note="A common academic version of momentum")
    for s in (0.08, 0.10, 0.12, 0.15):
        add(f"Live rules plus a {s*100:.0f}% trailing stop", "variant", *run(px, base, stop=s),
            note="Sells at the weekly check once that far below the highest close since purchase")
    ind = dict(base); ind["base"] = base["base"] & pd.Series({k: C.THEME_OF[k] not in NARROW for k in C.UNIVERSE})
    add("Broad funds only", "variant", *run(px, ind), note="No single-sector or thematic ETFs")
    add("Live rules, checked monthly", "variant", *run(px, base, every="M"))
    ind = dict(base); ind["above_in"] = base["above_in"] & (P < base["sma"] * 1.20)
    add("No new buys more than 20% above the trend line", "variant", *run(px, ind), note="Avoids buying the most stretched funds")
    eq, n = trend_mix(px)
    add("Index mix, each part only while above its trend line", "variant", eq, None, n)

    live = next(r for r in rows if r["kind"] == "live")
    mix = next(r for r in rows if r["kind"] == "index")
    var = [r for r in rows if r["kind"] == "variant"]
    return {"built": dt.date.today().isoformat(), "start": str(px.loc[START:].index[0].date()), "end": str(px.index[-1].date()),
            "rules_version": C.RULES_VERSION, "fills": "next day's close, 0.15% cost per trade", "rows": rows,
            "summary": {"variants": len(var), "beat_live": int(sum(r["cagr"] > live["cagr"] + 0.005 for r in var)),
                        "beat_mix": int(sum(r["cagr"] > mix["cagr"] for r in var)),
                        "best_variant": float(max(r["cagr"] for r in var)), "live": live["cagr"], "mix": mix["cagr"]}}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.expanduser("~/.etf-signal-cache"))
    ap.add_argument("--csv", help="folder of TICKER.csv.gz daily files, instead of downloading from EODHD")
    ap.add_argument("--out", default="docs/variants.json")
    a = ap.parse_args(argv)
    if a.csv:
        adj, close, turnover = load_csv(a.csv)
        proxy = True
    else:
        from .research import fetch, frames, fix_adjustments
        key = os.environ["EODHD_API_KEY"]
        adj, close, turnover = frames(fetch(key, C.UNIVERSE + [C.CASH, C.INDEX], a.cache))
        adj = fix_adjustments(adj, close, key, a.cache)
        proxy = False
    px = with_cash_history(clean_prices(adj).loc["2011-01-01":])
    out = build(px, turnover.reindex(px.index))
    out["regime_proxy"] = "STW price" if proxy else None
    json.dump(out, open(a.out, "w"), indent=1)
    s = out["summary"]
    print(f"\n{s['variants']} other rule ideas: {s['beat_live']} clearly beat the live rules ({s['live']*100:.1f}% a year), "
          f"{s['beat_mix']} beat the index mix ({s['mix']*100:.1f}%). Best alternative: {s['best_variant']*100:.1f}%.")


if __name__ == "__main__":
    main()
