# 🤖 Master Quantitative Bot Architecture — Handover Document for Qwen

**Project Name**: Weather-Ensemble 31-Model AI Trading Bot  
**Target Exchange**: Binance USDT-M Perpetual Futures (Hedge Mode Dual-Side)  
**Execution Timeframe**: 15M Execution with 4H / 1H Macro SMC Trend Filtering  
**Current Production Profile**: 50x Isolated Leverage | 3.0% Dynamic Margin Sizing | Max 5 Slots | VIP0+BNB Tier

---

## 📂 Core Files in This Package

1. **[`main.py`](file:///d:/Bot2/To%20Qwen/main.py)**:
   * Master execution engine.
   * Houses the **31 Quantitative Models** spanning 9 Independent Pillars:
     * Trend Following (EMA, Supertrend, Hull MA, Parabolic SAR, KAMA)
     * Momentum & Oscillators (RSI, CCI, StochRSI, MACD, Williams %R, Ultimate Oscillator)
     * Volatility & Bands (Bollinger Bands, Keltner Channels, Donchian Channels)
     * Microstructure & Volume (OBV, MFI, CMF, VWAP Bands)
     * Order Flow & Liquidity (Order Book Imbalance, Funding Rate, Absorption Delta)
     * Price Action & S&R (Potato Floor/Ceiling, Fibonacci Golden Pocket, Dual Divergences)
   * Real-time protective stop replacement engine (`place_protective_stop`, `_replace_protective_stop`, `cancel_binance_order_by_id`).
   * 3-Stage Scale-Out Daemon:
     * **TP1**: 33% Scale-out at $1.00\text{x}$ / $1.5\text{x}$ ATR $\rightarrow$ Instant Breakeven Stop ($+0.05\%$ fee buffer).
     * **TP2**: 33% Scale-out at $2.8\text{x}$ ATR $\rightarrow$ Real exchange-side conditional order.
     * **TP3 Runner**: Dynamic $0.8\text{x}-1.4\text{x}$ ATR trailing stop walking behind price.
   * Interactive Telegram Command & Control (`/status`, `/positions`, `/balance`, `/circuit reset`, `/pause`, `/resume`).

2. **[`order_flow_engine.py`](file:///d:/Bot2/To%20Qwen/order_flow_engine.py)**:
   * Real-time tape & volume delta analyzer.
   * Calculates Buyer/Seller volume delta and Institutional Absorption flags.

3. **[`smc_mss_strategy.py`](file:///d:/Bot2/To%20Qwen/smc_mss_strategy.py)**:
   * Higher-timeframe (4H / 1H) Smart Money Concepts & Market Structure Shift (MSS) bias engine.
   * Prevents shorting macro bull markets and buying falling knives.

4. **[`server.py`](file:///d:/Bot2/To%20Qwen/server.py)**:
   * Backend REST & WebSocket telemetry server for real-time dashboard monitoring.

5. **[`desktop_terminal.py`](file:///d:/Bot2/To%20Qwen/desktop_terminal.py)** & **[`terminal_dashboard.py`](file:///d:/Bot2/To%20Qwen/terminal_dashboard.py)**:
   * Terminal-based live monitoring dashboards.

6. **[`run_24_7_windows_watchdog.bat`](file:///d:/Bot2/To%20Qwen/run_24_7_windows_watchdog.bat)**:
   * Auto-healing Windows watchdog process with 3-second crash recovery loop.

7. **[`TRADING_BOT_FIX_PROMPT.md`](file:///d:/Bot2/To%20Qwen/TRADING_BOT_FIX_PROMPT.md)**:
   * Master 7-Phase Engineering Blueprint (Backtesting $\rightarrow$ WebSocket $\rightarrow$ Risk Hardening $\rightarrow$ Regime Detection $\rightarrow$ Reliability $\rightarrow$ Model Evolution $\rightarrow$ Frontend).

---

## 🛡️ Critical Safety Invariants & Execution Rules

1. **Place $\rightarrow$ Verify $\rightarrow$ Cancel Protocol**:
   * When trailing or moving a stop loss, the bot **places and confirms the new stop on Binance first** before cancelling the old stop. A leveraged position is **NEVER** left with zero protective orders.
2. **Hedge Mode Dual-Side Routing**:
   * All order parameters must specify `positionSide='LONG'` or `positionSide='SHORT'`.
3. **Core Entry Gates Filter (`_check_core_entry_gates`)**:
   * Every entry channel (Consensus, Fibonacci Golden Pocket, Dual Divergence, Potato S&R) must pass L2 Order Book depth imbalance ($\ge 1.05\text{x}$), adverse funding rate filters, and order-flow absorption.
4. **ADX Anti-Chop Protection**:
   * Automatically pauses breakout entries if market volatility collapses ($\text{ADX} < 22.0$).
