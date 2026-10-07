"""Your actual money: deposits and withdrawals, the trades you recorded, and the distributions your ETFs paid.

Holdings are valued at the real market price (what Betashares shows) times the units you hold. Distributions are
counted separately, as cash on their ex-dividend day: an estimate from the published amount per unit times the units
you held the day before, until you record what you actually received (or the units a reinvestment plan gave you).

For a fair comparison, every deposit and withdrawal is also applied, on the same day, to two imaginary
portfolios: one that follows every Strategy B recommendation and one that holds the index yardstick.
So "You vs recommendations" always compares the same money, put in on the same days.

When you sell part of a holding, the parcels sold are the ones that create the least tax: parcels held for more
than 12 months (50% capital gains discount) and parcels bought at a higher price go first. Australia lets you
choose which parcels you sell as long as your records identify them; this record is that identification."""
import datetime as dt
import pandas as pd

FLOW = ("DEPOSIT", "WITHDRAW")
ORDER = {"DEPOSIT": 0, "BUY": 1, "SELL": 2, "DIST": 3, "WITHDRAW": 4}


def _date(x) -> dt.date:
    return x if isinstance(x, dt.date) and not isinstance(x, dt.datetime) else pd.Timestamp(x).date()


def long_term_from(d) -> dt.date:
    """First day a sale gets the 50% CGT discount: held at least 12 months, not counting the day bought or the day sold."""
    d = _date(d)
    try:
        y = d.replace(year=d.year + 1)
    except ValueError:                      # bought on 29 February
        y = d.replace(year=d.year + 1, day=28)
    return y + dt.timedelta(days=1)


def is_long_term(bought, sold) -> bool:
    return _date(sold) >= long_term_from(bought)


def parcel_order(lots: list, price: float, on) -> list:
    """Lots sorted so the least taxable go first: the taxable gain per unit is halved for long-term gains,
    losses count in full (they offset gains before the discount). Ties: oldest first."""
    def key(l):
        g = price - l["price"]
        disc = 0.5 if g > 0 and is_long_term(l["date"], on) else 1.0
        return (g * disc, l["date"])
    return sorted(lots, key=key)


def sale_tax(lots: list, units: float, price: float, on) -> dict:
    """Estimate for a sale of `units` at `price`: gain split into short-term (taxed in full) and long-term."""
    left, short_g, long_g, short_u = units, 0.0, 0.0, 0.0
    for l in parcel_order(lots, price, on):
        if left <= 1e-9:
            break
        take = min(left, l["units"])
        g = take * (price - l["price"])
        if is_long_term(l["date"], on):
            long_g += g
        else:
            short_g += g; short_u += take
        left -= take
    return {"gain": short_g + long_g, "short_gain": short_g, "long_gain": long_g, "short_units": short_u}


def _at(series: pd.Series, d: pd.Timestamp):
    s = series.loc[:d].dropna()
    return float(s.iloc[-1]) if len(s) else None


def compute(trades: list, px: pd.DataFrame, close: pd.DataFrame, capital: float, paper_hist: list, today: dt.date,
            divs: dict = None):
    """divs: {ticker: [{"ex": "YYYY-MM-DD", "pay": "YYYY-MM-DD" | None, "amount": per-unit cash}]}"""
    warnings, done, flows, dist_recs = [], [], [], []
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
        if side in FLOW or side == "DIST":
            try:
                amt = float(x["amount"])
            except (KeyError, TypeError, ValueError):
                warnings.append(f"Skipped a record with no amount ({x.get('id','?')})."); continue
            if amt <= 0:
                warnings.append(f"Skipped {x.get('id','?')}: amount must be above zero."); continue
            if side in FLOW:
                flows.append({**x, "_d": d, "_a": amt})
                continue
            k = x.get("ticker")
            if k not in close.columns:
                warnings.append(f"Skipped distribution {x.get('id','?')}: unknown ETF {k}."); continue
            try:
                drp = float(x.get("units") or 0)
            except (TypeError, ValueError):
                drp = 0.0
            dist_recs.append({**x, "_d": d, "_a": amt, "_drp": max(drp, 0.0)})
            continue
        try:
            u = float(x["units"]); p = float(x["price"]); k = x["ticker"]
        except (KeyError, TypeError, ValueError):
            warnings.append(f"Skipped an incomplete trade record ({x.get('id', '?')})."); continue
        if k not in close.columns or side not in ("BUY", "SELL") or u <= 0 or p <= 0:
            warnings.append(f"Skipped trade {x.get('id','?')}: check ticker, side, units and price."); continue
        if not _at(close[k], d):
            warnings.append(f"Skipped trade {x.get('id','?')}: no price history for {k} on {x['date']}."); continue
        done.append({**x, "_d": d, "_u": u, "_p": p})

    if not done and not flows and not dist_recs:
        return {"has_trades": False, "warnings": warnings, "records": len(trades or [])}
    legacy = not flows
    if legacy:
        # Older records: no deposits logged, so the investment amount in Settings is the starting cash,
        # treated as deposited on the day of the first trade.
        first = min(z["_d"] for z in done + dist_recs)
        flows = [{"id": "start", "side": "DEPOSIT", "date": first.date().isoformat(), "_d": first, "_a": float(capital),
                  "note": "Starting amount (from Settings)"}]

    # Published distributions (estimates) and which of your records confirms each one
    traded = {z["ticker"] for z in done}
    est = []
    for k, rows in (divs or {}).items():
        if k not in traded:
            continue
        for r in rows or []:
            try:
                ex = pd.Timestamp(r["ex"]); per = float(r["amount"])
            except (KeyError, TypeError, ValueError):
                continue
            if per > 0 and ex.date() <= today:
                est.append({"ticker": k, "_ex": ex, "ex": ex.date().isoformat(), "pay": r.get("pay"), "per_unit": per, "rec": None})
    est.sort(key=lambda e: (e["_ex"], e["ticker"]))
    unmatched = []
    for rc in sorted(dist_recs, key=lambda z: z["_d"]):
        cands = [e for e in est if e["ticker"] == rc["ticker"] and e["rec"] is None]
        exact = [e for e in cands if rc.get("ex") and e["ex"] == rc["ex"]]
        near = [e for e in cands if -75 <= (e["_ex"] - rc["_d"]).days <= 10]
        pick = exact[0] if exact else min(near, key=lambda e: abs((e["_ex"] - rc["_d"]).days)) if near else None
        if pick:
            pick["rec"] = rc
        else:
            unmatched.append(rc)

    events = sorted(done + flows + unmatched, key=lambda z: (z["_d"], ORDER[z["side"]]))
    start = events[0]["_d"]          # never empty: there is always at least one deposit
    days = close.loc[start:].index
    paper = pd.DataFrame(paper_hist or [])
    if len(paper):
        paper["d"] = pd.to_datetime(paper["d"]); paper = paper.set_index("d").sort_index()

    def paper_at(col, d):
        if not len(paper) or col not in paper:
            return None
        v = _at(paper[col], d)
        return v if v else float(paper[col].dropna().iloc[0])

    lots, realised, hist, dist_view = {}, [], [], []
    received = {}
    cash = contributed = 0.0
    units_r = units_m = 0.0          # imaginary portfolios fed with the same deposits and withdrawals

    def credit(k, amount, drp_units, when, rec):
        nonlocal cash
        received[k] = received.get(k, 0.0) + amount
        if drp_units > 1e-9:       # reinvested: new units at the reinvestment price, no cash
            lots.setdefault(k, []).append({"date": (rec.get("date") if rec else when), "units": drp_units,
                                           "price": amount / drp_units, "drp": True})
        else:
            cash += amount

    def pay_dist(e):
        k = e["ticker"]
        units = sum(l["units"] for l in lots.get(k, []))
        rc = e["rec"]
        if units <= 1e-9 and rc is None:
            return
        amount = rc["_a"] if rc else units * e["per_unit"]
        drp = rc["_drp"] if rc else 0.0
        credit(k, amount, drp, e["ex"], rc)
        dist_view.append({"ticker": k, "ex": e["ex"], "pay": e.get("pay"), "per_unit": e["per_unit"], "units": units,
                          "estimate": units * e["per_unit"], "amount": amount, "status": "recorded" if rc else "estimated",
                          "id": rc.get("id") if rc else None, "drp_units": drp or None})

    def apply(z):
        nonlocal cash, contributed, units_r, units_m
        if z["side"] in FLOW:
            sign = 1 if z["side"] == "DEPOSIT" else -1
            cash += sign * z["_a"]; contributed += sign * z["_a"]
            b, m = paper_at("B", z["_d"]), paper_at("M", z["_d"])
            if b: units_r += sign * z["_a"] / b
            if m: units_m += sign * z["_a"] / m
            return
        if z["side"] == "DIST":    # a distribution you recorded that matches no published one
            credit(z["ticker"], z["_a"], z["_drp"], z["date"], z)
            dist_view.append({"ticker": z["ticker"], "ex": None, "pay": z["date"], "per_unit": None, "units": None,
                              "estimate": None, "amount": z["_a"], "status": "recorded", "id": z.get("id"),
                              "drp_units": z["_drp"] or None})
            return
        k, u, p = z["ticker"], z["_u"], z["_p"]
        if z["side"] == "BUY":
            cash -= u * p
            lots.setdefault(k, []).append({"date": z["date"], "units": u, "price": p})
        else:
            cash += u * p
            left = u
            for lot in parcel_order(lots.get(k, []), p, z["_d"]):
                if left <= 1e-9:
                    break
                take = min(left, lot["units"])
                held = (z["_d"] - pd.Timestamp(lot["date"])).days
                realised.append({"date": z["date"], "ticker": k, "units": take, "proceeds": take * p,
                                 "cost": take * lot["price"], "gain": take * (p - lot["price"]), "days": held,
                                 "bought": lot["date"], "long_term": is_long_term(lot["date"], z["_d"])})
                lot["units"] -= take; left -= take
            lots[k] = [l for l in lots.get(k, []) if l["units"] > 1e-9]
            if left > 1e-6:
                warnings.append(f"Sold {left:.2f} more {k} units than recorded as bought on {z['date']}.")

    i = j = 0
    for t in days:
        while j < len(est) and est[j]["_ex"] <= t:       # entitlement: units held before this day's trades
            pay_dist(est[j]); j += 1
        while i < len(events) and events[i]["_d"] <= t:
            apply(events[i]); i += 1
        v = cash + sum(l["units"] * close.at[t, k] for k, ls in lots.items() for l in ls if pd.notna(close.at[t, k]))
        b, m = paper_at("B", t), paper_at("M", t)
        hist.append({"d": t.date().isoformat(), "Y": v, "C": contributed,
                     "R": units_r * b if b else None, "M": units_m * m if m else None})
    for e in est[j:]:                # anything dated today before today's prices exist
        pay_dist(e)
    for z in events[i:]:
        apply(z)

    t = days[-1] if len(days) else start
    holdings = []
    for k, ls in lots.items():
        if not ls:
            continue
        units = sum(l["units"] for l in ls)
        price = float(close[k].dropna().iloc[-1])
        val = units * price
        cost = sum(l["units"] * l["price"] for l in ls)
        lot_view = []
        for l in ls:
            age = (pd.Timestamp(today) - pd.Timestamp(l["date"])).days
            lot_view.append({"date": l["date"], "units": l["units"], "price": l["price"], "days": age,
                             "long_term": is_long_term(l["date"], today), "long_term_from": long_term_from(l["date"]).isoformat(),
                             "drp": bool(l.get("drp"))})
        holdings.append({"ticker": k, "units": units, "value": val, "cost": cost, "gain": val - cost,
                         "price": price, "lots": lot_view, "distributions": received.get(k, 0.0)})
    holdings.sort(key=lambda h: -h["value"])
    value_now = cash + sum(h["value"] for h in holdings)
    last = hist[-1] if hist else {"Y": value_now, "R": None, "M": None}
    flow_view = [{"date": z["date"], "side": z["side"], "amount": z["_a"], "id": z.get("id"), "note": z.get("note")}
                 for z in sorted(flows, key=lambda z: z["_d"])]
    dist_view.sort(key=lambda d: d["ex"] or d["pay"] or "", reverse=True)
    return {"has_trades": True, "legacy": legacy, "start": start.date().isoformat(), "compare_from": start.date().isoformat(),
            "capital": contributed, "contributed": contributed, "cash": cash, "value": value_now,
            "gain": value_now - contributed, "rec_value": last.get("R"), "index_value": last.get("M"),
            "holdings": holdings, "realised": realised[-100:], "flows": flow_view, "history": hist, "warnings": warnings,
            "distributions": dist_view[:80], "dist_total": sum(received.values()), "valuation": "market",
            "records": len(trades or [])}
