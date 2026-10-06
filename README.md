# ETF Signals

A paper-trading test of two ETF strategies on the ASX, with alerts to your phone and laptop.

- **Strategy B (trend-following, weekly).** Ranks ASX ETFs that beat cash and sit above their 200-day average by 3, 6 and 12-month momentum, and holds up to 5, with no more than 2 from one theme and none trading under $1M a day. Any holding above 40% is trimmed back to 30%. Checked every Friday from 3pm. In a bear market it holds at most 2 and keeps the rest in AAA.
- **Strategy A (daily pullbacks, paper only, no alerts).** Buys short dips in uptrending ETFs and sells on the bounce. The backtest showed about 0–1% a year after costs, so it runs silently as a comparison.
- **Buy and hold.** 40% STW, 40% IVV, 20% VEU, rebalanced monthly, as the yardstick.

Each starts with $10,000 of paper money. Every trade pays a 0.15% allowance for the bid-ask spread. To see orders and results for a different amount, set **Investment amount** in the dashboard's Settings. The paper portfolios still run on $10,000, and every dollar figure in the dashboard and alerts is scaled to your amount, so percentages are the same.

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
- **Weekdays from 3pm:** Strategy A makes its paper trades. No alerts.
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

## Backtest results (rules version 2, 2 Jan 2013 to 2 Oct 2026)

Trades are filled at the next day's close after each decision, with a 0.15% cost on every trade.

| | Per year | Volatility | Sharpe | Worst fall | $10k became |
|---|---|---|---|---|---|
| Strategy B | 11.1% | 11.2% | 0.77 | −17.8% | $42,966 |
| Strategy A (paper) | 0.9% | 6.4% | −0.23 | −16.4% | $11,358 |
| Buy and hold 40/40/20 | 13.8% | 12.0% | 0.92 | −27.8% | $59,371 |

Strategy B holds an ETF for about 156 days on average, and 88% of its sales happen within 12 months, so most gains would be taxed without the 50% discount. These results use only ETFs that still exist today, which flatters them.

**Rules are frozen at version 2** (4 October 2026, after independent review). Don't tune them on this history again; the paper test from October 2026 onwards is the real out-of-sample check.

## Recording your own trades

In **Orders**, tap **I did this** after you trade in Betashares and enter your actual units and price, or **Skipped** if you didn't follow an order. Trades that weren't in an order go in **Record another trade**. They are saved to `mytrades.json` in your Gist.

The engine values your trades the same way as the paper portfolio (dividends included), and the **Overview** compares them: your value against what the same money would be worth had it followed Strategy B exactly. **Holdings** shows each parcel's tax status: short-term until it has been held 12 months.

## Adding money over time

On the Overview, under **Your holdings**, tap **Add money** whenever you move money into Betashares for this strategy (or **Take money out**), with the date. Your gain is then measured against what you've actually put in, and the two yardsticks ("every recommendation" and the index mix) get the same deposits on the same days, so the comparison stays fair however often you add money. The first time you add money, your original starting amount is kept as the first deposit.

## Real-money mode

In **Settings** → **Trading mode**, choose **Real money**. Set **Investment amount** to the cash you've put aside for this strategy.

- The engine then gives you **your own orders**: what to buy and sell so your recorded holdings match Strategy B, sized from your real cash and units. It does this at every Friday check, on the first check after you switch, and whenever you tap **Recalculate my orders**.
- Your Friday alert becomes those orders. The $10,000 paper portfolio keeps running as the yardstick.
- Record every trade with **I did this** (actual units and price), or the next orders will be wrong. If you add money, raise the investment amount and recalculate.
- Leftover cash of $100 or more is parked in AAA, as the strategy does. Purchases you can't fully fund are scaled down together.

## Reliable updates (recommended)

GitHub's built-in timer often delays or skips runs, sometimes running only a couple of times a day. Two fixes, both using one fine-grained token:

**Create the token.** GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token. Repository access: **Only select repositories** → `etf-signal`. Permissions → Repository permissions → **Actions: Read and write**. Generate and copy it.

**1. An outside timer (cron-job.org, free).** Create a cron job with:
- URL: `https://api.github.com/repos/YOUR-USERNAME/etf-signal/actions/workflows/engine.yml/dispatches`
- Schedule: every 20 minutes, 10:00 to 16:20, Monday to Friday, time zone Australia/Sydney
- Method **POST**, headers `Authorization: Bearer YOUR-TOKEN`, `Accept: application/vnd.github+json`, `Content-Type: application/json`
- Body: `{"ref":"main","inputs":{"mode":"scheduled"}}`

A test run should return status 204. GitHub's own timer stays on as a backup; overlapping runs are harmless.

**2. Update now in the dashboard.** In Settings → **Live updates**, paste the same token and `YOUR-USERNAME/etf-signal`. During ASX hours, Refresh then asks for fresh prices and waits about a minute for them.

## ETF price charts

Tap any underlined ETF name (in Orders, Holdings or Rankings) to see its price over 1, 3, 6 or 12 months, with the 200-day trend line, the buy line (+1%) and sell line (−2%), your average cost if you hold it, and today's 20-minute snapshots.

## Known limitations

- Prices are delayed 15–20 minutes, and GitHub can run checks a few minutes late.
- Ex-dividend days are handled: the engine adds back any distribution going ex that day (from EODHD's dividend calendar). If that calendar can't be reached, the old behaviour applies for that day.
- The engine stores the alert signing key in your Gist (`keys.json`). Anyone with your Gist ID could see it, but it only lets them send notifications to your devices. Keep the Gist secret.

This is a personal research tool, not financial advice.
