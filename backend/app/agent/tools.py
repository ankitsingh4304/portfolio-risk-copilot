"""Tools the AI agent can call.

Important design choice: the LLM never does the math. Every number comes from
our tested Python code (risk_engine, scenarios). The LLM only decides WHICH tool
to call and then explains the result in plain words. LLMs are bad at arithmetic,
so this keeps the answers correct.

Tools are created per request, so each one only sees the logged-in user's data.
"""
import functools
from typing import Literal

from langchain_core.tools import StructuredTool
from sqlalchemy.orm import Session

from ..models import User
from ..services import scenarios as sc
from ..services.news import fetch_news
from ..services.portfolio_data import NoHoldingsError, build_snapshot, risk_report

EventKey = Literal["covid_2020", "rate_hikes_2022", "election_day_2024"]


def _r(x, nd=2):
    return round(x, nd) if isinstance(x, (int, float)) else x


def _pct(x, nd=1):
    """Fraction -> percent number. 0.1234 -> 12.3"""
    return round(x * 100, nd) if isinstance(x, (int, float)) else None


def _scenario_summary(res: dict) -> dict:
    return {
        "scenario": res["name"],
        "current_value_inr": round(res["current_value"]),
        "estimated_change_inr": round(res["total_impact"]),
        "estimated_change_pct": _r(res["total_impact_pct"]),
        "value_after_inr": round(res["new_value"]),
        "biggest_hits": [
            {"symbol": r["symbol"], "move_pct": _r(r["move_pct"], 1), "change_inr": round(r["impact"]), "how": r["method"]}
            for r in res["rows"][:5] if r["impact"] != 0
        ],
        "notes": res["notes"],
    }


class ToolContext:
    """Holds the DB session and user, and builds the portfolio snapshot only once per request."""

    def __init__(self, db: Session, user: User):
        self.db, self.user = db, user
        self._snap = None
        self._report = None

    def snap(self):
        if self._snap is None:
            self._snap = build_snapshot(self.db, self.user)
        return self._snap

    def report(self):
        if self._report is None:
            self._report = risk_report(self.snap())
        return self._report


def build_tools(ctx: ToolContext) -> list[StructuredTool]:
    def safe(fn):
        """Turn errors into a message the LLM can relay, instead of crashing the chat."""
        @functools.wraps(fn)  # keeps the name, docstring and argument types for the tool schema
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except NoHoldingsError as exc:
                return {"error": str(exc)}
            except sc.ScenarioError as exc:
                return {"error": str(exc)}
        return wrapper

    @safe
    def get_portfolio_overview() -> dict:
        """Get the user's holdings: total value, profit/loss, each stock's weight, and sector split."""
        r = ctx.report()
        return {
            "as_of": r["as_of"],
            "total_value_inr": round(r["total_value"]),
            "invested_inr": round(r["total_cost"]),
            "profit_loss_inr": round(r["total_pnl"]),
            "profit_loss_pct": _r(r["total_pnl_pct"]),
            "holdings": [
                {"symbol": h["symbol"], "sector": h["sector"], "value_inr": round(h["value"]),
                 "weight_pct": _pct(h["weight"]), "profit_loss_pct": _r(h["pnl_pct"], 1)}
                for h in r["holdings"]
            ],
            "sector_weights_pct": {k: _pct(v) for k, v in r["concentration"]["sector_weights"].items()},
        }

    @safe
    def get_risk_metrics() -> dict:
        """Get risk numbers for the whole portfolio over the last year: volatility, max drawdown,
        1-day Value at Risk, beta vs NIFTY 50, Sharpe ratio, concentration, and which stocks
        contribute the most risk."""
        r = ctx.report()
        m = r["metrics"]
        if not m:
            return {"error": "Not enough price history yet to measure risk.", "warnings": r["warnings"]}
        c = r["concentration"]
        top_risk = sorted([h for h in r["holdings"] if h["risk_share"] is not None],
                          key=lambda h: h["risk_share"], reverse=True)[:5]
        return {
            "annual_volatility_pct": _pct(m["annual_volatility"]),
            "nifty_annual_volatility_pct": _pct(m["market_annual_volatility"]),
            "one_year_return_pct": _pct(m["annual_return"]),
            "nifty_one_year_return_pct": _pct(m["market_annual_return"]),
            "max_drawdown_pct": _pct(m["max_drawdown"]),
            "drawdown_peak_date": m["drawdown_peak"],
            "drawdown_bottom_date": m["drawdown_trough"],
            "current_drawdown_pct": _pct(m["current_drawdown"]),
            "var_95_one_day_inr": round(m["var_95_amount"]),
            "var_95_one_day_pct": _pct(m["var_95_pct"], 2),
            "expected_shortfall_95_inr": round(m["cvar_95_amount"]),
            "beta_vs_nifty": _r(m["beta"]),
            "sharpe_ratio": _r(m["sharpe"]),
            "diversification_ratio": _r(m["diversification_ratio"]),
            "largest_holding": {"symbol": c["top_holding"]["symbol"], "weight_pct": _pct(c["top_holding"]["weight"])},
            "top3_weight_pct": _pct(c["top3_weight"]),
            "effective_number_of_stocks": _r(c["effective_holdings"], 1),
            "top_risk_contributors": [
                {"symbol": h["symbol"], "weight_pct": _pct(h["weight"]), "share_of_risk_pct": _pct(h["risk_share"])}
                for h in top_risk
            ],
            "coverage_pct": _pct(r["coverage"]),
            "warnings": r["warnings"],
        }

    @safe
    def get_risk_outlook() -> dict:
        """Forward-looking risk: is the portfolio swinging more than usual right now (EWMA volatility),
        what a bad / typical next month could look like (10,000-path Monte Carlo simulation),
        the chance of losing more than 10% in a month, and whether the VaR model passed its backtest."""
        r = ctx.report()
        o = r.get("outlook")
        if not o:
            return {"error": "Not enough price history yet for a forecast."}
        out = {"based_on_days": o["days_used"], "share_of_portfolio_covered_pct": _pct(o["coverage"])}
        if o["volatility"]:
            v = o["volatility"]
            out["volatility_now_pct"] = _pct(v["now"])
            out["volatility_usual_pct"] = _pct(v["typical"])
            out["volatility_vs_usual"] = v["text"]
        if o["month"]:
            m = o["month"]
            out["next_month_bad_case_pct"] = _pct(m["bad_month"])
            out["next_month_bad_case_inr"] = round(m["bad_month_amount"])
            out["next_month_typical_pct"] = _pct(m["typical_month"])
            out["next_month_good_case_pct"] = _pct(m["good_month"])
            out["chance_of_any_loss_pct"] = _pct(m["prob_loss"])
            out["chance_of_losing_over_10pct"] = _pct(m["prob_loss_over_10"])
            out["simulated_paths"] = m["paths"]
        if o["var_backtest"]:
            b = o["var_backtest"]
            out["var_backtest"] = {
                "days_tested": b["days_tested"], "breaches": b["breaches"], "expected_breaches": round(b["expected"], 1),
                "passed": b["passed"], "kupiec_p_value": _r(b["p_value"], 3),
            }
        out["note"] = "Simulations are based on past price behaviour, not a prediction."
        return out

    @safe
    def get_stock_details(symbol: str) -> dict:
        """Get risk details for ONE stock the user holds: weight, volatility, beta, 1-year return, share of risk."""
        r = ctx.report()
        h = next((x for x in r["holdings"] if x["symbol"] == symbol.strip().upper()), None)
        if not h:
            return {"error": f"{symbol} is not in the portfolio."}
        return {
            "symbol": h["symbol"], "name": h["name"], "sector": h["sector"], "value_inr": round(h["value"]),
            "weight_pct": _pct(h["weight"]), "profit_loss_pct": _r(h["pnl_pct"], 1),
            "annual_volatility_pct": _pct(h["annual_volatility"]), "beta_vs_nifty": _r(h["beta"]),
            "one_year_return_pct": _pct(h["one_year_return"]), "share_of_portfolio_risk_pct": _pct(h["risk_share"]),
        }

    @safe
    def run_sector_scenario(sector: str, drop_pct: float) -> dict:
        """Estimate the loss if one sector falls. Example: sector='IT', drop_pct=15 means IT falls 15%.
        Includes knock-on effects on other stocks that usually move with that sector."""
        return _scenario_summary(sc.sector_shock(ctx.snap(), sector, abs(drop_pct)))

    @safe
    def run_market_scenario(drop_pct: float) -> dict:
        """Estimate the loss if the whole market (NIFTY 50) falls by drop_pct percent. Uses each stock's beta."""
        return _scenario_summary(sc.market_shock(ctx.snap(), abs(drop_pct)))

    @safe
    def run_historical_scenario(event: EventKey) -> dict:
        """Replay a real past crash on today's portfolio. Events: covid_2020 (Feb-Mar 2020 crash),
        rate_hikes_2022 (Apr-Jun 2022 selloff), election_day_2024 (4 June 2024 one-day fall)."""
        return _scenario_summary(sc.historical_replay(ctx.snap(), event))

    @safe
    def run_custom_scenario(symbols: list[str], moves_pct: list[float]) -> dict:
        """Apply your own price moves to specific stocks. symbols and moves_pct are matched by position;
        negative means a fall. Example: symbols=["INFY", "TCS"], moves_pct=[-20, -10]."""
        if len(symbols) != len(moves_pct):
            return {"error": "symbols and moves_pct must have the same length."}
        return _scenario_summary(sc.custom_shock(ctx.snap(), dict(zip(symbols, moves_pct))))

    @safe
    def get_correlated_pairs() -> dict:
        """Find pairs of holdings that move together the most (correlation from -1 to +1).
        Highly correlated pairs give little diversification."""
        r = ctx.report()
        return {"pairs": [{"a": p["a"], "b": p["b"], "correlation": _r(p["correlation"])}
                          for p in r.get("top_correlated_pairs", [])]}

    @safe
    def get_stock_news(symbol: str) -> dict:
        """Get recent news headlines (last 7 days) for a stock the user holds, tagged by tone and type."""
        t = ctx.snap().table
        sym = symbol.strip().upper()
        if sym not in t.index:
            return {"error": f"{symbol} is not in the portfolio."}
        items = fetch_news(t.loc[sym, "name"], sym, limit=8)
        if not items:
            return {"symbol": sym, "headlines": [], "note": "No recent headlines found (or news is unavailable)."}
        return {"symbol": sym, "headlines": [
            {"title": i.title, "source": i.source, "published": i.published, "tone": i.tone, "type": i.event_type}
            for i in items
        ]}

    fns = [get_portfolio_overview, get_risk_metrics, get_risk_outlook, get_stock_details, run_sector_scenario,
           run_market_scenario, run_historical_scenario, run_custom_scenario, get_correlated_pairs, get_stock_news]
    return [StructuredTool.from_function(f) for f in fns]
