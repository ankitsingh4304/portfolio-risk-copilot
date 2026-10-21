"""Time-series and probability models, checked against known answers."""
import math

import numpy as np
import pandas as pd
import pytest

from app.services import quant

DAYS = pd.bdate_range("2021-01-01", periods=900)


def test_ewma_follows_the_riskmetrics_formula():
    r = pd.Series([0.01, -0.02, 0.015, 0.0, 0.03] * 10, index=DAYS[:50])
    ewma = quant.ewma_volatility(r, seed_days=5)
    var = np.var(r.iloc[:5], ddof=1)
    for x in r.iloc[5:]:
        var = 0.94 * var + 0.06 * x**2
    assert ewma.iloc[-1] == pytest.approx(math.sqrt(var * 252))


def test_ewma_reacts_to_a_volatility_jump():
    rng = np.random.default_rng(0)
    calm = rng.normal(0, 0.005, 400)
    wild = rng.normal(0, 0.03, 40)
    ewma = quant.ewma_volatility(pd.Series(np.r_[calm, wild], index=DAYS[:440]))
    sig = quant.volatility_signal(ewma)
    assert sig["level"] == "high" and sig["ratio"] > 2


def test_monte_carlo_matches_normal_theory():
    # With no trend and today's daily volatility v, a 21-day return is about normal
    # with standard deviation v x sqrt(21). So the 1-in-20 bad month is about -1.645 x that.
    rng = np.random.default_rng(1)
    r = pd.Series(rng.normal(0, 0.01, 800), index=DAYS[:800])
    mc = quant.monte_carlo_month(r, n_paths=20_000)
    v_now = quant.ewma_volatility(r).iloc[-1] / math.sqrt(252)
    sd = v_now * math.sqrt(21)
    assert mc["bad_month"] == pytest.approx(-1.645 * sd, abs=0.01)
    assert mc["typical_month"] == pytest.approx(0, abs=0.006)
    assert mc["prob_loss"] == pytest.approx(0.5, abs=0.04)
    assert mc["bad_month"] < mc["typical_month"] < mc["good_month"]
    assert sum(b["count"] for b in mc["histogram"]) == 20_000


def test_monte_carlo_scales_with_volatility():
    rng = np.random.default_rng(5)
    base = rng.normal(0, 0.01, 600)
    calm = quant.monte_carlo_month(pd.Series(base, index=DAYS[:600]))
    wild = quant.monte_carlo_month(pd.Series(base * 2, index=DAYS[:600]))
    assert wild["bad_month"] == pytest.approx(2 * calm["bad_month"], rel=0.1)


def test_monte_carlo_is_repeatable():
    rng = np.random.default_rng(2)
    r = pd.Series(rng.normal(0, 0.01, 500), index=DAYS[:500])
    assert quant.monte_carlo_month(r) == quant.monte_carlo_month(r)


def test_kupiec():
    assert quant.kupiec_pof(12, 250) > 0.8     # 12 vs 12.5 expected: fine
    assert quant.kupiec_pof(30, 250) < 0.001   # far too many breaches
    assert quant.kupiec_pof(0, 250) < 0.001    # zero breaches is also suspicious
    # Worked by hand: x=20, n=250, p=0.05 -> LR = 4.04, p-value = erfc(sqrt(4.04/2)) = 0.044
    assert quant.kupiec_pof(20, 250) == pytest.approx(0.0444, abs=0.0005)


def test_var_backtest_on_well_behaved_data_usually_passes():
    # A correct model still "fails" about 5% of the time by bad luck, so check many runs.
    passes = 0
    for seed in range(20):
        rng = np.random.default_rng(seed)
        bt = quant.var_backtest(pd.Series(rng.normal(0, 0.01, 800), index=DAYS[:800]))
        assert bt["days_tested"] == 250
        passes += bt["passed"]
    assert passes >= 16


def test_var_backtest_catches_a_regime_change():
    rng = np.random.default_rng(4)
    r = pd.Series(np.r_[rng.normal(0, 0.005, 500), rng.normal(0, 0.02, 250)], index=DAYS[:750])
    bt = quant.var_backtest(r)
    assert bt["breaches"] > 25 and not bt["passed"]  # VaR from a calm period underestimates


def test_not_enough_data():
    r = pd.Series([0.01] * 50, index=DAYS[:50])
    assert quant.var_backtest(r) is None
    assert quant.monte_carlo_month(r) is None
