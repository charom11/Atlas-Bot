from strategy_candidate_v9_2 import bootstrap_mean_ci, capacity_buckets, equity_stats, leave_one_out, stress_costs, validation_gate


def test_stress_costs_reduces_net():
    result = stress_costs(100, 10, 60, 50, 20)
    assert [round(x.net_r, 2) for x in result] == [90.0, 87.5, 85.0, 80.0]


def test_leave_one_out():
    result = leave_one_out(100.0, 25.0)
    assert result.remaining_net_r == 75.0
    assert result.retained_fraction == 0.75


def test_subset_net_r():
    from strategy_candidate_v9_2 import subset_net_r
    assert subset_net_r(100, [20, 5]) == 75.0


def test_equity_stats_and_loss_streak():
    stats = equity_stats([1, -1, -2, -3, 2])
    assert stats["net_r"] == -3.0
    assert stats["max_drawdown_r"] == 6.0
    assert stats["max_consecutive_losses"] == 3


def test_bootstrap_is_deterministic():
    a = bootstrap_mean_ci([1, -1, 2, -2, 3], samples=200)
    b = bootstrap_mean_ci([1, -1, 2, -2, 3], samples=200)
    assert a == b
    assert a[1] <= a[0] <= a[2]


def test_capacity_buckets():
    result = capacity_buckets([4, 10, 11, 25])
    assert result[5.0] == 0.75
    assert result[10.0] == 0.5
    assert result[20.0] == 0.25


def test_validation_gate_passes_only_explicit_checks():
    result = validation_gate({"oos_pf": 1.04, "oos_net_r": 20, "max_drawdown_r": 50}, max_dd_r=60)
    assert result["pass"] is True
    failed = validation_gate({"oos_pf": 0.99, "oos_net_r": 20, "max_drawdown_r": 50})
    assert failed["pass"] is False


def test_validation_rejects_missing_oos_metrics():
    result = validation_gate({})
    assert result["pass"] is False


def test_invalid_inputs():
    import pytest
    with pytest.raises(ValueError):
        stress_costs(10, -1, 2, 3, 1)
    with pytest.raises(ValueError):
        bootstrap_mean_ci([], samples=200)
    with pytest.raises(ValueError):
        bootstrap_mean_ci([1], samples=10)
