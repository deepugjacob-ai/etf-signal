"""Research only: download 5-minute ASX bars from EODHD (Active Trader plan) for the intraday backtest.
Writes one gzipped CSV per ticker to OUT_DIR (the private data repository, never this public one).
Does not touch the live engine or any of its files."""
import csv, datetime as dt, gzip, json, os, sys, time
import requests

KEY = os.environ["EODHD_API_KEY"]
OUT = sys.argv[1] if len(sys.argv) > 1 else "intraday"

# Liquid ASX ETFs (from the strategy universe) plus the most traded ASX shares
TICKERS = [
    "STW", "IOZ", "A200", "VAS", "IVV", "NDQ", "VGS", "OZR", "QRE", "GOLD", "HACK", "SEMI",
    "FUEL", "VHY", "ETHI", "IAA", "FANG", "QAU", "MVW", "AAA",
    "BHP", "CBA", "CSL", "NAB", "WBC", "ANZ", "FMG", "RIO", "WES", "MQG", "WDS", "TLS", "XRO", "PLS",
]
START = dt.datetime(2020, 10, 1, tzinfo=dt.timezone.utc)
STEP = dt.timedelta(days=540)         # under EODHD's 600-day limit per 5-minute request


def get(sym, a, b):
    url = f"https://eodhd.com/api/intraday/{sym}.AU"
    p = {"api_token": KEY, "interval": "5m", "fmt": "json", "from": int(a.timestamp()), "to": int(b.timestamp())}
    for i in range(3):
        try:
            r = requests.get(url, params=p, timeout=120)
            if r.status_code == 200:
                return r.json(), None
            err = f"HTTP {r.status_code}: {r.text[:200]}"
            if r.status_code in (401, 403):
                return None, err
        except requests.RequestException as e:
            err = type(e).__name__        # never print the URL: it contains the key
        time.sleep(2 + 3 * i)
    return None, err


def main():
    os.makedirs(OUT, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc)
    status = {"run": now.isoformat(), "tickers": {}}
    for sym in TICKERS:
        rows, errs, a = {}, [], START
        while a < now:
            b = min(a + STEP, now)
            d, err = get(sym, a, b)
            if err:
                errs.append(err)
                if err.startswith(("HTTP 401", "HTTP 403")):
                    break
            for x in d or []:
                if x.get("close") is not None:
                    rows[x["timestamp"]] = x
            a = b
        if rows:
            with gzip.open(os.path.join(OUT, f"{sym}.csv.gz"), "wt", newline="") as f:
                w = csv.writer(f)
                w.writerow(["ts", "open", "high", "low", "close", "volume"])
                for ts in sorted(rows):
                    x = rows[ts]
                    w.writerow([ts, x["open"], x["high"], x["low"], x["close"], x.get("volume") or 0])
        first = min(rows) if rows else None
        status["tickers"][sym] = {"bars": len(rows), "errors": errs[:2],
                                  "first": dt.datetime.fromtimestamp(first, dt.timezone.utc).isoformat() if first else None}
        print(sym, len(rows), "bars", errs[:1])
        if errs and errs[0].startswith(("HTTP 401", "HTTP 403")) and sym == TICKERS[0]:
            print("Intraday data not included in this EODHD plan; stopping.")
            break
    json.dump(status, open(os.path.join(OUT, "status.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
