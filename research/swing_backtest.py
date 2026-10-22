"""Research only: do simple 1-5 day trades make money on ASX ETFs and big shares after costs?

Rules are fixed here BEFORE looking at results, then judged on two periods:
  design period  2012 - 2019
  test period    2020 - now   (the one that counts)

Long only (Betashares can't short). Signals use the day's close; every trade fills at the NEXT day's open,
and every exit is decided at a close and filled at the next open, so nothing uses information you couldn't
have had. Prices are adjusted for distributions, so distributions count as return.
Only tickers trading at least $1M a day (median of the last 60 days) can be bought, as in the live tool.

Costs: Betashares brokerage is $0; each round trip pays the spread plus slippage (see round_trip_cost),
also shown at zero and double cost.

Account: $10,000, up to 5 positions of 20% each. Uninvested cash earns nothing (in practice AAA pays about
4%, so this understates a mostly-in-cash rule a little). Compared with buying and holding STW.

Usage: python research/swing_backtest.py DATA_DIR OUT_DIR"""
import glob, json, math, os, sys
import numpy as np
import pandas as pd

DESIGN = ("2012-01-01", "2019-12-31")
TEST = ("2020-01-01", "2100-01-01")
SLOTS = 5
LIQ_MIN = 1_000_000.0
CORE_ETFS = {"STW", "IOZ", "A200", "VAS", "IVV", "VGS", "NDQ", "AAA"}
SHARES = {"BHP", "CBA", "CSL", "NAB", "WBC", "ANZ", "FMG", "RIO", "WES", "MQG", "WDS", "TLS", "XRO", "PLS"}
EXCLUDE = {"AAA"}                     # cash ETF: never a trade


def round_trip_cost(t):
    return 0.0008 if (t in CORE_ETFS or t in SHARES) else 0.0025


def load(data_dir):
    out = {}
    for p in sorted(glob.glob(os.path.join(data_dir, "*.csv.gz"))):
        t = os.path.basename(p).split(".")[0]
        if t in EXCLUDE:
            continue
        df = pd.read_csv(p, parse_dates=["date"]).set_index("date").sort_index()
        df = df[(df["close"] > 0) & (df["open"] > 0) & (df["volume"] > 0)]
        if len(df) < 300:
            continue
        f = df["adjusted_close"] / df["close"]
        d = pd.DataFrame({"o": df["open"] * f, "h": df["high"] * f, "l": df["low"] * f, "c": df["adjusted_close"]})
        d["turn"] = (df["close"] * df["volume"]).rolling(60, min_periods=40).median()
        # drop days with an implausible move (data errors): over 25% close to close
        bad = d["c"].pct_change().abs() > 0.25
        d = d[~bad]
        out[t] = d
    return out


def rsi(c, n):
    ch = c.diff()
    up = ch.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-ch.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def indicators(d):
    d = d.copy()
    d["sma200"] = d["c"].rolling(200).mean()
    d["sma5"] = d["c"].rolling(5).mean()
    d["rsi2"] = rsi(d["c"], 2)
    d["hi20"] = d["c"].rolling(20).max()
    tr = pd.concat([d["h"] - d["l"], (d["h"] - d["c"].shift()).abs(), (d["l"] - d["c"].shift()).abs()], axis=1).max(axis=1)
    d["atr14"] = tr.rolling(14).mean()
    rng = (d["h"] - d["l"]).replace(0, np.nan)
    d["ibs"] = (d["c"] - d["l"]) / rng
    d["down3"] = (d["c"] < d["c"].shift(1)) & (d["c"].shift(1) < d["c"].shift(2)) & (d["c"].shift(2) < d["c"].shift(3))
    d["uptrend"] = d["c"] > d["sma200"]
    d["liquid"] = d["turn"] >= LIQ_MIN
    return d


# ---------- the rules (fixed). Each: entry signal at close, and an exit test at each later close. ----------
# exit(d, i_entry_bar, i_now, entry_price) -> True to sell at the next open

RULES = {
    "RSI(2) dip in an uptrend": {
        "doc": "Above its 200-day average and 2-day RSI under 10. Sell after the first close above the 5-day average, or after 5 days.",
        "entry": lambda d: d["uptrend"] & (d["rsi2"] < 10),
        "exit": lambda d, e, i, px: d["c"].iat[i] > d["sma5"].iat[i] or i - e >= 4,
        "rank": "rsi2",
    },
    "3 down days in an uptrend": {
        "doc": "Above its 200-day average after three lower closes in a row. Sell after 3 days.",
        "entry": lambda d: d["uptrend"] & d["down3"],
        "exit": lambda d, e, i, px: i - e >= 2,
        "rank": "rsi2",
    },
    "20-day breakout": {
        "doc": "Closes at a 20-day high while above its 200-day average. Sell if it closes 2 ATR below the buy price, else after 5 days.",
        "entry": lambda d: d["uptrend"] & (d["c"] >= d["hi20"]),
        "exit": lambda d, e, i, px: d["c"].iat[i] < px - 2 * d["atr14"].iat[e] or i - e >= 4,
        "rank": "-ret20",
    },
    "Weak close in an uptrend": {
        "doc": "Above its 200-day average and closes in the bottom 20% of the day's range. Sell after 1 day.",
        "entry": lambda d: d["uptrend"] & (d["ibs"] < 0.2),
        "exit": lambda d, e, i, px: True,
        "rank": "ibs",
    },
}


def all_trades(data, rule):
    """Every signal as an independent trade (no position limit). Entry at next open, exit at the open after
    the exit close. Returns DataFrame of trades."""
    rows = []
    for t, d in data.items():
        sig = (rule["entry"](d) & d["liquid"]).values
        o, n = d["o"].values, len(d)
        i = 0
        while i < n - 1:
            if sig[i] and not np.isnan(d["sma200"].iat[i]):
                e = i + 1                         # bought at the open of bar e
                px = o[e]
                j = e
                while j < n - 1 and not rule["exit"](d, e, j, px):
                    j += 1
                if j >= n - 1:
                    break                         # still open at the end of the data
                rows.append({"ticker": t, "signal": d.index[i], "entry": d.index[e], "exit": d.index[j + 1],
                             "gross": o[j + 1] / px - 1, "cost": round_trip_cost(t), "days": j + 1 - e})
                i = j + 1                         # one position per ticker at a time
            else:
                i += 1
    return pd.DataFrame(rows)


def account(data, tr, cost_mult, cal):
    """$10,000 with up to SLOTS positions of 1/SLOTS of equity each. Signals on the same day are taken
    in rank order (most extreme first). Marked to market at each close. Returns daily equity Series."""
    if tr.empty:
        return pd.Series(1.0, index=cal)
    tr = tr.sort_values(["entry", "rank"]).reset_index(drop=True)
    by_entry = {k: g for k, g in tr.groupby("entry")}
    cash, pos, eq = 1.0, [], []
    closes = {t: d["c"] for t, d in data.items()}
    opens = {t: d["o"] for t, d in data.items()}
    for day in cal:
        # exits fill at today's open
        keep = []
        for p in pos:
            if p["exit"] == day:
                cash += p["units"] * opens[p["t"]].get(day, p["last"]) * (1 - p["c"] / 2)
            else:
                keep.append(p)
        pos = keep
        # entries at today's open
        if day in by_entry:
            equity_now = cash + sum(p["units"] * p["last"] for p in pos)
            for _, r in by_entry[day].iterrows():
                if len(pos) >= SLOTS:
                    break
                if any(p["t"] == r["ticker"] for p in pos):
                    continue
                spend = min(equity_now / SLOTS, cash)
                if spend <= 1e-9:
                    break
                c = r["cost"] * cost_mult
                px = opens[r["ticker"]][day]
                pos.append({"t": r["ticker"], "units": spend * (1 - c / 2) / px, "exit": r["exit"], "c": c, "last": px})
                cash -= spend
        for p in pos:
            p["last"] = closes[p["t"]].get(day, p["last"])
        eq.append(cash + sum(p["units"] * p["last"] for p in pos))
    return pd.Series(eq, index=cal)


def acct_stats(eq):
    if len(eq) < 30:
        return {}
    r = eq.pct_change().fillna(0)
    yrs = len(eq) / 252
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    dd = (eq / eq.cummax() - 1).min()
    sh = r.mean() / r.std() * math.sqrt(252) if r.std() > 0 else 0
    return {"per_year_pct": round(cagr * 100, 2), "worst_fall_pct": round(dd * 100, 1), "sharpe": round(float(sh), 2)}


def trade_stats(tr, mult, yrs):
    if tr.empty:
        return {"trades": 0}
    net = tr["gross"] - tr["cost"] * mult
    t = net.mean() / (net.std() / math.sqrt(len(net))) if net.std() > 0 else 0
    return {"trades": int(len(net)), "per_year": round(len(net) / yrs, 1), "avg_net_pct": round(net.mean() * 100, 3),
            "win_pct": round((net > 0).mean() * 100, 1), "t_stat": round(float(t), 2),
            "avg_days": round(float(tr["days"].mean()), 1)}


def main():
    data_dir, out_dir = sys.argv[1], sys.argv[2]
    raw = load(data_dir)
    data = {t: indicators(d) for t, d in raw.items()}
    os.makedirs(out_dir, exist_ok=True)
    cal = sorted(set().union(*[set(d.index) for d in data.values()]))
    cal = pd.DatetimeIndex(cal)
    cal = cal[cal >= pd.Timestamp(DESIGN[0])]
    periods = {"design (2012-19)": DESIGN, "test (2020-now)": TEST}
    res = {"tickers": len(data), "data_to": str(cal[-1].date()), "rules": {}, "yardstick": {}}

    stw = data["STW"]["c"].reindex(cal).ffill()
    for pn, (a, b) in periods.items():
        res["yardstick"][f"STW buy and hold, {pn}"] = acct_stats(stw[(stw.index >= a) & (stw.index <= b)])

    for name, rule in RULES.items():
        tr = all_trades(data, rule)
        if not tr.empty:
            rk = rule["rank"]
            if rk == "-ret20":
                tr["rank"] = [-(data[t]["c"].loc[s] / data[t]["c"].shift(20).loc[s] - 1) for t, s in zip(tr["ticker"], tr["signal"])]
            else:
                tr["rank"] = [data[t][rk].loc[s] for t, s in zip(tr["ticker"], tr["signal"])]
        out = {"doc": rule["doc"]}
        eqs = {lab: account(data, tr, m, cal) for lab, m in (("no cost", 0.0), ("realistic cost", 1.0), ("double cost", 2.0))}
        for pn, (a, b) in periods.items():
            part = tr[(tr["entry"] >= a) & (tr["entry"] <= b)] if not tr.empty else tr
            days = cal[(cal >= a) & (cal <= b)]
            yrs = len(days) / 252
            o = {}
            for lab, m in (("no cost", 0.0), ("realistic cost", 1.0), ("double cost", 2.0)):
                e = eqs[lab]
                o[lab] = {"every signal": trade_stats(part, m, yrs),
                          "account": acct_stats(e[(e.index >= a) & (e.index <= b)])}
            for grp, f in (("ETFs only", lambda x: x not in SHARES), ("shares only", lambda x: x in SHARES)):
                sub = part[part["ticker"].map(f)] if not part.empty else part
                o[grp + " (realistic cost)"] = trade_stats(sub, 1.0, yrs)
            out[pn] = o
        if not tr.empty:
            te = tr[tr["entry"] >= TEST[0]]
            out["test by year (avg net % per trade, realistic cost)"] = {
                str(y): round(float((g["gross"] - g["cost"]).mean() * 100), 3) for y, g in te.groupby(te["entry"].dt.year)}
        res["rules"][name] = out

    json.dump(res, open(os.path.join(out_dir, "swing_backtest.json"), "w"), indent=1, default=str)
    lines = ["| Rule | Period | Signals/yr | Avg net/trade | Win % | t | Account %/yr | Worst fall | Sharpe |",
             "|---|---|---|---|---|---|---|---|---|"]
    for name, r in res["rules"].items():
        for pn in periods:
            s, a = r[pn]["realistic cost"]["every signal"], r[pn]["realistic cost"]["account"]
            if s.get("trades"):
                lines.append(f"| {name} | {pn} | {s['per_year']} | {s['avg_net_pct']}% | {s['win_pct']} | {s['t_stat']} | "
                             f"{a.get('per_year_pct')}% | {a.get('worst_fall_pct')}% | {a.get('sharpe')} |")
    for k, v in res["yardstick"].items():
        lines.append(f"| {k} | | | | | | {v.get('per_year_pct')}% | {v.get('worst_fall_pct')}% | {v.get('sharpe')} |")
    open(os.path.join(out_dir, "swing_backtest.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
