# Atlas-Bot risk hardening

## Current guardrails

`risk_guard.py` provides a side-effect-free, fail-closed account-level gate for order admission. It checks:

- maximum leverage
- maximum open positions
- maximum margin utilization
- maximum aggregate notional exposure
- maximum daily loss
- invalid/missing account state

Conservative defaults are 10x leverage, 3 positions, 10% margin utilization, 100% equity notional exposure, and a 5% daily loss stop.

Environment overrides:

- `ATLAS_MAX_LEVERAGE`
- `ATLAS_MAX_POSITIONS`
- `ATLAS_MAX_MARGIN_UTILIZATION`
- `ATLAS_MAX_TOTAL_NOTIONAL_PCT`
- `ATLAS_MAX_DAILY_LOSS_PCT`

## Important integration requirement

The guard must be called immediately before every new-position submission, using authoritative Binance account/position state. It must **not** be treated as a post-trade monitor. Existing positions may still be managed when the gate blocks new entries.

The V9 backtest should use realistic stop/gap/slippage/funding assumptions before a strategy is considered live-ready. See `V9_backtest_audit.md` for the existing findings.

The live workflow remains an explicit manual action. Risk guardrails should be integrated into the live execution path before enabling unattended production trading.
