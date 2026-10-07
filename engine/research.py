"""Shared helpers for the offline research scripts (sensitivity grid, odds table). Not used by the live engine.

Downloads full daily history from EODHD once and caches it as one JSON file per symbol, so re-running a script
doesn't spend API calls. Delete the cache folder to refresh."""
import json, os, datetime as dt
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
from .data import BASE, _get, code

START = "2010-01-01"


def fetch(key: str, symbols, cache: str, start: str = START, soft: bool = False) -> dict:
    """{symbol: DataFrame[adjusted_close, close, volume]}. soft=True skips symbols that fail (delisted lists)."""
    os.makedirs(cache, exist_ok=True)

    def one(sym):
        p = os.path.join(cache, sym.replace("/", "_") + ".json")
        if os.path.exists(p):
            rows = json.load(open(p))
        else:
            try:
                rows = _get(f"{BASE}/eod/{code(sym)}", {"api_token": key, "fmt": "json", "from": start})
            except RuntimeError:
                if not soft:
                    raise
                rows = []
            json.dump(rows if isinstance(rows, list) else [], open(p, "w"))
        if not rows:
            return sym, None
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        return sym, df[["adjusted_close", "close", "volume"]].astype(float)

    with ThreadPoolExecutor(max_workers=6) as ex:
        out = dict(ex.map(one, list(dict.fromkeys(symbols))))
    return {k: v for k, v in out.items() if v is not None and len(v)}


def frames(data: dict):
    """adjusted prices, raw closes and $ turnover as wide DataFrames."""
    adj = pd.DataFrame({s: d["adjusted_close"] for s, d in data.items()}).sort_index()
    close = pd.DataFrame({s: d["close"] for s, d in data.items()}).sort_index()
    vol = pd.DataFrame({s: d["volume"] for s, d in data.items()}).sort_index()
    return adj, close, close * vol


def exchange_etfs(key: str, cache: str) -> list:
    """Every ASX ETF EODHD knows about, listed now or delisted since: [{"code", "name", "delisted"}]."""
    os.makedirs(cache, exist_ok=True)
    out = []
    for delisted in (0, 1):
        p = os.path.join(cache, f"_symbols_{delisted}.json")
        if os.path.exists(p):
            rows = json.load(open(p))
        else:
            rows = _get(f"{BASE}/exchange-symbol-list/AU", {"api_token": key, "fmt": "json", "delisted": delisted})
            json.dump(rows, open(p, "w"))
        out += [{"code": r["Code"], "name": r.get("Name") or "", "delisted": bool(delisted)}
                for r in rows if r.get("Type") == "ETF"]
    return out


def dividends(key: str, sym: str, cache: str) -> pd.Series:
    """Cash distributions per unit (as paid at the time) by ex-date, cached."""
    p = os.path.join(cache, f"_div_{sym}.json")
    if os.path.exists(p):
        rows = json.load(open(p))
    else:
        try:
            rows = _get(f"{BASE}/div/{code(sym)}", {"api_token": key, "fmt": "json", "from": START})
        except RuntimeError:
            rows = []
        json.dump(rows if isinstance(rows, list) else [], open(p, "w"))
    vals = {}
    for r in rows or []:
        try:
            v = float(r.get("unadjustedValue") if r.get("unadjustedValue") is not None else r.get("value"))
        except (TypeError, ValueError):
            continue
        if v > 0 and r.get("date"):
            d = pd.Timestamp(r["date"])
            vals[d] = vals.get(d, 0.0) + v
    return pd.Series(vals, dtype=float).sort_index()


def fix_adjustments(adj: pd.DataFrame, close: pd.DataFrame, key: str = "", cache: str = None, report=print) -> pd.DataFrame:
    """Repair provider errors in the adjusted (distributions-included) prices.

    Symptom: the adjusted price jumps more than 4% on a day the real price didn't fall. A real distribution makes the
    real price drop while the adjusted price stays flat, so a jump like this is a mistake. Two causes were found:
    a distribution applied with the wrong factor (IVV's three ex-dates in 2013: +94% that year instead of about +54%),
    and a distribution applied a day early (several funds on 30 June 2026). For each affected ETF, the whole series is
    rebuilt as a total return from the real prices plus EODHD's per-unit distribution records:
    (price today + distribution going ex today) / price yesterday. Unit splits keep the adjusted return."""
    ra = adj.pct_change(fill_method=None)
    rc = close.reindex_like(adj).pct_change(fill_method=None)
    gap = ra - rc
    bad = (gap > 0.04) & (rc > -0.02) & (rc.abs() < 0.3)
    if not bad.any().any():
        return adj
    out = adj.copy()
    for k in adj.columns[bad.any()]:
        days = list(bad.index[bad[k]])
        c = close[k].reindex(adj.index)
        s = adj[k].dropna()
        div = dividends(key, k, cache) if cache else pd.Series(dtype=float)
        d = div.reindex(c.index).fillna(0.0)
        # A distribution makes the real price drop by about that much. A recorded one over 4% of the price with no
        # matching drop within a few days is a bad record (IVV 2013 shows $13-15 per unit instead of about $0.65):
        # use the median of that ETF's other distributions within a year instead.
        prev = c.ffill().shift(1)
        drop = rc[k].rolling(5, min_periods=1).min().shift(-3).reindex(c.index)      # worst day from e-1 to e+3
        for e in d.index[d > 0]:
            y = d[e] / prev[e] if prev[e] else 0
            if y > 0.04 and -(drop[e] if pd.notna(drop[e]) else 0) < y / 2:
                near = div[(abs((div.index - e).days) <= 400) & (div.index != e)]
                ok = near[near / float(prev[e]) < 0.04]
                report(f"  ignored a {k} distribution of ${d[e]:.2f} on {e.date()} with no matching price drop"
                       + (f"; used ${ok.median():.2f}" if len(ok) else ""))
                d[e] = float(ok.median()) if len(ok) else 0.0
        tr = (c + d) / c.shift(1) - 1
        split = (rc[k].abs() >= 0.3) & (ra[k].abs() < 0.3)          # unit split or consolidation: use the adjusted return
        r = tr.where(~split, ra[k]).loc[s.index]
        r = r.replace([np.inf, -np.inf], np.nan).fillna(0)
        rebuilt = (1 + r).cumprod()
        out.loc[s.index, k] = rebuilt * (s.iloc[-1] / rebuilt.iloc[-1])     # keep today's level unchanged
        report(f"Rebuilt {k} from real prices and {int((d > 0).sum())} distributions (bad jumps on "
               f"{', '.join(str(x.date()) for x in days)})")
    return out
