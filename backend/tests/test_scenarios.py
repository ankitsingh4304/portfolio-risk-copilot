"""Scenarios on a hand-built portfolio where we know the exact answers."""
import numpy as np
import pandas as pd
import pytest

from app.services import scenarios as sc
from app.services.portfolio_data import Snapshot

DAYS = pd.bdate_range("2019-06-03", "2025-06-30")


def make_snapshot():
    rng = np.random.default_rng(42)
    mkt_r = rng.normal(0.0004, 0.01, len(DAYS))
    market = pd.Series(10000 * np.cumprod(1 + mkt_r), index=DAYS)
    # Stocks that are exact multiples of the market -> known betas.
    prices = pd.DataFrame({
        "AAA": 100 * np.cumprod(1 + 1.5 * mkt_r),  # beta 1.5, IT
        "BBB": 200 * np.cumprod(1 + 0.5 * mkt_r),  # beta 0.5, IT
        "CCC": 50 * np.cumprod(1 + 1.0 * mkt_r),   # beta 1.0, Banking
    }, index=DAYS)
    table = pd.DataFrame({
        "name": ["A Ltd", "B Ltd", "C Ltd"],
        "sector": ["Information Technology", "Information Technology", "Financial Services"],
        "quantity": [10, 5, 20],
        "avg_price": [100, 200, 50],
    }, index=["AAA", "BBB", "CCC"])
    table["last_price"] = prices.iloc[-1]
    table["value"] = table["quantity"] * table["last_price"]
    table["weight"] = table["value"] / table["value"].sum()
    table["cost"] = table["quantity"] * table["avg_price"]
    table["day_change_pct"] = None
    table["has_price"] = True
    return Snapshot(table=table, prices=prices, market=market, total_value=float(table["value"].sum()),
                    total_cost=float(table["cost"].sum()), as_of=DAYS[-1].date().isoformat())


def rows(res):
    return {r["symbol"]: r for r in res["rows"]}


def test_market_shock_uses_beta():
    snap = make_snapshot()
    res = sc.market_shock(snap, 10)
    r = rows(res)
    assert r["AAA"]["move_pct"] == pytest.approx(-15, abs=0.01)
    assert r["BBB"]["move_pct"] == pytest.approx(-5, abs=0.01)
    assert r["CCC"]["move_pct"] == pytest.approx(-10, abs=0.01)
    expected = sum(snap.table.loc[s, "value"] * m for s, m in [("AAA", -0.15), ("BBB", -0.05), ("CCC", -0.10)])
    assert res["total_impact"] == pytest.approx(expected, rel=1e-3)
    assert res["new_value"] == pytest.approx(snap.total_value + res["total_impact"])


def test_sector_shock_direct_only():
    snap = make_snapshot()
    res = sc.sector_shock(snap, "IT", 20, knock_on=False)  # "IT" is matched to "Information Technology"
    r = rows(res)
    assert r["AAA"]["move_pct"] == pytest.approx(-20)
    assert r["BBB"]["move_pct"] == pytest.approx(-20)
    assert r["CCC"]["impact"] == 0
    it_value = snap.table.loc[["AAA", "BBB"], "value"].sum()
    assert res["total_impact"] == pytest.approx(-0.2 * it_value)


def test_sector_shock_knock_on_hits_correlated_stock():
    snap = make_snapshot()
    res = sc.sector_shock(snap, "tech", 20)  # "tech" is a synonym for IT
    ccc = rows(res)["CCC"]
    assert ccc["impact"] < 0  # CCC moves with the market, like the IT stocks
    assert "knock-on" in ccc["method"]


def test_sector_not_held():
    with pytest.raises(sc.ScenarioError, match="don't hold any"):
        sc.sector_shock(make_snapshot(), "Pharma", 10)


def test_custom_shock():
    snap = make_snapshot()
    res = sc.custom_shock(snap, {"aaa": -50, "NOPE": -10})
    assert rows(res)["AAA"]["impact"] == pytest.approx(-0.5 * snap.table.loc["AAA", "value"])
    assert any("NOPE" in n for n in res["notes"])


def test_historical_replay_uses_actual_moves():
    snap = make_snapshot()
    res = sc.historical_replay(snap, "covid_2020")
    start, end = pd.Timestamp("2020-02-19"), pd.Timestamp("2020-03-23")
    p = snap.prices["AAA"]
    expected = p[p.index <= end].iloc[-1] / p[p.index <= start].iloc[-1] - 1
    assert rows(res)["AAA"]["move_pct"] == pytest.approx(expected * 100)
    assert rows(res)["AAA"]["method"] == "actual move in that period"


def test_historical_replay_estimates_for_new_listing():
    snap = make_snapshot()
    snap.prices.loc[:"2021-01-01", "CCC"] = np.nan  # pretend CCC listed in 2021
    res = sc.historical_replay(snap, "covid_2020")
    assert "estimated" in rows(res)["CCC"]["method"]


def test_bad_inputs():
    snap = make_snapshot()
    with pytest.raises(sc.ScenarioError):
        sc.historical_replay(snap, "not_an_event")
    with pytest.raises(sc.ScenarioError):
        sc.market_shock(snap, 150)
