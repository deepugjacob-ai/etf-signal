"""Price data from EODHD: daily history plus 15-20 minute delayed quotes for today."""
import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo
import pandas as pd
import requests
from . import config as C

BASE = "https://eodhd.com/api"


def code(sym: str) -> str:
    return sym if sym.endswith(".INDX") else f"{sym}.AU"


def _get(url, params, tries=3):
    last = None
    for _ in range(tries):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}: {r.text[:120]}"
        except requests.RequestException as e:
            last = type(e).__name__          # never include the URL: it contains the API key
    raise RuntimeError(f"EODHD request failed ({url.split('/api/')[-1]}): {last}") from None


def symbols():
    return C.UNIVERSE + [C.CASH, C.INDEX]


EXTRA = []        # extra tickers to price (your core holdings); never required for the strategy itself


def history(key: str, today: dt.date, days: int = C.HISTORY_DAYS):
    frm = (today - dt.timedelta(days=days)).isoformat()

    def one(sym):
        d = _get(f"{BASE}/eod/{code(sym)}", {"api_token": key, "fmt": "json", "from": frm})
        if not isinstance(d, list) or not d:
            raise RuntimeError(f"No history returned for {sym}")
        df = pd.DataFrame(d)
        df["date"] = pd.to_datetime(df["date"])
        return sym, df.set_index("date")

    def soft(sym):            # a core ticker that can't be fetched is skipped, not fatal
        try:
            return one(sym)
        except Exception:
            return sym, None

    with ThreadPoolExecutor(max_workers=6) as ex:
        res = dict(ex.map(one, symbols()))
        extra = [s for s in EXTRA if s not in res]
        res.update({s: df for s, df in ex.map(soft, extra) if df is not None})
    adj = pd.DataFrame({s: res[s]["adjusted_close"].astype(float) for s in res}).sort_index()
    close = pd.DataFrame({s: res[s]["close"].astype(float) for s in res}).sort_index()
    vol = pd.DataFrame({s: res[s]["volume"].astype(float) for s in res}).sort_index()
    return adj, close, close * vol


def quotes(key: str):
    syms = symbols() + [s for s in EXTRA if s not in symbols()]
    out = {}
    for i in range(0, len(syms), 20):
        chunk = syms[i:i + 20]
        d = _get(f"{BASE}/real-time/{code(chunk[0])}",
                 {"api_token": key, "fmt": "json", "s": ",".join(code(s) for s in chunk[1:])})
        d = d if isinstance(d, list) else [d]
        for q in d:
            out[q.get("code", "")] = q
    return out


def dividends_today(key: str, today: dt.date) -> dict:
    """Cash distributions going ex today, per unit, for our ETFs (one bulk call). {} if unavailable."""
    try:
        d = _get(f"{BASE}/eod-bulk-last-day/AU", {"api_token": key, "type": "dividends",
                                                   "date": today.isoformat(), "fmt": "json"}, tries=2)
    except RuntimeError:
        return {}
    out = {}
    for x in d if isinstance(d, list) else []:
        if x.get("date") == today.isoformat() and x.get("code") in C.UNIVERSE + [C.CASH]:
            try:
                out[x["code"]] = out.get(x["code"], 0.0) + float(x.get("unadjustedValue") or x.get("dividend"))
            except (TypeError, ValueError):
                pass
    return out


def load(key: str, now: dt.datetime):
    """Returns adjusted prices (with today's delayed price appended when the market traded today),
    $ turnover, raw last prices (for order sizes), and info about data freshness."""
    tz = ZoneInfo(C.TZ)
    today = now.date()
    adj, close, turnover = history(key, today)
    eod_last = adj.index[-1].date().isoformat()
    q = quotes(key)
    live_raw, fresh, rejected, newest = {}, 0, [], None
    for s in symbols() + [s for s in EXTRA if s not in symbols() and s in close.columns]:
        x = q.get(code(s), {})
        p, ts = x.get("close"), x.get("timestamp")
        if not isinstance(p, (int, float)) or not isinstance(ts, (int, float)) or p <= 0:
            continue
        qtime = dt.datetime.fromtimestamp(ts, tz)
        if qtime.date() != today:
            continue
        last_close = close[s].dropna().iloc[-1]
        if abs(p / last_close - 1) > 0.25:      # implausible jump: ignore, keep last close
            rejected.append(s)
            continue
        live_raw[s] = float(p)
        fresh += 1
        newest = max(newest, qtime) if newest else qtime
    market_open = fresh >= 0.5 * len(symbols())
    tday = pd.Timestamp(today)
    divs = dividends_today(key, today) if market_open else {}
    if market_open:
        # Today's row: use the official daily close where EODHD has already published it (just after 4pm some
        # ETFs have it and others don't), otherwise the delayed live price. The adjustment ratio always comes
        # from the last day BEFORE today.
        before_adj, before_close = adj.loc[adj.index < tday], close.loc[close.index < tday]
        ratio = before_adj.ffill().iloc[-1] / before_close.ffill().iloc[-1]
        if tday not in adj.index:
            adj.loc[tday] = float("nan"); close.loc[tday] = float("nan"); turnover.loc[tday] = float("nan")
            adj, close, turnover = adj.sort_index(), close.sort_index(), turnover.sort_index()
        for s_, p in live_raw.items():
            if pd.isna(adj.at[tday, s_]) or pd.isna(close.at[tday, s_]):
                # Ex-dividend fix: add back a distribution going ex today, so its price drop isn't read as a fall
                adj.at[tday, s_] = (p + divs.get(s_, 0.0)) * ratio[s_]
                close.at[tday, s_] = p
    raw_last = close.ffill().iloc[-1].to_dict()
    info = {"market_open": bool(market_open), "fresh_quotes": fresh, "rejected": rejected,
            "quote_time": newest.isoformat() if newest else None,
            "last_daily_close": eod_last, "ex_dividend_today": divs,
            "tradable": sorted(live_raw) if market_open else None}
    return adj, turnover, raw_last, info, close
