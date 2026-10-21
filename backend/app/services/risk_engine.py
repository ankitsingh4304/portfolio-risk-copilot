"""Portfolio risk math. Pure functions: numbers in, numbers out. Easy to test.

Key idea: we take TODAY's portfolio weights and ask "if I had held exactly this
mix over the past year, how bumpy would the ride have been?" That is the standard
way to estimate the risk of a portfolio as it stands now.

All returns are simple daily returns: (today's price / yesterday's price) - 1.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def daily_returns(prices: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    return prices.sort_index().pct_change(fill_method=None).iloc[1:]


def portfolio_returns(stock_returns: pd.DataFrame, weights: pd.Series) -> pd.Series:
    """Daily return of the whole portfolio = weighted sum of each stock's return."""
    w = weights.reindex(stock_returns.columns).fillna(0.0)
    return stock_returns.mul(w, axis=1).sum(axis=1)


def annualized_volatility(returns: pd.Series) -> float:
    """How much returns jump around, scaled to a year. sqrt(252) because variance adds up over days."""
    return float(returns.std(ddof=1) * np.sqrt(TRADING_DAYS))


def annualized_return(returns: pd.Series) -> float:
    """Compound growth rate per year."""
    n = len(returns)
    if n == 0:
        return 0.0
    growth = float((1 + returns).prod())
    return growth ** (TRADING_DAYS / n) - 1


@dataclass
class Drawdown:
    max_drawdown: float  # negative number, e.g. -0.23 = fell 23% from a peak
    peak_date: str | None
    trough_date: str | None
    recovery_date: str | None  # None = has not yet climbed back to the old peak
    current_drawdown: float
    series: pd.Series  # drawdown at each day, for charts


def drawdown(returns: pd.Series) -> Drawdown:
    """Biggest fall from a high point to a later low point."""
    if returns.empty:
        return Drawdown(0.0, None, None, None, 0.0, pd.Series(dtype=float))
    wealth = (1 + returns).cumprod()
    running_peak = wealth.cummax()
    dd = wealth / running_peak - 1
    trough = dd.idxmin()
    max_dd = float(dd.min())
    if max_dd >= 0:
        return Drawdown(0.0, None, None, None, 0.0, dd)
    peak = wealth.loc[:trough].idxmax()
    after = wealth.loc[trough:]
    recovered = after[after >= wealth.loc[peak]]
    recovery = recovered.index[0] if not recovered.empty else None

    def fmt(d):
        return pd.Timestamp(d).date().isoformat() if d is not None else None

    return Drawdown(max_dd, fmt(peak), fmt(trough), fmt(recovery), float(dd.iloc[-1]), dd)


def value_at_risk(returns: pd.Series, confidence: float = 0.95) -> tuple[float, float]:
    """Historical 1-day VaR and CVaR, as positive loss fractions.

    VaR 95% = "on 95% of days, we lost less than this".
    CVaR (Expected Shortfall) = "on the worst 5% of days, we lost this much on average".
    """
    if returns.empty:
        return 0.0, 0.0
    cutoff = float(np.percentile(returns, (1 - confidence) * 100))
    tail = returns[returns <= cutoff]
    var = max(0.0, -cutoff)
    cvar = max(0.0, -float(tail.mean())) if not tail.empty else var
    return var, cvar


def beta(asset_returns: pd.Series, market_returns: pd.Series) -> float | None:
    """How much the asset moves when the market moves 1%. Beta 1.2 -> moves ~1.2%."""
    joined = pd.concat([asset_returns, market_returns], axis=1, join="inner").dropna()
    if len(joined) < 30:
        return None
    a, m = joined.iloc[:, 0], joined.iloc[:, 1]
    var_m = m.var(ddof=1)
    if var_m == 0:
        return None
    return float(a.cov(m) / var_m)


def sharpe_ratio(returns: pd.Series, risk_free_rate: float) -> float | None:
    """Return earned per unit of risk, above a safe government bond."""
    vol = annualized_volatility(returns)
    if vol == 0 or np.isnan(vol):
        return None
    return (annualized_return(returns) - risk_free_rate) / vol


def concentration(weights: pd.Series, sectors: pd.Series) -> dict:
    """Is too much money in one place?

    HHI (sum of squared weights): 1.0 = everything in one stock.
    Effective number of stocks = 1 / HHI. 10 equal stocks -> 10. One big + 9 tiny -> close to 1.
    """
    w = weights[weights > 0].sort_values(ascending=False)
    hhi = float((w**2).sum())
    sector_w = w.groupby(sectors.reindex(w.index).fillna("Other")).sum().sort_values(ascending=False)
    return {
        "top_holding": {"symbol": w.index[0], "weight": float(w.iloc[0])} if len(w) else None,
        "top3_weight": float(w.head(3).sum()),
        "hhi": hhi,
        "effective_holdings": (1 / hhi) if hhi > 0 else 0.0,
        "sector_weights": {k: float(v) for k, v in sector_w.items()},
    }


def risk_contribution(stock_returns: pd.Series | pd.DataFrame, weights: pd.Series) -> pd.DataFrame:
    """Which stocks cause the most risk? (Euler risk decomposition.)

    A stock can be 10% of your money but 25% of your risk if it is very volatile
    or moves together with your other big holdings.

    contribution_i = w_i * (Cov @ w)_i / portfolio_vol      (these add up to portfolio_vol)
    """
    cols = list(stock_returns.columns)
    w = weights.reindex(cols).fillna(0.0).to_numpy()
    cov = stock_returns.cov().to_numpy() * TRADING_DAYS
    port_var = float(w @ cov @ w)
    if port_var <= 0:
        return pd.DataFrame({"weight": w, "risk_share": np.zeros(len(cols))}, index=cols)
    port_vol = np.sqrt(port_var)
    contrib = w * (cov @ w) / port_vol
    return pd.DataFrame(
        {"weight": w, "risk_contribution": contrib, "risk_share": contrib / port_vol}, index=cols
    ).sort_values("risk_share", ascending=False)


def top_correlated_pairs(stock_returns: pd.DataFrame, n: int = 5) -> list[dict]:
    """Pairs of stocks that move together most. They don't diversify each other much."""
    corr = stock_returns.corr()
    cols = list(corr.columns)
    pairs = [
        {"a": cols[i], "b": cols[j], "correlation": float(corr.iat[i, j])}
        for i in range(len(cols))
        for j in range(i + 1, len(cols))
        if pd.notna(corr.iat[i, j])
    ]
    return sorted(pairs, key=lambda p: p["correlation"], reverse=True)[:n]


def diversification_ratio(stock_returns: pd.DataFrame, weights: pd.Series) -> float | None:
    """Weighted average of individual volatilities / portfolio volatility.

    1.0 = no diversification benefit. Higher = your stocks cancel out each other's swings more.
    """
    w = weights.reindex(stock_returns.columns).fillna(0.0)
    indiv = stock_returns.std(ddof=1) * np.sqrt(TRADING_DAYS)
    port = annualized_volatility(portfolio_returns(stock_returns, w))
    if port == 0:
        return None
    return float((w * indiv).sum() / port)
