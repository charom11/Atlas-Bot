import numpy as np
import pandas as pd
import pytest

from strategy_candidate_v6 import (
    LONG, SHORT, FLAT, EXIT,
    MAX_LEVERAGE,
    _atr, resample_ohlcv_to_1h, generate_strategy_signal, structure_stop,
    adaptive_pullback_limit, choose_leverage, risk_based_notional,
    trailing_stop, manage_position, calculate_drawdown_multiplier,
    calculate_cost_budget, calculate_expected_net_r, backtest_frame,
    compile_partition_stats
)


def make_ohlcv_15m(n: int = 1000, trend: float = 0.0002, vol: float = 0.002) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    rets = trend + rng.normal(0, vol, n)
    close = 100 * np.exp(np.cumsum(rets))
    high = close * (1 + rng.uniform(0.0002, 0.002, n))
    low = close * (1 - rng.uniform(0.0002, 0.002, n))
    open_ = close * (1 + rng.normal(0, 0.0002, n))
    volume = rng.integers(1000, 5000, n).astype(float)
    dates = pd.date_range("2023-01-01", periods=n, freq="15min")
    return pd.DataFrame({"open_time": dates, "open": open_, "high": high, "low": low, "close": close, "volume": volume})


def test_resample_ohlcv_to_1h():
    df_15m = make_ohlcv_15m(n=40)  # 40 15m bars = 10 1h bars
    df_1h = resample_ohlcv_to_1h(df_15m)
    assert len(df_1h) == 10
    # First 1h bar should aggregate first 4 15m bars
    assert df_1h["open"].iloc[0] == df_15m["open"].iloc[0]
    assert df_1h["close"].iloc[0] == df_15m["close"].iloc[3]
    assert df_1h["high"].iloc[0] == df_15m["high"].iloc[:4].max()
    assert df_1h["low"].iloc[0] == df_15m["low"].iloc[:4].min()
    assert df_1h["volume"].iloc[0] == df_15m["volume"].iloc[:4].sum()


def test_invalid_data_flat():
    assert generate_strategy_signal(pd.DataFrame({"close": [1, 2, 3]}))["signal"] == FLAT


def test_adaptive_pullback_limits():
    assert adaptive_pullback_limit("BULL_TREND", 0.70, 0) == 0.60
    assert adaptive_pullback_limit("BULL_TREND", 0.80, 0) == 0.90
    assert adaptive_pullback_limit("BULL_TREND", 0.80, 1) == 1.20


def test_structure_stop_correct_side():
    d = make_ohlcv_15m(n=300)
    p = float(d.close.iloc[-1])
    a = float(_atr(d).iloc[-1])
    assert structure_stop(d, LONG, a) < p
    assert structure_stop(d, SHORT, a) > p


def test_leverage_volatility_aware_and_clamped():
    assert choose_leverage(0.0001, target_risk_pct=0.035, stop_atr=2.0) == 75.0
    lev_high_vol = choose_leverage(0.05, target_risk_pct=0.035, stop_atr=2.0)
    assert lev_high_vol < 10.0
    assert lev_high_vol >= 1.0


def test_risk_based_notional_respects_limits():
    n = risk_based_notional(1000.0, 0.0035, 100.0, 98.0, max_leverage=75.0, max_notional_pct=0.30)
    assert abs(n - 175.0) < 1e-6
    n_cap = risk_based_notional(1000.0, 0.10, 100.0, 99.9, max_leverage=75.0, max_notional_pct=0.30)
    assert n_cap == 300.0


def test_cost_aware_net_r_filtering():
    net_r = calculate_expected_net_r(100.0, 98.0, 0.005, 0.004, turnover_penalty_r=0.0)
    assert net_r == pytest.approx(0.05, abs=1e-3)
    assert net_r < 0.20


def test_cost_stress_multiplier():
    cost_base = calculate_cost_budget(taker_fee_pct=0.045, slippage_pct=0.015, cost_multiplier=1.0)
    cost_stressed = calculate_cost_budget(taker_fee_pct=0.045, slippage_pct=0.015, cost_multiplier=1.5)
    assert cost_stressed > cost_base
    assert cost_stressed == pytest.approx(cost_base * 1.5, rel=0.1)


def test_manage_position_giveback_with_initial_stop():
    # Trailed stop at breakeven (100.0) does not cause division-by-zero because initial_stop (95.0) is used
    x = manage_position(LONG, 100.0, 100.0, 110.0, 20, 0.8, 0.4, 2.0, initial_stop=95.0)
    assert x["action"] == EXIT and "giveback" in x["reason"]


def test_drawdown_throttle_multipliers():
    assert calculate_drawdown_multiplier(0.02) == 1.00
    assert calculate_drawdown_multiplier(0.07) == 0.75
    assert calculate_drawdown_multiplier(0.12) == 0.50
    assert calculate_drawdown_multiplier(0.17) == 0.25
    assert calculate_drawdown_multiplier(0.22) == 0.00


def test_btc_macro_regime_filtering():
    d = make_ohlcv_15m(n=300)
    sig = generate_strategy_signal(d, btc_score=-0.70)
    if sig["score"] > 0:
        assert sig["signal"] == FLAT
        assert any("btc strong bear restricts" in r for r in sig["reasons"])


def test_backtest_frame_execution_shifted():
    d = make_ohlcv_15m(n=250)
    res = backtest_frame(d, fast=True)
    assert "execution_signal" in res.columns
    assert res["execution_signal"].iloc[0] == FLAT
    assert (res["execution_signal"].iloc[1:].values == res["signal"].iloc[:-1].values).all()


def test_vectorized_equivalence_1h():
    d_15m = make_ohlcv_15m(n=1000)
    d_1h = resample_ohlcv_to_1h(d_15m)  # 250 1h bars
    fast_res = backtest_frame(d_1h, fast=True)
    slow_res = backtest_frame(d_1h, fast=False)
    assert (fast_res["signal"].values == slow_res["signal"].values).all()
    assert (fast_res["execution_signal"].values == slow_res["execution_signal"].values).all()
    assert np.allclose(fast_res["score"].values, slow_res["score"].values, atol=1e-5)


def test_compile_partition_stats():
    trades = [
        {"win": True, "net_pnl": 10.0, "r_multiple": 2.0},
        {"win": False, "net_pnl": -5.0, "r_multiple": -1.0},
    ]
    st = compile_partition_stats(trades, "TEST")
    assert st["trades"] == 2
    assert st["win_rate"] == 50.0
    assert st["pnl"] == 5.0
    assert st["pf"] == 2.0
    assert st["avg_r"] == 0.5
