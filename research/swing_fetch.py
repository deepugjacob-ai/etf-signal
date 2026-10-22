"""Research only: download daily ASX prices (2010 onwards) for the 1-5 day swing backtest.
Writes one gzipped CSV per ticker to OUT_DIR. Does not touch the live engine or its files."""
import csv, gzip, json, os, sys, time
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from engine import config as C          # noqa: E402  (the live strategy's ETF list, read only)

KEY = os.environ["EODHD_API_KEY"]
OUT = sys.argv[1] if len(sys.argv) > 1 else "daily"
SHARES = ["BHP", "CBA", "CSL", "NAB", "WBC", "ANZ", "FMG", "RIO", "WES", "MQG", "WDS", "TLS", "XRO", "PLS"]
TICKERS = sorted(set(C.UNIVERSE + [C.CASH])) + SHARES


def get(sym):
    for i in range(3):
        try:
            r = requests.get(f"https://eodhd.com/api/eod/{sym}.AU",
                             params={"api_token": KEY, "fmt": "json", "from": "2010-01-01"}, timeout=120)
            if r.status_code == 200:
                return r.json(), None
            err = f"HTTP {r.status_code}: {r.text[:200]}"
        except requests.RequestException as e:
            err = type(e).__name__              # never print the URL: it contains the key
        time.sleep(2 + 3 * i)
    return None, err


def main():
    os.makedirs(OUT, exist_ok=True)
    status = {}
    for sym in TICKERS:
        d, err = get(sym)
        rows = [x for x in (d or []) if x.get("close")]
        if rows:
            with gzip.open(os.path.join(OUT, f"{sym}.csv.gz"), "wt", newline="") as f:
                w = csv.writer(f)
                w.writerow(["date", "open", "high", "low", "close", "adjusted_close", "volume"])
                for x in rows:
                    w.writerow([x["date"], x["open"], x["high"], x["low"], x["close"], x["adjusted_close"], x.get("volume") or 0])
        status[sym] = {"days": len(rows), "first": rows[0]["date"] if rows else None, "error": err}
        print(sym, len(rows), err or "")
    json.dump(status, open(os.path.join(OUT, "status.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
