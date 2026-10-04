"""Real-money orders: what YOU need to trade so your actual holdings match Strategy B's current portfolio.
Uses your recorded trades (units you really hold, your real cash), not the $10k paper portfolio."""
from . import config as C
from .strategies import b_new_weights


def orders(ind, t, targets: list, tradable, holdings: list, cash: float, raw_last: dict) -> dict:
    """targets: the ETFs Strategy B holds now. holdings: your actual holdings from mine.compute.
    Returns {"items": [...], "total": your value, "skipped": [...]}."""
    held = {h["ticker"]: h["units"] for h in holdings if h["units"] > 1e-9}
    price = lambda k: raw_last.get(k)
    value = {k: u * price(k) for k, u in held.items() if price(k)}
    total = max(cash, 0.0) + sum(value.values())
    items, skipped = [], []
    avail = cash
    # 1. sell anything the strategy no longer holds (AAA is your cash parking, handled below)
    for k, u in held.items():
        if k == C.CASH or k in targets or not price(k):
            continue
        items.append({"side": "SELL", "ticker": k, "units": round(u, 4), "price": price(k), "value": value[k], "whole": True})
        avail += value[k] * (1 - C.COST)
    # 2. trim anything above 40% of your portfolio back to 30%
    for k in targets:
        if k in value and total > 0 and value[k] / total > C.B_TRIM_ABOVE:
            amt = value[k] - C.B_MAX_WEIGHT * total
            items.append({"side": "SELL", "ticker": k, "units": round(amt / price(k), 4), "price": price(k), "value": amt,
                          "whole": False, "trim": True})
            avail += amt * (1 - C.COST)
    # 3. buy strategy holdings you don't have, at their target share of YOUR portfolio
    w = b_new_weights(ind, t, targets, targets) if targets else {}
    want = {}
    for k in targets:
        if k in held or k == C.CASH:
            continue
        if not price(k) or (tradable is not None and k not in tradable):
            skipped.append({"ticker": k, "why": "no fresh price today"}); continue
        if not bool(ind["above_in"].at[t, k]):
            skipped.append({"ticker": k, "why": "now below the buy line (101% of its 200-day average)"}); continue
        want[k] = w[k] * total
    aaa_val = value.get(C.CASH, 0.0)
    need = sum(want.values())
    scale = min(1.0, (avail + aaa_val) / need) if need > 0 else 1.0
    need *= scale
    if need > avail + 1 and aaa_val > 0:
        amt = min(aaa_val, need - avail)
        items.append({"side": "SELL", "ticker": C.CASH, "units": round(amt / price(C.CASH), 4), "price": price(C.CASH),
                      "value": amt, "whole": amt >= aaa_val - 1, "cash": True})
        avail += amt
    for k, a in want.items():
        a *= scale
        if a >= 1:
            items.append({"side": "BUY", "ticker": k, "units": round(a / price(k), 4), "price": price(k), "value": a, "whole": False})
            avail -= a
    # 4. park leftover cash in AAA, as the strategy does (skip small amounts)
    if avail >= 100 and price(C.CASH):
        items.append({"side": "BUY", "ticker": C.CASH, "units": round(avail / price(C.CASH), 4), "price": price(C.CASH),
                      "value": avail, "whole": False, "cash": True})
    return {"items": items, "total": total, "skipped": skipped}
