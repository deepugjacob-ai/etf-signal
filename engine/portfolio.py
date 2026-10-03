"""Paper portfolio held in units. Valued with dividend-adjusted prices so income is counted.
Uninvested money sits in the cash ETF (AAA)."""
from . import config as C


def new_portfolio(cash_price: float) -> dict:
    return {"units": {}, "cash_units": C.START_CAPITAL / cash_price, "meta": {}}


def value(pf: dict, prices: dict) -> float:
    v = pf["cash_units"] * prices[C.CASH]
    for k, u in pf["units"].items():
        v += u * prices[k]
    return v


def sell_all(pf: dict, k: str, prices: dict) -> float:
    """Sell the whole position. Returns gross trade value."""
    u = pf["units"].pop(k, 0.0)
    gross = u * prices[k]
    pf["cash_units"] += gross * (1 - C.COST) / prices[C.CASH]
    pf["meta"].pop(k, None)
    return gross


def buy_value(pf: dict, k: str, amount: float, prices: dict) -> float:
    """Spend `amount` dollars from cash on k (capped at cash available). Returns gross trade value."""
    avail = pf["cash_units"] * prices[C.CASH]
    amount = max(0.0, min(amount, avail))
    if amount <= 0:
        return 0.0
    pf["cash_units"] -= amount / prices[C.CASH]
    pf["units"][k] = pf["units"].get(k, 0.0) + amount * (1 - C.COST) / prices[k]
    return amount


def needs_trim(pf: dict, prices: dict) -> bool:
    return any(w > C.B_TRIM_ABOVE for w in weights(pf, prices).values())


def rebalance_b(pf: dict, keep: list, new_weights: dict, prices: dict) -> list:
    """Sell what left the list, trim any holding above 40% back to 30%, then buy the newcomers at their target
    weight. Other existing holdings are left alone. If cash is short, newcomers are scaled down together so the
    portfolio never exceeds 100% invested."""
    trades = []
    for k in [k for k in pf["units"] if k not in keep]:
        g = sell_all(pf, k, prices)
        trades.append({"side": "SELL", "ticker": k, "value": g, "whole": True})
    eq = value(pf, prices)
    for k in list(pf["units"]):
        w = pf["units"][k] * prices[k] / eq
        if w > C.B_TRIM_ABOVE:
            cut = (w - C.B_MAX_WEIGHT) * eq
            frac = cut / (pf["units"][k] * prices[k])
            pf["units"][k] -= cut / prices[k]
            pf["cash_units"] += cut * (1 - C.COST) / prices[C.CASH]
            if pf["meta"].get(k, {}).get("cost"):
                pf["meta"][k]["cost"] *= (1 - frac)
            trades.append({"side": "SELL", "ticker": k, "value": cut, "whole": False, "trim": True})
    eq = value(pf, prices)
    want = {k: w * eq for k, w in new_weights.items()}
    avail = pf["cash_units"] * prices[C.CASH]
    scale = min(1.0, avail / sum(want.values())) if want and sum(want.values()) > 0 else 1.0
    for k, amt in want.items():
        g = buy_value(pf, k, amt * scale, prices)
        if g > 0:
            trades.append({"side": "BUY", "ticker": k, "value": g})
    return trades


def weights(pf: dict, prices: dict) -> dict:
    eq = value(pf, prices)
    return {k: u * prices[k] / eq for k, u in pf["units"].items()}
