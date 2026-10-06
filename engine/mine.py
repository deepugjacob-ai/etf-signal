"""Your actual money: deposits and withdrawals, plus the trades you recorded in the dashboard.

Valued the same way as the paper portfolio (adjusted prices from the trade date, so distributions count).
For a fair comparison, every deposit and withdrawal is also applied, on the same day, to two imaginary
portfolios: one that follows every Strategy B recommendation and one that holds the index yardstick.
So "You vs recommendations" always compares the same money, put in on the same days."""
import datetime as dt
import pandas as pd

FLOW = ("DEPOSIT", "WITHDRAW")
ORDER = {"DEPOSIT": 0, "BUY": 1, "SELL": 2, "WITHDRAW": 3}


def _at(series: pd.Series, d: pd.Timestamp):
    s = series.loc[:d].dropna()
    return float(s.iloc[-1]) if len(s) else None


def compute(trades: list, px: pd.DataFrame, close: pd.DataFrame, capital: float, paper_hist: list, today: dt.date):
    warnings, done, flows = [], [], []
    for x in trades or []:
        if x.get("status") != "done":
            continue
        side = x.get("side")
        try:
            d = pd.Timestamp(x["date"])
        except (KeyError, TypeError, ValueError):
            warnings.append(f"Skipped a record with no valid date ({x.get('id', '?')})."); continue
        if d.date() > today:
            warnings.append(f"Skipped {x.get('id','?')}: dated in the future."); continue
        if side in FLOW:
            try:
                amt = float(x["amount"])
            except (KeyError, TypeError, ValueError):
                warnings.append(f"Skipped a deposit or withdrawal with no amount ({x.get('id','?')})."); continue
            if amt <= 0:
                warnings.append(f"Skipped {x.get('id','?')}: amount must be above zero."); continue
            flows.append({**x, "_d": d, "_a": amt})
            continue
        try:
            u = float(x["units"]); p = float(x["price"]); k = x["ticker"]
        except (KeyError, TypeError, ValueError):
            warnings.append(f"Skipped an incomplete trade record ({x.get('id', '?')})."); continue
        if k not in px.columns or side not in ("BUY", "SELL") or u <= 0 or p <= 0:
            warnings.append(f"Skipped trade {x.get('id','?')}: check ticker, side, units and price."); continue
        a, r = _at(px[k], d), _at(close[k], d)
        if not a or not r:
            warnings.append(f"Skipped trade {x.get('id','?')}: no price history for {k} on {x['date']}."); continue
        done.append({**x, "_d": d, "_u": u, "_p": p, "_ratio": a / r})

    if not done and not flows:
        return {"has_trades": False, "warnings": warnings, "records": len(trades or [])}
    legacy = not flows
    if legacy:
        # Older records: no deposits logged, so the investment amount in Settings is the starting cash,
        # treated as deposited on the day of the first trade.
        first = min(z["_d"] for z in done)
        flows = [{"id": "start", "side": "DEPOSIT", "date": first.date().isoformat(), "_d": first, "_a": float(capital),
                  "note": "Starting amount (from Settings)"}]
    events = sorted(done + flows, key=lambda z: (z["_d"], ORDER[z["side"]]))

    start = events[0]["_d"]
    days = px.loc[start:].index
    paper = pd.DataFrame(paper_hist or [])
    if len(paper):
        paper["d"] = pd.to_datetime(paper["d"]); paper = paper.set_index("d").sort_index()
    def paper_at(col, d):
        if not len(paper) or col not in paper:
            return None
        v = _at(paper[col], d)
        return v if v else float(paper[col].dropna().iloc[0])

    lots, realised, hist = {}, [], []
    cash = contributed = 0.0
    units_r = units_m = 0.0          # imaginary portfolios fed with the same deposits and withdrawals

    def apply(z):
        nonlocal cash, contributed, units_r, units_m
        if z["side"] in FLOW:
            sign = 1 if z["side"] == "DEPOSIT" else -1
            cash += sign * z["_a"]; contributed += sign * z["_a"]
            b, m = paper_at("B", z["_d"]), paper_at("M", z["_d"])
            if b: units_r += sign * z["_a"] / b
            if m: units_m += sign * z["_a"] / m
            return
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
                take = min(left, lot["units"]); frac = take / lot["units"]
                held = (z["_d"] - pd.Timestamp(lot["date"])).days
                realised.append({"date": z["date"], "ticker": k, "units": take, "proceeds": take * p,
                                 "cost": take * lot["price"], "gain": take * (p - lot["price"]), "days": held,
                                 "long_term": held >= 365})
                lot["adj_units"] -= lot["adj_units"] * frac; lot["units"] -= take; left -= take
                if lot["units"] <= 1e-9:
                    lots[k].remove(lot)
            if left > 1e-6:
                warnings.append(f"Sold {left:.2f} more {k} units than recorded as bought on {z['date']}.")

    i = 0
    for t in days:
        while i < len(events) and events[i]["_d"] <= t:
            apply(events[i]); i += 1
        v = cash + sum(l["adj_units"] * px.at[t, k] for k, ls in lots.items() for l in ls if pd.notna(px.at[t, k]))
        b, m = paper_at("B", t), paper_at("M", t)
        hist.append({"d": t.date().isoformat(), "Y": v, "C": contributed,
                     "R": units_r * b if b else None, "M": units_m * m if m else None})
    if i < len(events):              # anything dated today before today's prices exist
        for z in events[i:]:
            apply(z)

    t = days[-1] if len(days) else start
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
    last = hist[-1] if hist else {"Y": cash, "R": None, "M": None}
    flow_view = [{"date": z["date"], "side": z["side"], "amount": z["_a"], "id": z.get("id"), "note": z.get("note")}
                 for z in sorted(flows, key=lambda z: z["_d"])]
    return {"has_trades": True, "legacy": legacy, "start": start.date().isoformat(), "compare_from": start.date().isoformat(),
            "capital": contributed, "contributed": contributed, "cash": cash, "value": last["Y"],
            "gain": last["Y"] - contributed, "rec_value": last.get("R"), "index_value": last.get("M"),
            "holdings": holdings, "realised": realised[-100:], "flows": flow_view, "history": hist, "warnings": warnings,
            "records": len(trades or [])}
