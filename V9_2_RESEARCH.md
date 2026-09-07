# Candidate V9.2 — Validation Hardening

## Purpose

V9.2 validates the V9.1 15-minute selective opportunity policy without adding indicators or changing live execution.

## Recommendation

Treat V9.1 as **promising but not production-ready** until robustness checks are complete. The reported 4-year PF of 1.01 is thin, while 2025/2026 OOS PF of 1.04/1.05 is encouraging. The key question is whether that edge survives costs, asset/regime removal, and statistical uncertainty.

## Priority order

1. Exact-code parity.
2. Cost and funding/slippage stress.
3. Asset and regime leave-one-out.
4. Setup ablation.
5. Bootstrap expectancy confidence interval.
6. Monthly/quarterly equity and loss streaks.
7. Capacity and turnover.
8. OOS-purity audit.

## Production recommendation

Do not wire V9.1 into `main.py` during V9.2. If V9.2 passes, perform a separate integration review in which V9.1 supplies opportunities while the existing execution and safety controls remain authoritative.
