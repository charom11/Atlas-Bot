#!/usr/bin/env python3
"""
==========================================================================================
📊 COMPREHENSIVE QUANT BACKTEST: CURRENT LIVE STRATEGY + 5-EMA STACK INTEGRATION
==========================================================================================
Evaluates:
1. Baseline: Current Live 4-Channel System (Potato S&R, Divergences, Fibonacci, Consensus)
2. Standalone: 5-EMA Stack (EMA 9, 20, 50, 100, 200 Breakouts + SL @ mid EMA50/100)
3. Integrated Ensemble: Current 4 Channels + 5-EMA Stack as Channel 4
4. Confluence Mode: Current 4 Channels confirmed with 5-EMA Trend Alignment

Execution:
- Sizing: $100 Initial Balance, 50x Leverage, 3% Dynamic Margin, Max 5 Concurrent Positions
- 3-Stage Scale-Out: TP1 -> Move SL to Breakeven (+0.05%) -> TP2 -> TP3 Trailing Runner
- Friction: VIP0+BNB (Maker 0.018%, Taker 0.045%, Slip 0.015%, Funding 0.010%/8h)
- 10 Pairs (BTC, ETH, SOL, SUI, NEAR, AVAX, LINK, XRP, DOGE, ADA) on 15m (July 2025 - August 2026)
==========================================================================================
"""

import os
import sys
import numpy as np
import pandas as pd

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
    'maker_fee': 0.00018,
    'taker_fee': 0.00045,
    'slippage': 0.00015,
    'funding_8h': 0.00010
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
    return ws(dx, period)

def precompute_market_signals(df, window=4):
    closes = df['close'].values
    highs = df['high'].values
    lows = df['low'].values
    volumes = df['volume'].values
    n = len(closes)

    ema9 = calc_ema(closes, 9)
    ema20 = calc_ema(closes, 20)
    ema50 = calc_ema(closes, 50)
    ema100 = calc_ema(closes, 100)
    ema200 = calc_ema(closes, 200)

    rsi14 = calc_rsi(closes, 14)
    cci20 = calc_cci(highs, lows, closes, 20)
    atr14 = calc_atr(highs, lows, closes, 14)
    atr50 = calc_atr(highs, lows, closes, 50)
    adx14 = calc_adx(highs, lows, closes, 14)

    # 4H Macro Trend Proxy
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
    for i in range(200, n):
        last_sh_p = last_sh_arr[i]
        last_sl_p = last_sl_arr[i]
        c = closes[i]
        prev_c = closes[i - 1]
        h = highs[i]
        l = lows[i]
        curr_atr = atr14[i] if atr14[i] > 0 else (c * 0.008)

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

        # 2. Triple Divergence
        div_long = (rsi14[i] < 32 and cci20[i] < -110 and l <= last_sl_p and c > l and is_vol_surge[i])
        div_short = (rsi14[i] > 68 and cci20[i] > 110 and h >= last_sh_p and c < h and (micro_bear[i] or c < ema20[i]) and is_vol_surge[i])

        # 3. Potato S&R Liquidity Sweeps
        potato_long = (l < last_sl_p and c >= last_sl_p and is_vol_surge[i])
        potato_short = (h > last_sh_p and c <= last_sh_p and (micro_bear[i] or c < ema20[i]) and is_vol_surge[i])

        # 4. Consensus Momentum
        cons_long = (c > ema20[i] > ema50[i]) and is_vol_surge[i] and is_atr_expanded[i] and rsi14[i] > 55
        cons_short = (c < ema20[i] < ema50[i]) and is_vol_surge[i] and is_atr_expanded[i] and rsi14[i] < 45 and micro_bear[i]

        # 5. 5-EMA Stack Breakout (Cross above/below all 5 MAs: 9, 20, 50, 100, 200)
        is_above_all_5 = (c > ema9[i]) and (c > ema20[i]) and (c > ema50[i]) and (c > ema100[i]) and (c > ema200[i])
        was_above_all_5 = (prev_c > ema9[i - 1]) and (prev_c > ema20[i - 1]) and (prev_c > ema50[i - 1]) and (prev_c > ema100[i - 1]) and (prev_c > ema200[i - 1])
        ema_stack_long = is_above_all_5 and not was_above_all_5

        is_below_all_5 = (c < ema9[i]) and (c < ema20[i]) and (c < ema50[i]) and (c < ema100[i]) and (c < ema200[i])
        was_below_all_5 = (prev_c < ema9[i - 1]) and (prev_c < ema20[i - 1]) and (prev_c < ema50[i - 1]) and (prev_c < ema100[i - 1]) and (prev_c < ema200[i - 1])
        ema_stack_short = is_below_all_5 and not was_below_all_5

        # Midpoint of EMA50 and EMA100 for Stop Loss
        ema_mid_sl = (ema50[i] + ema100[i]) / 2.0

        sig = {
            'fib_long': fib_long, 'fib_short': fib_short,
            'div_long': div_long, 'div_short': div_short,
            'potato_long': potato_long, 'potato_short': potato_short,
            'cons_long': cons_long, 'cons_short': cons_short,
            'ema_stack_long': ema_stack_long, 'ema_stack_short': ema_stack_short,
            'is_above_all_5': is_above_all_5, 'is_below_all_5': is_below_all_5,
            'ema_mid_sl': ema_mid_sl,
            'macro_bull': macro_bull[i], 'macro_bear': macro_bear[i],
            'micro_bull': micro_bull[i], 'micro_bear': micro_bear[i],
            'adx': adx14[i],
            'atr': curr_atr, 'last_sh': last_sh_p, 'last_sl': last_sl_p
        }
        signals.append((i, sig))

    return signals

def run_simulation(strategy_mode="CURRENT_PLUS_5EMA", initial_balance=100.0, leverage=50, margin_pct=0.03, max_positions=5):
    """
    strategy_mode:
    - 'CURRENT_ONLY': Current Live 4-Channel System
    - '5EMA_ONLY': 5-EMA Stack Standalone Strategy
    - 'CURRENT_PLUS_5EMA': Current Live Channels + 5-EMA Stack as 5th Trigger Channel
    - 'CONFLUENCE_FILTER': Current Channels confirmed by 5-EMA alignment
    """
    data = {}
    for sym in SYMBOLS:
        fpath = os.path.join(CACHE_DIR, f"{sym}_15m_from_2025-07-01.csv")
        if not os.path.exists(fpath):
            fpath = os.path.join(CACHE_DIR, f"{sym}_15m_from_2024-08-25.csv")
        if os.path.exists(fpath):
            df = pd.read_csv(fpath)
            t_col = 'open_time' if 'open_time' in df.columns else 'timestamp'
            df['open_time'] = pd.to_datetime(df[t_col], utc=True)
            df = df.sort_values('open_time').reset_index(drop=True)
            data[sym] = df

    min_len = min(len(df) for df in data.values())
    sym_signals = {sym: precompute_market_signals(df) for sym, df in data.items()}

    balance = initial_balance
    peak_balance = balance
    max_drawdown = 0.0
    active_positions = {}
    trade_history = []
    symbol_stats = {sym: {'trades': 0, 'wins': 0, 'pnl': 0.0} for sym in data.keys()}
    channel_stats = {}
    total_fees = 0.0
    last_trade_bar = {sym: -100 for sym in data.keys()}

    for bar_idx in range(210, min_len):
        cur_dt = data['BTCUSDT']['open_time'].iloc[bar_idx]

        # 1. Manage Active Positions
        closed_syms = []
        for sym, pos in list(active_positions.items()):
            h = data[sym]['high'].iloc[bar_idx]
            l = data[sym]['low'].iloc[bar_idx]
            c = data[sym]['close'].iloc[bar_idx]
            is_long = pos['side'] == 'BUY'
            is_short = pos['side'] == 'SELL'

            # Stop Loss Check
            hit_sl = (is_long and l <= pos['sl']) or (is_short and h >= pos['sl'])
            if hit_sl:
                sl_p = pos['sl']
                rem_qty = pos['rem_qty']
                raw_pnl = rem_qty * (sl_p - pos['entry_price']) if is_long else rem_qty * (pos['entry_price'] - sl_p)
                t_fee = rem_qty * sl_p * (FEE_SCHEDULE['taker_fee'] + FEE_SCHEDULE['slippage'])
                total_fees += t_fee
                net_pnl = raw_pnl - t_fee
                balance += net_pnl
                pos['realized_pnl'] += net_pnl
                trade_history.append(pos)
                
                symbol_stats[sym]['trades'] += 1
                symbol_stats[sym]['pnl'] += pos['realized_pnl']
                if pos['realized_pnl'] > 0:
                    symbol_stats[sym]['wins'] += 1

                ch = pos['channel']
                if ch not in channel_stats:
                    channel_stats[ch] = {'trades': 0, 'wins': 0, 'pnl': 0.0}
                channel_stats[ch]['trades'] += 1
                channel_stats[ch]['pnl'] += pos['realized_pnl']
                if pos['realized_pnl'] > 0:
                    channel_stats[ch]['wins'] += 1

                closed_syms.append(sym)
                continue

            # Stage 1: TP1 Check (33% / 50% scale-out)
            if not pos['tp1_hit']:
                tp1_hit = (is_long and h >= pos['tp1']) or (is_short and l <= pos['tp1'])
                if tp1_hit:
                    pos['tp1_hit'] = True
                    q_close = pos['initial_qty'] * pos['scale_pct']
                    pos['rem_qty'] -= q_close
                    tp_p = pos['tp1']
                    raw_pnl = q_close * (tp_p - pos['entry_price']) if is_long else q_close * (pos['entry_price'] - tp_p)
                    m_fee = q_close * tp_p * FEE_SCHEDULE['maker_fee']
                    total_fees += m_fee
                    net_pnl = raw_pnl - m_fee
                    balance += net_pnl
                    pos['realized_pnl'] += net_pnl

                    # Move SL to Breakeven (+0.05% buffer)
                    pos['sl'] = pos['entry_price'] * 1.0005 if is_long else pos['entry_price'] * 0.9995
                    pos['trailing'] = True
                    pos['highest'] = h
                    pos['lowest'] = l

            # Stage 2: TP2 Check (for 3-stage modes)
            if pos['tp1_hit'] and not pos.get('tp2_hit') and pos.get('tp2', 0) > 0:
                tp2_hit = (is_long and h >= pos['tp2']) or (is_short and l <= pos['tp2'])
                if tp2_hit:
                    pos['tp2_hit'] = True
                    q_close = pos['initial_qty'] * 0.33
                    pos['rem_qty'] -= q_close
                    tp_p = pos['tp2']
                    raw_pnl = q_close * (tp_p - pos['entry_price']) if is_long else q_close * (pos['entry_price'] - tp_p)
                    m_fee = q_close * tp_p * FEE_SCHEDULE['maker_fee']
                    total_fees += m_fee
                    net_pnl = raw_pnl - m_fee
                    balance += net_pnl
                    pos['realized_pnl'] += net_pnl

            # Stage 3: Dynamic Trailing Stop Runner
            if pos.get('trailing'):
                trail_dist = pos['trail_dist']
                if is_long:
                    if h > pos['highest']:
                        pos['highest'] = h
                    calc_trail = pos['highest'] - trail_dist
                    if calc_trail > pos['sl'] and calc_trail > pos['entry_price']:
                        pos['sl'] = calc_trail
                elif is_short:
                    if l < pos['lowest']:
                        pos['lowest'] = l
                    calc_trail = pos['lowest'] + trail_dist
                    if calc_trail < pos['sl'] and calc_trail < pos['entry_price']:
                        pos['sl'] = calc_trail

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
            if sym in active_positions or (bar_idx - last_trade_bar[sym]) < 12:
                continue

            sig_list = sym_signals[sym]
            sig_idx = bar_idx - 200
            if sig_idx < 0 or sig_idx >= len(sig_list):
                continue
            _, sig = sig_list[sig_idx]
            cur_p = data[sym]['close'].iloc[bar_idx]
            atr_v = sig['atr']

            # ADX Anti-Chop Gate
            if sig['adx'] < 22.0:
                continue

            action = None
            channel = None
            is_5ema_trade = False

            # Select Channel Candidates based on strategy_mode
            if strategy_mode in ['CURRENT_ONLY', 'CURRENT_PLUS_5EMA', 'CONFLUENCE_FILTER']:
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

            # 5-EMA Stack Trigger
            if not action and strategy_mode in ['5EMA_ONLY', 'CURRENT_PLUS_5EMA']:
                if sig['ema_stack_long'] and long_count < 3:
                    action, channel, is_5ema_trade = 'BUY', '5EMA_STACK', True
                elif sig['ema_stack_short'] and short_count < 3:
                    action, channel, is_5ema_trade = 'SELL', '5EMA_STACK', True

            # Confluence Filter Mode Check: Require price to be aligned with 5-EMA stack
            if strategy_mode == 'CONFLUENCE_FILTER' and action:
                if action == 'BUY' and not sig['is_above_all_5']:
                    action = None
                elif action == 'SELL' and not sig['is_below_all_5']:
                    action = None

            if action:
                # Classify Quick Scalp vs Trend Runner
                is_quick_scalp = (action == 'SELL' and sig['macro_bull']) or (action == 'BUY' and sig['macro_bear'])

                if is_5ema_trade:
                    # 5-EMA Stack Specification: SL @ mid EMA50/100, TP1 @ 1:2 R:R (50% scale-out), 50% runner
                    sl_mid = sig['ema_mid_sl']
                    min_risk = 0.8 * atr_v
                    if action == 'BUY':
                        sl_v = min(sl_mid, cur_p - min_risk)
                        sl_v = max(sl_v, cur_p - (3.5 * atr_v))
                        risk_r = cur_p - sl_v
                        tp1_v = cur_p + (2.0 * risk_r) # 1:2 R:R
                    else:
                        sl_v = max(sl_mid, cur_p + min_risk)
                        sl_v = min(sl_v, cur_p + (3.5 * atr_v))
                        risk_r = sl_v - cur_p
                        tp1_v = cur_p - (2.0 * risk_r) # 1:2 R:R

                    tp2_v = 0.0
                    scale_pct = 0.50
                    trail_dist = 1.0 * atr_v
                    min_rr = 1.8
                else:
                    # Live Current 3-Stage Specification (33% TP1 -> BE -> 33% TP2 -> 34% Trailing Runner)
                    scale_pct = 0.33
                    if is_quick_scalp:
                        tp1_v = (cur_p + 1.3 * atr_v) if action == 'BUY' else (cur_p - 1.3 * atr_v)
                        tp2_v = (cur_p + 2.0 * atr_v) if action == 'BUY' else (cur_p - 2.0 * atr_v)
                        sl_v  = (cur_p - 0.9 * atr_v) if action == 'BUY' else (cur_p + 0.9 * atr_v)
                        trail_dist = 0.7 * atr_v
                        min_rr = 1.2
                    else:
                        tp1_v = (cur_p + 1.8 * atr_v) if action == 'BUY' else (cur_p - 1.8 * atr_v)
                        tp2_v = (cur_p + 2.8 * atr_v) if action == 'BUY' else (cur_p - 2.8 * atr_v)
                        sl_v  = (cur_p - 1.5 * atr_v) if action == 'BUY' else (cur_p + 1.5 * atr_v)
                        trail_dist = 1.4 * atr_v
                        min_rr = 1.8

                risk_d = abs(cur_p - sl_v)
                reward_d = abs((tp2_v if tp2_v > 0 else tp1_v) - cur_p)
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
                    total_fees += e_fee
                    balance -= e_fee

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
                        'scale_pct': scale_pct,
                        'trail_dist': trail_dist,
                        'tp1_hit': False,
                        'tp2_hit': False,
                        'trailing': False,
                        'highest': cur_p,
                        'lowest': cur_p,
                        'channel': channel,
                        'realized_pnl': -e_fee
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
        total_fees += t_fee
        net_pnl = raw_pnl - t_fee
        balance += net_pnl
        pos['realized_pnl'] += net_pnl
        trade_history.append(pos)
        
        symbol_stats[sym]['trades'] += 1
        symbol_stats[sym]['pnl'] += pos['realized_pnl']
        if pos['realized_pnl'] > 0:
            symbol_stats[sym]['wins'] += 1

        ch = pos['channel']
        if ch not in channel_stats:
            channel_stats[ch] = {'trades': 0, 'wins': 0, 'pnl': 0.0}
        channel_stats[ch]['trades'] += 1
        channel_stats[ch]['pnl'] += pos['realized_pnl']
        if pos['realized_pnl'] > 0:
            channel_stats[ch]['wins'] += 1

    tot_trades = len(trade_history)
    wins = [t for t in trade_history if t['realized_pnl'] > 0]
    losses = [t for t in trade_history if t['realized_pnl'] <= 0]
    wr = (len(wins) / tot_trades * 100.0) if tot_trades > 0 else 0.0
    tot_pnl = balance - initial_balance
    roi = (tot_pnl / initial_balance * 100.0)
    gross_profit = sum(t['realized_pnl'] for t in wins)
    gross_loss = abs(sum(t['realized_pnl'] for t in losses))
    pf = (gross_profit / (gross_loss + 1e-9)) if gross_loss > 0 else 99.0
    tp1_rate = (sum(1 for t in trade_history if t.get('tp1_hit')) / tot_trades * 100.0) if tot_trades > 0 else 0.0

    return {
        'mode': strategy_mode,
        'ending_balance': balance,
        'net_pnl': tot_pnl,
        'roi': roi,
        'trades': tot_trades,
        'win_rate': wr,
        'tp1_rate': tp1_rate,
        'profit_factor': pf,
        'max_drawdown': max_drawdown,
        'fees_paid': total_fees,
        'channel_stats': channel_stats,
        'symbol_stats': symbol_stats
    }

def print_master_report():
    print("=" * 115)
    print(" 🚀 INTEGRATED QUANT AUDIT: CURRENT LIVE STRATEGY + 5-EMA STACK SYSTEM")
    print("=" * 115)
    print(" • Universe:              10 Liquid Perpetual Pairs (BTC, ETH, SOL, SUI, NEAR, AVAX, LINK, XRP, DOGE, ADA)")
    print(" • Dataset:               39,459 Bars x 10 Assets on 15m (July 2025 – August 2026)")
    print(" • Friction:              Binance VIP0+BNB (Maker 0.018% | Taker 0.045% | Slip 0.015% | Funding 0.010%)")
    print(" • Risk Architecture:     50x Isolated | 3.0% Dynamic Margin | Midpoint SL | TP 1:2 R:R + Trailing Runner")
    print("=" * 115)

    print("\n⚡ [1/4] Simulating: Baseline (Current Live 4-Channel System)...")
    r_current = run_simulation('CURRENT_ONLY')

    print("⚡ [2/4] Simulating: Standalone 5-EMA Stack Strategy...")
    r_5ema = run_simulation('5EMA_ONLY')

    print("⚡ [3/4] Simulating: Combined Ensemble (Current 4 Channels + 5-EMA Stack as Channel 5)...")
    r_combined = run_simulation('CURRENT_PLUS_5EMA')

    print("⚡ [4/4] Simulating: Confluence Mode (Current Channels Filtered by 5-EMA Alignment)...")
    r_confluence = run_simulation('CONFLUENCE_FILTER')

    print("\n" + "=" * 115)
    print(" 🏆 HEAD-TO-HEAD QUANT RESULTS MATRIX")
    print("=" * 115)
    print(f"{'Strategy Architecture':<34} | {'Trades':>7} | {'Win Rate':>9} | {'TP1 Hit Rate':>13} | {'Profit Factor':>14} | {'Net PnL ($)':>14} | {'Fees Paid':>12}")
    print("-" * 115)
    print(f"{'1. Current Live System (Baseline)':<34} | {r_current['trades']:>7} | {r_current['win_rate']:>8.1f}% | {r_current['tp1_rate']:>12.1f}% | {r_current['profit_factor']:>14.2f} | ${r_current['net_pnl']:>+13.2f} | ${r_current['fees_paid']:>11.2f}")
    print(f"{'2. Standalone 5-EMA Stack':<34} | {r_5ema['trades']:>7} | {r_5ema['win_rate']:>8.1f}% | {r_5ema['tp1_rate']:>12.1f}% | {r_5ema['profit_factor']:>14.2f} | ${r_5ema['net_pnl']:>+13.2f} | ${r_5ema['fees_paid']:>11.2f}")
    print(f"{'3. Combined Ensemble (+ 5-EMA)':<34} | {r_combined['trades']:>7} | {r_combined['win_rate']:>8.1f}% | {r_combined['tp1_rate']:>12.1f}% | {r_combined['profit_factor']:>14.2f} | ${r_combined['net_pnl']:>+13.2f} | ${r_combined['fees_paid']:>11.2f}")
    print(f"{'4. Confluence Filtered Mode':<34} | {r_confluence['trades']:>7} | {r_confluence['win_rate']:>8.1f}% | {r_confluence['tp1_rate']:>12.1f}% | {r_confluence['profit_factor']:>14.2f} | ${r_confluence['net_pnl']:>+13.2f} | ${r_confluence['fees_paid']:>11.2f}")
    print("=" * 115)

    # Channel-by-Channel Breakdown for Combined Ensemble
    print("\n🔬 COMBINED ENSEMBLE CHANNEL CONTRIBUTION BREAKDOWN:")
    print("-" * 115)
    print(f"{'Trigger Channel':<25} | {'Trades':>8} | {'Wins':>8} | {'Win Rate':>12} | {'Net PnL ($)':>16}")
    print("-" * 115)
    for ch, st in r_combined['channel_stats'].items():
        ch_wr = (st['wins'] / st['trades'] * 100.0) if st['trades'] > 0 else 0.0
        print(f" • {ch:<22} | {st['trades']:>8} | {st['wins']:>8} | {ch_wr:>11.1f}% | ${st['pnl']:>+15.2f} USDT")
    print("=" * 115)

if __name__ == '__main__':
    print_master_report()
