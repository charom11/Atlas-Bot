# V9.2 Validation Plan

V9.2 is a research-only validation-hardening stage for V9.1. It must not modify `main.py` or place orders.

## Required validation

1. Reproduce the V9.1 baseline from the exact committed code.
2. Stress friction at 1.00x, 1.25x, 1.50x, and 2.00x.
3. Measure funding/slippage sensitivity separately where the backtest data supports it.
4. Run asset leave-one-out and report whether the strategy remains profitable without each major asset.
5. Run regime leave-one-out and report dependence on HIGH_VOL, STRONG_TREND, MILD_TREND, and BREAKDOWN.
6. Run setup ablations for TREND_CONTINUATION, BB_ATR_EXPANSION, MSS_SHIFT, BREAKOUT_RETEST, FIB_OTE, VWAP_TREND, and PULLBACK_CONTINUATION.
7. Report bootstrap confidence intervals for trade expectancy.
8. Report monthly/quarterly returns, maximum consecutive losses, and drawdown.
9. Report daily trade-rate buckets and capacity pressure.
10. Verify that 2025 and 2026 were not used to tune the final policy. If any V9.1 rule was selected using those periods, label them validation rather than true OOS.

## Recommended decision gates

- OOS PF must remain >= 1.00.
- OOS net R must remain > 0.
- No single asset or regime should be solely responsible for the edge.
- Positive expectancy should survive realistic cost stress.
- Bootstrap lower confidence bound should be explicitly reported; a point estimate alone is not sufficient.
- If any gate fails, do not wire V9.1 into production execution.

## Production boundary

`main.py` remains the execution, reconciliation, protective-stop, portfolio-risk, and fail-closed safety layer. V9.1 may become an opportunity/admission layer only after V9.2 validation passes and a separate integration review is completed.
