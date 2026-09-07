import numpy as np
import pandas as pd
import pytest

from strategy_candidate_v9 import (
    LONG, SHORT, FLAT, SETUPS,
    add_indicators, allowed_setups, classify_regime,
    setup_votes, opportunity_score, generate_signals,
    backtest_frame, summarize, load_ohlcv_csv,
)


def make_frame(n=320, trend=0.0004, symbol="TESTUSDT"):
    idx = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    base = 100 * np.exp(np.arange(n) * trend)
    wiggle = 0.25 * np.sin(np.arange(n) / 5.0)
    close = base + wiggle
    open_ = close - 0.05
    high = close + 0.35
    low = close - 0.35
    volume = np.full(n, 1000.0)
    return pd.DataFrame({
        "open": open_, "high": high, "low": low,
        "close": close, "volume": volume, "symbol": symbol,
    }, index=idx)


def test_indicator_builder_requires_ohlcv():
    with pytest.raises(ValueError):
        add_indicators(pd.DataFrame({"close": [1, 2, 3]}))


def test_indicator_builder_is_deterministic():
    df = make_frame()
    a = add_indicators(df)
    b = add_indicators(df)
    pd.testing.assert_frame_equal(a, b)


def test_indicator_columns_exist():
    out = add_indicators(make_frame())
    for col in ("ema9", "ema20", "ema50", "ema100", "ema200", "atr", "rsi", "vwap", "bb_upper", "bb_lower", "atr_ratio"):
        assert col in out.columns


def test_regime_is_known():
    out = add_indicators(make_frame())
    regimes = {classify_regime(row) for _, row in out.iloc[220:].iterrows()}
    assert regimes <= {"STRONG_TREND", "MILD_TREND", "RANGE", "HIGH_VOL", "BREAKDOWN", "CHOP"}


def test_chop_disables_all_setups():
    assert allowed_setups("CHOP") == set()


def test_regime_setup_matrix_contains_vwap_dual_mode():
    assert "VWAP_TREND" in allowed_setups("STRONG_TREND")
    assert "VWAP_REVERSION" in allowed_setups("RANGE")
    assert "VWAP_REVERSION" not in allowed_setups("STRONG_TREND")


def test_setup_names_are_unique():
    assert len(SETUPS) == len(set(SETUPS)) == 10


def test_side_constants_are_distinct():
    assert {LONG, SHORT, FLAT} == {1, -1, 0}


def test_votes_are_bounded_to_known_setups_and_sides():
    out = add_indicators(make_frame())
    row = out.iloc[-1]
    row = row.copy()
    row["regime"] = "MILD_TREND"
    votes = setup_votes(row, out.iloc[-2])
    assert set(votes) == set(SETUPS)
    assert set(votes.values()) <= {LONG, SHORT, FLAT}


def test_invalid_atr_cannot_score():
    out = add_indicators(make_frame())
    row = out.iloc[-1].copy()
    row["atr"] = 0.0
    row["regime"] = "STRONG_TREND"
    votes = {s: LONG for s in SETUPS}
    score, confirmations = opportunity_score(row, votes, "TREND_CONTINUATION")
    assert score == 0
    assert confirmations == 0


def test_score_requires_allowed_setup():
    out = add_indicators(make_frame())
    row = out.iloc[-1].copy()
    row["regime"] = "CHOP"
    votes = {s: LONG for s in SETUPS}
    assert opportunity_score(row, votes, "VWAP_REVERSION")[0] == 0


def test_generate_signals_returns_valid_trade_geometry():
    out = make_frame(trend=0.001)
    signals = generate_signals(out, min_score=4, min_confirmations=1)
    for s in signals:
        assert s.side in (LONG, SHORT)
        assert s.setup in SETUPS
        assert s.score >= 4
        assert s.atr > 0
        if s.side == LONG:
            assert s.stop < s.entry < s.target
        else:
            assert s.target < s.entry < s.stop


def test_backtest_is_repeatable():
    df = make_frame(trend=0.0008)
    a = backtest_frame(df, min_score=4, friction_r=0.026)
    b = backtest_frame(df, min_score=4, friction_r=0.026)
    assert a == b


def test_backtest_applies_friction():
    df = make_frame(trend=0.001)
    no_cost = backtest_frame(df, min_score=4, friction_r=0.0)
    with_cost = backtest_frame(df, min_score=4, friction_r=0.10)
    assert len(no_cost) == len(with_cost)
    if no_cost:
        assert sum(t.r_multiple for t in with_cost) < sum(t.r_multiple for t in no_cost)


def test_backtest_uses_next_bar_open():
    df = make_frame(trend=0.001)
    trades = backtest_frame(df, min_score=4, friction_r=0.0)
    if trades:
        first = trades[0]
        assert first.entry in set(df["open"].iloc[202:].round(10))


def test_summary_empty_is_safe():
    stats = summarize([])
    assert stats.trades == 0
    assert stats.profit_factor == 0.0
    assert stats.max_drawdown_r == 0.0


def test_summary_drawdown_nonnegative():
    df = make_frame(trend=0.001)
    stats = summarize(backtest_frame(df, min_score=4))
    assert stats.max_drawdown_r >= 0


def test_load_ohlcv_csv_accepts_timestamp(tmp_path):
    p = tmp_path / "bars.csv"
    make_frame(10).reset_index(names="timestamp").to_csv(p, index=False)
    out = load_ohlcv_csv(p)
    assert len(out) == 10
    assert out.index.tz is not None


def test_load_ohlcv_csv_rejects_missing_time_column(tmp_path):
    p = tmp_path / "bad.csv"
    pd.DataFrame({"open": [1], "high": [1], "low": [1], "close": [1], "volume": [1]}).to_csv(p, index=False)
    with pytest.raises(ValueError):
        load_ohlcv_csv(p)


def test_vwap_reversion_is_not_global_trend_signal():
    out = add_indicators(make_frame())
    row = out.iloc[-1].copy()
    row["regime"] = "STRONG_TREND"
    row["vwap_dist_atr"] = 2.0
    row["rsi"] = 80
    votes = setup_votes(row, out.iloc[-2])
    assert votes["VWAP_REVERSION"] == FLAT


def test_vwap_trend_requires_trend_regime():
    out = add_indicators(make_frame())
    row = out.iloc[-1].copy()
    row["regime"] = "RANGE"
    row["vwap_dist_atr"] = 0.0
    row["ema20"] = 110.0
    row["ema50"] = 105.0
    row["ema100"] = 102.0
    row["ema200"] = 100.0
    votes = setup_votes(row, out.iloc[-2])
    assert votes["VWAP_TREND"] == FLAT


def test_extreme_volatility_can_activate_expansion():
    out = add_indicators(make_frame())
    row = out.iloc[-1].copy()
    row["regime"] = "HIGH_VOL"
    row["atr_ratio"] = 2.0
    row["vol_ratio"] = 2.0
    row["close"] = row["bb_upper"] + row["atr"]
    votes = setup_votes(row, out.iloc[-2])
    assert votes["BB_ATR_EXPANSION"] == LONG
