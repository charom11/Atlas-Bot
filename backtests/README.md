# Weather-Ensemble Backtesting & Research Suite

This directory contains consolidated backtesting engines and historical Binance Futures market data cache for the **Weather-Ensemble AI Trading System**.

---

## Active Backtest Engines

| Script | Purpose & Description |
| :--- | :--- |
| **`backtest_1year_complete_engine.py`** | Comprehensive 1-year (365-day) multi-asset backtest with 2-stage partial take-profit scaling (50% TP1 @ 1.5x ATR, 50% Runner @ S/R Level), Break-Even stop adjustments (+0.085% fee cover), and Milestone Floor Locks. |
| **`backtest_july2025_to_now.py`** | Real historical Binance Futures candle backtester (from July 2025 to present) with full taker and maker fee deduction modeling. |
| **`historical_data_cache/`** | Cached real Binance Futures OHLCV candle CSV datasets across core trading pairs. |

---

## How to Run Backtests

```bash
# Run 1-Year Comprehensive Multi-Asset Partial Scaling Engine
python backtests/backtest_1year_complete_engine.py

# Run Real Binance Futures Historical Data Engine
python backtests/backtest_july2025_to_now.py
```

