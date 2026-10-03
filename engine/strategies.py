"""Decision rules. Pure functions: given indicators for one day and current holdings, return targets."""
from . import config as C


def decide_b(ind: dict, t, held: list):
    """Strategy B. Returns (keep list, ranking list, n_max)."""
    n_max = C.B_BEAR_N if ind["regime"][t] == "bear" else C.B_N
    sc = ind["score"].loc[t].where(ind["base"].loc[t]).dropna().sort_values(ascending=False)
    ranks = {k: i + 1 for i, k in enumerate(sc.index)}
    above_hold, above_in = ind["above_hold"].loc[t], ind["above_in"].loc[t]
    keep = [h for h in held if h in ranks and ranks[h] <= C.B_BUFFER and bool(above_hold[h])][:n_max]
    # theme cap also applies to holdings already kept (lowest-ranked extras go)
    kk = []
    for h in sorted(keep, key=lambda x: ranks[x]):
        if sum(C.THEME_OF[x] == C.THEME_OF[h] for x in kk) < C.THEME_CAP:
            kk.append(h)
    keep = [h for h in keep if h in kk]
    for k in sc.index:
        if len(keep) >= n_max:
            break
        if k in keep or not bool(above_in[k]):
            continue
        if sum(C.THEME_OF[x] == C.THEME_OF[k] for x in keep) >= C.THEME_CAP:
            continue
        keep.append(k)
    return keep, ranks, n_max


def b_new_weights(ind: dict, t, keep: list, new: list) -> dict:
    """Target weight (share of total equity) for newly bought ETFs, sized by inverse volatility."""
    if not keep:
        return {}
    iv = 1 / ind["vol"].loc[t, keep]
    iv = (iv / iv.sum() * len(keep) / C.B_N).clip(upper=C.B_MAX_WEIGHT)
    return {k: float(iv[k]) for k in new}


def decide_a_exits(ind: dict, t, positions: dict) -> list:
    """Strategy A exits: bounce above 5-day average, held 7 days, or bear regime. positions: tic -> days held (already incremented)."""
    out = []
    for k, days in positions.items():
        if ind["P"].at[t, k] > ind["sma5"].at[t, k] or days >= C.A_HOLD_DAYS or ind["regime"][t] == "bear":
            out.append(k)
    return out


def decide_a_entries(ind: dict, t, positions_after_exit: list) -> list:
    if ind["regime"][t] == "bear":
        return []
    r = ind["rsi2"].loc[t]
    P, sma = ind["P"].loc[t], ind["sma"].loc[t]
    ok = (r < C.A_ENTRY_RSI) & (P > sma) & (ind["liq"].loc[t] > C.LIQ_MIN)
    cands = r[ok].sort_values().index.tolist()
    room = C.A_MAX_POS - len(positions_after_exit)
    return [k for k in cands if k not in positions_after_exit][:max(room, 0)]
