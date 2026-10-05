"""Price charts for the dashboard: about a year of daily closes plus today's 20-minute snapshots,
for every ETF the dashboard can show (holdings, orders, top rankings)."""
import pandas as pd
from . import config as C


def build(tickers, close: pd.DataFrame, px: pd.DataFrame, sma: pd.DataFrame, prev: dict, raw_last: dict,
          info: dict, now, days: int = 260) -> dict:
    """Daily prices are the real (unadjusted) prices you see at the broker. The 200-day trend line is the one the
    strategy uses, converted to the same scale, so price-vs-line distances match the strategy's decisions exactly."""
    idx = close.index[-days:]
    out = {"dates": [d.date().isoformat() for d in idx], "series": {}, "intraday": {}, "updated": now.isoformat()}
    today = now.date().isoformat()
    old_intra = (prev or {}).get("intraday", {}) if (prev or {}).get("intraday_date") == today else {}
    for k in sorted(set(tickers)):
        if k not in close.columns:
            continue
        c = close[k].reindex(idx)
        ratio = (c / px[k].reindex(idx)) if k in px.columns else None
        trend = (sma[k].reindex(idx) * ratio) if (k in sma.columns and ratio is not None) else None
        out["series"][k] = {
            "close": [None if pd.isna(v) else round(float(v), 4) for v in c],
            "trend": [None if trend is None or pd.isna(v) else round(float(v), 4) for v in (trend if trend is not None else c)],
        }
        pts = list(old_intra.get(k, []))
        if info.get("market_open") and raw_last.get(k):
            stamp = now.strftime("%H:%M")
            if not pts or pts[-1][0] != stamp:
                pts.append([stamp, round(float(raw_last[k]), 4)])
        out["intraday"][k] = pts[-40:]
    out["intraday_date"] = today
    return out


def wanted(state: dict) -> list:
    """Which ETFs to chart: paper and real holdings, current orders, and the top of the rankings."""
    t = set()
    for side in ("B", "A"):
        t |= set(((state.get(side) or {}).get("pf") or {}).get("units", {}))
    B = state.get("B") or {}
    for o in [B.get("orders"), B.get("real_orders")]:
        for it in (o or {}).get("items", []):
            t.add(it["ticker"])
    for h in (state.get("mine") or {}).get("holdings", []):
        t.add(h["ticker"])
    for r in state.get("rankings", [])[:20]:
        t.add(r["ticker"])
    t.add(C.CASH)
    return sorted(t)
