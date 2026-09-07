import numpy as np
import pandas as pd

from strategy_candidate_v8 import (
    LONG, SHORT, FLAT, AssetMetrics, ChannelEvidence,
    MAX_LEVERAGE, MAX_PORTFOLIO_RISK, MAX_POSITIONS,
    asset_quality_score, backtest_frame, channel_meta_score,
    choose_leverage, classify_market_regime, correlation_discount,
    cost_budget_pct, drawdown_risk_multiplier, expected_net_r,
    portfolio_gate, rank_assets, risk_based_notional,
)


def test_market_regime_states():
    assert classify_market_regime(0.7, 0.5, 0.02) == "RISK_ON"
    assert classify_market_regime(-0.7, -0.6, 0.02) == "BREAKDOWN"
    assert classify_market_regime(0.0, 0.0, 0.05) == "EXTREME_VOL"


def test_channel_meta_score_combines_and_preserves_direction():
    score, side = channel_meta_score([
        ChannelEvidence("FIBONACCI", LONG, 0.9),
        ChannelEvidence("MSS_SHIFT", LONG, 0.8),
        ChannelEvidence("DIVERGENCE", SHORT, 0.2),
    ])
    assert score > 0.4
    assert side == LONG


def test_unavailable_channel_does_not_vote():
    score, side = channel_meta_score([ChannelEvidence("MSS_SHIFT", LONG, 1.0, available=False)])
    assert score == 0.0 and side == FLAT


def test_asset_admission_rejects_weak_history():
    weak = AssetMetrics("BAD", -0.01, 0.9, 100, 0.10)
    good = AssetMetrics("GOOD", 0.08, 1.2, 100, 0.08, stability_score=0.8)
    ranked = rank_assets([weak, good])
    assert [x[0] for x in ranked] == ["GOOD"]
    assert asset_quality_score(good) > 0


def test_turnover_penalty_reduces_expected_net_r():
    base = expected_net_r(100, 95, 0.03, 0.001)
    penalized = expected_net_r(100, 95, 0.03, 0.001, turnover_penalty_r=0.2)
    assert penalized < base


def test_cost_budget_stress_increases_cost():
    assert cost_budget_pct(multiplier=2.0) > cost_budget_pct(multiplier=1.0)


def test_correlation_discount_reduces_exposure():
    corr = pd.DataFrame([[1.0, 0.8], [0.8, 1.0]], index=["SOL", "AVAX"], columns=["SOL", "AVAX"])
    assert correlation_discount("AVAX", ["SOL"], corr) < 1.0


def test_drawdown_throttle_steps():
    assert drawdown_risk_multiplier(0.02) == 1.0
    assert drawdown_risk_multiplier(0.07) == 0.75
    assert drawdown_risk_multiplier(0.12) == 0.50
    assert drawdown_risk_multiplier(0.17) == 0.25
    assert drawdown_risk_multiplier(0.20) == 0.0


def test_risk_sizing_and_leverage_are_capped():
    notional = risk_based_notional(1000, 0.001, max_leverage=MAX_LEVERAGE)
    assert notional <= 1000 * MAX_LEVERAGE
    assert choose_leverage(0.00001) <= MAX_LEVERAGE


def test_portfolio_guards_fail_closed():
    args = dict(action=LONG, equity=1000, current_risk=0.0, open_positions=0,
                same_direction=0, daily_loss=0.03, weekly_loss=0.0, drawdown=0.0,
                selected=[], symbol="SOL")
    ok, reason = portfolio_gate(**args)
    assert not ok and reason == "DAILY_LOSS_GUARD"
    args["daily_loss"] = 0.0
    args["current_risk"] = MAX_PORTFOLIO_RISK
    ok, reason = portfolio_gate(**args)
    assert not ok and reason == "PORTFOLIO_RISK"


def test_position_and_direction_caps():
    args = dict(action=LONG, equity=1000, current_risk=0.0, open_positions=MAX_POSITIONS,
                same_direction=0, daily_loss=0.0, weekly_loss=0.0, drawdown=0.0,
                selected=[], symbol="SOL")
    ok, reason = portfolio_gate(**args)
    assert not ok and reason == "MAX_POSITIONS"
    args["open_positions"] = 0
    args["same_direction"] = 10
    ok, reason = portfolio_gate(**args)
    assert not ok and reason == "MAX_DIRECTION"


def test_backtest_execution_is_next_bar():
    df = pd.DataFrame({"signal": [LONG, SHORT, FLAT]})
    out = backtest_frame(df)
    assert out["execution_signal"].tolist() == [FLAT, LONG, SHORT]


def test_nan_regime_fails_closed():
    assert classify_market_regime(float("nan"), 0.2, 0.02) == "UNAVAILABLE"


def test_cost_filter_can_turn_trade_flat():
    from strategy_candidate_v8 import decide
    asset = AssetMetrics("SOL", 0.05, 1.2, 100, 0.08, stability_score=0.8)
    evidence = [ChannelEvidence("FIBONACCI", LONG, 0.95), ChannelEvidence("5MA_CONSENSUS", LONG, 0.9)]
    decision = decide(evidence, asset, breadth=0.7, btc_trend=0.6, volatility=0.02,
                      entry=100, stop=99, expected_move_pct=0.001, equity=1000)
    assert decision.action == FLAT


def test_resample_to_1h():
    from strategy_candidate_v8 import resample_to_1h
    times = pd.date_range("2024-01-01 00:00:00", periods=8, freq="15min")
    df = pd.DataFrame({
        "open_time": times,
        "open": [10.0, 10.5, 11.0, 10.8, 11.2, 11.5, 11.0, 10.9],
        "high": [10.8, 11.2, 11.5, 11.0, 11.6, 11.8, 11.3, 11.1],
        "low": [9.9, 10.3, 10.8, 10.6, 11.0, 11.1, 10.8, 10.5],
        "close": [10.5, 11.0, 10.8, 11.2, 11.5, 11.2, 10.9, 11.0],
        "volume": [100.0] * 8,
    })
    h1 = resample_to_1h(df)
    assert len(h1) == 2
    assert h1["open"].iloc[0] == 10.0
    assert h1["high"].iloc[0] == 11.5
    assert h1["low"].iloc[0] == 9.9
    assert h1["close"].iloc[0] == 11.2
    assert h1["volume"].iloc[0] == 400.0


def test_precompute_v8_channel_signals():
    from strategy_candidate_v8 import precompute_v8_channel_signals
    times = pd.date_range("2024-01-01", periods=100, freq="1h")
    trend = np.linspace(100, 150, 100) + np.sin(np.linspace(0, 10, 100)) * 5
    df = pd.DataFrame({
        "open_time": times,
        "open": trend - 0.5,
        "high": trend + 1.0,
        "low": trend - 1.0,
        "close": trend,
        "volume": np.full(100, 1000.0),
    })
    ch = precompute_v8_channel_signals(df)
    for key in ("fib_side", "mss_side", "ma_side", "sr_side", "div_side", "atr_pct", "close"):
        assert key in ch
        assert len(ch[key]) == 100


def test_simulate_v8_portfolio_synthetic():
    from strategy_candidate_v8 import (
        precompute_v8_channel_signals, simulate_v8_portfolio, AssetMetrics
    )
    times = pd.date_range("2024-01-01", periods=80, freq="1h")
    trend1 = np.linspace(100, 130, 80)
    trend2 = np.linspace(50, 65, 80)
    df1 = pd.DataFrame({"open_time": times, "open": trend1-0.2, "high": trend1+0.5, "low": trend1-0.5, "close": trend1, "volume": 1000.0})
    df2 = pd.DataFrame({"open_time": times, "open": trend2-0.2, "high": trend2+0.5, "low": trend2-0.5, "close": trend2, "volume": 1000.0})
    data_map = {"SOL": df1, "AVAX": df2}
    channel_map = {"SOL": precompute_v8_channel_signals(df1), "AVAX": precompute_v8_channel_signals(df2)}
    timeline = list(times)
    metrics_map = {
        "SOL": AssetMetrics("SOL", 0.08, 1.25, 50, 0.08, stability_score=0.8),
        "AVAX": AssetMetrics("AVAX", 0.06, 1.15, 45, 0.10, stability_score=0.75),
    }

    res = simulate_v8_portfolio(
        data_map=data_map,
        channel_map=channel_map,
        timeline=timeline,
        target_symbols=["SOL", "AVAX"],
        asset_metrics_map=metrics_map,
        initial_balance=1000.0,
        mode="V8",
    )
    assert "balance" in res
    assert "max_drawdown" in res
    assert "closed_trades" in res
    assert res["balance"] > 0


def test_compile_partition_stats():
    from strategy_candidate_v8 import compile_partition_stats
    trades = [
        {"win": True, "net_pnl": 15.0, "r_multiple": 1.5},
        {"win": False, "net_pnl": -10.0, "r_multiple": -1.0},
        {"win": True, "net_pnl": 20.0, "r_multiple": 2.0},
    ]
    st = compile_partition_stats(trades, "TEST")
    assert st["trades"] == 3
    assert abs(st["win_rate"] - 66.666) < 0.1
    assert st["pnl"] == 25.0
    assert st["pf"] == 3.5

