#!/usr/bin/env python3
"""
==========================================================================================
⚡ QUANT AUDIT: COUNTER-MACRO QUICK SCALP VS WITH-MACRO TREND RUNNER BACKTEST
==========================================================================================
Isolates and evaluates the exact performance of:
1. ⚡ Quick Scalps (Counter-Macro Reversals: Micro Short in Macro Bull / Micro Long in Macro Bear)
2. 🌊 Trend Runners (With-Macro Continuations: Micro Long in Macro Bull / Micro Short in Macro Bear)
3. 🚀 Combined Unified System (Dual-Engine Execution)

Execution Architecture:
- Quick Scalp: 33% TP1 @ 1.3x ATR -> Move SL to Breakeven (+0.05%) -> 33% TP2 @ 2.0x ATR -> 34% Trailing Runner @ 0.7x ATR (SL: 0.9x ATR)
- Trend Runner: 33% TP1 @ 1.8x ATR -> Move SL to Breakeven (+0.05%) -> 33% TP2 @ 2.8x ATR -> 34% Trailing Runner @ 1.4x ATR (SL: 1.5x ATR)
- Real Friction: Binance VIP0+BNB 0.018% Maker, 0.045% Taker, 0.015% Slippage, 0.010% 8h Funding
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
    'maker_fee': 0.00018,
    'taker': 0.00045,        # 0.045% Taker Stop/Market
    'taker_fee': 0.00045,
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

def calc_adx(highs, lows, closes, period=14):
    n = len(closes)
    if n < period * 2 + 1:
        return np.full(n, 25.0)
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        if up > down and up > 0:
            plus_dm[i] = up
        if down > up and down > 0:
            minus_dm[i] = down

    def ws(arr, p):
        out = np.zeros(len(arr))
        out[p] = np.mean(arr[:p])
        for j in range(p + 1, len(arr)):
            out[j] = (out[j - 1] * (p - 1) + arr[j]) / p
        return out

    s_tr = ws(tr, period)
    s_pdm = ws(plus_dm, period)
    s_mdm = ws(minus_dm, period)

    plus_di = 100.0 * (s_pdm / (s_tr + 1e-9))
    minus_di = 100.0 * (s_mdm / (s_tr + 1e-9))
    dx = 100.0 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-9)
    adx = ws(dx, period)
    return adx

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
    adx14 = calc_adx(highs, lows, closes, 14)

    # 4H Macro Trend Proxy (EMA50 vs EMA200 & Price vs EMA200)
    macro_bull = (closes > ema200) & (ema50 >= ema200)
    macro_bear = (closes < ema200) & (ema50 <= ema200)

    # 15m Micro Trend
    micro_bear = (closes < ema20) & (ema9 <= ema20)
    micro_bull = (closes > ema20) & (ema9 >= ema20)

    # Volume & Volatility
    vol_sma20 = np.zeros(n)
    for i in range(20, n):
        vol_sma20[i] = np.mean(volumes[i - 20 : i])
    is_vol_surge = volumes >= (vol_sma20 * 1.20)
    is_atr_expanded = atr14 >= (atr50 * 1.05)

    # Fractal Swings
    is_sh = np.zeros(n, dtype=bool)
    is_sl = np.zeros(n, dtype=bool)
    for i in range(window, n - window):
        if np.all(highs[i] >= highs[i - window : i]) and np.all(highs[i] >= highs[i + 1 : i + window + 1]):
            is_sh[i] = True
        if np.all(lows[i] <= lows[i - window : i]) and np.all(lows[i] <= lows[i + 1 : i + window + 1]):
            is_sl[i] = True

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

    signals = []

    for i in range(50, n):
        last_sh_p = last_sh_arr[i]
        last_sl_p = last_sl_arr[i]
        c = closes[i]
        h = highs[i]
        l = lows[i]
        curr_atr = atr14[i] if atr14[i] > 0 else (c * 0.008)
        adx_val = adx14[i]

        # 1. Fibonacci Golden Pocket (0.618 - 0.786)
        fib_long = False
        fib_short = False
        if last_sh_p > last_sl_p and (last_sh_p - last_sl_p) > (curr_atr * 2.5) and is_vol_surge[i]:
            diff = last_sh_p - last_sl_p
            f618 = last_sh_p - (diff * 0.618)
            f786 = last_sh_p - (diff * 0.786)
            if l <= f618 and c >= f786 and micro_bull[i]:
                fib_long = True
            
            f618_s = last_sl_p + (diff * 0.618)
            f786_s = last_sl_p + (diff * 0.786)
            if h >= f618_s and c <= f786_s and (micro_bear[i] or c < ema20[i]):
                fib_short = True

        # 2. Triple Divergence (Reversals at Extremes)
        div_long = (rsi14[i] < 32 and cci20[i] < -110 and l <= last_sl_p and c > l and is_vol_surge[i])
        div_short = (rsi14[i] > 68 and cci20[i] > 110 and h >= last_sh_p and c < h and (micro_bear[i] or c < ema20[i]) and is_vol_surge[i])

        # 3. Potato S&R Liquidity Sweeps (ICT Turtle Soup @ Support Floor / Resistance Ceiling)
        potato_long = (l < last_sl_p and c >= last_sl_p and is_vol_surge[i])
        potato_short = (h > last_sh_p and c <= last_sh_p and (micro_bear[i] or c < ema20[i]) and is_vol_surge[i])

        # 4. Consensus Momentum (Strict volume + ATR expansion)
        cons_long = (c > ema20[i] > ema50[i]) and is_vol_surge[i] and is_atr_expanded[i] and rsi14[i] > 55
        cons_short = (c < ema20[i] < ema50[i]) and is_vol_surge[i] and is_atr_expanded[i] and rsi14[i] < 45 and micro_bear[i]

        sig = {
            'fib_long': fib_long, 'fib_short': fib_short,
            'div_long': div_long, 'div_short': div_short,
            'potato_long': potato_long, 'potato_short': potato_short,
            'cons_long': cons_long, 'cons_short': cons_short,
            'macro_bull': macro_bull[i], 'macro_bear': macro_bear[i],
            'micro_bull': micro_bull[i], 'micro_bear': micro_bear[i],
            'adx': adx_val,
            'atr': curr_atr, 'last_sh': last_sh_p, 'last_sl': last_sl_p
        }
        signals.append((i, sig))

    return signals

def run_backtest_mode(mode_filter="ALL", initial_balance=100.0, leverage=50, margin_pct=0.03, max_positions=5, start_date='2025-07-01'):
    """
    mode_filter:
    - 'ALL': Evaluates both Quick Scalps and Trend Runners
    - 'SCALP_ONLY': Evaluates ONLY Counter-Macro Quick Scalps
    - 'RUNNER_ONLY': Evaluates ONLY With-Macro Trend Runners
    """
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

    scalp_stats = {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0, 'gross_win': 0.0, 'gross_loss': 0.0}
    runner_stats = {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0, 'gross_win': 0.0, 'gross_loss': 0.0}

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

        # 1. Manage Active Positions (3-Stage TP1 -> BE -> TP2 -> TP3 Runner)
        closed_syms = []
        for sym, pos in list(active_positions.items()):
            h = data[sym]['high'].iloc[bar_idx]
            l = data[sym]['low'].iloc[bar_idx]
            c = data[sym]['close'].iloc[bar_idx]
            is_long = pos['side'] == 'BUY'
            is_short = pos['side'] == 'SELL'

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
                pos['exit_reason'] = 'TP3_TRAILED' if pos.get('trailing') else ('SL_BE' if pos['tp1_hit'] else 'STOP_LOSS')
                
                # Attribution tracking
                is_sc = pos['is_quick_scalp']
                target_dict = scalp_stats if is_sc else runner_stats
                target_dict['trades'] += 1
                target_dict['pnl'] += pos['realized_pnl']
                if pos['realized_pnl'] > 0:
                    target_dict['wins'] += 1
                    target_dict['gross_win'] += pos['realized_pnl']
                else:
                    target_dict['losses'] += 1
                    target_dict['gross_loss'] += abs(pos['realized_pnl'])

                trade_history.append(pos)
                closed_syms.append(sym)
                continue

            # Stage 1: TP1 Check (33% Scale-Out + Move Stop to Breakeven)
            if not pos['tp1_hit']:
                tp1_hit = (is_long and h >= pos['tp1']) or (is_short and l <= pos['tp1'])
                if tp1_hit:
                    pos['tp1_hit'] = True
                    close_qty = pos['initial_qty'] * 0.33
                    pos['rem_qty'] -= close_qty
                    tp_p = pos['tp1']
                    raw_pnl = close_qty * (tp_p - pos['entry_price']) if is_long else close_qty * (pos['entry_price'] - tp_p)
                    m_fee = close_qty * tp_p * FEE_SCHEDULE['maker_fee']
                    total_maker_fees += m_fee
                    net_pnl = raw_pnl - m_fee
                    balance += net_pnl
                    monthly_pnl[m_key] += net_pnl
                    pos['realized_pnl'] += net_pnl

                    # Shift Stop Loss to Breakeven (+0.05% fee cover buffer)
                    pos['sl'] = pos['entry_price'] * 1.0005 if is_long else pos['entry_price'] * 0.9995
                    pos['trailing'] = True
                    pos['highest'] = h
                    pos['lowest'] = l

            # Stage 2: TP2 Check (Additional 33% Scale-Out + Tighten Trailing Stop)
            if pos['tp1_hit'] and not pos.get('tp2_hit') and pos.get('tp2', 0) > 0:
                tp2_hit = (is_long and h >= pos['tp2']) or (is_short and l <= pos['tp2'])
                if tp2_hit:
                    pos['tp2_hit'] = True
                    close_qty = pos['initial_qty'] * 0.33
                    pos['rem_qty'] -= close_qty
                    tp_p = pos['tp2']
                    raw_pnl = close_qty * (tp_p - pos['entry_price']) if is_long else close_qty * (pos['entry_price'] - tp_p)
                    m_fee = close_qty * tp_p * FEE_SCHEDULE['maker_fee']
                    total_maker_fees += m_fee
                    net_pnl = raw_pnl - m_fee
                    balance += net_pnl
                    monthly_pnl[m_key] += net_pnl
                    pos['realized_pnl'] += net_pnl

            # Stage 3: Dynamic TP3 Trailing Stop on the Final 34% Runner
            if pos.get('trailing'):
                is_sc = pos['is_quick_scalp']
                if is_sc:
                    trail_dist = (0.5 * pos['atr']) if pos.get('tp2_hit') else (0.7 * pos['atr'])
                else:
                    trail_dist = (0.8 * pos['atr']) if pos.get('tp2_hit') else (1.4 * pos['atr'])

                if is_long:
                    if h > pos['highest']:
                        pos['highest'] = h
                    calc_sl = pos['highest'] - trail_dist
                    if calc_sl > pos['sl'] and calc_sl > pos['entry_price']:
                        pos['sl'] = calc_sl
                elif is_short:
                    if l < pos['lowest']:
                        pos['lowest'] = l
                    calc_sl = pos['lowest'] + trail_dist
                    if calc_sl < pos['sl'] and calc_sl < pos['entry_price']:
                        pos['sl'] = calc_sl

        for sym in closed_syms:
            if sym in active_positions:
                del active_positions[sym]

        if balance > peak_balance:
            peak_balance = balance
        dd = (peak_balance - balance) / peak_balance * 100.0 if peak_balance > 0 else 0.0
        if dd > max_drawdown:
            max_drawdown = dd

        # 2. Check New Entries
        if len(active_positions) >= max_positions or balance <= 2.0:
            continue

        long_count = sum(1 for p in active_positions.values() if p['side'] == 'BUY')
        short_count = sum(1 for p in active_positions.values() if p['side'] == 'SELL')

        for sym in data.keys():
            if sym in active_positions or (bar_idx - last_trade_bar[sym]) < 16: # 4-hour trade spacing
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

            # Check Channels
            if sig['fib_long'] and long_count < 3:
                action, channel = 'BUY', 'FIBONACCI'
            elif sig['fib_short'] and short_count < 3:
                action, channel = 'SELL', 'FIBONACCI'
            elif sig['potato_long'] and long_count < 3:
                action, channel = 'BUY', 'POTATO_SR'
            elif sig['potato_short'] and short_count < 3:
                action, channel = 'SELL', 'POTATO_SR'
            elif sig['div_long'] and long_count < 3:
                action, channel = 'BUY', 'DIVERGENCE'
            elif sig['div_short'] and short_count < 3:
                action, channel = 'SELL', 'DIVERGENCE'
            elif sig['cons_long'] and long_count < 3:
                action, channel = 'BUY', 'CONSENSUS'
            elif sig['cons_short'] and short_count < 3:
                action, channel = 'SELL', 'CONSENSUS'

            if action:
                # Classify Quick Scalp vs Trend Runner
                # Quick Scalp: Action opposes Higher Timeframe Macro Trend
                is_quick_scalp = False
                if action == 'SELL' and sig['macro_bull']:
                    is_quick_scalp = True # Counter-Macro Short
                elif action == 'BUY' and sig['macro_bear']:
                    is_quick_scalp = True # Counter-Macro Long

                # Apply Mode Filter
                if mode_filter == 'SCALP_ONLY' and not is_quick_scalp:
                    continue
                if mode_filter == 'RUNNER_ONLY' and is_quick_scalp:
                    continue

                # Set TP1, TP2, and SL based on Scalp vs Runner Mode
                if is_quick_scalp:
                    tp1_v = (cur_p + 1.3 * atr_v) if action == 'BUY' else (cur_p - 1.3 * atr_v)
                    tp2_v = (cur_p + 2.0 * atr_v) if action == 'BUY' else (cur_p - 2.0 * atr_v)
                    sl_v  = (cur_p - 0.9 * atr_v) if action == 'BUY' else (cur_p + 0.9 * atr_v)
                    min_rr = 1.2
                else:
                    tp1_v = (cur_p + 1.8 * atr_v) if action == 'BUY' else (cur_p - 1.8 * atr_v)
                    tp2_v = (cur_p + 2.8 * atr_v) if action == 'BUY' else (cur_p - 2.8 * atr_v)
                    sl_v  = (cur_p - 1.5 * atr_v) if action == 'BUY' else (cur_p + 1.5 * atr_v)
                    min_rr = 1.8

                # ADX Anti-Chop Gate (Require ADX >= 22.0)
                if sig.get('adx', 25.0) < 22.0:
                    continue

                # R:R Check
                risk_d = abs(cur_p - sl_v)
                reward_d = abs(tp2_v - cur_p)
                if (reward_d / (risk_d + 1e-9)) < min_rr:
                    continue

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
                        'sl': sl_v,
                        'tp1': tp1_v,
                        'tp2': tp2_v,
                        'tp1_hit': False,
                        'tp2_hit': False,
                        'trailing': False,
                        'atr': atr_v,
                        'highest': cur_p,
                        'lowest': cur_p,
                        'realized_pnl': -e_fee,
                        'channel': channel,
                        'is_quick_scalp': is_quick_scalp
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

        is_sc = pos['is_quick_scalp']
        target_dict = scalp_stats if is_sc else runner_stats
        target_dict['trades'] += 1
        target_dict['pnl'] += pos['realized_pnl']
        if pos['realized_pnl'] > 0:
            target_dict['wins'] += 1
            target_dict['gross_win'] += pos['realized_pnl']
        else:
            target_dict['losses'] += 1
            target_dict['gross_loss'] += abs(pos['realized_pnl'])

    tot_trades = len(trade_history)
    wins = [t for t in trade_history if t['realized_pnl'] > 0]
    losses = [t for t in trade_history if t['realized_pnl'] <= 0]
    wr = (len(wins) / tot_trades * 100.0) if tot_trades > 0 else 0.0
    tot_pnl = balance - initial_balance
    roi = (tot_pnl / initial_balance * 100.0)

    gross_profit = sum(t['realized_pnl'] for t in wins)
    gross_loss = abs(sum(t['realized_pnl'] for t in losses))
    pf = (gross_profit / (gross_loss + 1e-9)) if gross_loss > 0 else 99.0

    return {
        'mode': mode_filter,
        'initial_balance': initial_balance,
        'ending_balance': balance,
        'net_pnl': tot_pnl,
        'roi': roi,
        'trades': tot_trades,
        'win_rate': wr,
        'profit_factor': pf,
        'max_drawdown': max_drawdown,
        'fees_paid': total_maker_fees + total_taker_fees + total_funding_fees + total_slippage,
        'scalp_stats': scalp_stats,
        'runner_stats': runner_stats,
        'monthly_pnl': monthly_pnl
    }

def print_audit_report(balance=16.50, start_date='2025-07-01'):
    print("=" * 100)
    print(" ⚡ VECTORIZED QUANT AUDIT: COUNTER-MACRO QUICK SCALP VS WITH-MACRO TREND RUNNER")
    print("=" * 100)
    print(f" • Historical Timeline:    From {start_date} to Present (1-Year Full Audit)")
    print(" • Evaluated Universe:      BTC, ETH, SOL, SUI, NEAR, AVAX, LINK, XRP, DOGE, ADA")
    print(f" • Account Sizing:          ${balance:,.2f} Initial Capital | 50x Isolated | 3.0% Dynamic Margin")
    print(" • Friction Schedule:       VIP0+BNB (Maker 0.018% | Taker 0.045% | Slip 0.015% | Funding 0.010%)")
    print("=" * 100)

    print("\n⚡ Running Simulation 1: ⚡ Counter-Macro Quick Scalps ONLY...")
    res_scalp = run_backtest_mode('SCALP_ONLY', initial_balance=balance, start_date=start_date)

    print("⚡ Running Simulation 2: 🌊 With-Macro Trend Runners ONLY...")
    res_runner = run_backtest_mode('RUNNER_ONLY', initial_balance=balance, start_date=start_date)

    print("⚡ Running Simulation 3: 🚀 Combined Dual-Engine (Quick Scalps + Trend Runners)...")
    res_combined = run_backtest_mode('ALL', initial_balance=balance, start_date=start_date)

    print("\n" + "=" * 100)
    print(" 🏆 HEAD-TO-HEAD QUANT PERFORMANCE COMPARISON")
    print("=" * 100)
    print(f"{'Performance Metric':<30} | {'⚡ Quick Scalp (Counter)':<20} | {'🌊 Trend Runner (Macro)':<20} | {'🚀 Combined Unified':<20}")
    print("-" * 100)
    print(f"{'Total Executed Trades':<30} | {res_scalp['trades']:>18} | {res_runner['trades']:>18} | {res_combined['trades']:>18}")
    print(f"{'Win Rate (%)':<30} | {res_scalp['win_rate']:>17.1f}% | {res_runner['win_rate']:>17.1f}% | {res_combined['win_rate']:>17.1f}%")
    print(f"{'Profit Factor (PF)':<30} | {res_scalp['profit_factor']:>18.2f} | {res_runner['profit_factor']:>18.2f} | {res_combined['profit_factor']:>18.2f}")
    print(f"{'Net Realized Profit':<30} | ${res_scalp['net_pnl']:>+17.2f} | ${res_runner['net_pnl']:>+17.2f} | ${res_combined['net_pnl']:>+17.2f}")
    print(f"{'Total Return (ROI)':<30} | {res_scalp['roi']:>+17.2f}% | {res_runner['roi']:>+17.2f}% | {res_combined['roi']:>+17.2f}%")
    print(f"{'Max Portfolio Drawdown':<30} | {res_scalp['max_drawdown']:>17.2f}% | {res_runner['max_drawdown']:>17.2f}% | {res_combined['max_drawdown']:>17.2f}%")
    print(f"{'Total Exchange Friction':<30} | ${res_scalp['fees_paid']:>17.2f} | ${res_runner['fees_paid']:>17.2f} | ${res_combined['fees_paid']:>17.2f}")
    print("=" * 100)

    # Detailed Sub-Attribution for Combined Mode
    c_sc = res_combined['scalp_stats']
    c_rn = res_combined['runner_stats']
    sc_wr = (c_sc['wins'] / c_sc['trades'] * 100.0) if c_sc['trades'] > 0 else 0.0
    rn_wr = (c_rn['wins'] / c_rn['trades'] * 100.0) if c_rn['trades'] > 0 else 0.0
    sc_pf = (c_sc['gross_win'] / (c_sc['gross_loss'] + 1e-9)) if c_sc['gross_loss'] > 0 else 99.0
    rn_pf = (c_rn['gross_win'] / (c_rn['gross_loss'] + 1e-9)) if c_rn['gross_loss'] > 0 else 99.0

    print("\n🎯 COMBINED DUAL-ENGINE ATTRIBUTION BREAKDOWN:")
    print("-" * 100)
    print(f" • ⚡ Counter-Macro Quick Scalps : {c_sc['trades']:>4} Trades | Win Rate: {sc_wr:>5.1f}% | Profit Factor: {sc_pf:>4.2f} | Net PnL: ${c_sc['pnl']:>+8.2f} USDT")
    print(f" • 🌊 With-Macro Trend Runners   : {c_rn['trades']:>4} Trades | Win Rate: {rn_wr:>5.1f}% | Profit Factor: {rn_pf:>4.2f} | Net PnL: ${c_rn['pnl']:>+8.2f} USDT")
    print("=" * 100)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Counter-Macro vs Trend Runner Backtest")
    parser.add_argument('--balance', type=float, default=16.50)
    parser.add_argument('--start-date', type=str, default='2025-07-01')
    args = parser.parse_args()
    print_audit_report(balance=args.balance, start_date=args.start_date)
