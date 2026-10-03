"""Your actual trades (recorded in the dashboard) valued the same way as the paper portfolio, so the two compare
fairly: dividends are counted by using adjusted prices from the trade date onwards."""
import datetime as dt
import pandas as pd


def _at(series: pd.Series, d: pd.Timestamp):
    s = series.loc[:d].dropna()
    return float(s.iloc[-1]) if len(s) else None


def compute(trades: list, px: pd.DataFrame, close: pd.DataFrame, capital: float, paper_hist: list, today: dt.date):
    warnings, done = [], []
    for x in trades or []:
        if x.get("status") != "done":
            continue
        try:
            d = pd.Timestamp(x["date"]); u = float(x["units"]); p = float(x["price"]); k = x["ticker"]; side = x["side"]
        except (KeyError, TypeError, ValueError):
            warnings.append(f"Skipped an incomplete trade record ({x.get('id', '?')})."); continue
        if k not in px.columns or side not in ("BUY", "SELL") or u <= 0 or p <= 0 or d.date() > today:
            warnings.append(f"Skipped trade {x.get('id','?')}: check ticker, side, units, price and date."); continue
        a, r = _at(px[k], d), _at(close[k], d)
        if not a or not r:
            warnings.append(f"Skipped trade {x.get('id','?')}: no price history for {k} on {x['date']}."); continue
        done.append({**x, "_d": d, "_u": u, "_p": p, "_ratio": a / r})
    done.sort(key=lambda z: (z["_d"], 0 if z["side"] == "BUY" else 1))
    if not done:
        return {"has_trades": False, "warnings": warnings}

    start = done[0]["_d"]
    days = px.loc[start:].index
    lots = {}          # ticker -> list of lots {date, units, price, adj_units}
    cash = capital
    realised = []
    i = 0
    hist = []
    # "Recommended" = what the same money would be worth had it followed Strategy B from the day both
    # records exist: your value on that day, grown at the paper portfolio's rate.
    paper = {pd.Timestamp(h["d"]): h["B"] for h in paper_hist or []}
    paper_s = pd.Series(paper).sort_index() if paper else pd.Series(dtype=float)
    cmp_start = max(start, paper_s.index[0]) if len(paper_s) else None
    base = {}

    def apply(z):
        nonlocal cash
        k, u, p = z["ticker"], z["_u"], z["_p"]
        if z["side"] == "BUY":
            cash -= u * p
            lots.setdefault(k, []).append({"date": z["date"], "units": u, "price": p, "adj_units": u / z["_ratio"]})
        else:
            cash += u * p
            left = u
            for lot in list(lots.get(k, [])):
                if left <= 1e-9:
                    break
                take = min(left, lot["units"])
                frac = take / lot["units"]
                held = (z["_d"] - pd.Timestamp(lot["date"])).days
                realised.append({"date": z["date"], "ticker": k, "units": take, "proceeds": take * p,
                                 "cost": take * lot["price"], "gain": take * (p - lot["price"]), "days": held,
                                 "long_term": held >= 365})
                lot["adj_units"] -= lot["adj_units"] * frac
                lot["units"] -= take
                left -= take
                if lot["units"] <= 1e-9:
                    lots[k].remove(lot)
            if left > 1e-6:
                warnings.append(f"Sold {left:.2f} more {k} units than recorded as bought on {z['date']}.")

    for t in days:
        while i < len(done) and done[i]["_d"] <= t:
            apply(done[i]); i += 1
        v = cash + sum(l["adj_units"] * px.at[t, k] for k, ls in lots.items() for l in ls if pd.notna(px.at[t, k]))
        rec = None
        if cmp_start is not None and t >= cmp_start:
            pv = _at(paper_s, t)
            if "y" not in base:
                base["y"], base["p"] = v, pv
            rec = base["y"] * pv / base["p"] if pv and base["p"] else None
        hist.append({"d": t.date().isoformat(), "Y": v, "R": rec})

    t = days[-1]
    holdings = []
    for k, ls in lots.items():
        if not ls:
            continue
        units = sum(l["units"] for l in ls)
        val = sum(l["adj_units"] * px.at[t, k] for l in ls)
        cost = sum(l["units"] * l["price"] for l in ls)
        lot_view = []
        for l in ls:
            age = (pd.Timestamp(today) - pd.Timestamp(l["date"])).days
            lt = (pd.Timestamp(l["date"]) + pd.Timedelta(days=366)).date().isoformat()
            lot_view.append({"date": l["date"], "units": l["units"], "price": l["price"], "days": age,
                             "long_term": age >= 365, "long_term_from": lt})
        holdings.append({"ticker": k, "units": units, "value": val, "cost": cost, "gain": val - cost,
                         "price": float(close[k].dropna().iloc[-1]), "lots": lot_view})
    holdings.sort(key=lambda h: -h["value"])
    value = hist[-1]["Y"]
    return {"has_trades": True, "start": start.date().isoformat(), "capital": capital, "cash": cash,
            "compare_from": cmp_start.date().isoformat() if cmp_start is not None else None,
            "value": value, "holdings": holdings, "realised": realised[-100:], "history": hist,
            "warnings": warnings}
