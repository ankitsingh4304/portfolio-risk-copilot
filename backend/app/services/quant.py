"""Time-series and probability models: "is risk rising?", "what could next month look like?",
and "can we trust our Value at Risk number?".

1. EWMA volatility (the RiskMetrics method, used by banks since the 1990s)
   Normal volatility treats every day of the past year equally. EWMA gives recent days
   more weight, so it reacts quickly when markets get jumpy.
       variance_today = 0.94 x variance_yesterday + 0.06 x (today's return)^2
   Comparing today's EWMA volatility with its usual level gives a simple signal:
   "your portfolio is swinging more than usual right now".

2. Monte Carlo for the next month (filtered historical simulation)
   We build 10,000 possible next months out of real past days, picked at random.
   Each past day is first rescaled to today's volatility level, so a calm past day
   counts as "calm for today's market", not as calm in absolute terms.
   We assume no trend (average return of zero), since past trends don't reliably continue.
   From the 10,000 outcomes we read: a bad month (1 in 20), a typical month, and
   the chance of losing more than 10%.

3. VaR backtest (Kupiec test)
   Our 95% VaR says: "only 1 day in 20 should be worse than this". We check that on the
   past year. For each day, we compute VaR using only the 250 days BEFORE it (no peeking),
   then count how often the real loss was bigger ("breaches"). About 5% is right.
   Kupiec's test says whether the count is too far from 5% to be bad luck.
"""
import math

import numpy as np
import pandas as pd

TRADING_DAYS = 252
EWMA_LAMBDA = 0.94  # RiskMetrics' standard value for daily data


def ewma_volatility(returns: pd.Series, lam: float = EWMA_LAMBDA, seed_days: int = 30) -> pd.Series:
    """Yearly volatility estimate at the end of each day (uses that day's return)."""
    r = returns.dropna().to_numpy()
    if len(r) <= seed_days:
        return pd.Series(dtype=float)
    var = np.empty(len(r))
    var[seed_days - 1] = np.var(r[:seed_days], ddof=1)
    for t in range(seed_days, len(r)):
        var[t] = lam * var[t - 1] + (1 - lam) * r[t] ** 2
    idx = returns.dropna().index
    return pd.Series(np.sqrt(var[seed_days - 1:] * TRADING_DAYS), index=idx[seed_days - 1:])


def volatility_signal(ewma: pd.Series, lookback: int = TRADING_DAYS) -> dict | None:
    """Today's EWMA volatility vs its usual (median) level over the last year."""
    if len(ewma) < 60:
        return None
    recent = ewma.tail(lookback)
    now, typical = float(ewma.iloc[-1]), float(recent.median())
    ratio = now / typical if typical > 0 else 1.0
    if ratio >= 1.5:
        level, text = "high", "much higher than usual"
    elif ratio >= 1.2:
        level, text = "elevated", "higher than usual"
    elif ratio <= 0.8:
        level, text = "low", "lower than usual"
    else:
        level, text = "normal", "about normal"
    return {"now": now, "typical": typical, "ratio": ratio, "level": level, "text": text}


def monte_carlo_month(
    returns: pd.Series, horizon: int = 21, n_paths: int = 10_000, seed: int = 7
) -> dict | None:
    """Possible portfolio returns over the next `horizon` trading days (21 = about a month)."""
    r = returns.dropna()
    ewma = ewma_volatility(r)
    if len(ewma) < 120:
        return None
    daily_vol = ewma / math.sqrt(TRADING_DAYS)
    # Standardise: each day's return divided by the volatility we expected BEFORE that day.
    prior_vol = daily_vol.shift(1).dropna()
    z = (r.reindex(prior_vol.index) / prior_vol).dropna().to_numpy()
    z = z[np.isfinite(z)]
    # Assume no trend: a strong past year shouldn't make next month look rosy (or the reverse).
    # Short-horizon risk models usually do this, because past trends don't reliably continue.
    z = z - z.mean()
    vol_now = float(daily_vol.iloc[-1])

    rng = np.random.default_rng(seed)  # fixed seed: same portfolio -> same answer every time
    picks = rng.choice(z, size=(n_paths, horizon), replace=True)
    daily = np.clip(picks * vol_now, -0.99, None)
    outcomes = np.prod(1 + daily, axis=1) - 1

    counts, edges = np.histogram(outcomes * 100, bins=30)
    return {
        "horizon_days": horizon,
        "paths": n_paths,
        "bad_month": float(np.percentile(outcomes, 5)),     # 1 in 20 months is worse
        "typical_month": float(np.percentile(outcomes, 50)),
        "good_month": float(np.percentile(outcomes, 95)),   # 1 in 20 months is better
        "prob_loss": float((outcomes < 0).mean()),
        "prob_loss_over_10": float((outcomes < -0.10).mean()),
        "histogram": [
            {"from_pct": round(float(edges[i]), 2), "to_pct": round(float(edges[i + 1]), 2), "count": int(c)}
            for i, c in enumerate(counts)
        ],
    }


def kupiec_pof(breaches: int, days: int, p: float = 0.05) -> float:
    """Kupiec 'proportion of failures' test. Returns the p-value.

    Small p-value (below 0.05) = the breach count is too far from expected to be luck,
    so the VaR model is probably wrong.
    """
    if days == 0:
        return 1.0
    x, n = breaches, days
    phat = x / n

    def loglik(prob):
        a = (n - x) * math.log(1 - prob) if x < n else 0.0
        b = x * math.log(prob) if x > 0 else 0.0
        return a + b

    lr = -2 * (loglik(p) - loglik(phat)) if 0 < phat < 1 else -2 * loglik(p)
    lr = max(lr, 0.0)
    # Chi-square with 1 degree of freedom: P(X > lr) = erfc(sqrt(lr / 2)). No scipy needed.
    return math.erfc(math.sqrt(lr / 2))


def var_backtest(returns: pd.Series, window: int = 250, test_days: int = 250, confidence: float = 0.95) -> dict | None:
    """Check historical VaR on the most recent `test_days`, using only past data for each day."""
    r = returns.dropna().to_numpy()
    if len(r) < window + test_days:
        return None
    p = 1 - confidence
    breaches = 0
    breach_dates = []
    start = len(r) - test_days
    dates = returns.dropna().index
    for t in range(start, len(r)):
        var_t = -np.percentile(r[t - window:t], p * 100)
        if r[t] < -var_t:
            breaches += 1
            breach_dates.append(pd.Timestamp(dates[t]).date().isoformat())
    p_value = kupiec_pof(breaches, test_days, p)
    return {
        "days_tested": test_days,
        "breaches": breaches,
        "expected": p * test_days,
        "breach_rate": breaches / test_days,
        "p_value": p_value,
        "passed": p_value >= 0.05,
        "last_breaches": breach_dates[-5:],
    }
