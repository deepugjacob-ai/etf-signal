"""Indicator maths shared by the live engine and the backtest (one code path)."""
import numpy as np
import pandas as pd
from . import config as C


def clean_prices(px: pd.DataFrame) -> pd.DataFrame:
    """Remove bad ticks: non-positive prices and one-day spikes that instantly reverse."""
    px = px.where(px > 0)
    for _ in range(2):
        r = px.pct_change(fill_method=None)
        rn = r.shift(-1)
        spike = ((r > 0.12) & (rn < -0.10)) | ((r < -0.12) & (rn > 0.10))
        px = px.mask(spike)
    return px.ffill(limit=5)


def rsi(s: pd.Series, n: int = 2) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def compute(px: pd.DataFrame, turnover: pd.DataFrame) -> dict:
    """px: adjusted prices (columns = UNIVERSE + CASH + INDEX). turnover: $ traded per day."""
    P = px[C.UNIVERSE]
    cash = px[C.CASH]
    idx = px[C.INDEX]
    ret = P.pct_change(fill_method=None).fillna(0)
    sma = P.rolling(C.B_MA, min_periods=C.B_MA).mean()
    score = sum(P / P.shift(l) - 1 for l in C.B_LOOKBACKS) / len(C.B_LOOKBACKS)
    cscore = sum(cash / cash.shift(l) - 1 for l in C.B_LOOKBACKS) / len(C.B_LOOKBACKS)
    vol = ret.rolling(C.B_VOL_DAYS).std()
    liq = turnover.reindex(columns=C.UNIVERSE).rolling(60, min_periods=40).median().shift(1)
    s200, s50 = idx.rolling(200).mean(), idx.rolling(50).mean()
    bull = (idx > s200) & (s50 > s200)
    bear = (idx < s200) & (s50 < s200)
    regime = pd.Series(np.where(bull, "bull", np.where(bear, "bear", "sideways")), index=px.index)
    regime[s200.isna()] = "unknown"
    return dict(
        P=P, score=score, cscore=cscore, sma=sma, vol=vol, liq=liq, regime=regime,
        base=score.gt(cscore, axis=0) & (liq > C.LIQ_MIN) & score.notna(),
        above_in=P > sma * (1 + C.B_BAND / 2),
        above_hold=P > sma * (1 - C.B_BAND),
        rsi2=P.apply(rsi), sma5=P.rolling(5).mean(),
    )
