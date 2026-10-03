# ETF Signals

A paper-trading test of two ETF strategies on the ASX, with alerts to your phone and laptop.

- **Strategy B (trend-following, weekly).** Ranks 57 ASX ETFs by 3, 6 and 12-month momentum, holds up to 5 that beat cash and sit above their 200-day average, with no more than 2 from one theme. Checked every Friday from 3pm. In a bear market it holds at most 2 and keeps the rest in AAA.
- **Strategy A (daily pullbacks, paper only).** Buys short dips in uptrending ETFs and sells on the bounce. The backtest showed about 0% a year after costs, so it is here only so you can see that for yourself.
- **Buy and hold.** 40% STW, 40% IVV, 20% VEU, rebalanced monthly, as the yardstick.

Each starts with $10,000 of paper money. Every trade pays a 0.15% allowance for the bid-ask spread.

## How it works

```
GitHub Actions (every 20 min, ASX hours)          Your private Gist             Dashboard (phone + laptop)
  engine/  ──── EODHD delayed prices ────►  state.json  ◄──── reads ─────  docs/index.html (GitHub Pages)
     │                                       subscriptions.json ◄── saves ── "Turn on alerts"
     └──────────── Web Push alerts ─────────────────────────────────────►  Home Screen app / browser
```

Nothing runs on your phone. The engine runs on GitHub's servers, saves results to your Gist, and sends alerts. The dashboard reads the same Gist, so phone and laptop always match.

## Setup (about 20 minutes, easiest on a laptop)

### 1. Create the Gist (your private data store)
1. Go to https://gist.github.com
2. Filename: `state.json`. Content: `{}`
3. Click the arrow next to the green button and choose **Create secret gist**.
4. Copy the long code at the end of the web address. That's your **Gist ID**.

### 2. Create a GitHub token
1. GitHub → your profile picture → **Settings** → **Developer settings** → **Personal access tokens** → **Tokens (classic)** → **Generate new token (classic)**.
2. Note: `ETF signals`. Expiration: pick one and put a reminder in your calendar to renew it. When it expires, the tool stops updating.
3. Tick **only** `gist`. Generate, then copy the token (starts with `ghp_`).

### 3. Create the repository and upload the files
1. New repository → name `etf-signal` → **Public** → Create. Public is needed for free GitHub Pages; the code contains no secrets.
2. Click **uploading an existing file**. Drag in everything from the unzipped folder **except** the `.github` folder: `engine`, `docs`, `requirements.txt`, `README.md`, `.gitignore`. Commit.
3. Click **Add file** → **Create new file**. Name it exactly `.github/workflows/engine.yml`, paste the contents of that file from the zip, and commit. (Doing this by hand avoids browsers skipping folders that start with a dot.)

### 4. Add the three secrets
Repository → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:

| Name | Value |
|---|---|
| `EODHD_API_KEY` | Your EODHD API token |
| `GIST_ID` | From step 1 |
| `GIST_TOKEN` | From step 2 |

### 5. Turn on the dashboard
Repository → **Settings** → **Pages** → Source: **Deploy from a branch** → Branch: `main`, folder `/docs` → Save. After a minute your dashboard is at `https://YOUR-USERNAME.github.io/etf-signal/`.

### 6. First run
Repository → **Actions** (enable workflows if asked) → **Signal engine** → **Run workflow** → mode **check now** → Run. It takes about a minute and should finish with a green tick. This starts the paper portfolios and makes Strategy B's first picks.

### 7. Connect the dashboard
Open the dashboard → **Settings** → enter the Gist ID and token → **Save and load**.

### 8. Alerts on your iPhone
1. Open the dashboard in **Safari** → **Share** → **Add to Home Screen**.
2. Open **Signals** from the new icon (not from Safari).
3. **Settings** → enter the Gist ID and token again (the Home Screen app has its own storage) → **Turn on alerts** → **Allow**.

On the laptop, open the dashboard in Chrome or Edge and tap **Turn on alerts** too.

### 9. Test the alerts
**Actions** → **Signal engine** → **Run workflow** → mode **test alert**. Each device should get "Test alert" within a minute.

## What you'll see

- **Every 20 minutes during ASX hours:** prices and paper values update. No alert.
- **Friday from 3pm:** Strategy B's weekly check. You get an alert with any buys and sells, or "no changes".
- **Weekdays from 3pm:** Strategy A checks for paper trades. Alert only if it trades.
- **When the market trend changes** (uptrend, sideways, downtrend): an alert.
- **If a check fails:** one alert per day explaining what went wrong. The dashboard shows the error too.

If a Friday is a public holiday, the weekly check runs at the first check of the next trading day.

## If something goes wrong

| What you see | What to do |
|---|---|
| Red banner "The last check failed" | Read the message. "401" from EODHD means the API key is wrong or the subscription lapsed. "Could not read the gist" means `GIST_ID` or `GIST_TOKEN` is wrong or the token expired. |
| "Updates are running late" | GitHub sometimes delays scheduled runs. If it lasts hours, check the Actions tab for failed runs. |
| No alerts on iPhone | Make sure you opened Signals from the Home Screen icon, alerts show as on in Settings, and notifications for Signals are allowed in iPhone Settings → Notifications. Then run **test alert**. |
| Actions say the schedule was disabled | GitHub pauses schedules after 60 days without activity. The workflow commits a tiny `.keepalive` file monthly to prevent this; if it happens anyway, re-enable it in the Actions tab. |

## Changing settings

All strategy settings are in `engine/config.py` (number of holdings, theme cap, trading cost, decision time). If you change them, rerun the backtest first:

```
pip install -r requirements.txt
EODHD_API_KEY=your_key python -m engine.backtest
```

The live engine and the backtest share the same decision code, so the backtest tests exactly what runs live.

## Backtest results (2 Jan 2013 to 2 Oct 2026)

| | Per year | Worst fall | $10k became |
|---|---|---|---|
| Strategy B | 10.6% | −18.6% | $40,395 |
| Strategy A | −0.1% | −19.2% | $9,837 |
| Buy and hold 40/40/20 | 13.8% | −27.8% | $59,585 |

These include a 0.15% cost per trade and only ETFs that still exist today, which flatters results slightly. Expect live results to be worse than a backtest.

## Known limitations

- Prices are delayed 15–20 minutes, and GitHub can run checks a few minutes late.
- On an ETF's ex-dividend day, its live price drops by the distribution before EODHD adjusts the history overnight. That can show a small false loss for that afternoon.
- The engine stores the alert signing key in your Gist (`keys.json`). Anyone with your Gist ID could see it, but it only lets them send notifications to your devices. Keep the Gist secret.

This is a personal research tool, not financial advice.
