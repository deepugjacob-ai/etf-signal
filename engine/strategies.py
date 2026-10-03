"""Decision rules (version 2). Pure functions shared by the live engine and the backtest."""
from . import config as C


def decide_b(ind: dict, t, held: list, tradable=None):
    """Strategy B weekly decision. Returns (keep list, ranks, n_max).
    tradable: optional set of ETFs with a fresh quote today; others are not bought (never forces a sale)."""
    n_max = C.B_BEAR_N if ind["regime"][t] == "bear" else C.B_N
    above_hold, above_in = ind["above_hold"].loc[t], ind["above_in"].loc[t]
    # v2: only ETFs that pass the trend test are ranked, so names below their trend line can't crowd the buffer
    elig = ind["base"].loc[t] & above_hold
    sc = ind["score"].loc[t].where(elig).dropna().sort_values(ascending=False)
    ranks = {k: i + 1 for i, k in enumerate(sc.index)}
    keep = [h for h in held if h in ranks and ranks[h] <= C.B_BUFFER]
    # v2 fix: when the limit shrinks (downtrend), keep the best-ranked holdings, not the oldest
    keep = sorted(keep, key=lambda x: ranks[x])[:n_max]
    kk = []
    for h in keep:
        if sum(C.THEME_OF[x] == C.THEME_OF[h] for x in kk) < C.THEME_CAP:
            kk.append(h)
    keep = kk
    for k in sc.index:
        if len(keep) >= n_max:
            break
        if k in keep or not bool(above_in[k]):
            continue
        if tradable is not None and k not in tradable:
            continue
        if sum(C.THEME_OF[x] == C.THEME_OF[k] for x in keep) >= C.THEME_CAP:
            continue
        keep.append(k)
    return keep, ranks, n_max


def b_new_weights(ind: dict, t, keep: list, new: list) -> dict:
    """Target share of total value for newly bought ETFs (inverse volatility). The |K|/5 factor is deliberate:
    with fewer qualifying ETFs, more money stays in cash."""
    if not keep:
        return {}
    iv = 1 / ind["vol"].loc[t, keep]
    iv = (iv / iv.sum() * len(keep) / C.B_N).clip(upper=C.B_MAX_WEIGHT)
    return {k: float(iv[k]) for k in new}


def decide_a_exits(ind: dict, t, positions: dict) -> list:
    """Strategy A exits: bounce above 5-day average, held 7 trading days, or bear regime."""
    out = []
    for k, days in positions.items():
        if ind["P"].at[t, k] > ind["sma5"].at[t, k] or days >= C.A_HOLD_DAYS or ind["regime"][t] == "bear":
            out.append(k)
    return out


def decide_a_entries(ind: dict, t, positions_after_exit: list, tradable=None) -> list:
    if ind["regime"][t] == "bear":
        return []
    r = ind["rsi2"].loc[t]
    P, sma = ind["P"].loc[t], ind["sma"].loc[t]
    ok = (r < C.A_ENTRY_RSI) & (P > sma) & (ind["liq"].loc[t] > C.LIQ_MIN)
    cands = [k for k in r[ok].sort_values().index if tradable is None or k in tradable]
    room = C.A_MAX_POS - len(positions_after_exit)
    return [k for k in cands if k not in positions_after_exit][:max(room, 0)]
