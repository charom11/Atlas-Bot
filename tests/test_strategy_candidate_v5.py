import numpy as np
import pandas as pd
import pytest

from strategy_candidate_v5 import (
    LONG, SHORT, FLAT, EXIT,
    MAX_LEVERAGE, MAX_HOLD_BARS,
    _atr, generate_strategy_signal, structure_stop, adaptive_pullback_limit,
    choose_leverage, risk_based_notional, trailing_stop, manage_position,
    calculate_drawdown_multiplier, calculate_expected_net_r,
    select_and_rank_assets, backtest_frame
)


def make_ohlcv(n: int = 260, trend: float = 0.0005, vol: float = 0.003) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    rets = trend + rng.normal(0, vol, n)
    close = 100 * np.exp(np.cumsum(rets))
    high = close * (1 + rng.uniform(0.0005, 0.003, n))
    low = close * (1 - rng.uniform(0.0005, 0.003, n))
    open_ = close * (1 + rng.normal(0, 0.0005, n))
    volume = rng.integers(1000, 5000, n).astype(float)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})


def test_invalid_data_flat():
    assert generate_strategy_signal(pd.DataFrame({"close": [1, 2, 3]}))["signal"] == FLAT


def test_adaptive_pullback_limits():
    assert adaptive_pullback_limit("BULL_TREND", 0.70, 0) == 0.60
    assert adaptive_pullback_limit("BULL_TREND", 0.80, 0) == 0.90
    assert adaptive_pullback_limit("BULL_TREND", 0.80, 1) == 1.20


def test_structure_stop_correct_side():
    d = make_ohlcv()
    p = float(d.close.iloc[-1])
    a = float(_atr(d).iloc[-1])
    assert structure_stop(d, LONG, a) < p
    assert structure_stop(d, SHORT, a) > p


def test_leverage_volatility_aware_and_clamped():
    # Low volatility -> clamped to MAX_LEVERAGE = 75.0
    assert choose_leverage(0.0001, target_risk_pct=0.035, stop_atr=2.0) == 75.0
    # High volatility -> lower leverage
    lev_high_vol = choose_leverage(0.05, target_risk_pct=0.035, stop_atr=2.0)
    assert lev_high_vol < 10.0
    assert lev_high_vol >= 1.0


def test_risk_based_notional_respects_limits():
    # Equity = $1000, risk = 0.35% ($3.50), stop distance = 2% -> notional = $175
    n = risk_based_notional(1000.0, 0.0035, 100.0, 98.0, max_leverage=75.0, max_notional_pct=0.30)
    assert abs(n - 175.0) < 1e-6

    # When risk requests huge notional, capped by max_notional_pct (30% of $1000 = $300)
    n_cap = risk_based_notional(1000.0, 0.10, 100.0, 99.9, max_leverage=75.0, max_notional_pct=0.30)
    assert n_cap == 300.0


def test_trailing_stop_monotonic():
    assert trailing_stop(100.0, 95.0, 110.0, LONG, 2.0, 2.0, 106.0, 104.0) >= 95.0
    assert trailing_stop(100.0, 105.0, 90.0, SHORT, 2.0, 2.0, 94.0, 96.0) <= 105.0


def test_manage_position_early_momentum_exit():
    x = manage_position(LONG, 100.0, 95.0, 110.0, 20, 1.5, 0.0, 2.0, initial_stop=95.0)
    assert x["action"] == EXIT and "deterioration" in x["reason"]


def test_manage_position_giveback_with_initial_stop():
    # When trailed stop is at breakeven (100.0), initial_stop (95.0) prevents division-by-zero!
    x = manage_position(LONG, 100.0, 100.0, 110.0, 20, 0.8, 0.4, 2.0, initial_stop=95.0)
    assert x["action"] == EXIT and "giveback" in x["reason"]

    # When not reached 1.5R peak, does NOT falsely trigger giveback
    x2 = manage_position(LONG, 100.0, 100.0, 102.0, 20, 0.2, 0.4, 2.0, initial_stop=95.0)
    assert x2["action"] == LONG and "runner" in x2["reason"]


def test_duration_exit():
    x = manage_position(LONG, 100.0, 95.0, 100.0, MAX_HOLD_BARS, 0.2, 0.5, 2.0, initial_stop=95.0)
    assert x["action"] == EXIT and "maximum duration" in x["reason"]


def test_drawdown_throttle_multipliers():
    assert calculate_drawdown_multiplier(0.02) == 1.00
    assert calculate_drawdown_multiplier(0.07) == 0.75
    assert calculate_drawdown_multiplier(0.12) == 0.50
    assert calculate_drawdown_multiplier(0.17) == 0.25
    assert calculate_drawdown_multiplier(0.22) == 0.00


def test_cost_aware_net_r_filtering():
    # If move is 0.5% and friction is 0.4% with 2% stop, net R is (0.5 - 0.4)/2 = 0.05R < 0.20R threshold
    net_r = calculate_expected_net_r(100.0, 98.0, 0.005, 0.004, turnover_penalty_r=0.0)
    assert net_r == pytest.approx(0.05, abs=1e-3)
    assert net_r < 0.20


def test_btc_macro_regime_filtering():
    d = make_ohlcv()
    # When BTC is strong bear (-0.7), altcoin long is restricted
    sig = generate_strategy_signal(d, btc_score=-0.70)
    if sig["score"] > 0:
        assert sig["signal"] == FLAT
        assert any("btc strong bear restricts" in r for r in sig["reasons"])


def test_asset_selection_training_only():
    metrics = {
        "SOL": {"trades": 100, "expectancy": 2.5, "profit_factor": 1.45, "win_rate": 42.0, "stability": 0.85, "max_dd": 0.15, "turnover": 0.3},
        "ADA": {"trades": 90, "expectancy": 1.8, "profit_factor": 1.25, "win_rate": 38.0, "stability": 0.75, "max_dd": 0.20, "turnover": 0.4},
        "LOSER": {"trades": 80, "expectancy": -0.5, "profit_factor": 0.85, "win_rate": 28.0, "stability": 0.40, "max_dd": 0.45, "turnover": 0.5},
        "LOW_TRADES": {"trades": 10, "expectancy": 5.0, "profit_factor": 2.00, "win_rate": 50.0, "stability": 0.90, "max_dd": 0.10, "turnover": 0.1},
    }
    ranked = select_and_rank_assets(metrics, min_trades=30, min_expectancy=0.0, min_profit_factor=1.05)
    syms = ranked["symbol"].tolist()
    assert "SOL" in syms and "ADA" in syms
    assert "LOSER" not in syms       # Negative expectancy / low PF filtered out
    assert "LOW_TRADES" not in syms  # Insufficient sample size filtered out
    assert ranked.iloc[0]["symbol"] == "SOL"  # Top rank


def test_backtest_frame_execution_shifted():
    d = make_ohlcv(n=250)
    res = backtest_frame(d, fast=True)
    assert "execution_signal" in res.columns
    assert res["execution_signal"].iloc[0] == FLAT
    assert (res["execution_signal"].iloc[1:].values == res["signal"].iloc[:-1].values).all()


def test_vectorized_equivalence():
    d = make_ohlcv(n=240)
    fast_res = backtest_frame(d, fast=True)
    slow_res = backtest_frame(d, fast=False)
    assert (fast_res["signal"].values == slow_res["signal"].values).all()
    assert (fast_res["execution_signal"].values == slow_res["execution_signal"].values).all()
    assert np.allclose(fast_res["score"].values, slow_res["score"].values, atol=1e-5)
