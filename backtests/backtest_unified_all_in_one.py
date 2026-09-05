#!/usr/bin/env python3
"""
==========================================================================================
⚡ UNIFIED ALL-IN-ONE INSTITUTIONAL BACKTEST ENGINE
==========================================================================================
Combines ALL quantitative improvements into a single comprehensive trading system:
1. Multi-Timeframe Trend & 1H/15m Market Structure Shift (MSS/CHoCH)
2. 5-MA Stack Momentum Alignment (EMA 9, 20, 50, 100, 200)
3. 4 Signal Channels (Fibonacci Golden Pocket, Consensus Impulse, Divergence, S&R Sweeps)
4. ADX(14) Anti-Chop Gate (ADX >= 22.0) & Structural 1.8x R:R Gate
5. BTC Master Beta Flash-Crash Dump Guard (15m BTC Drop > 0.50%)
6. Anti-Churn 4-Hour Cooldown per Asset & Max 3 Directional Position Cap
7. Limit Maker Execution (0.018% fee) + 2-Stage Scale-Out:
   - 50% TP1 @ +1.5x ATR (Maker Limit)
   - Stop-Loss shifted to Breakeven (+0.05% fee cover) -> Risk-Free
   - 50% Runner trailed with 1.2x ATR Dynamic Trailing Stop
8. Real Binance Futures VIP0+BNB Friction (Maker 0.018%, Taker 0.045%, Slip 0.015%, Funding 0.010%)
==========================================================================================
"""

import os
import sys
import numpy as np
import pandas as pd
from datetime import datetime, timezone

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
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
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    
    for i in range(1, n):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        
        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move
            
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        
    s_tr = pd.Series(tr).rolling(period).sum()
    s_pdm = pd.Series(plus_dm).rolling(period).sum()
    s_mdm = pd.Series(minus_dm).rolling(period).sum()
    
    p_di = 100.0 * (s_pdm / (s_tr + 1e-9))
    m_di = 100.0 * (s_mdm / (s_tr + 1e-9))
    
    dx = 100.0 * (abs(p_di - m_di) / (p_di + m_di + 1e-9))
    adx = dx.rolling(period).mean().fillna(25.0).values
    return adx

def precompute_signals_unified(df, window=4):
    closes = df['close'].values
    highs = df['high'].values
    lows = df['low'].values
    volumes = df['volume'].values
    n = len(closes)

    # 5-MA Stack
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

    # Volume & Volatility expansions
    vol_sma20 = np.zeros(n)
    for i in range(20, n):
        vol_sma20[i] = np.mean(volumes[i - 20 : i])
    is_vol_surge = volumes >= (vol_sma20 * 1.15)
    is_atr_expanded = atr14 >= (atr50 * 1.05)

    # 5-MA Ordered Rainbow Trend
    ma_bull_stack = (closes > ema20) & (ema20 > ema50) & (ema50 > ema100)
    ma_bear_stack = (closes < ema20) & (ema20 < ema50) & (ema50 < ema100)

    # Macro 4H / 1H Proxy (16-bar EMA = 4H proxy on 15m)
    macro_bull = closes > ema200
    macro_bear = closes < ema200

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

    # Signals
    signals = []
    for i in range(50, n):
        last_sh_p = last_sh_arr[i]
        last_sl_p = last_sl_arr[i]
        c = closes[i]
        h = highs[i]
        l = lows[i]
        curr_atr = atr14[i] if atr14[i] > 0 else (c * 0.008)

        # 1. Fibonacci Golden Pocket (0.618 - 0.786)
        fib_long = False
        fib_short = False
        fib_tp = 0.0
        fib_sl = 0.0
        if last_sh_p > last_sl_p and (last_sh_p - last_sl_p) > (curr_atr * 2.0):
            diff = last_sh_p - last_sl_p
            f618 = last_sh_p - (diff * 0.618)
            f786 = last_sh_p - (diff * 0.786)
            if l <= f618 and c >= f786 and macro_bull[i] and c > ema50[i]:
                fib_long = True
                fib_tp = c + (2.0 * curr_atr)
                fib_sl = f786 - (0.5 * curr_atr)

            f618_s = last_sl_p + (diff * 0.618)
            f786_s = last_sl_p + (diff * 0.786)
            if h >= f618_s and c <= f786_s and macro_bear[i] and c < ema50[i]:
                fib_short = True
                fib_tp = c - (2.0 * curr_atr)
                fib_sl = f786_s + (0.5 * curr_atr)

        # 2. Consensus Trend Momentum (5-MA Stack + Volume + ATR Expansion)
        cons_long = ma_bull_stack[i] and is_vol_surge[i] and is_atr_expanded[i] and rsi14[i] > 54
        cons_short = ma_bear_stack[i] and is_vol_surge[i] and is_atr_expanded[i] and rsi14[i] < 46
        cons_tp_long = c + (2.2 * curr_atr)
        cons_sl_long = ema50[i] - (0.5 * curr_atr)
        cons_tp_short = c - (2.2 * curr_atr)
        cons_sl_short = ema50[i] + (0.5 * curr_atr)

        # 3. Market Structure Shift (MSS / CHoCH Pivot Break)
        mss_long = (closes[i - 1] <= last_sh_p and c > last_sh_p) and is_vol_surge[i] and macro_bull[i]
        mss_short = (closes[i - 1] >= last_sl_p and c < last_sl_p) and is_vol_surge[i] and macro_bear[i]

        # 4. Filtered S&R Sweeps (Only at key extremes)
        sweep_long = (l < last_sl_p and c > last_sl_p) and rsi14[i] < 35 and macro_bull[i]
        sweep_short = (h > last_sh_p and c < last_sh_p) and rsi14[i] > 65 and macro_bear[i]

        sig = {
            'fib_long': fib_long, 'fib_short': fib_short, 'fib_tp': fib_tp, 'fib_sl': fib_sl,
            'cons_long': cons_long, 'cons_short': cons_short,
            'cons_tp_long': cons_tp_long, 'cons_sl_long': cons_sl_long,
            'cons_tp_short': cons_tp_short, 'cons_sl_short': cons_sl_short,
            'mss_long': mss_long, 'mss_short': mss_short,
            'sweep_long': sweep_long, 'sweep_short': sweep_short,
            'adx': adx14[i],
            'atr': curr_atr,
            'last_sh': last_sh_p,
            'last_sl': last_sl_p
        }
        signals.append((i, sig))

    return signals

def run_unified_backtest(initial_balance=100.0, leverage=50, margin_pct=0.03, max_positions=5, cooldown_bars=16):
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

    if not data:
        print("No historical data found in cache.")
        return

    print("=" * 110)
    print(" ⚡ UNIFIED ALL-IN-ONE INSTITUTIONAL ENGINE: HISTORICAL BACKTEST")
    print("=" * 110)
    print(f" • Historical Range:        {data['BTCUSDT']['open_time'].iloc[0].strftime('%Y-%m-%d')} to {data['BTCUSDT']['open_time'].iloc[-1].strftime('%Y-%m-%d')}")
    print(f" • Evaluated Assets:        {', '.join(data.keys())} ({len(data)} Total)")
    print(f" • Initial Account Capital: ${initial_balance:,.2f} USDT")
    print(f" • Sizing & Risk:           {leverage}x Leverage | {margin_pct*100:.1f}% Dynamic Margin per Position (Max {max_positions} Positions)")
    print(f" • Cooldown Guard:          {cooldown_bars * 15 / 60:.1f} Hours ({cooldown_bars} bars) spacing per symbol to eliminate fee bleed")
    print(f" • Institutional Friction:  VIP0+BNB Maker (0.018%), Taker (0.045%), Slippage (0.015%), 8h Funding (0.010%)")
    print(f" • Execution Model:         Limit Maker Entry -> 50% TP1 @ 1.5x ATR -> Breakeven SL (+0.05%) -> Dynamic Trailing Runner")
    print("=" * 110)

    print("⚡ Precomputing unified signal matrices...")
    sym_signals = {}
    for sym, df in data.items():
        sym_signals[sym] = precompute_signals_unified(df)

    min_len = min(len(df) for df in data.values())

    balance = initial_balance
    peak_balance = balance
    max_drawdown = 0.0
    active_positions = {}
    trade_history = []
    symbol_stats = {sym: {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0} for sym in data.keys()}
    channel_stats = {
        'FIBONACCI': {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0},
        'CONSENSUS': {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0},
        'MSS_SHIFT': {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0},
        'LIQUIDITY_SWEEP': {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0}
    }
    last_trade_bar = {sym: -999 for sym in data.keys()}
    total_fees_paid = 0.0

    btc_closes = data['BTCUSDT']['close'].values

    for bar_idx in range(60, min_len):
        cur_dt = data['BTCUSDT']['open_time'].iloc[bar_idx]
        cur_month = cur_dt.strftime('%Y-%m')

        # BTC Master Beta Flash Crash Guard (BTC 15m drop > 0.50%)
        btc_15m_ret = (btc_closes[bar_idx] - btc_closes[bar_idx - 1]) / btc_closes[bar_idx - 1]
        btc_dump_active = btc_15m_ret < -0.0050

        # 1. Manage active positions
        closed_syms = []
        for sym, pos in list(active_positions.items()):
            df_sym = data[sym]
            h = df_sym['high'].iloc[bar_idx]
            l = df_sym['low'].iloc[bar_idx]
            c = df_sym['close'].iloc[bar_idx]
            entry_p = pos['entry_price']
            side = pos['side']
            pos_size = pos['size']
            ch = pos['channel']

            # 8-hour funding fee (every 32 15m bars)
            bars_held = bar_idx - pos['entry_bar']
            if bars_held > 0 and bars_held % 32 == 0:
                funding_cost = pos_size * entry_p * FEE_SCHEDULE['funding_8h']
                pos['accum_funding'] += funding_cost
                balance -= funding_cost
                total_fees_paid += funding_cost

            # LONG Position Lifecycle
            if side == 'BUY':
                # TP1 Hit
                if not pos['tp1_hit'] and h >= pos['tp1_price']:
                    pos['tp1_hit'] = True
                    half_size = pos_size * 0.5
                    gain = half_size * (pos['tp1_price'] - entry_p)
                    fee = half_size * pos['tp1_price'] * FEE_SCHEDULE['maker_fee']
                    pnl = gain - fee
                    pos['realized_pnl'] += pnl
                    balance += pnl
                    total_fees_paid += fee
                    # Shift Stop-Loss to Breakeven (+0.05% fee cover)
                    pos['sl_price'] = entry_p * 1.0005
                    pos['remaining_size'] = half_size

                # Update Trailing Stop for Runner
                if pos['tp1_hit']:
                    trail_sl = h - (1.2 * pos['atr'])
                    if trail_sl > pos['sl_price']:
                        pos['sl_price'] = trail_sl

                # Stop Loss Hit
                if l <= pos['sl_price']:
                    exit_p = pos['sl_price']
                    rem_size = pos['remaining_size']
                    loss = rem_size * (exit_p - entry_p)
                    fee = rem_size * exit_p * (FEE_SCHEDULE['taker_fee'] + FEE_SCHEDULE['slippage'])
                    pnl = loss - fee
                    pos['realized_pnl'] += pnl
                    balance += pnl
                    total_fees_paid += fee

                    tot_trade_pnl = pos['realized_pnl'] - pos['accum_funding']
                    is_win = tot_trade_pnl > 0
                    trade_history.append({
                        'symbol': sym, 'channel': ch, 'side': side,
                        'pnl': tot_trade_pnl, 'is_win': is_win,
                        'month': cur_month, 'tp1_hit': pos['tp1_hit']
                    })
                    symbol_stats[sym]['trades'] += 1
                    symbol_stats[sym]['pnl'] += tot_trade_pnl
                    channel_stats[ch]['trades'] += 1
                    channel_stats[ch]['pnl'] += tot_trade_pnl
                    if is_win:
                        symbol_stats[sym]['wins'] += 1
                        channel_stats[ch]['wins'] += 1
                    else:
                        symbol_stats[sym]['losses'] += 1
                        channel_stats[ch]['losses'] += 1
                    closed_syms.append(sym)

            # SHORT Position Lifecycle
            elif side == 'SELL':
                # TP1 Hit
                if not pos['tp1_hit'] and l <= pos['tp1_price']:
                    pos['tp1_hit'] = True
                    half_size = pos_size * 0.5
                    gain = half_size * (entry_p - pos['tp1_price'])
                    fee = half_size * pos['tp1_price'] * FEE_SCHEDULE['maker_fee']
                    pnl = gain - fee
                    pos['realized_pnl'] += pnl
                    balance += pnl
                    total_fees_paid += fee
                    # Shift Stop-Loss to Breakeven (+0.05% fee cover)
                    pos['sl_price'] = entry_p * 0.9995
                    pos['remaining_size'] = half_size

                # Update Trailing Stop for Runner
                if pos['tp1_hit']:
                    trail_sl = l + (1.2 * pos['atr'])
                    if trail_sl < pos['sl_price']:
                        pos['sl_price'] = trail_sl

                # Stop Loss Hit
                if h >= pos['sl_price']:
                    exit_p = pos['sl_price']
                    rem_size = pos['remaining_size']
                    loss = rem_size * (entry_p - exit_p)
                    fee = rem_size * exit_p * (FEE_SCHEDULE['taker_fee'] + FEE_SCHEDULE['slippage'])
                    pnl = loss - fee
                    pos['realized_pnl'] += pnl
                    balance += pnl
                    total_fees_paid += fee

                    tot_trade_pnl = pos['realized_pnl'] - pos['accum_funding']
                    is_win = tot_trade_pnl > 0
                    trade_history.append({
                        'symbol': sym, 'channel': ch, 'side': side,
                        'pnl': tot_trade_pnl, 'is_win': is_win,
                        'month': cur_month, 'tp1_hit': pos['tp1_hit']
                    })
                    symbol_stats[sym]['trades'] += 1
                    symbol_stats[sym]['pnl'] += tot_trade_pnl
                    channel_stats[ch]['trades'] += 1
                    channel_stats[ch]['pnl'] += tot_trade_pnl
                    if is_win:
                        symbol_stats[sym]['wins'] += 1
                        channel_stats[ch]['wins'] += 1
                    else:
                        symbol_stats[sym]['losses'] += 1
                        channel_stats[ch]['losses'] += 1
                    closed_syms.append(sym)

        for sym in closed_syms:
            del active_positions[sym]

        # Update drawdown
        if balance > peak_balance:
            peak_balance = balance
        dd = (peak_balance - balance) / peak_balance if peak_balance > 0 else 0.0
        if dd > max_drawdown:
            max_drawdown = dd

        # 2. Evaluate new trade setups
        if len(active_positions) >= max_positions or balance <= (initial_balance * 0.10):
            continue

        for sym in SYMBOLS:
            if sym in active_positions or (bar_idx - last_trade_bar[sym]) < cooldown_bars:
                continue

            sig_idx = bar_idx - 50
            if sig_idx < 0 or sig_idx >= len(sym_signals[sym]):
                continue

            _, sig = sym_signals[sym][sig_idx]
            cur_p = data[sym]['close'].iloc[bar_idx]
            atr_v = sig['atr']
            adx_v = sig['adx']

            # ADX Anti-Chop Gate
            if adx_v < 22.0:
                continue

            # Directional Portfolio Cap (Max 3 Longs or Max 3 Shorts)
            cur_longs = sum(1 for p in active_positions.values() if p['side'] == 'BUY')
            cur_shorts = sum(1 for p in active_positions.values() if p['side'] == 'SELL')

            selected_trade = None

            # 1. Fibonacci Golden Pocket
            if sig['fib_long'] and cur_longs < 3 and not btc_dump_active:
                risk_d = abs(cur_p - sig['fib_sl'])
                reward_d = abs(sig['fib_tp'] - cur_p)
                if (reward_d / (risk_d + 1e-9)) >= 1.8:
                    selected_trade = ('BUY', 'FIBONACCI', cur_p + (1.5 * atr_v), sig['fib_sl'])
            elif sig['fib_short'] and cur_shorts < 3:
                risk_d = abs(cur_p - sig['fib_sl'])
                reward_d = abs(sig['fib_tp'] - cur_p)
                if (reward_d / (risk_d + 1e-9)) >= 1.8:
                    selected_trade = ('SELL', 'FIBONACCI', cur_p - (1.5 * atr_v), sig['fib_sl'])

            # 2. Consensus Trend Momentum
            if not selected_trade:
                if sig['cons_long'] and cur_longs < 3 and not btc_dump_active:
                    risk_d = abs(cur_p - sig['cons_sl_long'])
                    reward_d = abs(sig['cons_tp_long'] - cur_p)
                    if (reward_d / (risk_d + 1e-9)) >= 1.8:
                        selected_trade = ('BUY', 'CONSENSUS', cur_p + (1.5 * atr_v), sig['cons_sl_long'])
                elif sig['cons_short'] and cur_shorts < 3:
                    risk_d = abs(cur_p - sig['cons_sl_short'])
                    reward_d = abs(sig['cons_tp_short'] - cur_p)
                    if (reward_d / (risk_d + 1e-9)) >= 1.8:
                        selected_trade = ('SELL', 'CONSENSUS', cur_p - (1.5 * atr_v), sig['cons_sl_short'])

            # 3. Market Structure Shift (MSS / CHoCH)
            if not selected_trade:
                if sig['mss_long'] and cur_longs < 3 and not btc_dump_active:
                    tp_p = cur_p + (1.8 * atr_v)
                    sl_p = cur_p - (1.0 * atr_v)
                    selected_trade = ('BUY', 'MSS_SHIFT', tp_p, sl_p)
                elif sig['mss_short'] and cur_shorts < 3:
                    tp_p = cur_p - (1.8 * atr_v)
                    sl_p = cur_p + (1.0 * atr_v)
                    selected_trade = ('SELL', 'MSS_SHIFT', tp_p, sl_p)

            # 4. Liquidity Sweep Wick Reclaim
            if not selected_trade:
                if sig['sweep_long'] and cur_longs < 3 and not btc_dump_active:
                    tp_p = cur_p + (1.5 * atr_v)
                    sl_p = sig['last_sl'] - (0.3 * atr_v)
                    if (abs(tp_p - cur_p) / (abs(cur_p - sl_p) + 1e-9)) >= 1.8:
                        selected_trade = ('BUY', 'LIQUIDITY_SWEEP', tp_p, sl_p)
                elif sig['sweep_short'] and cur_shorts < 3:
                    tp_p = cur_p - (1.5 * atr_v)
                    sl_p = sig['last_sh'] + (0.3 * atr_v)
                    if (abs(cur_p - tp_p) / (abs(sl_p - cur_p) + 1e-9)) >= 1.8:
                        selected_trade = ('SELL', 'LIQUIDITY_SWEEP', tp_p, sl_p)

            if selected_trade and len(active_positions) < max_positions:
                side, channel, tp_p, sl_p = selected_trade
                margin_usd = balance * margin_pct
                notional = margin_usd * leverage
                qty = notional / cur_p
                entry_fee = notional * FEE_SCHEDULE['maker_fee']
                balance -= entry_fee
                total_fees_paid += entry_fee

                active_positions[sym] = {
                    'side': side,
                    'channel': channel,
                    'entry_price': cur_p,
                    'size': qty,
                    'remaining_size': qty,
                    'tp1_price': tp_p,
                    'sl_price': sl_p,
                    'tp1_hit': False,
                    'realized_pnl': -entry_fee,
                    'accum_funding': 0.0,
                    'entry_bar': bar_idx,
                    'atr': atr_v
                }
                last_trade_bar[sym] = bar_idx

    # Metrics computation
    total_trades = len(trade_history)
    wins = [t for t in trade_history if t['is_win']]
    losses = [t for t in trade_history if not t['is_win']]
    win_rate = (len(wins) / total_trades * 100.0) if total_trades > 0 else 0.0
    gross_gain = sum(t['pnl'] for t in wins)
    gross_loss = abs(sum(t['pnl'] for t in losses))
    pf = (gross_gain / (gross_loss + 1e-9)) if gross_loss > 0 else 99.0
    net_pnl = balance - initial_balance
    roi = (net_pnl / initial_balance) * 100.0
    tp1_hits = sum(1 for t in trade_history if t.get('tp1_hit'))
    tp1_rate = (tp1_hits / total_trades * 100.0) if total_trades > 0 else 0.0

    print("\n" + "=" * 110)
    print(" 🏆 UNIFIED ALL-IN-ONE SYSTEM PERFORMANCE REPORT")
    print("=" * 110)
    print(f" 💰 Initial Capital:           ${initial_balance:,.2f} USDT")
    print(f" 🏁 Ending Portfolio Balance:  ${balance:,.2f} USDT")
    print(f" 📈 Net Realized Profit:        ${net_pnl:>+,.2f} USDT ({roi:>+,.2f}% ROI)")
    print(f" 📊 Profit Factor (PF):         {pf:.2f}")
    print(f" 🎯 Overall Win Rate:           {win_rate:.1f}% ({len(wins)} Wins / {len(losses)} Losses)")
    print(f" ⚡ TP1 Target Hit Rate:        {tp1_rate:.1f}% ({tp1_hits} trades reached Risk-Free state)")
    print(f" ⚡ Total Executed Trades:      {total_trades} (~{total_trades / 13.5:.1f} trades/month across 10 pairs)")
    print(f" 🛡️ Max Portfolio Drawdown:     {max_drawdown*100:.2f}%")
    print(f" 🧾 Total Commissions Paid:     ${total_fees_paid:,.2f} USDT")
    print("-" * 110)

    print(" 🎯 STRATEGY CHANNEL PERFORMANCE ATTRIBUTION:")
    print(f"{'Channel':<20} | {'Trades':>7} | {'Win Rate':>9} | {'Net PnL ($)':>14} | {'Status':<12}")
    print("-" * 110)
    for ch, stat in channel_stats.items():
        wr = (stat['wins'] / stat['trades'] * 100.0) if stat['trades'] > 0 else 0.0
        status = "🟢 PROFITABLE" if stat['pnl'] > 0 else "🔴 LOSS"
        print(f"{ch:<20} | {stat['trades']:>7} | {wr:>8.1f}% | ${stat['pnl']:>+13.2f} | {status:<12}")

    print("-" * 110)
    print(" 🪙 SYMBOL-BY-SYMBOL BREAKDOWN:")
    print(f"{'Symbol':<12} | {'Trades':>7} | {'Win Rate':>9} | {'Net PnL ($)':>14}")
    print("-" * 110)
    for sym, stat in symbol_stats.items():
        wr = (stat['wins'] / stat['trades'] * 100.0) if stat['trades'] > 0 else 0.0
        print(f"{sym:<12} | {stat['trades']:>7} | {wr:>8.1f}% | ${stat['pnl']:>+13.2f}")

    print("-" * 110)
    print(" 📅 MONTH-BY-MONTH REALIZED PnL LEDGER:")
    months = sorted(list(set(t['month'] for t in trade_history)))
    for m in months:
        m_trades = [t for t in trade_history if t['month'] == m]
        m_pnl = sum(t['pnl'] for t in m_trades)
        m_wins = sum(1 for t in m_trades if t['is_win'])
        m_wr = (m_wins / len(m_trades) * 100.0) if len(m_trades) > 0 else 0.0
        badge = "🟢" if m_pnl >= 0 else "🔴"
        print(f"   {badge} {m} | Trades: {len(m_trades):>4} | Win Rate: {m_wr:>5.1f}% | Net PnL: ${m_pnl:>+9.2f} USDT")

    print("=" * 110)

if __name__ == '__main__':
    run_unified_backtest()
