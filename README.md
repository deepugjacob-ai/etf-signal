# ETF Signals

A paper-trading test of two ETF strategies on the ASX, with alerts to your phone and laptop.

- **Strategy B (trend-following, weekly).** Ranks ASX ETFs that beat cash and sit above their 200-day average by 3, 6 and 12-month momentum, and holds up to 5, with no more than 2 from one theme and none trading under $1M a day. Any holding above 40% is trimmed back to 30%. Checked every Friday from 3pm. In a bear market it holds at most 2 and keeps the rest in AAA.
- **Strategy A (daily pullbacks, paper only, no alerts).** Buys short dips in uptrending ETFs and sells on the bounce. The backtest showed about 0–1% a year after costs, so it runs silently as a comparison.
- **Buy and hold.** 40% STW, 40% IVV, 20% VEU, rebalanced monthly, as the yardstick.

Each starts with $10,000 of paper money. Every trade pays a 0.15% allowance for the bid-ask spread. To see orders and results for a different amount, set **Investment amount** in the dashboard's Settings. The paper portfolios still run on $10,000, and every dollar figure in the dashboard and alerts is scaled to your amount, so percentages are the same.

## How it works

```
GitHub Actions (every 20 min, ASX hours)     Your private data repository      Dashboard (phone + laptop)
  engine/  ──── EODHD delayed prices ────►  state.json  ◄──── reads ─────  docs/index.html (GitHub Pages)
     │                                       subscriptions.json ◄── saves ── "Turn on alerts"
     └──────────── Web Push alerts ─────────────────────────────────────►  Home Screen app / browser
```

Nothing runs on your phone. The engine runs on GitHub's servers, saves results to a private GitHub repository that only you can see, and sends alerts. The dashboard reads the same repository, so phone and laptop always match. (Older setups used a secret Gist; see "Moving from the Gist" below.)

## Setup (about 20 minutes, easiest on a laptop)

### 1. Create the private data repository
1. GitHub → **+** → **New repository** → name `etf-data` → **Private** → tick **Add a README file** → Create.
2. Nothing else to do: the engine fills it in.

### 2. Create a data token
1. GitHub → your profile picture → **Settings** → **Developer settings** → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
2. Name: `ETF data`. Expiration: pick one and put a reminder in your calendar to renew it. When it expires, the tool stops updating.
3. Repository access: **Only select repositories** → `etf-data`.
4. Permissions → Repository permissions → **Contents: Read and write**. Generate, then copy the token (starts with `github_pat_`).

This token can only touch your data repository: not your code, not your other repositories or Gists.

### 3. Create the repository and upload the files
1. New repository → name `etf-signal` → **Public** → Create. Public is needed for free GitHub Pages; the code contains no secrets.
2. Click **uploading an existing file**. Drag in everything from the unzipped folder **except** the `.github` folder: `engine`, `docs`, `requirements.txt`, `README.md`, `.gitignore`. Commit.
3. Click **Add file** → **Create new file**. Name it exactly `.github/workflows/engine.yml`, paste the contents of that file from the zip, and commit. (Doing this by hand avoids browsers skipping folders that start with a dot.)

### 4. Add the three secrets
Repository `etf-signal` → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:

| Name | Value |
|---|---|
| `EODHD_API_KEY` | Your EODHD API token |
| `DATA_REPO` | `YOUR-USERNAME/etf-data` |
| `DATA_TOKEN` | The data token from step 2 |

### 5. Turn on the dashboard
Repository → **Settings** → **Pages** → Source: **Deploy from a branch** → Branch: `main`, folder `/docs` → Save. After a minute your dashboard is at `https://YOUR-USERNAME.github.io/etf-signal/`.

### 6. First run
Repository → **Actions** (enable workflows if asked) → **Signal engine** → **Run workflow** → mode **check now** → Run. It takes about a minute and should finish with a green tick. This starts the paper portfolios and makes Strategy B's first picks.

### 7. Connect the dashboard
Open the dashboard → **Settings** → **Connect your data** → enter `YOUR-USERNAME/etf-data` and the data token → **Save and load**.

### 8. Alerts on your iPhone
1. Open the dashboard in **Safari** → **Share** → **Add to Home Screen**.
2. Open **Signals** from the new icon (not from Safari).
3. **Settings** → enter the data repository and token again (the Home Screen app has its own storage) → **Turn on alerts** → **Allow**.

On the laptop, open the dashboard in Chrome or Edge and tap **Turn on alerts** too.

### 9. Test the alerts
**Actions** → **Signal engine** → **Run workflow** → mode **test alert**. Each device should get "Test alert" within a minute.

## What you'll see

- **Every 20 minutes during ASX hours:** prices and paper values update. No alert.
- **Friday from 3pm:** Strategy B's weekly check. You get an alert with any buys and sells, or "no changes".
- **Weekdays from 3pm:** Strategy A makes its paper trades. No alerts.
- **When the market trend changes** (uptrend, sideways, downtrend): an alert.
- **Mid-week, if something you hold drops below its sell line** (98% of its 200-day average): a heads-up, at most once a week per ETF. It's information only: the rules still sell at the Friday check, and only if it's still below then. In real-money mode this watches your actual holdings; in paper mode, the paper portfolio.
- **If a check fails:** one alert per day explaining what went wrong. The dashboard shows the error too.

If a Friday is a public holiday, the weekly check runs at the first check of the next trading day.

## If something goes wrong

| What you see | What to do |
|---|---|
| Red banner "The last check failed" | Read the message. "401" from EODHD means the API key is wrong or the subscription lapsed. "GitHub refused access to the data repository" means `DATA_TOKEN` is wrong or expired; "not found" means `DATA_REPO` is wrong or the token wasn't given that repository. |
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

In **Orders**, tap **I did this** after you trade in Betashares and enter your actual units and price, or **Skipped** if you didn't follow an order. Trades that weren't in an order go in **Record another trade**. They are saved to `mytrades.json` in your data repository.

Your holdings are valued at the real market price (what Betashares shows) times your units, plus your cash, which includes the distributions you've received. The **Overview** compares that with what the same money would be worth had it followed Strategy B exactly. **Holdings** shows each parcel's tax status: short-term until it has been held at least 12 months, not counting the day bought or the day sold.

## Distributions

The engine looks up every distribution published for the ETFs you've traded and estimates what you received: the amount per unit times the units you held the day before the ex-date. It's counted as cash on the ex-date. In **Holdings** → **Distributions**, tap **Record** to enter what actually arrived, or the units you got if you're on a reinvestment plan (those become a new parcel at the reinvestment price). Use **Record another distribution** for anything the engine missed. If the money goes to your bank account rather than staying with Betashares, also log it with **Take money out** so your cash for orders stays right.

## Which parcels a sale uses (capital gains tax)

When you sell part of a holding, the tool counts the parcels that create the least tax as sold first: parcels held over 12 months (50% discount) and parcels bought at a higher price go first. Australia lets you choose parcels this way as long as your records identify them, and your trade record does. In real-money mode each sale order shows the estimated gain and how much of it is short-term (taxed in full). Selling everything uses every parcel, so there's no choice to make. This is an estimate; confirm with your accountant or tax software, and note it doesn't include cost-base adjustments from AMIT statements.

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

The historical odds under each chart use momentum and trend-line distance measured on distribution-adjusted prices, exactly as the strategy and the odds table measure them. The 95% ranges allow for the fact that weekly samples overlap in time.

## Moving from the Gist

If your setup started with a Gist, move to the private repository once:

1. Do steps 1 and 2 above (create `etf-data`, private, with a README; create the data token).
2. In `etf-signal` → Settings → Secrets → Actions, add `DATA_REPO` and `DATA_TOKEN`. Keep `GIST_ID` and `GIST_TOKEN` for now.
3. Replace `.github/workflows/engine.yml` with the new version (it passes the two new secrets to the engine).
4. Actions → Signal engine → Run workflow → **check now**. On this run the engine copies every file from the Gist into `etf-data` (your trades, settings, core holdings, alert devices and signing key), then leaves a note in the Gist. The Gist itself is kept as a backup.
5. On each device: dashboard → Settings → **Connect your data** → enter `YOUR-USERNAME/etf-data` and the data token → **Save and load**. Until you do, that device shows "Your data has moved" and won't save anything to the old Gist.
6. Alerts keep working; no need to turn them on again. After a week of normal running you can delete the `GIST_ID` and `GIST_TOKEN` secrets and the old classic token.

## Known limitations

- Prices are delayed 15–20 minutes, and GitHub can run checks a few minutes late.
- Ex-dividend days are handled: the engine adds back any distribution going ex that day (from EODHD's dividend calendar). If that calendar can't be reached, the old behaviour applies for that day.
- The engine stores the alert signing key in your private data repository (`keys.json`). It only lets someone send notifications to your devices.
- The data repository gets one small commit per check. That's a few hundred megabytes a year at most, well within GitHub's limits.

This is a personal research tool, not financial advice.
