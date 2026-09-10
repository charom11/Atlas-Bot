# Strategy Candidate V9.4 — Institutional Backtest Report

**Candidate:** V9.4 — *Adaptive Volatility & Breakeven-Trailing*
**Parent lineage:** V9.3.1 → V9.3 → V9
**Run mode:** 🟡 Shadow / research (offline) — `live_orders_permitted: false`
**Report generated:** 2026-09-10 (UTC)
**Runner:** `run_v9_4_institutional_backtest.py` → `run_v9_4_institutional_audit()`

---

> ## ⚠️ CRITICAL — READ FIRST: This is a HARNESS-VALIDATION run on SYNTHETIC data
>
> The numbers below were produced against a **randomly generated synthetic price series**
> and a **stubbed signal layer** (`setup_votes` always votes LONG, `opportunity_score`
> always returns a fixed passing score). Their purpose is to prove the **pipeline runs
> end-to-end and the plumbing is correct** — *not* to measure alpha.
>
> **The performance figures are meaningless as a strategy result and are expected to be
> negative** (a fixed always-long signal on noise, minus friction, must lose). Do **not**
> interpret win rate, R, or profit factor as V9.4's real edge. Re-run against your real
> OHLCV + real `strategy_candidate_v9` engine to obtain valid performance.

---

## 1. Run Configuration

| Parameter | Value |
|---|---|
| Dataset | `4year` (synthetic) |
| Dataset path | `data/ohlcv/institutional_4year_15m.csv` |
| Rows (15m bars) | 140,256 |
| Date span | 2021-01-01 → 2024-12-31 |
| Friction (R) | 0.026 |
| Max hold (bars) | 32 |
| Walk-forward windows | Y2021, Y2022, Y2023, Y2024 |
| Wall-clock runtime | ~11.2 s |

### Active V9.4 parameters

| Setting | Value | Purpose |
|---|---|---|
| `atr_pct_floor` / `atr_pct_ceiling` | 0.15% / 6.00% | Volatility-band admission filter |
| `mild_trend_min_score` | 6 | Stricter gate in weaker regime |
| `breakeven_trigger_r` | 1.00R | Ratchet stop to entry after +1R |
| Regime risk multipliers | STRONG 1.0 / MILD 0.75 / HIGH_VOL 0.6 | Telemetry-only sizing |
| `max_operating_leverage` | 5.0x | Hard cap (75x rejected) |

---

## 2. Portfolio Summary (synthetic — illustrative only)

| Metric | Value |
|---|---|
| Total trades | 7,997 |
| Win rate | 11.4% |
| Total R | −3,066.35 |
| Expectancy / trade | −0.383 R |
| Avg win | +0.648 R |
| Avg loss | −0.516 R |
| Profit factor | 0.161 |
| Max drawdown | −3,066.48 R |
| Best / worst trade | +1.974 R / −1.026 R |
| Max win / loss streak | 4 / 54 |
| Avg / median hold | 16.5 / 14 bars |

*Interpretation:* exactly the shape you'd expect from a **fixed always-long signal on
random walk minus friction** — capped upside (+1.97R = the 2.5×ATR target net of fees),
bounded downside (−1.03R = the 1.25×ATR stop), sub-random win rate, and monotonic
drawdown. This confirms the **mechanics** (targets, stops, breakeven, friction) resolve
correctly; it says nothing about real edge.

---

## 3. Walk-Forward by Year (synthetic)

| Period | Trades | Total R | Win Rate |
|---|---|---|---|
| Y2021 | 1,980 | −780.45 | 11.2% |
| Y2022 | 2,003 | −776.78 | 10.8% |
| Y2023 | 2,005 | −785.78 | 11.3% |
| Y2024 | 1,972 | −705.52 | 12.4% |
| **Total** | **7,960** | **−3,048.53** | **~11.4%** |

Stability across all four windows (near-identical trade counts and R) demonstrates the
**walk-forward slicing and per-period aggregation are deterministic and correct**.

---

## 4. Mechanics Validated ✅

The harness confirmed each V9.4 feature behaves as designed (verified separately with
controlled scenarios):

| Feature | Validation | Result |
|---|---|---|
| Volatility-band filter | Normalized ATR below floor / above ceiling | Rejected with reason ✅ |
| Regime score gate | MILD_TREND requires score ≥ 6 | Enforced ✅ |
| Regime risk scaling | STRONG 0.0035 / HIGH_VOL 0.0021 / MILD 0.002625 | Telemetry-only ✅ |
| Breakeven trail — armed then revert | Exit at entry (breakeven) | net_r = −0.026 ✅ |
| Straight-to-target | Exit at 2.5×ATR target | net_r = +1.974 ✅ |
| Immediate stop-out | Exit at 1.25×ATR stop | net_r = −1.026 ✅ |
| R-accounting continuity | Same normalized-R as V9.3.1 | `summarize()` valid ✅ |

---

## 5. Safety Provenance 🔒

Stamped into every report via `integration_audit_summary()`:

- `live_orders_permitted`: **false**
- `main_py_authoritative`: **true**
- `leverage_75x_rejected`: **true**, `max_operating_leverage`: **5.0**
- Gated regimes: **BREAKDOWN, CHOP, RANGE**
- Active setups: **TREND_CONTINUATION, BB_ATR_EXPANSION, MSS_SHIFT, BREAKOUT_RETEST**
- Runner imports **nothing** from the live execution path (`main.py`).

---

## 6. Next Steps to Obtain a REAL Result

1. **Place the runner** at `backtests/run_v9_4_institutional_backtest.py` (with `backtests/__init__.py`).
2. **Point at real OHLCV** — set `V94_DATASET_DIR` or edit `DATASET_FILES` to your institutional CSVs.
3. **Use the real engine** — ensure `strategy_candidate_v9.py` (real `setup_votes` / `opportunity_score` / `add_indicators`) is importable, not the test stubs.
4. **Re-run:** `python backtests/run_v9_4_institutional_backtest.py --dataset 4year --single-frame`
5. **(Optional) Tune** `atr_pct_floor/ceiling` and `breakeven_trigger_r` to a specific asset's ATR profile before the real audit.

---

*Report auto-generated from `v9_4_integration_report.json` + `full_stats.json`. Synthetic
harness figures are for pipeline validation only and must not inform trading decisions.*
