"""Live engine. Runs every 20 minutes during ASX hours (GitHub Actions).
python -m engine.main [--force] [--test-push] [--local DIR] [--now 2026-10-09T15:05]"""
import argparse, datetime as dt, math, os, sys, traceback
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
from . import config as C
from . import portfolio as PF
from .data import load as load_data
from .indicators import clean_prices, compute
from .notify import ensure_keys, send_all
from .store import Store
from .strategies import b_new_weights, decide_a_entries, decide_a_exits, decide_b

VERSION = 1


def clean(o):
    """Make an object JSON-safe (numpy types, NaN)."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if math.isnan(float(o)) or math.isinf(float(o)) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def money(x):
    return f"${x:,.0f}"


def in_window(now):
    return now.weekday() < 5 and C.MARKET_OPEN <= (now.hour, now.minute) <= C.MARKET_CLOSE


def after_decision(now):
    return (now.hour, now.minute) >= C.DECISION_TIME


def make_orders(trades, raw_last, cash_leg):
    items = []
    for tr in trades:
        p = raw_last.get(tr["ticker"])
        items.append({"side": tr["side"], "ticker": tr["ticker"], "value": round(tr["value"], 2),
                      "price": p, "units": round(tr["value"] / p, 2) if p else None,
                      "whole": tr["side"] == "SELL"})
    if abs(cash_leg) >= 1:
        p = raw_last.get(C.CASH)
        items.append({"side": "BUY" if cash_leg > 0 else "SELL", "ticker": C.CASH, "value": round(abs(cash_leg), 2),
                      "price": p, "units": round(abs(cash_leg) / p, 2) if p else None, "whole": False, "cash": True})
    return items


def describe(items):
    parts = []
    for o in items:
        if o.get("cash"):
            parts.append(f"{'Put' if o['side']=='BUY' else 'Take'} {money(o['value'])} {'in' if o['side']=='BUY' else 'from'} {o['ticker']}")
        elif o["whole"]:
            parts.append(f"Sell all {o['ticker']} (~{money(o['value'])})")
        else:
            parts.append(f"Buy {money(o['value'])} of {o['ticker']}")
    return ". ".join(parts) + "."


def holdings_view(pf, prices, raw_last, ind, t, ranks):
    eq = PF.value(pf, prices)
    rows = []
    for k, u in pf["units"].items():
        v = u * prices[k]
        m = pf["meta"].get(k, {})
        rows.append({"ticker": k, "theme": C.THEME_OF.get(k, ""), "value": v, "weight": v / eq,
                     "units": v / raw_last[k] if raw_last.get(k) else None, "price": raw_last.get(k),
                     "since": m.get("date"), "cost": m.get("cost"),
                     "gain": (v - m["cost"]) if m.get("cost") else None,
                     "rank": ranks.get(k), "in_trend": bool(ind["above_hold"].at[t, k])})
    rows.sort(key=lambda r: -r["value"])
    return {"equity": eq, "cash": pf["cash_units"] * prices[C.CASH], "holdings": rows}


def add_alert(state, alerts, now, title, body, tag):
    a = {"id": f"{now.isoformat()}|{tag}", "time": now.isoformat(), "title": title, "body": body, "tag": tag}
    alerts.append(a)
    state["alerts"] = ([a] + state.get("alerts", []))[:40]


def run(state, now, key, alerts):
    today = now.date()
    adj, turnover, raw_last, info = load_data(key, now)
    px = clean_prices(adj)
    ind = compute(px, turnover)
    t = px.index[-1]
    tstr = t.date().isoformat()
    prices = px.ffill().loc[t].to_dict()
    open_today = info["market_open"]

    first = "B" not in state
    if first:
        state.update({
            "version": VERSION, "started": tstr, "alerts": [], "history": [],
            "B": {"pf": PF.new_portfolio(prices[C.CASH]), "last": None, "trades": [], "orders": None},
            "A": {"pf": PF.new_portfolio(prices[C.CASH]), "last": None, "trades": [], "orders": None, "pos": {}},
            "bench": {"units": {k: C.START_CAPITAL * w / prices[k] for k, w in C.BENCH_MIX.items()},
                      "month": tstr[:7]},
        })
        add_alert(state, alerts, now, "Paper trading started",
                  f"Both strategies start with {money(C.START_CAPITAL)} of paper money.", "start")

    # Market regime
    reg = ind["regime"].iloc[-1]
    prev = state.get("regime")
    if prev and prev != reg and open_today:
        add_alert(state, alerts, now, f"Market regime: {reg}", f"The ASX 200 trend changed from {prev} to {reg}. "
                  + ("Strategy B will hold at most 2 ETFs at the next weekly check." if reg == "bear" else ""), "regime")
    if prev != reg:
        state["regime_since"] = tstr
    state["regime"] = reg

    # Strategy B: weekly (Friday from 3pm), catch-up if a week was missed, and at start
    B = state["B"]
    held = list(B["pf"]["units"])
    keep, ranks, n_max = decide_b(ind, t, held)
    lastB = dt.date.fromisoformat(B["last"]) if B.get("last") else None
    due_B = first or (open_today and (
        (now.weekday() == 4 and after_decision(now) and lastB != today) or
        (lastB is not None and (today - lastB).days > 7)))
    if due_B:
        cash_before = B["pf"]["cash_units"] * prices[C.CASH]
        trades = []
        if set(keep) != set(held):
            new = [k for k in keep if k not in held]
            trades = PF.rebalance_b(B["pf"], keep, b_new_weights(ind, t, keep, new), prices)
            for tr in trades:
                if tr["side"] == "BUY":
                    B["pf"]["meta"][tr["ticker"]] = {"date": tstr, "cost": tr["value"]}
        cash_after = B["pf"]["cash_units"] * prices[C.CASH]
        cash_leg = cash_after if first else (cash_after - cash_before)
        items = make_orders(trades, raw_last, cash_leg if trades else 0)
        B["orders"] = {"date": tstr, "time": now.isoformat(), "items": items, "keep": keep, "regime": reg}
        B["trades"] = (B["trades"] + [{"date": tstr, **tr, "price": raw_last.get(tr["ticker"])} for tr in trades])[-200:]
        B["last"] = today.isoformat()
        if trades:
            add_alert(state, alerts, now, "Strategy B: new orders", describe(items), "B")
        else:
            add_alert(state, alerts, now, "Strategy B: no changes",
                      "Keep holding " + (", ".join(keep) if keep else f"everything in {C.CASH}") + ".", "B")

    # Strategy A (paper only): daily from 3pm
    A = state["A"]
    if open_today and after_decision(now) and A.get("last") != today.isoformat():
        pos = A["pos"]
        days = {k: len(px.loc[pd.Timestamp(d):t]) - 1 for k, d in pos.items()}
        trades = []
        for k in decide_a_exits(ind, t, days):
            trades.append({"side": "SELL", "ticker": k, "value": PF.sell_all(A["pf"], k, prices)})
            pos.pop(k)
        for k in decide_a_entries(ind, t, list(pos)):
            g = PF.buy_value(A["pf"], k, PF.value(A["pf"], prices) / C.A_MAX_POS, prices)
            if g > 0:
                pos[k] = tstr
                A["pf"]["meta"][k] = {"date": tstr, "cost": g}
                trades.append({"side": "BUY", "ticker": k, "value": g})
        A["last"] = today.isoformat()
        A["orders"] = {"date": tstr, "time": now.isoformat(), "items": make_orders(trades, raw_last, 0)}
        A["trades"] = (A["trades"] + [{"date": tstr, **tr, "price": raw_last.get(tr["ticker"])} for tr in trades])[-200:]
        if trades:
            add_alert(state, alerts, now, "Strategy A (paper): trades", describe(A["orders"]["items"]), "A")

    # Buy-and-hold comparison, rebalanced monthly
    bench = state["bench"]
    if open_today and bench["month"] != tstr[:7]:
        eqM = sum(u * prices[k] for k, u in bench["units"].items())
        bench["units"] = {k: eqM * w / prices[k] for k, w in C.BENCH_MIX.items()}
        bench["month"] = tstr[:7]
    eqM = sum(u * prices[k] for k, u in bench["units"].items())

    # Views for the dashboard
    vB = holdings_view(B["pf"], prices, raw_last, ind, t, ranks)
    vA = holdings_view(A["pf"], prices, raw_last, ind, t, ranks)
    B["view"], A["view"] = vB, vA
    state["bench"]["equity"] = eqM
    h = state["history"]
    point = {"d": tstr, "B": vB["equity"], "A": vA["equity"], "M": eqM}
    if h and h[-1]["d"] == tstr:
        h[-1] = point
    else:
        h.append(point)
    sc, P, sma = ind["score"].loc[t], ind["P"].loc[t], ind["sma"].loc[t]
    state["rankings"] = [{"rank": r, "ticker": k, "theme": C.THEME_OF[k], "score": sc[k],
                          "vs_trend": P[k] / sma[k] - 1, "in_trend": bool(ind["above_in"].at[t, k]),
                          "heldB": k in B["pf"]["units"]} for k, r in sorted(ranks.items(), key=lambda x: x[1])[:20]]
    state["n_max"] = n_max
    state["market"] = info
    state["prices_date"] = tstr


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="run even outside ASX hours")
    ap.add_argument("--test-push", action="store_true", help="send a test notification and stop")
    ap.add_argument("--local", help="use a local folder instead of the gist (testing)")
    ap.add_argument("--now", help="pretend the Sydney time is this (testing), e.g. 2026-10-09T15:05")
    a = ap.parse_args(argv)
    tz = ZoneInfo(C.TZ)
    now = dt.datetime.fromisoformat(a.now).replace(tzinfo=tz) if a.now else dt.datetime.now(tz)
    store = Store(os.environ.get("GIST_ID"), os.environ.get("GIST_TOKEN"), a.local)
    keys = ensure_keys(store)
    subs = store.read("subscriptions.json", []) or []
    state = store.read("state.json", {}) or {}
    claim = os.environ.get("VAPID_SUB") or "https://github.com"

    if a.test_push:
        sent, errs, _ = send_all(store, keys, subs, "Test alert", "Alerts are working on this device.", "test", claim)
        print(f"Test alert sent to {sent} of {len(subs)} device(s). Errors: {errs or 'none'}")
        state.setdefault("status", {})["last_test"] = {"time": now.isoformat(), "sent": sent, "devices": len(subs), "errors": errs}
        store.write({"state.json": clean(state)})
        return 0 if sent else 1

    if not a.force and not in_window(now):
        print(f"Outside ASX hours ({now:%a %H:%M} Sydney). Nothing to do.")
        return 0

    key = os.environ.get("EODHD_API_KEY")
    alerts, code = [], 0
    try:
        if not key:
            raise RuntimeError("EODHD_API_KEY is not set")
        run(state, now, key, alerts)
        state["status"] = {**state.get("status", {}), "ok": True, "checked": now.isoformat(), "message": "Up to date"}
    except Exception as e:
        st = state.get("status", {})
        msg = f"{type(e).__name__}: {e}"
        for secret in (key, os.environ.get("GIST_TOKEN")):
            if secret:
                msg = msg.replace(secret, "***")
        msg = msg[:300]
        print("Error:", msg)
        if os.environ.get("DEBUG"):
            traceback.print_exc()
        if st.get("error_day") != now.date().isoformat():
            add_alert(state, alerts, now, "Signal tool problem", f"The check at {now:%H:%M} failed: {msg}", "error")
        state["status"] = {**st, "ok": False, "checked": now.isoformat(), "message": msg, "error_day": now.date().isoformat()}
        code = 1
    push_errors = []
    for al in reversed(alerts):
        _, errs, subs = send_all(store, keys, subs, al["title"], al["body"], al["id"], claim)
        push_errors += errs
    state["status"]["push_errors"] = push_errors[-5:]
    state["status"]["devices"] = len(subs)
    state["public_key"] = keys["public"]
    store.write({"state.json": clean(state)})
    print(f"{now:%Y-%m-%d %H:%M} done. Alerts: {[x['title'] for x in alerts]}")
    return code


if __name__ == "__main__":
    sys.exit(main())
