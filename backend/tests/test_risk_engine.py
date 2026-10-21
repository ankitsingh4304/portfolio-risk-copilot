"""Risk math checked against values worked out by hand."""
import numpy as np
import pandas as pd
import pytest

from app.services import risk_engine as re_

DAYS = pd.bdate_range("2025-01-01", periods=300)


def test_daily_returns():
    p = pd.Series([100, 110, 99], index=DAYS[:3])
    r = re_.daily_returns(p)
    assert r.tolist() == pytest.approx([0.10, -0.10])


def test_annualized_volatility_matches_formula():
    r = pd.Series([0.01, -0.01] * 50)
    expected = np.std([0.01, -0.01] * 50, ddof=1) * np.sqrt(252)
    assert re_.annualized_volatility(r) == pytest.approx(expected)


def test_annualized_return_compounds():
    r = pd.Series([0.001] * 252)
    assert re_.annualized_return(r) == pytest.approx(1.001**252 - 1)


def test_drawdown_peak_trough_recovery():
    # 100 -> 120 (peak) -> 60 (trough, -50%) -> 90 -> 130 (recovered)
    prices = pd.Series([100, 120, 60, 90, 130], index=DAYS[:5])
    dd = re_.drawdown(re_.daily_returns(prices))
    assert dd.max_drawdown == pytest.approx(-0.5)
    assert dd.peak_date == DAYS[1].date().isoformat()
    assert dd.trough_date == DAYS[2].date().isoformat()
    assert dd.recovery_date == DAYS[4].date().isoformat()
    assert dd.current_drawdown == pytest.approx(0.0)


def test_drawdown_not_recovered():
    prices = pd.Series([100, 120, 60, 90], index=DAYS[:4])
    dd = re_.drawdown(re_.daily_returns(prices))
    assert dd.recovery_date is None
    assert dd.current_drawdown == pytest.approx(90 / 120 - 1)


def test_drawdown_only_rising():
    prices = pd.Series([100, 101, 102], index=DAYS[:3])
    assert re_.drawdown(re_.daily_returns(prices)).max_drawdown == 0.0


def test_value_at_risk_and_expected_shortfall():
    # Returns -1%, -2%, ... -100%?  Use -0.001 * k for k = 1..100 shuffled with gains.
    losses = [-0.001 * k for k in range(1, 21)]  # 20 losing days: -0.1% ... -2.0%
    gains = [0.005] * 80
    r = pd.Series(losses + gains)
    var, cvar = re_.value_at_risk(r, 0.95)
    cutoff = np.percentile(r, 5)
    assert var == pytest.approx(-cutoff)
    assert cvar == pytest.approx(-r[r <= cutoff].mean())
    assert cvar >= var  # the average of the worst days is at least as bad as the cutoff


def test_beta_exact():
    rng = np.random.default_rng(0)
    m = pd.Series(rng.normal(0, 0.01, 200), index=DAYS[:200])
    assert re_.beta(2 * m, m) == pytest.approx(2.0)
    assert re_.beta(0.5 * m + 0.001, m) == pytest.approx(0.5)


def test_beta_needs_enough_data():
    m = pd.Series([0.01, -0.01] * 5, index=DAYS[:10])
    assert re_.beta(m, m) is None


def test_concentration():
    w = pd.Series({"A": 0.5, "B": 0.3, "C": 0.2})
    sectors = pd.Series({"A": "IT", "B": "IT", "C": "Banking"})
    c = re_.concentration(w, sectors)
    assert c["top_holding"] == {"symbol": "A", "weight": 0.5}
    assert c["hhi"] == pytest.approx(0.25 + 0.09 + 0.04)
    assert c["effective_holdings"] == pytest.approx(1 / 0.38)
    assert c["sector_weights"] == pytest.approx({"IT": 0.8, "Banking": 0.2})


def test_risk_contribution_adds_up():
    rng = np.random.default_rng(1)
    rets = pd.DataFrame(rng.normal(0, [0.01, 0.02, 0.015], (250, 3)), columns=list("ABC"))
    w = pd.Series({"A": 0.5, "B": 0.3, "C": 0.2})
    rc = re_.risk_contribution(rets, w)
    port_vol = re_.annualized_volatility(re_.portfolio_returns(rets, w))
    assert rc["risk_contribution"].sum() == pytest.approx(port_vol)
    assert rc["risk_share"].sum() == pytest.approx(1.0)


def test_risk_contribution_symmetric_case():
    # Two identical-but-independent stocks, equal weights -> equal risk shares.
    rng = np.random.default_rng(2)
    a = rng.normal(0, 0.01, 5000)
    b = rng.normal(0, 0.01, 5000)
    rc = re_.risk_contribution(pd.DataFrame({"A": a, "B": b}), pd.Series({"A": 0.5, "B": 0.5}))
    assert rc.loc["A", "risk_share"] == pytest.approx(0.5, abs=0.03)


def test_volatile_small_holding_can_dominate_risk():
    rng = np.random.default_rng(3)
    rets = pd.DataFrame({"SAFE": rng.normal(0, 0.003, 500), "WILD": rng.normal(0, 0.04, 500)})
    rc = re_.risk_contribution(rets, pd.Series({"SAFE": 0.8, "WILD": 0.2}))
    assert rc.loc["WILD", "risk_share"] > 0.8  # 20% of the money, >80% of the risk


def test_top_correlated_pairs():
    rng = np.random.default_rng(4)
    a = rng.normal(0, 0.01, 300)
    df = pd.DataFrame({"A": a, "A2": a + rng.normal(0, 0.001, 300), "Z": rng.normal(0, 0.01, 300)})
    pairs = re_.top_correlated_pairs(df, 1)
    assert {pairs[0]["a"], pairs[0]["b"]} == {"A", "A2"}
    assert pairs[0]["correlation"] > 0.95


def test_diversification_ratio():
    rng = np.random.default_rng(5)
    a = rng.normal(0, 0.01, 2000)
    same = pd.DataFrame({"A": a, "B": a})
    independent = pd.DataFrame({"A": a, "B": rng.normal(0, 0.01, 2000)})
    w = pd.Series({"A": 0.5, "B": 0.5})
    assert re_.diversification_ratio(same, w) == pytest.approx(1.0)
    assert re_.diversification_ratio(independent, w) == pytest.approx(np.sqrt(2), abs=0.08)


def test_sharpe_ratio():
    r = pd.Series([0.002, -0.001] * 126)
    expected = (re_.annualized_return(r) - 0.05) / re_.annualized_volatility(r)
    assert re_.sharpe_ratio(r, 0.05) == pytest.approx(expected)
