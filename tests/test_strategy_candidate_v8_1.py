from strategy_candidate_v8_1 import (
    AlphaEvent,
    CHANNELS,
    evaluate_channels,
    evaluate_channel_slices,
    evaluate_combinations,
    evaluate_incremental_pairs,
    evaluate_slices,
    normalize_channels,
    rank_channels,
    recommend_gates,
    walk_forward,
)


def make_events():
    return [
        AlphaEvent("SOLUSDT", "2025-01-01T00:00:00", "RISK_ON", "LONG", 1.0, 0.05, ("5MA_CONSENSUS",)),
        AlphaEvent("SOLUSDT", "2025-01-01T01:00:00", "RISK_ON", "LONG", 0.5, 0.05, ("5MA_CONSENSUS", "MSS_SHIFT")),
        AlphaEvent("SOLUSDT", "2025-01-01T02:00:00", "RISK_OFF", "SHORT", -0.5, 0.05, ("MSS_SHIFT",)),
        AlphaEvent("XRPUSDT", "2025-01-02T00:00:00", "BREAKDOWN", "SHORT", 1.2, 0.04, ("FIBONACCI", "DIVERGENCE")),
        AlphaEvent("XRPUSDT", "2025-01-02T01:00:00", "BREAKDOWN", "SHORT", -0.2, 0.04, ("FIBONACCI", "DIVERGENCE")),
    ]


def test_normalize_channels_deduplicates_and_rejects_unknowns():
    assert normalize_channels(["5ma_consensus", "mss_shift", "5MA_CONSENSUS", "bogus"]) == ("5MA_CONSENSUS", "MSS_SHIFT")


def test_each_production_channel_is_evaluated_without_weighting():
    result = evaluate_channels(make_events())
    assert tuple(result) == CHANNELS
    assert result["5MA_CONSENSUS"].trades == 2
    assert result["5MA_CONSENSUS"].net_r == 1.5
    assert result["MSS_SHIFT"].trades == 2


def test_profit_factor_is_gross_wins_over_gross_losses():
    stats = evaluate_channels(make_events())["MSS_SHIFT"]
    assert stats.profit_factor == 1.0
    assert stats.win_rate == 0.5


def test_slice_attribution_covers_regime_asset_and_side():
    rows = evaluate_slices(make_events())
    assert {r.dimension for r in rows} == {"regime", "symbol", "side"}
    assert any(r.dimension == "symbol" and r.value == "XRPUSDT" for r in rows)


def test_channel_slice_attribution_is_explicit():
    rows = evaluate_channel_slices(make_events())
    assert any(r.dimension == "5MA_CONSENSUS:regime" and r.value == "RISK_ON" for r in rows)
    assert any(r.dimension == "FIBONACCI:symbol" and r.value == "XRPUSDT" for r in rows)


def test_pairwise_incremental_requires_sample_threshold():
    assert evaluate_incremental_pairs(make_events(), min_trades=3) == []


def test_pairwise_incremental_identifies_a_useful_confirmation():
    events = [
        AlphaEvent("SOLUSDT", f"2025-01-01T{i:02d}:00:00", "RISK_ON", "LONG", 0.1, 0.01, ("5MA_CONSENSUS",))
        for i in range(3)
    ] + [
        AlphaEvent("SOLUSDT", f"2025-01-02T{i:02d}:00:00", "RISK_ON", "LONG", 0.5, 0.01, ("5MA_CONSENSUS", "MSS_SHIFT"))
        for i in range(3)
    ]
    pairs = evaluate_incremental_pairs(events, min_trades=2)
    pair = next(x for x in pairs if x.baseline == "5MA_CONSENSUS" and x.added == "MSS_SHIFT")
    assert pair.incremental_expectancy_r > 0
    assert pair.useful


def test_combinations_only_include_sufficiently_sampled_cohorts():
    events = [
        AlphaEvent("SOLUSDT", f"2025-01-01T{i:02d}:00:00", "RISK_ON", "LONG", 0.2, 0.01, ("5MA_CONSENSUS", "MSS_SHIFT"))
        for i in range(3)
    ]
    combos = evaluate_combinations(events, max_size=3, min_trades=3)
    assert "5MA_CONSENSUS+MSS_SHIFT" in combos
    assert combos["5MA_CONSENSUS+MSS_SHIFT"].net_r == 0.6


def test_rank_channels_orders_by_expectancy_then_profit_factor():
    stats = evaluate_channels(make_events())
    ranked = rank_channels(stats, min_trades=1)
    assert ranked[0].label == "5MA_CONSENSUS"


def test_recommendation_is_research_only():
    stats = evaluate_channels(make_events())
    pairs = evaluate_incremental_pairs(make_events(), min_trades=1)
    recommendation = recommend_gates(stats, pairs, min_trades=1)
    assert "anchor_candidates" in recommendation
    assert "warning" in recommendation
    assert "main.py" in recommendation["warning"]


def test_walk_forward_uses_explicit_non_overlapping_iso_windows():
    rows = walk_forward(
        make_events(),
        [("2025", "2025-01-01/2026-01-01"), ("2026", "2026-01-01/2027-01-01")],
    )
    assert rows[0].trades == 5
    assert rows[0].net_r == 2.0
    assert rows[1].trades == 0


def test_empty_input_fails_closed_to_zero_stats():
    result = evaluate_channels([])
    assert all(v.trades == 0 and v.net_r == 0 for v in result.values())


def test_unknown_channel_is_ignored():
    event = AlphaEvent("BTCUSDT", "2025-01-01T00:00:00", "NEUTRAL", "LONG", 1.0, 0.0, ("UNKNOWN",))
    result = evaluate_channels([event])
    assert all(v.trades == 0 for v in result.values())
