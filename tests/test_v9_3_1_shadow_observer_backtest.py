import numpy as np
import pandas as pd

from backtests.run_v9_3_1_shadow_observer_backtest import (
    ReplayConfig,
    replay_symbol,
    _dataset_path,
)
from strategy_candidate_v9_3_1 import V931Config


def _synthetic_bars(n=360):
    idx = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    base = 100.0 * np.exp(np.arange(n) * 0.0005)
    return pd.DataFrame(
        {
            "open": base - 0.05,
            "high": base + 0.35,
            "low": base - 0.35,
            "close": base,
            "volume": np.full(n, 1000.0),
            "symbol": "SOLUSDT",
        },
        index=idx,
    )


def test_shadow_replay_returns_structured_result_without_exchange_access():
    result = replay_symbol(_synthetic_bars(), "SOLUSDT", V931Config(), ReplayConfig())
    assert result.symbol == "SOLUSDT"
    assert result.bars == 360
    assert result.opportunities_evaluated == 159
    assert result.resolved == len(result.trades)
    for trade in result.trades:
        assert trade.symbol == "SOLUSDT"
        assert trade.setup in {
            "TREND_CONTINUATION",
            "BB_ATR_EXPANSION",
            "MSS_SHIFT",
            "BREAKOUT_RETEST",
        }


def test_shadow_replay_hard_excludes_tier_three_assets():
    result = replay_symbol(_synthetic_bars(), "AVAXUSDT", V931Config(), ReplayConfig())
    assert result.opportunities_evaluated == 0
    assert result.admitted == 0
    assert result.resolved == 0
    assert result.trades == []


def test_dataset_path_matches_existing_institutional_cache_convention(tmp_path):
    p4 = _dataset_path(tmp_path, "BTCUSDT", "4year")
    assert p4.name == "BTCUSDT_15m_4year_2022-09-01.csv"

    p1 = _dataset_path(tmp_path, "BTCUSDT", "1year")
    assert p1.name == "BTCUSDT_15m_from_2025-07-01.csv"

    fallback = tmp_path / "BTCUSDT_15m_from_2024-08-25.csv"
    fallback.write_text("placeholder", encoding="utf-8")
    assert _dataset_path(tmp_path, "BTCUSDT", "1year") == fallback
