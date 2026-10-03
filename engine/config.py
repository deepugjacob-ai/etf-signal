"""All strategy settings in one place.
RULES VERSION 2 (frozen 4 Oct 2026 after independent review). Do not tune these on the 2013-2026 history again;
the paper test from October 2026 is the out-of-sample check."""
RULES_VERSION = 2

# ETFs the tool can pick from, grouped by theme. No more than THEME_CAP from one theme.
THEMES = {
    "Australian shares": ["STW", "IOZ", "A200", "VAS", "RARI"],
    "Australian small caps": ["VSO", "ISO", "MVS"],
    "Australian dividends": ["VHY", "IHD"],
    "Australian banks": ["OZF"],
    "Australian resources": ["OZR", "QRE"],
    "Property": ["VAP", "SLF", "MVA", "DJRE"],
    "US shares": ["IVV", "VTS", "IHVV"],
    "Global shares": ["VGS", "IWLD", "IOO", "VEU", "WDIV", "QUAL", "MOAT", "ETHI", "INCM"],
    "Technology": ["NDQ", "TECH", "HACK", "SEMI", "FANG", "ROBO", "ATEC", "ASIA"],
    "Asia & emerging": ["IAA", "IZZ", "IEM", "VGE"],
    "Europe": ["IEU"],
    "Japan": ["IJP"],
    "Healthcare": ["IXJ", "DRUG"],
    "Energy": ["FUEL"],
    "Gold": ["GOLD", "QAU", "MNRS"],
    "Infrastructure": ["IFRA"],
    "Bonds": ["VAF", "IAF", "VGB", "IGB", "BOND", "QPON", "FLOT"],
}
THEME_OF = {t: k for k, v in THEMES.items() for t in v}
UNIVERSE = sorted(THEME_OF)

CASH = "AAA"              # defensive holding: Betashares cash ETF
INDEX = "AXJO.INDX"       # S&P/ASX 200 index, used for the market regime
BENCH_MIX = {"STW": 0.4, "IVV": 0.4, "VEU": 0.2}   # buy-and-hold comparison

START_CAPITAL = 10_000.0
COST = 0.0015             # 0.15% per trade, allowance for the bid-ask spread
LIQ_MIN = 1_000_000.0     # min median daily $ traded (60 days); thin ETFs have wider spreads than COST assumes

# Strategy B (trend, weekly)
B_N = 5                   # max holdings
B_BEAR_N = 2              # max holdings in a bear regime
B_MA = 200                # trend filter moving average (days)
B_BAND = 0.02             # buy above MA+1%, sell below MA-2% (avoids flip-flopping)
B_BUFFER = 15             # keep a holding while it ranks in the top 15
B_LOOKBACKS = (63, 126, 252)   # 3, 6 and 12 month momentum
B_VOL_DAYS = 63
B_MAX_WEIGHT = 0.30       # target cap for a new purchase
B_TRIM_ABOVE = 0.40       # at a weekly check, any holding above 40% is trimmed back to B_MAX_WEIGHT
THEME_CAP = 2

# Strategy A (daily pullback, paper only)
A_ENTRY_RSI = 10
A_MAX_POS = 5
A_HOLD_DAYS = 7
A_ALERTS = False          # Strategy A stays on paper but sends no alerts

# Live timing (Sydney time)
TZ = "Australia/Sydney"
DECISION_TIME = (15, 0)   # decisions are made at the first check from 3:00pm
MARKET_OPEN = (9, 55)
MARKET_CLOSE = (16, 30)
HISTORY_DAYS = 560        # calendar days of daily history to load
