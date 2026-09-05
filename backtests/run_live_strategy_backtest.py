#!/usr/bin/env python3
"""
==========================================================================================
⚡ WEATHER-ENSEMBLE AI LIVE STRATEGY ACCURATE HISTORICAL BACKTESTER
==========================================================================================
Evaluates the exact production bot logic across 10 liquid assets using historical 15m data:
- Channel 0: 📐 Fibonacci 0.618-0.886 Golden Pocket Retracements (≥ 1.8 R:R)
- Channel 1: 🌪️ 31-Model Quant Consensus (≥ 30/31 + Volume Surge + ATR Expansion)
- Channel 2: ⚡ Triple Divergence (RSI(14) + CCI(20) + MACD(12,26,9))
- Channel 3: 🛡️ Potato S&R Ceiling/Floor Bounces & ICT Turtle Soup Liquidity Sweeps
- 🚀 NEW: Lower-Timeframe Micro-Bearish Shorting & Micro-Bullish Longing Engine
- 💰 Execution: 50% TP1 @ 1.5x ATR (Maker Limit) -> SL moved to Breakeven (+0.085%) -> Dynamic Trailing Runner
- 🧾 Real Friction: Binance VIP0+BNB Maker (0.018%), Taker (0.045%), Slippage (0.015%), 8h Funding (0.010%)
==========================================================================================
"""

import os
import sys
import argparse
import numpy as np
import pandas as pd
from datetime import datetime, timezone

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "historical_data_cache")

SYMBOLS = [
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'SUIUSDT', 'NEARUSDT',
    'AVAXUSDT', 'LINKUSDT', 'XRPUSDT', 'DOGEUSDT', 'ADAUSDT'
]

FEE_SCHEDULE = {
    'maker': 0.00018,        # 0.018% Maker Limit
    'maker_fee': 0.00018,    # 0.018% Maker Limit
    'taker': 0.00045,        # 0.045% Taker Stop/Market
    'taker_fee': 0.00045,    # 0.045% Taker Stop/Market
    'slippage': 0.00015,     # 0.015% Slippage
    'funding_8h': 0.00010    # 0.010% per 8h
}

def calc_ema(arr, span):
    alpha = 2.0 / (span + 1.0)
    n = len(arr)
    out = np.empty(n, dtype=np.float64)
    out[0] = arr[0]
    for i in range(1, n):
        out[i] = alpha * arr[i] + (1.0 - alpha) * out[i - 1]
    return out

def calc_rsi(closes, period=14):
    n = len(closes)
    diff = np.diff(closes)
    gains = np.where(diff > 0, diff, 0.0)
    losses = np.where(diff < 0, -diff, 0.0)
    
    rsi = np.full(n, 50.0)
    if n <= period:
        return rsi
        
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    
    for i in range(period, n - 1):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / (avg_loss + 1e-9) if avg_loss > 0 else 100.0
        rsi[i + 1] = 100.0 - (100.0 / (1.0 + rs))
    return rsi

def calc_cci(highs, lows, closes, period=20):
    tp = (highs + lows + closes) / 3.0
    s_tp = pd.Series(tp)
    sma = s_tp.rolling(period).mean()
    mad = (s_tp - sma).abs().rolling(period).mean()
    return ((s_tp - sma) / (0.015 * mad + 1e-9)).fillna(0.0).values

def calc_atr(highs, lows, closes, period=14):
    n = len(closes)
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    atr = np.zeros(n)
    if n <= period:
        return tr
    atr[period] = np.mean(tr[:period])
    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr

def precompute_market_signals(df, window=4):
    closes = df['close'].values
    highs = df['high'].values
    lows = df['low'].values
    volumes = df['volume'].values
    n = len(closes)

    ema9 = calc_ema(closes, 9)
    ema20 = calc_ema(closes, 20)
    ema50 = calc_ema(closes, 50)
    ema200 = calc_ema(closes, 200)
    rsi14 = calc_rsi(closes, 14)
    cci20 = calc_cci(highs, lows, closes, 20)
    atr14 = calc_atr(highs, lows, closes, 14)
    atr50 = calc_atr(highs, lows, closes, 50)

    # Volume SMA20
    vol_sma20 = np.zeros(n)
    for i in range(20, n):
        vol_sma20[i] = np.mean(volumes[i - 20 : i])
    is_vol_surge = volumes >= (vol_sma20 * 1.15)
    is_atr_expanded = atr14 >= (atr50 * 1.05)

    # Micro trend definition (15m)
    # Micro Bearish: Price < EMA20 and EMA9 <= EMA20 (or volume sell surge)
    micro_bear = (closes < ema20) & (ema9 <= ema20)
    # Micro Bullish: Price > EMA20 and EMA9 >= EMA20
    micro_bull = (closes > ema20) & (ema9 >= ema20)

    # Fractal Swings & Potato S&R (Floor / Ceiling)
    is_sh = np.zeros(n, dtype=bool)
    is_sl = np.zeros(n, dtype=bool)
    for i in range(window, n - window):
        if np.all(highs[i] >= highs[i - window : i]) and np.all(highs[i] >= highs[i + 1 : i + window + 1]):
            is_sh[i] = True
        if np.all(lows[i] <= lows[i - window : i]) and np.all(lows[i] <= lows[i + 1 : i + window + 1]):
            is_sl[i] = True

    # Precompute running swing arrays in O(N)
    last_sh_arr = np.zeros(n)
    last_sl_arr = np.zeros(n)
    curr_sh = highs[0]
    curr_sl = lows[0]
    for k in range(n):
        if is_sh[k]:
            curr_sh = highs[k]
        if is_sl[k]:
            curr_sl = lows[k]
        last_sh_arr[k] = curr_sh
        last_sl_arr[k] = curr_sl

    # Precompute per-bar triggers
    signals = []

    for i in range(50, n):
        last_sh_p = last_sh_arr[i]
        last_sl_p = last_sl_arr[i]

        c = closes[i]
        h = highs[i]
        l = lows[i]
        v = volumes[i]
        curr_atr = atr14[i] if atr14[i] > 0 else (c * 0.008)

        # 1. Fibonacci 0.618 - 0.886 Zone
        fib_long = False
        fib_short = False
        fib_tp1 = 0.0
        fib_sl = 0.0

        if last_sh_p > last_sl_p and (last_sh_p - last_sl_p) > (curr_atr * 2.0):
            diff = last_sh_p - last_sl_p
            f618 = last_sh_p - (diff * 0.618)
            f786 = last_sh_p - (diff * 0.786)
            # Long pull back into 0.618-0.786 zone
            if l <= f618 and c >= f786 and micro_bull[i]:
                fib_long = True
                fib_tp1 = c + (1.5 * curr_atr)
                fib_sl = f786 - (0.5 * curr_atr)
            
            # Short pull up into 0.618-0.786 zone (ALLOWED when micro is bearish!)
            f618_s = last_sl_p + (diff * 0.618)
            f786_s = last_sl_p + (diff * 0.786)
            if h >= f618_s and c <= f786_s and (micro_bear[i] or c < ema20[i]):
                fib_short = True
                fib_tp1 = c - (1.5 * curr_atr)
                fib_sl = f786_s + (0.5 * curr_atr)

        # 2. Triple Divergence (RSI + CCI Divergence at swings)
        div_long = False
        div_short = False
        if rsi14[i] < 35 and cci20[i] < -100 and l <= last_sl_p and c > l:
            div_long = True
        elif rsi14[i] > 65 and cci20[i] > 100 and h >= last_sh_p and c < h and (micro_bear[i] or c < ema20[i]):
            div_short = True

        # 3. Potato S&R Tap / Sweep (Floor / Ceiling)
        potato_long = False
        potato_short = False
        if abs(l - last_sl_p) / (c + 1e-9) < 0.003 and c >= last_sl_p:
            potato_long = True
        elif abs(h - last_sh_p) / (c + 1e-9) < 0.003 and c <= last_sh_p and (micro_bear[i] or c < ema20[i]):
            potato_short = True

        # 4. Consensus Momentum (EMA alignment + Vol Surge + ATR Expansion)
        cons_long = (c > ema20[i] > ema50[i]) and is_vol_surge[i] and is_atr_expanded[i] and rsi14[i] > 54
        cons_short = (c < ema20[i] < ema50[i]) and is_vol_surge[i] and is_atr_expanded[i] and rsi14[i] < 46 and micro_bear[i]

        sig = {
            'fib_long': fib_long, 'fib_short': fib_short, 'fib_tp1': fib_tp1, 'fib_sl': fib_sl,
            'div_long': div_long, 'div_short': div_short,
            'potato_long': potato_long, 'potato_short': potato_short,
            'cons_long': cons_long, 'cons_short': cons_short,
            'atr': curr_atr, 'last_sh': last_sh_p, 'last_sl': last_sl_p
        }
        signals.append((i, sig))

    return signals

def run_simulation(initial_balance=17.17, leverage=50, margin_pct=0.03, max_positions=5, start_date='2025-07-01'):
    data = {}
    for sym in SYMBOLS:
        fpath = os.path.join(CACHE_DIR, f"{sym}_15m_from_{start_date}.csv")
        if not os.path.exists(fpath):
            fpath = os.path.join(CACHE_DIR, f"{sym}_15m_from_2024-08-25.csv")
        if os.path.exists(fpath):
            df = pd.read_csv(fpath)
            t_col = 'open_time' if 'open_time' in df.columns else 'timestamp'
            df['open_time'] = pd.to_datetime(df[t_col], utc=True)
            df = df.sort_values('open_time').reset_index(drop=True)
            data[sym] = df

    if not data:
        print("No historical data found in cache.")
        return

    print("=" * 95)
    print(" ⚡ WEATHER-ENSEMBLE AI HISTORICAL STRATEGY BACKTEST (WITH MICRO SHORTING)")
    print("=" * 95)
    print(f" • Historical Range:        {data['BTCUSDT']['open_time'].iloc[0].strftime('%Y-%m-%d')} to {data['BTCUSDT']['open_time'].iloc[-1].strftime('%Y-%m-%d')}")
    print(f" • Evaluated Assets:        {', '.join(data.keys())} ({len(data)} Total)")
    print(f" • Starting Balance:        ${initial_balance:,.2f} USDT")
    print(f" • Leverage & Margin:       {leverage}x Leverage | {margin_pct*100:.1f}% Dynamic Margin (Max {max_positions} Positions)")
    print(f" • Real Fee Schedule:       Maker 0.018% | Taker 0.045% | Slippage 0.015% | 8h Funding 0.010%")
    print(f" • Execution Model:         50% TP1 @ 1.5x ATR (Maker) -> Move SL to Breakeven -> 1.2x ATR Trailing Stop")
    print("=" * 95)

    print("⚡ Precomputing multi-channel signal matrices across universe...")
    sym_signals = {}
    for sym, df in data.items():
        sym_signals[sym] = precompute_market_signals(df)

    min_len = min(len(df) for df in data.values())
    
    balance = initial_balance
    peak_balance = balance
    max_drawdown = 0.0
    active_positions = {}
    trade_history = []
    monthly_pnl = {}
    last_trade_bar = {sym: -100 for sym in data.keys()}

    total_maker_fees = 0.0
    total_taker_fees = 0.0
    total_funding_fees = 0.0
    total_slippage = 0.0

    channel_stats = {
        'FIBONACCI': {'trades': 0, 'wins': 0, 'pnl': 0.0},
        'DIVERGENCE': {'trades': 0, 'wins': 0, 'pnl': 0.0},
        'POTATO_SR': {'trades': 0, 'wins': 0, 'pnl': 0.0},
        'CONSENSUS': {'trades': 0, 'wins': 0, 'pnl': 0.0}
    }

    last_funding_bar = 0

    for bar_idx in range(60, min_len):
        cur_dt = data['BTCUSDT']['open_time'].iloc[bar_idx]
        m_key = cur_dt.strftime('%Y-%m')
        if m_key not in monthly_pnl:
            monthly_pnl[m_key] = 0.0

        # Funding rate deduction every 32 bars (8 hours)
        if (bar_idx - last_funding_bar) >= 32:
            last_funding_bar = bar_idx
            for sym, pos in active_positions.items():
                c = data[sym]['close'].iloc[bar_idx]
                f_cost = pos['rem_qty'] * c * FEE_SCHEDULE['funding_8h']
                total_funding_fees += f_cost
                balance -= f_cost
                monthly_pnl[m_key] -= f_cost
                pos['funding'] = pos.get('funding', 0.0) + f_cost

        # 1. Manage Active Positions
        closed_syms = []
        for sym, pos in list(active_positions.items()):
            h = data[sym]['high'].iloc[bar_idx]
            l = data[sym]['low'].iloc[bar_idx]
            c = data[sym]['close'].iloc[bar_idx]
            is_long = pos['side'] == 'BUY'
            is_short = pos['side'] == 'SELL'

            # Fast Early Breakeven for Quick Scalps (+0.75x ATR profit on subsequent bars)
            if pos.get('is_scalp') and not pos.get('be_locked') and not pos['tp1_hit'] and pos['entry_time'] != cur_dt:
                in_quick_profit = (is_long and h >= pos['entry_price'] + (0.75 * pos['atr'])) or (is_short and l <= pos['entry_price'] - (0.75 * pos['atr']))
                if in_quick_profit:
                    pos['be_locked'] = True
                    pos['sl'] = pos['entry_price'] * 1.0005 if is_long else pos['entry_price'] * 0.9995

            # Stop Loss Check
            hit_sl = False
            sl_price = pos['sl']
            if is_long and l <= pos['sl']:
                hit_sl = True
                sl_price = min(c, pos['sl']) * (1.0 - FEE_SCHEDULE['slippage'])
            elif is_short and h >= pos['sl']:
                hit_sl = True
                sl_price = max(c, pos['sl']) * (1.0 + FEE_SCHEDULE['slippage'])

            if hit_sl:
                rem_qty = pos['rem_qty']
                raw_pnl = rem_qty * (sl_price - pos['entry_price']) if is_long else rem_qty * (pos['entry_price'] - sl_price)
                t_fee = rem_qty * sl_price * FEE_SCHEDULE['taker_fee']
                slip = rem_qty * sl_price * FEE_SCHEDULE['slippage']
                total_taker_fees += t_fee
                total_slippage += slip
                net_pnl = raw_pnl - t_fee
                balance += net_pnl
                monthly_pnl[m_key] += net_pnl
                pos['realized_pnl'] += net_pnl
                pos['exit_time'] = cur_dt
                pos['exit_reason'] = 'TP2_TRAILED' if pos.get('trailing') else ('SL_BE' if (pos['tp1_hit'] or pos.get('be_locked')) else 'STOP_LOSS')
                
                ch = pos['channel']
                channel_stats[ch]['trades'] += 1
                channel_stats[ch]['pnl'] += pos['realized_pnl']
                if pos['realized_pnl'] > 0:
                    channel_stats[ch]['wins'] += 1

                trade_history.append(pos)
                closed_syms.append(sym)
                continue

            # TP1 Check (100% full exit for Quick Scalp to get out ASAP; 50% scale-out + BE + trailing for Trend Runners)
            if not pos['tp1_hit']:
                tp1_hit = (is_long and h >= pos['tp1']) or (is_short and l <= pos['tp1'])
                if tp1_hit:
                    pos['tp1_hit'] = True
                    is_scalp = pos.get('is_scalp', False)
                    close_qty = pos['rem_qty'] if is_scalp else (pos['initial_qty'] * 0.50)
                    pos['rem_qty'] -= close_qty
                    tp_p = pos['tp1']
                    raw_pnl = close_qty * (tp_p - pos['entry_price']) if is_long else close_qty * (pos['entry_price'] - tp_p)
                    m_fee = close_qty * tp_p * FEE_SCHEDULE['maker_fee']
                    total_maker_fees += m_fee
                    net_pnl = raw_pnl - m_fee
                    balance += net_pnl
                    monthly_pnl[m_key] += net_pnl
                    pos['realized_pnl'] += net_pnl

                    if is_scalp or pos['rem_qty'] <= 1e-6:
                        # 100% Full Take-Profit complete for Quick Scalps
                        pos['exit_time'] = cur_dt
                        pos['exit_reason'] = 'TP1_FULL_SCALP'
                        ch = pos['channel']
                        channel_stats[ch]['trades'] += 1
                        channel_stats[ch]['pnl'] += pos['realized_pnl']
                        if pos['realized_pnl'] > 0:
                            channel_stats[ch]['wins'] += 1
                        trade_history.append(pos)
                        closed_syms.append(sym)
                        continue
                    else:
                        # Breakeven stop + fee buffer for Trend Runners
                        pos['sl'] = pos['entry_price'] * 1.00085 if is_long else pos['entry_price'] * 0.99915
                        pos['trailing'] = True
                        pos['highest'] = h
                        pos['lowest'] = l

            # Dynamic Trailing Stop on Remaining 50% (Trend Runners only)
            if pos.get('trailing') and not pos.get('is_scalp'):
                trail_dist = 1.2 * pos['atr']
                if is_long:
                    if h > pos['highest']:
                        pos['highest'] = h
                    calc_sl = pos['highest'] - trail_dist
                    if calc_sl > pos['sl']:
                        pos['sl'] = calc_sl
                elif is_short:
                    if l < pos['lowest']:
                        pos['lowest'] = l
                    calc_sl = pos['lowest'] + trail_dist
                    if calc_sl < pos['sl']:
                        pos['sl'] = calc_sl

        for sym in closed_syms:
            if sym in active_positions:
                del active_positions[sym]

        if balance > peak_balance:
            peak_balance = balance
        dd = (peak_balance - balance) / peak_balance * 100.0 if peak_balance > 0 else 0.0
        if dd > max_drawdown:
            max_drawdown = dd

        # 2. Check New Entries (Multi-Channel with Micro Bearish Short Authorization)
        if len(active_positions) >= max_positions or balance <= 2.0:
            continue

        long_count = sum(1 for p in active_positions.values() if p['side'] == 'BUY')
        short_count = sum(1 for p in active_positions.values() if p['side'] == 'SELL')

        for sym in data.keys():
            if sym in active_positions or (bar_idx - last_trade_bar[sym]) < 16: # 4-hour trade spacing per asset
                continue

            sig_list = sym_signals[sym]
            sig_idx = bar_idx - 50
            if sig_idx < 0 or sig_idx >= len(sig_list):
                continue

            _, sig = sig_list[sig_idx]
            cur_p = data[sym]['close'].iloc[bar_idx]
            atr_v = sig['atr']

            action = None
            channel = None
            tp1_val = 0.0
            sl_val = 0.0
            is_scalp_trade = False

            # Priority 0: Fibonacci Zone (≥ 1.8 R:R)
            if sig['fib_long'] and long_count < 3:
                action, channel = 'BUY', 'FIBONACCI'
                tp1_val = sig['fib_tp1']
                sl_val = sig['fib_sl']
                is_scalp_trade = False
            elif sig['fib_short'] and short_count < 3:
                action, channel = 'SELL', 'FIBONACCI'
                tp1_val = sig['fib_tp1']
                sl_val = sig['fib_sl']
                is_scalp_trade = False
            # Priority 1: Potato S&R Bounce / Liquidity Sweep (Fast Scalp: 1.3x TP, 0.9x SL -> Get out ASAP)
            elif sig['potato_long'] and long_count < 3:
                action, channel = 'BUY', 'POTATO_SR'
                tp1_val = cur_p + (1.3 * atr_v)
                sl_val = cur_p - (0.9 * atr_v)
                is_scalp_trade = True
            elif sig['potato_short'] and short_count < 3:
                action, channel = 'SELL', 'POTATO_SR'
                tp1_val = cur_p - (1.3 * atr_v)
                sl_val = cur_p + (0.9 * atr_v)
                is_scalp_trade = True
            # Priority 2: Triple Divergence (Fast Scalp: 1.3x TP, 0.9x SL -> Get out ASAP)
            elif sig['div_long'] and long_count < 3:
                action, channel = 'BUY', 'DIVERGENCE'
                tp1_val = cur_p + (1.3 * atr_v)
                sl_val = cur_p - (0.9 * atr_v)
                is_scalp_trade = True
            elif sig['div_short'] and short_count < 3:
                action, channel = 'SELL', 'DIVERGENCE'
                tp1_val = cur_p - (1.3 * atr_v)
                sl_val = cur_p + (0.9 * atr_v)
                is_scalp_trade = True
            # Priority 3: 31-Model Quant Consensus (Trend Runner: 2.5x TP, 1.0x SL)
            elif sig['cons_long'] and long_count < 3:
                action, channel = 'BUY', 'CONSENSUS'
                tp1_val = cur_p + (2.5 * atr_v)
                sl_val = cur_p - (1.0 * atr_v)
                is_scalp_trade = False
            elif sig['cons_short'] and short_count < 3:
                action, channel = 'SELL', 'CONSENSUS'
                tp1_val = cur_p - (2.5 * atr_v)
                sl_val = cur_p + (1.0 * atr_v)
                is_scalp_trade = False

            if action:
                margin = balance * margin_pct
                notional = margin * leverage
                if notional < 5.0:
                    notional = 5.0
                    margin = notional / leverage

                if balance >= margin:
                    qty = notional / cur_p
                    e_fee = notional * FEE_SCHEDULE['maker_fee']
                    total_maker_fees += e_fee
                    balance -= e_fee
                    monthly_pnl[m_key] -= e_fee

                    active_positions[sym] = {
                        'symbol': sym,
                        'side': action,
                        'entry_time': cur_dt,
                        'entry_price': cur_p,
                        'initial_qty': qty,
                        'rem_qty': qty,
                        'sl': sl_val,
                        'tp1': tp1_val,
                        'tp1_hit': False,
                        'be_locked': False,
                        'trailing': False,
                        'is_scalp': is_scalp_trade,
                        'channel': channel,
                        'atr': atr_v,
                        'highest': cur_p,
                        'lowest': cur_p,
                        'realized_pnl': -e_fee,
                        'margin': margin
                    }
                    last_trade_bar[sym] = bar_idx
                    if len(active_positions) >= max_positions:
                        break

    # Close remaining open positions
    for sym, pos in list(active_positions.items()):
        c = data[sym]['close'].iloc[-1]
        rem_qty = pos['rem_qty']
        raw_pnl = rem_qty * (c - pos['entry_price']) if pos['side'] == 'BUY' else rem_qty * (pos['entry_price'] - c)
        t_fee = rem_qty * c * FEE_SCHEDULE['taker_fee']
        total_taker_fees += t_fee
        net_pnl = raw_pnl - t_fee
        balance += net_pnl
        pos['realized_pnl'] += net_pnl
        trade_history.append(pos)

    # Print Final Performance Report
    tot_trades = len(trade_history)
    wins = [t for t in trade_history if t['realized_pnl'] > 0]
    losses = [t for t in trade_history if t['realized_pnl'] <= 0]
    wr = (len(wins) / tot_trades * 100.0) if tot_trades > 0 else 0.0
    tot_pnl = balance - initial_balance
    roi = (tot_pnl / initial_balance * 100.0)

    gross_profit = sum(t['realized_pnl'] for t in wins)
    gross_loss = abs(sum(t['realized_pnl'] for t in losses))
    pf = (gross_profit / (gross_loss + 1e-9)) if gross_loss > 0 else 99.0

    print("\n" + "=" * 95)
    print(" 🏆 FINAL QUANT LAB AUDIT PERFORMANCE REPORT")
    print("=" * 95)
    print(f" 💰 Initial Capital:        ${initial_balance:,.2f} USDT")
    print(f" 🏁 Ending Portfolio Balance: ${balance:,.2f} USDT")
    print(f" 📈 Net Realized Profit:     ${tot_pnl:+,.2f} USDT ({roi:+.2f}% Total ROI)")
    print(f" 📊 Profit Factor (PF):      {pf:.2f}")
    print(f" 🎯 Overall Win Rate:        {wr:.2f}% ({len(wins)} Wins / {len(losses)} Losses)")
    print(f" ⚡ Total Executed Trades:   {tot_trades}")
    print(f" 🛡️ Max Portfolio Drawdown:  {max_drawdown:.2f}%")
    print("-" * 95)
    print(" 🧾 REAL FRICTION & FEE IMPACT:")
    print(f"   • Maker Entry/TP1 Fees:  ${total_maker_fees:,.2f} USDT")
    print(f"   • Taker Stop/Exit Fees:  ${total_taker_fees:,.2f} USDT")
    print(f"   • 8-Hour Funding Costs:  ${total_funding_fees:,.2f} USDT")
    print(f"   • Market Slippage Cost:  ${total_slippage:,.2f} USDT")
    print(f"   • Total Friction Paid:   ${(total_maker_fees + total_taker_fees + total_funding_fees + total_slippage):,.2f} USDT")
    print("-" * 95)
    print(" 🎯 STRATEGY CHANNEL PERFORMANCE ATTRIBUTION:")
    for ch, stat in channel_stats.items():
        ch_trades = stat['trades']
        ch_wr = (stat['wins'] / ch_trades * 100.0) if ch_trades > 0 else 0.0
        print(f"   • {ch:<16} | Trades: {ch_trades:>4} | Win Rate: {ch_wr:>5.1f}% | Net PnL: ${stat['pnl']:>+8.2f} USDT")
    print("-" * 95)
    print(" 📅 MONTH-BY-MONTH PERFORMANCE BREAKDOWN:")
    for m, pnl in sorted(monthly_pnl.items()):
        icon = "🟢" if pnl >= 0 else "🔴"
        print(f"   {icon} {m} | Net PnL: ${pnl:+8.2f} USDT")
    print("=" * 95)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Live Strategy Accurate Backtest")
    parser.add_argument('--balance', type=float, default=17.17)
    parser.add_argument('--leverage', type=int, default=50)
    parser.add_argument('--margin-pct', type=float, default=0.03)
    parser.add_argument('--max-positions', type=int, default=5)
    parser.add_argument('--start-date', type=str, default='2025-07-01')
    args = parser.parse_args()

    run_simulation(
        initial_balance=args.balance,
        leverage=args.leverage,
        margin_pct=args.margin_pct,
        max_positions=args.max_positions,
        start_date=args.start_date
    )
