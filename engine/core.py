"""Long-term core holdings: your investments outside the strategy (e.g. DHHF, NDQ, VHY, INCM and a Betashares
managed portfolio). Kept completely separate from the strategy tracking and comparisons.

core.json = {"lots": [{"id", "group", "ticker", "units", "cost", "date", "note", "estimated"}]}
A lot is a parcel: units bought on a date for a total cost (cost may be missing if unknown)."""
import pandas as pd


def tickers(core: dict) -> list:
    return sorted({l["ticker"] for l in (core or {}).get("lots", []) if l.get("ticker")})


def compute(core: dict, close: pd.DataFrame, today) -> dict:
    lots = [l for l in (core or {}).get("lots", []) if l.get("ticker") and (l.get("units") or 0) > 0]
    if not lots:
        return {"has_core": False}
    today_s = today.isoformat()
    groups, missing = {}, []
    for l in lots:
        k = l["ticker"]
        s = close[k].dropna() if k in close.columns else pd.Series(dtype=float)
        if s.empty:
            missing.append(k)
            continue
        now = float(s.iloc[-1])
        last_d = s.index[-1].date().isoformat()
        prev = float(s.iloc[-2]) if len(s) > 1 else None
        u = float(l["units"])
        value = u * now
        cost = float(l["cost"]) if l.get("cost") not in (None, "") else None
        # change on the latest trading day: from the previous close, or from your price if bought that day
        base = (cost / u) if (l.get("date") == last_d and cost) else prev
        day = u * (now - base) if base else None
        g = groups.setdefault(l.get("group") or "Core", {"name": l.get("group") or "Core", "positions": {}, "value": 0.0,
                                                         "cost": 0.0, "cost_known": True, "day": 0.0})
        p = g["positions"].setdefault(k, {"ticker": k, "units": 0.0, "value": 0.0, "cost": 0.0, "cost_known": True,
                                          "day": 0.0, "price": now, "first": l.get("date"), "estimated": False, "lots": 0})
        p["units"] += u; p["value"] += value; p["day"] += day or 0.0; p["lots"] += 1
        p["estimated"] = p["estimated"] or bool(l.get("estimated"))
        if l.get("date") and (not p["first"] or l["date"] < p["first"]):
            p["first"] = l["date"]
        if cost is None:
            p["cost_known"] = False; g["cost_known"] = False
        else:
            p["cost"] += cost; g["cost"] += cost
        g["value"] += value; g["day"] += day or 0.0
    out_groups = []
    for g in groups.values():
        pos = sorted(g["positions"].values(), key=lambda p: -p["value"])
        for p in pos:
            p["gain"] = p["value"] - p["cost"] if p["cost_known"] else None
        out_groups.append({**g, "positions": pos, "gain": g["value"] - g["cost"] if g["cost_known"] else None})
    out_groups.sort(key=lambda g: -g["value"])
    total = sum(g["value"] for g in out_groups)
    cost_known = all(g["cost_known"] for g in out_groups)
    cost = sum(g["cost"] for g in out_groups)
    # daily history of value and cost since the earliest lot
    start = min(pd.Timestamp(l["date"]) for l in lots if l.get("date")) if any(l.get("date") for l in lots) else close.index[-1]
    hist = []
    for t in close.loc[start:].index:
        v = c = 0.0
        for l in lots:
            k = l["ticker"]
            if k in missing or (l.get("date") and pd.Timestamp(l["date"]) > t):
                continue
            px = close.at[t, k]
            if pd.notna(px):
                v += float(l["units"]) * float(px)
            c += float(l.get("cost") or 0)
        hist.append({"d": t.date().isoformat(), "V": v, "C": c})
    return {"has_core": True, "value": total, "cost": cost if cost_known else None,
            "gain": (total - cost) if cost_known else None, "day": sum(g["day"] for g in out_groups),
            "groups": out_groups, "missing": sorted(set(missing)), "history": hist[-400:], "as_of": today_s}
