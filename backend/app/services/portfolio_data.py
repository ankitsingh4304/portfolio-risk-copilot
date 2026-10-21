"""Builds a 'snapshot' of a user's portfolio (prices, values, weights) and the full risk report.

Both the API routes and the AI agent use these functions, so the numbers the agent
talks about are exactly the numbers shown on the dashboard.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Holding, User
from . import quant
from . import risk_engine as re_
from .prices import get_prices

settings = get_settings()
MIN_HISTORY_DAYS = 60  # need at least ~3 months of prices to say anything about risk
LONG_WINDOW_DAYS = 2 * 252 + 40  # ~2 years: the VaR backtest needs 250 days to learn + 250 to test
MIN_LONG_COVERAGE = 0.6  # use the 2-year series only if it covers 60%+ of the portfolio's value


class NoHoldingsError(Exception):
    pass


@dataclass
class Snapshot:
    table: pd.DataFrame  # one row per holding (index = symbol)
    prices: pd.DataFrame  # daily close per symbol
    market: pd.Series  # daily close of the market index
    total_value: float
    total_cost: float
    as_of: str | None
    warnings: list[str] = field(default_factory=list)


def build_snapshot(db: Session, user: User) -> Snapshot:
    holdings = db.scalars(select(Holding).where(Holding.user_id == user.id)).all()
    if not holdings:
        raise NoHoldingsError("No holdings yet. Upload your broker export or add a stock first.")

    symbols = [h.symbol for h in holdings]
    prices, market = get_prices(db, symbols)
    warnings: list[str] = []
    rows = []
    for h in holdings:
        s = prices[h.symbol].dropna() if h.symbol in prices else pd.Series(dtype=float)
        if s.empty:
            last, prev, has_price = h.avg_price, None, False
            warnings.append(f"No price data for {h.symbol}. Using your average price, and leaving it out of risk stats.")
        else:
            last, prev, has_price = float(s.iloc[-1]), (float(s.iloc[-2]) if len(s) > 1 else None), True
        value = h.quantity * last
        cost = h.quantity * h.avg_price
        rows.append({
            "symbol": h.symbol,
            "name": h.name or h.symbol,
            "sector": h.sector or "Other",
            "quantity": h.quantity,
            "avg_price": h.avg_price,
            "last_price": last,
            "day_change_pct": ((last / prev - 1) * 100) if prev else None,
            "value": value,
            "cost": cost,
            "pnl": value - cost,
            "pnl_pct": ((value / cost - 1) * 100) if cost > 0 else None,
            "has_price": has_price,
            "history_days": int(len(s)),
        })
    table = pd.DataFrame(rows).set_index("symbol")
    total_value = float(table["value"].sum())
    table["weight"] = table["value"] / total_value if total_value > 0 else 0.0
    as_of = prices.dropna(how="all").index.max()
    return Snapshot(
        table=table.sort_values("value", ascending=False),
        prices=prices,
        market=market,
        total_value=total_value,
        total_cost=float(table["cost"].sum()),
        as_of=as_of.date().isoformat() if pd.notna(as_of) else None,
        warnings=warnings,
    )


def _clean(x):
    """Make numbers JSON-safe (no NaN/inf)."""
    if x is None:
        return None
    if isinstance(x, (float, np.floating)):
        return None if (np.isnan(x) or np.isinf(x)) else float(x)
    return x


def analysis_window(snap: Snapshot) -> tuple[pd.DataFrame, pd.Series, pd.Series, list[str]]:
    """Returns over the lookback window, for stocks with enough history.

    Gives (stock returns, weights re-scaled to the covered stocks, market returns, covered symbols).
    """
    window = snap.prices.tail(settings.lookback_days + 1)
    rets = re_.daily_returns(window)
    covered = [s for s in rets.columns if rets[s].notna().sum() >= MIN_HISTORY_DAYS]
    rets = rets[covered].dropna(how="any")
    w = snap.table.loc[covered, "weight"] if covered else pd.Series(dtype=float)
    w = w / w.sum() if w.sum() > 0 else w
    mkt = re_.daily_returns(snap.market).reindex(rets.index) if not snap.market.empty else pd.Series(dtype=float)
    return rets, w, mkt, covered


def long_portfolio_returns(snap: Snapshot) -> tuple[pd.Series, float]:
    """~2 years of daily portfolio returns, using stocks that have (almost) full history.

    Returns (returns, share of the portfolio's value those stocks make up).
    """
    rets = re_.daily_returns(snap.prices.tail(LONG_WINDOW_DAYS + 1))
    if rets.empty:
        return pd.Series(dtype=float), 0.0
    full = [s for s in rets.columns if rets[s].notna().sum() >= 0.98 * len(rets)]
    if not full:
        return pd.Series(dtype=float), 0.0
    rets = rets[full].dropna(how="any")
    w = snap.table.loc[full, "weight"]
    coverage = float(w.sum())
    return re_.portfolio_returns(rets, w / w.sum()), coverage


def outlook(snap: Snapshot, one_year: pd.Series, one_year_coverage: float) -> dict:
    """Time-series and probability views: is risk rising, what could next month look like,
    and does our VaR hold up on past data? (See quant.py.)"""
    long_ret, long_cov = long_portfolio_returns(snap)
    use_long = long_cov >= MIN_LONG_COVERAGE and len(long_ret) >= 300
    series, cov = (long_ret, long_cov) if use_long else (one_year, one_year_coverage)
    value = snap.total_value * cov
    ewma = quant.ewma_volatility(series)
    month = quant.monte_carlo_month(series)
    if month:
        month["bad_month_amount"] = month["bad_month"] * value
        month["typical_month_amount"] = month["typical_month"] * value
    return {
        "volatility": quant.volatility_signal(ewma),
        "month": month,
        "var_backtest": quant.var_backtest(long_ret) if use_long else None,
        "coverage": cov,
        "days_used": int(len(series)),
        "ewma": ewma,  # removed before sending; used for the chart
    }


def risk_report(snap: Snapshot) -> dict:
    t = snap.table
    rets, w, mkt, covered = analysis_window(snap)
    coverage = float(t.loc[covered, "weight"].sum()) if covered else 0.0
    conc = re_.concentration(t["weight"], t["sector"])
    warnings = list(snap.warnings)
    for sym in t.index:
        if t.loc[sym, "has_price"] and sym not in covered:
            warnings.append(f"{sym} has less than {MIN_HISTORY_DAYS} days of prices, so it's left out of risk stats.")

    base = {
        "as_of": snap.as_of,
        "total_value": snap.total_value,
        "total_cost": snap.total_cost,
        "total_pnl": snap.total_value - snap.total_cost,
        "total_pnl_pct": ((snap.total_value / snap.total_cost - 1) * 100) if snap.total_cost > 0 else None,
        "coverage": coverage,
        "concentration": conc,
        "warnings": warnings,
        "lookback_days": int(len(rets)),
    }
    if rets.empty or len(rets) < MIN_HISTORY_DAYS:
        base["metrics"] = None
        base["holdings"] = _holdings_rows(t, {}, {}, {}, None)
        return base

    port = re_.portfolio_returns(rets, w)
    dd = re_.drawdown(port)
    var95, cvar95 = re_.value_at_risk(port, 0.95)
    covered_value = snap.total_value * coverage
    port_beta = re_.beta(port, mkt) if not mkt.empty else None
    rc = re_.risk_contribution(rets, w)

    stock_beta = {s: re_.beta(rets[s], mkt) for s in covered} if not mkt.empty else {}
    stock_vol = {s: re_.annualized_volatility(rets[s]) for s in covered}
    stock_ret = {s: re_.annualized_return(rets[s]) for s in covered}

    mkt_growth = (1 + mkt.fillna(0)).cumprod() * 100 if not mkt.empty else None
    port_growth = (1 + port).cumprod() * 100
    history = [
        {
            "date": d.date().isoformat(),
            "portfolio": round(float(port_growth.loc[d]), 2),
            "market": round(float(mkt_growth.loc[d]), 2) if mkt_growth is not None else None,
            "drawdown": round(float(dd.series.loc[d]) * 100, 2),
        }
        for d in port.index
    ]
    corr = rets.corr()

    base["metrics"] = {
        "annual_volatility": re_.annualized_volatility(port),
        "annual_return": re_.annualized_return(port),
        "sharpe": _clean(re_.sharpe_ratio(port, settings.risk_free_rate)),
        "risk_free_rate": settings.risk_free_rate,
        "beta": _clean(port_beta),
        "var_95_pct": var95,
        "var_95_amount": var95 * covered_value,
        "cvar_95_pct": cvar95,
        "cvar_95_amount": cvar95 * covered_value,
        "max_drawdown": dd.max_drawdown,
        "drawdown_peak": dd.peak_date,
        "drawdown_trough": dd.trough_date,
        "drawdown_recovered": dd.recovery_date,
        "current_drawdown": dd.current_drawdown,
        "diversification_ratio": _clean(re_.diversification_ratio(rets, w)),
        "market_annual_volatility": _clean(re_.annualized_volatility(mkt.dropna())) if not mkt.empty else None,
        "market_annual_return": _clean(re_.annualized_return(mkt.dropna())) if not mkt.empty else None,
    }
    base["top_correlated_pairs"] = re_.top_correlated_pairs(rets, 5)
    base["correlation_matrix"] = {
        "symbols": list(corr.columns),
        "values": [[round(float(v), 3) for v in row] for row in corr.to_numpy()],
    }
    look = outlook(snap, port, coverage)
    ewma = look.pop("ewma")
    for row in history:
        v = ewma.get(pd.Timestamp(row["date"]))
        row["ewma_vol"] = round(float(v) * 100, 2) if v is not None and pd.notna(v) else None
    base["outlook"] = look
    base["history"] = history
    base["holdings"] = _holdings_rows(t, stock_vol, stock_beta, stock_ret, rc)
    return base


def _holdings_rows(t, vol, beta, ret, rc) -> list[dict]:
    rows = []
    for sym, r in t.iterrows():
        rows.append({
            "symbol": sym,
            "name": r["name"],
            "sector": r["sector"],
            "quantity": r["quantity"],
            "avg_price": r["avg_price"],
            "last_price": r["last_price"],
            "day_change_pct": _clean(r["day_change_pct"]),
            "value": r["value"],
            "pnl": r["pnl"],
            "pnl_pct": _clean(r["pnl_pct"]),
            "weight": r["weight"],
            "annual_volatility": _clean(vol.get(sym)),
            "beta": _clean(beta.get(sym)),
            "one_year_return": _clean(ret.get(sym)),
            "risk_share": _clean(float(rc.loc[sym, "risk_share"])) if rc is not None and sym in rc.index else None,
            "has_price": bool(r["has_price"]),
        })
    return rows
