"""Research only: does any simple intraday rule make money on ASX ETFs and big shares after costs?

Rules are fixed here BEFORE looking at results, then judged on two periods:
  design period  Oct 2020 - Dec 2023
  test period    Jan 2024 - now   (the one that counts)

Long only (Betashares Direct can't short). One trade per ticker per day, always flat by 15:55,
before the closing auction. Signals use completed 5-minute bars only and fill at the NEXT bar's open.
If a bar touches both the stop and the target, the stop is assumed to hit first.

Costs: Betashares brokerage is $0, but every round trip pays the bid-ask spread plus a little slippage.
Spread estimates per ticker are in SPREAD below; results are also shown at zero and at double cost.

Usage: python research/intraday_backtest.py DATA_DIR OUT_DIR"""
import glob, json, math, os, sys
import numpy as np
import pandas as pd

TZ = "Australia/Sydney"
TEST_FROM = pd.Timestamp("2024-01-01")

# Round-trip cost (spread + slippage), as a fraction. Conservative estimates for small retail orders.
CORE_ETFS = {"STW", "IOZ", "A200", "VAS", "IVV", "VGS", "NDQ", "AAA"}
SHARES = {"BHP", "CBA", "CSL", "NAB", "WBC", "ANZ", "FMG", "RIO", "WES", "MQG", "WDS", "TLS", "XRO", "PLS"}


def round_trip_cost(t):
    if t in CORE_ETFS:
        return 0.0008
    if t in SHARES:
        return 0.0008
    return 0.0025            # thematic / sector ETFs: wider spreads


def load(data_dir):
    out = {}
    for p in sorted(glob.glob(os.path.join(data_dir, "*.csv.gz"))):
        t = os.path.basename(p).split(".")[0]
        df = pd.read_csv(p)
        if df.empty:
            continue
        idx = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(TZ)
        df = df.drop(columns="ts").set_index(idx).astype(float)
        hm = df.index.hour * 100 + df.index.minute
        df = df[(hm >= 1000) & (hm < 1600) & (df["volume"] > 0)]       # continuous trading only
        df = df[~df.index.duplicated()]
        out[t] = df
    return out


# ---------- the rules (fixed) ----------

def _sim_day(day, entry_i, stop, target):
    """Long from the open of bar entry_i. Exit at stop/target, or at the open of the 15:55 bar.
    Returns (gross return, exit reason) or None."""
    o, h, l = day["open"].values, day["high"].values, day["low"].values
    hm = day.index.hour * 100 + day.index.minute
    last = np.where(hm >= 1555)[0]
    if entry_i >= len(day) or len(last) == 0 or entry_i >= last[0]:
        return None
    end = last[0]
    px = o[entry_i]
    if not (px > 0):
        return None
    for i in range(entry_i, end):
        if stop is not None and l[i] <= stop:
            fill = min(stop, o[i]) if i > entry_i else min(stop, px)
            return fill / px - 1, "stop"
        if target is not None and h[i] >= target:
            fill = max(target, o[i]) if i > entry_i else max(target, px)
            return fill / px - 1, "target"
    return o[end] / px - 1, "close"


def rule_orb(day, prev_close):
    """Opening range breakout: high/low of 10:10-10:40. Buy on the first close above the range high
    (before 13:00); stop at the range low; hold to the close."""
    hm = day.index.hour * 100 + day.index.minute
    rng = day[(hm >= 1010) & (hm < 1040)]
    if len(rng) < 5:
        return None
    hi, lo = rng["high"].max(), rng["low"].min()
    if hi <= lo:
        return None
    cand = np.where((hm >= 1040) & (hm < 1300) & (day["close"].values > hi))[0]
    if len(cand) == 0:
        return None
    return _sim_day(day, cand[0] + 1, lo, None)


def rule_vwap_reversion(day, prev_close):
    """Buy a sharp dip: first close at least 1.0% below the day's running VWAP (after 10:40).
    Target: back to 0.5% below VWAP at entry. Stop: a further 1.0% down. Otherwise exit at close."""
    hm = day.index.hour * 100 + day.index.minute
    tp = (day["high"] + day["low"] + day["close"]) / 3
    vwap = (tp * day["volume"]).cumsum() / day["volume"].cumsum()
    gap = day["close"] / vwap - 1
    cand = np.where((hm >= 1040) & (hm < 1500) & (gap.values <= -0.010))[0]
    if len(cand) == 0 or cand[0] + 1 >= len(day):
        return None
    i = cand[0] + 1
    px = day["open"].values[i]
    target = vwap.values[cand[0]] * 0.995
    if target <= px:                  # already bounced back before we could buy: no trade
        return None
    return _sim_day(day, i, px * 0.99, target)


def rule_gap_down_fade(day, prev_close):
    """If the first 10:10 bar opens 1% or more below yesterday's close, buy at 10:15 and hold to close,
    stop 1.5% below entry."""
    hm = day.index.hour * 100 + day.index.minute
    first = np.where(hm >= 1010)[0]
    if len(first) == 0 or prev_close is None or not (prev_close > 0):
        return None
    i = first[0]
    if day["open"].values[i] / prev_close - 1 > -0.01 or i + 1 >= len(day):
        return None
    return _sim_day(day, i + 1, day["open"].values[i + 1] * 0.985, None)


def rule_trend_day(day, prev_close):
    """Momentum: at 12:00, if the price is up at least 0.7% from yesterday's close AND above VWAP,
    buy and hold to the close, stop at the day's low so far."""
    hm = day.index.hour * 100 + day.index.minute
    tp = (day["high"] + day["low"] + day["close"]) / 3
    vwap = (tp * day["volume"]).cumsum() / day["volume"].cumsum()
    at = np.where(hm >= 1155)[0]
    if len(at) == 0 or prev_close is None or at[0] + 1 >= len(day):
        return None
    i = at[0]
    c = day["close"].values[i]
    if c / prev_close - 1 < 0.007 or c < vwap.values[i]:
        return None
    return _sim_day(day, i + 1, day["low"].values[:i + 1].min(), None)


def rule_baseline(day, prev_close):
    """Yardstick, not a strategy: buy every day at 10:15, sell at 15:55. Shows the cost of just being in."""
    hm = day.index.hour * 100 + day.index.minute
    first = np.where(hm >= 1015)[0]
    if len(first) == 0:
        return None
    return _sim_day(day, first[0], None, None)


RULES = {
    "Opening range breakout": rule_orb,
    "Dip below VWAP (mean reversion)": rule_vwap_reversion,
    "Gap-down fade": rule_gap_down_fade,
    "Strong-morning momentum": rule_trend_day,
    "Baseline: in 10:15, out 15:55": rule_baseline,
}


def trades(data, rule):
    rows = []
    for t, df in data.items():
        cost = round_trip_cost(t)
        prev_close = None
        for d, day in df.groupby(df.index.date):
            if len(day) >= 40:                               # skip half-days and data gaps
                r = rule(day, prev_close)
                if r is not None:
                    rows.append({"date": pd.Timestamp(d), "ticker": t, "gross": r[0], "cost": cost, "exit": r[1]})
            prev_close = day["close"].values[-1]
    return pd.DataFrame(rows)


def account(tr, cost_mult, slots=3):
    """$ account: each day, up to `slots` trades (in ticker order), each using 1/slots of capital.
    Unused slots stay in cash (no interest). Returns daily returns."""
    if tr.empty:
        return pd.Series(dtype=float)
    net = tr["gross"] - tr["cost"] * cost_mult
    tr = tr.assign(net=net).sort_values(["date", "ticker"])
    daily = tr.groupby("date")["net"].apply(lambda s: s.head(slots).sum() / slots)
    return daily


def stats(tr, daily, cost_mult, all_days):
    if tr.empty:
        return {"trades": 0}
    net = tr["gross"] - tr["cost"] * cost_mult
    years = max(len(all_days) / 252, 1e-9)
    d = daily.reindex(all_days, fill_value=0.0)
    eq = (1 + d).cumprod()
    cagr = eq.iloc[-1] ** (1 / years) - 1
    dd = (eq / eq.cummax() - 1).min()
    sharpe = d.mean() / d.std() * math.sqrt(252) if d.std() > 0 else 0.0
    t = net.mean() / (net.std() / math.sqrt(len(net))) if net.std() > 0 else 0.0
    return {"trades": int(len(tr)), "trades_per_year": round(len(tr) / years, 1),
            "avg_net_pct": round(net.mean() * 100, 3), "win_rate_pct": round((net > 0).mean() * 100, 1),
            "t_stat": round(float(t), 2), "account_cagr_pct": round(cagr * 100, 2),
            "account_worst_fall_pct": round(dd * 100, 1), "sharpe": round(float(sharpe), 2)}


def main():
    data_dir, out_dir = sys.argv[1], sys.argv[2]
    data = load(data_dir)
    os.makedirs(out_dir, exist_ok=True)
    all_dates = sorted({pd.Timestamp(d) for df in data.values() for d in df.index.date})
    periods = {"design (2020-23)": [d for d in all_dates if d < TEST_FROM],
               "test (2024-now)": [d for d in all_dates if d >= TEST_FROM]}
    res = {"tickers": {t: {"days": int(df.index.normalize().nunique()), "from": str(df.index[0].date()),
                           "to": str(df.index[-1].date())} for t, df in data.items()},
           "rules": {}}
    for name, rule in RULES.items():
        tr = trades(data, rule)
        res["rules"][name] = {"doc": " ".join(rule.__doc__.split())}
        for pname, days in periods.items():
            part = tr[tr["date"].isin(days)] if not tr.empty else tr
            res["rules"][name][pname] = {}
            for label, mult in (("no cost", 0.0), ("realistic cost", 1.0), ("double cost", 2.0)):
                res["rules"][name][pname][label] = stats(part, account(part, mult), mult, days)
            # split ETFs vs shares at realistic cost, test period matters most
            for grp, members in (("ETFs only", lambda x: x not in SHARES), ("shares only", lambda x: x in SHARES)):
                sub = part[part["ticker"].map(members)] if not part.empty else part
                res["rules"][name][pname][grp] = stats(sub, account(sub, 1.0), 1.0, days)
        if not tr.empty:
            te = tr[tr["date"] >= TEST_FROM]
            res["rules"][name]["test by year (avg net % per trade, realistic cost)"] = {
                str(y): round(float((g["gross"] - g["cost"]).mean() * 100), 3)
                for y, g in te.groupby(te["date"].dt.year)}
            res["rules"][name]["exit reasons (all)"] = tr["exit"].value_counts().to_dict()
    json.dump(res, open(os.path.join(out_dir, "backtest.json"), "w"), indent=1)
    # short readable table
    lines = ["| Rule | Period | Trades/yr | Avg net/trade | Win % | t | Account %/yr | Worst fall |", "|---|---|---|---|---|---|---|---|"]
    for name, r in res["rules"].items():
        for p in periods:
            s = r[p]["realistic cost"]
            if s.get("trades"):
                lines.append(f"| {name} | {p} | {s['trades_per_year']} | {s['avg_net_pct']}% | {s['win_rate_pct']} | "
                             f"{s['t_stat']} | {s['account_cagr_pct']}% | {s['account_worst_fall_pct']}% |")
    open(os.path.join(out_dir, "backtest.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
