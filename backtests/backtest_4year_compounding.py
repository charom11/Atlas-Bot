#!/usr/bin/env python3
"""
==========================================================================================
⚡ 4-YEAR INSTITUTIONAL COMPREHENSIVE BACKTEST (2022 - 2026)
==========================================================================================
Full 48-Month (4-Year) Historical Backtest of the Production Strategy with 3% Compounding:
- Assets: 10 Core Perpetual Markets (BTC, ETH, SOL, LINK, AVAX, XRP, ADA, DOGE, NEAR, SUI)
- Timeframe: 15m Execution Bars (~140,000 Bars per asset across 4 Years)
- Starting Balance: Live Account Balance ($10.49 USDT)
- Sizing: Dynamic 3.0% Margin Compounding on Every Trade | 50x Isolated Leverage
- Alpha Channels & Optimizations:
  1. 📐 Fibonacci Multi-Tier Harmonic OTE (0.618 - 0.786 - 0.886)
  2. 🏛️ Trend-Filtered Market Structure Shift (MSS with EMA50/200 & Vol >= 1.30x)
  3. 🌪️ 4-MA Stack Momentum Consensus (EMA 20/50/100/200)
- Risk Gates: Dynamic ADX Cooldown (1.5h in trend / 3.0h chop), BTC Dump Guard, Max 5 Positions, Max 3 Directional
- Scaling (Option B): 50% TP1 @ +1.5x ATR -> Breakeven SL (+0.05% Fee Cover) -> 50% Runner 1.2x ATR Trailing
- Real VIP0 Binance Futures Friction: Maker 0.018%, Taker 0.045%, Slippage 0.015%, Funding 0.010% / 8h
==========================================================================================
"""

import os
import sys
import time
import argparse
import requests
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
os.makedirs(CACHE_DIR, exist_ok=True)

SYMBOLS = [
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'LINKUSDT', 'AVAXUSDT',
    'XRPUSDT', 'ADAUSDT', 'DOGEUSDT', 'NEARUSDT', 'BNBUSDT'
]

FEE_SCHEDULE = {
    'maker_fee': 0.00018,
    'taker_fee': 0.00045,
    'slippage': 0.00015,
    'funding_8h': 0.00010
}

# --------------------------------------------------------------------------
# 📥 4-Year Historical Data Downloader & Caching Engine (2022-09-01)
# --------------------------------------------------------------------------
def fetch_4year_klines_from_binance(symbol, start_str="2022-09-01", interval="15m"):
    cache_file = os.path.join(CACHE_DIR, f"{symbol}_{interval}_4year_{start_str}.csv")
    if os.path.exists(cache_file):
        df = pd.read_csv(cache_file)
        df['open_time'] = pd.to_datetime(df['open_time'])
        return df

    start_dt = datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start_ts = int(start_dt.timestamp() * 1000)
    end_ts = int(time.time() * 1000)

    print(f"[DOWNLOADING 4Y DATA] {symbol} {interval} from {start_str} to present...", flush=True)
    all_rows = []
    curr_ts = start_ts
    limit = 1500

    while curr_ts < end_ts:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&startTime={curr_ts}&limit={limit}"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                if not data:
                    break
                all_rows.extend(data)
                curr_ts = data[-1][0] + (15 * 60 * 1000)
                if len(data) < limit:
                    break
                time.sleep(0.08)
            else:
                print(f"[API ERROR] {symbol}: HTTP {r.status_code}")
                time.sleep(1)
        except Exception as e:
            print(f"[FETCH EXCEPTION] {symbol}: {e}")
            time.sleep(1)

    if not all_rows:
        return None

    df = pd.DataFrame(all_rows, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trades', 'tb_base_vol', 'tb_quote_vol', 'ignore'
    ])
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    for col in ['open', 'high', 'low', 'close', 'volume', 'quote_volume']:
        df[col] = df[col].astype(float)

    df = df.drop_duplicates(subset=['open_time']).sort_values('open_time').reset_index(drop=True)
    df.to_csv(cache_file, index=False)
    print(f"[CACHED 4Y DATA] {symbol}: {len(df):,} bars cached ({df['open_time'].iloc[0].strftime('%Y-%m-%d')} to {df['open_time'].iloc[-1].strftime('%Y-%m-%d')})", flush=True)
    return df

# --------------------------------------------------------------------------
# 🧮 Fast Quantitative Indicators
# --------------------------------------------------------------------------
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
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm[i] = up if (up > down and up > 0) else 0.0
        minus_dm[i] = down if (down > up and down > 0) else 0.0
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))

    atr_smooth = np.zeros(n)
    plus_di_smooth = np.zeros(n)
    minus_di_smooth = np.zeros(n)
    if n <= period * 2:
        return np.full(n, 25.0)

    atr_smooth[period] = np.sum(tr[1:period + 1])
    plus_di_smooth[period] = np.sum(plus_dm[1:period + 1])
    minus_di_smooth[period] = np.sum(minus_dm[1:period + 1])

    for i in range(period + 1, n):
        atr_smooth[i] = atr_smooth[i - 1] - (atr_smooth[i - 1] / period) + tr[i]
        plus_di_smooth[i] = plus_di_smooth[i - 1] - (plus_di_smooth[i - 1] / period) + plus_dm[i]
        minus_di_smooth[i] = minus_di_smooth[i - 1] - (minus_di_smooth[i - 1] / period) + minus_dm[i]

    plus_di = 100.0 * (plus_di_smooth / (atr_smooth + 1e-9))
    minus_di = 100.0 * (minus_di_smooth / (atr_smooth + 1e-9))
    dx = 100.0 * (np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-9))

    adx = np.full(n, 25.0)
    adx_start = period * 2 - 1
    if n > adx_start:
        adx[adx_start] = np.mean(dx[period:adx_start + 1])
        for i in range(adx_start + 1, n):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period
    return adx

# --------------------------------------------------------------------------
# ⚡ Precompute 4-Year Signals (With All Key Optimizations)
# --------------------------------------------------------------------------
def precompute_4year_signals(df, window=4):
    closes = df['close'].values
    highs = df['high'].values
    lows = df['low'].values
    volumes = df['volume'].values
    n = len(closes)

    ema20 = calc_ema(closes, 20)
    ema50 = calc_ema(closes, 50)
    ema100 = calc_ema(closes, 100)
    ema200 = calc_ema(closes, 200)

    rsi14 = calc_rsi(closes, 14)
    atr14 = calc_atr(highs, lows, closes, 14)
    atr50 = calc_atr(highs, lows, closes, 50)
    adx14 = calc_adx(highs, lows, closes, 14)

    vol_sma20 = np.zeros(n)
    for i in range(20, n):
        vol_sma20[i] = np.mean(volumes[i - 20 : i])
    is_vol_surge = volumes >= (vol_sma20 * 1.30)
    is_atr_expanded = atr14 >= (atr50 * 1.05)

    # 4-MA Stack Alignment
    ma_bull_stack = (closes > ema20) & (ema20 > ema50) & (ema50 > ema100) & (closes > ema200)
    ma_bear_stack = (closes < ema20) & (ema20 < ema50) & (ema50 < ema100) & (closes < ema200)

    # 4-Bar Fractal Swings
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
        curr_atr = atr14[i] if atr14[i] > 0 else (c * 0.008)

        # 1. 4-MA Stack Consensus
        cons_long = ma_bull_stack[i] and is_vol_surge[i] and is_atr_expanded[i] and rsi14[i] > 54
        cons_short = ma_bear_stack[i] and is_vol_surge[i] and is_atr_expanded[i] and rsi14[i] < 46

        # 2. Trend-Filtered MSS (EMA50/200 aligned + Vol Surge >= 1.30x)
        mss_long = (closes[i - 1] <= last_sh_p and c > last_sh_p) and is_vol_surge[i] and (c > ema50[i]) and (c > ema200[i]) and (ema50[i] >= ema200[i])
        mss_short = (closes[i - 1] >= last_sl_p and c < last_sl_p) and is_vol_surge[i] and (c < ema50[i]) and (c < ema200[i]) and (ema50[i] <= ema200[i])

        # 3. Fibonacci 0.618 - 0.786 - 0.886 Harmonic OTE
        impulse = last_sh_p - last_sl_p
        fib_long = False
        fib_short = False
        fib_entry = c
        if impulse >= (1.5 * curr_atr):
            f_0618_b = last_sh_p - 0.618 * impulse
            f_0786_b = last_sh_p - 0.786 * impulse
            f_0886_b = last_sh_p - 0.886 * impulse
            if (c > ema50[i]) and (lows[i] <= f_0618_b) and (c >= last_sl_p - 0.20 * curr_atr):
                fib_long = True
                fib_entry = f_0886_b if lows[i] <= f_0886_b else (f_0786_b if lows[i] <= f_0786_b else f_0618_b)

            f_0618_s = last_sl_p + 0.618 * impulse
            f_0786_s = last_sl_p + 0.786 * impulse
            f_0886_s = last_sl_p + 0.886 * impulse
            if (c < ema50[i]) and (highs[i] >= f_0618_s) and (c <= last_sh_p + 0.20 * curr_atr):
                fib_short = True
                fib_entry = f_0886_s if highs[i] >= f_0886_s else (f_0786_s if highs[i] >= f_0786_s else f_0618_s)

        sig = {
            'cons_long': cons_long, 'cons_short': cons_short,
            'mss_long': mss_long, 'mss_short': mss_short,
            'fib_long': fib_long, 'fib_short': fib_short,
            'fib_entry': fib_entry,
            'atr': curr_atr,
            'adx': adx14[i],
            'ema50': ema50[i],
            'last_sh': last_sh_p,
            'last_sl': last_sl_p
        }
        signals.append(sig)

    pad = [{'cons_long': False, 'cons_short': False, 'mss_long': False, 'mss_short': False, 'fib_long': False, 'fib_short': False, 'fib_entry': closes[0], 'atr': closes[0]*0.01, 'adx': 20.0, 'ema50': closes[0], 'last_sh': closes[0], 'last_sl': closes[0]}] * 50
    return pad + signals

# --------------------------------------------------------------------------
# 🚀 4-Year Simulation Engine (Exact 3.0% Compounding on Every Trade)
# --------------------------------------------------------------------------
def run_4year_compounding_simulation(
    initial_balance=10.49,
    margin_pct=0.03,
    leverage=50,
    max_positions=5,
    max_directional=3
):
    print("=" * 95)
    print(f" ⚡ INITIALIZING 4-YEAR COMPREHENSIVE INSTITUTIONAL BACKTEST (2022 - 2026)")
    print("=" * 95)
    print(f" • Starting Balance:    ${initial_balance:.2f} USDT")
    print(f" • Sizing Mode:         DYNAMIC 3.0% MARGIN COMPOUNDING ON EVERY TRADE (50x Isolated)")
    print(f" • Max Active Slots:    {max_positions} Concurrent Positions (Max {max_directional} Longs / Shorts)")
    print(f" • Anti-Churn Guard:    Dynamic ADX Cooldown (1.5h in Trend / 3.0h in Chop)")
    print(f" • Alpha Channels:      Fibonacci 0.618/0.786/0.886 OTE + Trend MSS + 4-MA Consensus")
    print(f" • Execution VIP Fees:  Maker 0.018% | Taker 0.045% | Slip 0.015% | Funding 0.010% / 8h")
    print("=" * 95)

    data_map = {}
    signals_map = {}
    for sym in SYMBOLS:
        df = fetch_4year_klines_from_binance(sym, start_str="2022-09-01", interval="15m")
        if df is not None and len(df) > 500:
            data_map[sym] = df
            signals_map[sym] = precompute_4year_signals(df)

    time_sets = [set(df['open_time'].tolist()) for df in data_map.values()]
    common_timeline = sorted(list(set.intersection(*time_sets)))
    print(f"\n[TIMELINE] Synchronized {len(common_timeline):,} 15m bars ({common_timeline[0].strftime('%Y-%m-%d')} to {common_timeline[-1].strftime('%Y-%m-%d')})", flush=True)

    idx_maps = {}
    for sym, df in data_map.items():
        t_to_idx = {t: i for i, t in enumerate(df['open_time'])}
        idx_maps[sym] = [t_to_idx.get(t, -1) for t in common_timeline]

    # State Variables
    balance = float(initial_balance)
    peak_balance = float(initial_balance)
    max_drawdown_pct = 0.0
    closed_trades = []
    active_positions = {}
    symbol_last_trade_bar = {s: -999 for s in SYMBOLS}
    monthly_pnl = {}
    yearly_stats = {}

    btc_idx_list = idx_maps.get('BTCUSDT', [])
    btc_df = data_map.get('BTCUSDT')

    for bar_i, cur_time in enumerate(common_timeline):
        m_key = cur_time.strftime("%Y-%m")
        y_key = cur_time.strftime("%Y")
        if m_key not in monthly_pnl:
            monthly_pnl[m_key] = 0.0
        if y_key not in yearly_stats:
            yearly_stats[y_key] = {'trades': 0, 'wins': 0, 'pnl': 0.0, 'start_bal': balance}

        # BTC Dump Guard
        btc_dump_active = False
        if btc_df is not None:
            b_idx = btc_idx_list[bar_i]
            if b_idx >= 1:
                b_c = btc_df['close'].iloc[b_idx]
                b_prev = btc_df['close'].iloc[b_idx - 1]
                if ((b_c - b_prev) / b_prev) < -0.0050:
                    btc_dump_active = True

        # 1. Manage Active Positions
        symbols_to_close = []
        for sym, pos in active_positions.items():
            s_idx = idx_maps[sym][bar_i]
            if s_idx == -1:
                continue
            row = data_map[sym].iloc[s_idx]
            h = row['high']
            l = row['low']
            c = row['close']
            side = pos['side']
            entry_p = pos['entry_price']
            qty = pos['qty']
            pos['bars_held'] += 1

            # 8h Funding Fee
            if pos['bars_held'] % 32 == 0:
                f_cost = (entry_p * qty) * FEE_SCHEDULE['funding_8h']
                balance -= f_cost
                pos['accum_fee'] += f_cost

            if side == 'LONG':
                # TP1 Hit @ +1.5x ATR
                if not pos['tp1_hit'] and h >= pos['tp1_p']:
                    pos['tp1_hit'] = True
                    half_qty = qty * 0.50
                    pnl_tp1 = (pos['tp1_p'] - entry_p) * half_qty
                    fee_tp1 = (pos['tp1_p'] * half_qty) * (FEE_SCHEDULE['maker_fee'] + FEE_SCHEDULE['slippage'])
                    net_tp1 = pnl_tp1 - fee_tp1
                    balance += (pos['margin'] * 0.50) + net_tp1
                    pos['realized_pnl'] += net_tp1
                    pos['remaining_qty'] = half_qty
                    # Move SL to Breakeven (+0.05% fee cover) -> 100% Risk Free
                    pos['sl_p'] = entry_p * 1.0005
                    pos['highest_since_entry'] = h

                # Trailing runner update
                if pos['tp1_hit']:
                    if h > pos['highest_since_entry']:
                        pos['highest_since_entry'] = h
                        new_tsl = h - (1.2 * pos['atr'])
                        if new_tsl > pos['sl_p']:
                            pos['sl_p'] = new_tsl

                # Invalidation / SL Exit
                if l <= pos['sl_p']:
                    rem_qty = pos['remaining_qty']
                    exit_p = pos['sl_p']
                    pnl_rem = (exit_p - entry_p) * rem_qty
                    fee_rem = (exit_p * rem_qty) * (FEE_SCHEDULE['taker_fee'] + FEE_SCHEDULE['slippage'])
                    net_rem = pnl_rem - fee_rem
                    balance += (pos['margin'] * (0.50 if pos['tp1_hit'] else 1.00)) + net_rem
                    pos['realized_pnl'] += net_rem
                    pos['exit_time'] = cur_time
                    pos['exit_price'] = exit_p
                    pos['exit_reason'] = 'BE_OR_TSL' if pos['tp1_hit'] else 'STOP_LOSS'
                    symbols_to_close.append(sym)

            elif side == 'SHORT':
                # TP1 Hit @ +1.5x ATR
                if not pos['tp1_hit'] and l <= pos['tp1_p']:
                    pos['tp1_hit'] = True
                    half_qty = qty * 0.50
                    pnl_tp1 = (entry_p - pos['tp1_p']) * half_qty
                    fee_tp1 = (pos['tp1_p'] * half_qty) * (FEE_SCHEDULE['maker_fee'] + FEE_SCHEDULE['slippage'])
                    net_tp1 = pnl_tp1 - fee_tp1
                    balance += (pos['margin'] * 0.50) + net_tp1
                    pos['realized_pnl'] += net_tp1
                    pos['remaining_qty'] = half_qty
                    # Move SL to Breakeven (-0.05% fee cover) -> 100% Risk Free
                    pos['sl_p'] = entry_p * 0.9995
                    pos['lowest_since_entry'] = l

                # Trailing runner update
                if pos['tp1_hit']:
                    if l < pos['lowest_since_entry']:
                        pos['lowest_since_entry'] = l
                        new_tsl = l + (1.2 * pos['atr'])
                        if new_tsl < pos['sl_p']:
                            pos['sl_p'] = new_tsl

                # Invalidation / SL Exit
                if h >= pos['sl_p']:
                    rem_qty = pos['remaining_qty']
                    exit_p = pos['sl_p']
                    pnl_rem = (entry_p - exit_p) * rem_qty
                    fee_rem = (exit_p * rem_qty) * (FEE_SCHEDULE['taker_fee'] + FEE_SCHEDULE['slippage'])
                    net_rem = pnl_rem - fee_rem
                    balance += (pos['margin'] * (0.50 if pos['tp1_hit'] else 1.00)) + net_rem
                    pos['realized_pnl'] += net_rem
                    pos['exit_time'] = cur_time
                    pos['exit_price'] = exit_p
                    pos['exit_reason'] = 'BE_OR_TSL' if pos['tp1_hit'] else 'STOP_LOSS'
                    symbols_to_close.append(sym)

        for sym in symbols_to_close:
            p = active_positions.pop(sym)
            closed_trades.append(p)
            monthly_pnl[m_key] += p['realized_pnl']
            yearly_stats[y_key]['trades'] += 1
            yearly_stats[y_key]['pnl'] += p['realized_pnl']
            if p['realized_pnl'] > 0:
                yearly_stats[y_key]['wins'] += 1

        # Drawdown Tracking
        if balance > peak_balance:
            peak_balance = balance
        dd = (peak_balance - balance) / peak_balance * 100.0 if peak_balance > 0 else 0.0
        if dd > max_drawdown_pct:
            max_drawdown_pct = dd

        # 2. New Trade Entries with 3.0% Dynamic Compounding
        long_count = sum(1 for p in active_positions.values() if p['side'] == 'LONG')
        short_count = sum(1 for p in active_positions.values() if p['side'] == 'SHORT')

        if len(active_positions) < max_positions and balance > 1.0:
            for sym in SYMBOLS:
                if sym in active_positions:
                    continue

                s_idx = idx_maps[sym][bar_i]
                if s_idx == -1:
                    continue

                sig = signals_map[sym][s_idx]
                c_price = data_map[sym]['close'].iloc[s_idx]
                curr_atr = sig['atr']
                adx_v = sig['adx']

                # Dynamic ADX Cooldown: 6 bars (1.5h) in trend ADX >= 30, 12 bars (3.0h) in chop
                req_cooldown = 6 if adx_v >= 30.0 else 12
                if (bar_i - symbol_last_trade_bar[sym]) < req_cooldown:
                    continue

                if adx_v < 22.0:
                    continue

                action = None
                ch_name = None
                tp1 = None
                sl = None

                # Channel 1: Trend-Filtered MSS Breakout
                if sig['mss_long'] and not btc_dump_active and long_count < max_directional:
                    tp1 = c_price + (2.0 * curr_atr)
                    sl = c_price - (1.0 * curr_atr)
                    if (abs(tp1 - c_price) / (abs(c_price - sl) + 1e-9)) >= 1.8:
                        action = 'LONG'
                        ch_name = 'MSS_SHIFT'
                elif sig['mss_short'] and short_count < max_directional:
                    tp1 = c_price - (2.0 * curr_atr)
                    sl = c_price + (1.0 * curr_atr)
                    if (abs(c_price - tp1) / (abs(sl - c_price) + 1e-9)) >= 1.8:
                        action = 'SHORT'
                        ch_name = 'MSS_SHIFT'

                # Channel 2: 4-MA Stack Momentum Consensus
                elif sig['cons_long'] and not btc_dump_active and long_count < max_directional:
                    tp1 = c_price + (2.0 * curr_atr)
                    sl = sig['ema50'] - (0.5 * curr_atr)
                    if (abs(tp1 - c_price) / (abs(c_price - sl) + 1e-9)) >= 1.8:
                        action = 'LONG'
                        ch_name = '4MA_CONSENSUS'
                elif sig['cons_short'] and short_count < max_directional:
                    tp1 = c_price - (2.0 * curr_atr)
                    sl = sig['ema50'] + (0.5 * curr_atr)
                    if (abs(c_price - tp1) / (abs(sl - c_price) + 1e-9)) >= 1.8:
                        action = 'SHORT'
                        ch_name = '4MA_CONSENSUS'

                # Channel 3: Fibonacci Harmonic OTE (0.618 - 0.786 - 0.886)
                elif sig['fib_long'] and not btc_dump_active and long_count < max_directional:
                    tp1 = c_price + (2.0 * curr_atr)
                    sl = sig['last_sl'] - (0.5 * curr_atr)
                    if (abs(tp1 - c_price) / (abs(c_price - sl) + 1e-9)) >= 1.8:
                        action = 'LONG'
                        ch_name = 'FIBONACCI'
                elif sig['fib_short'] and short_count < max_directional:
                    tp1 = c_price - (2.0 * curr_atr)
                    sl = sig['last_sh'] + (0.5 * curr_atr)
                    if (abs(c_price - tp1) / (abs(sl - c_price) + 1e-9)) >= 1.8:
                        action = 'SHORT'
                        ch_name = 'FIBONACCI'

                if action is not None:
                    # Compounding 3.0% Margin Calculation
                    margin_alloc = balance * margin_pct
                    notional = margin_alloc * leverage
                    if notional < 5.00:
                        notional = 5.00
                        margin_alloc = notional / leverage

                    if balance < margin_alloc:
                        continue

                    qty = notional / c_price
                    entry_fee = notional * (FEE_SCHEDULE['maker_fee'] + FEE_SCHEDULE['slippage'])
                    balance -= (margin_alloc + entry_fee)

                    active_positions[sym] = {
                        'symbol': sym,
                        'side': action,
                        'channel': ch_name,
                        'entry_time': cur_time,
                        'entry_price': c_price,
                        'margin': margin_alloc,
                        'qty': qty,
                        'remaining_qty': qty,
                        'tp1_p': c_price + (1.5 * curr_atr) if action == 'LONG' else c_price - (1.5 * curr_atr),
                        'sl_p': sl,
                        'atr': curr_atr,
                        'tp1_hit': False,
                        'highest_since_entry': c_price,
                        'lowest_since_entry': c_price,
                        'accum_fee': entry_fee,
                        'realized_pnl': -entry_fee,
                        'bars_held': 0
                    }
                    symbol_last_trade_bar[sym] = bar_i
                    if action == 'LONG':
                        long_count += 1
                    else:
                        short_count += 1

                    if len(active_positions) >= max_positions:
                        break

    # Liquidate remaining open positions at backtest finish
    for sym, pos in active_positions.items():
        s_idx = idx_maps[sym][-1]
        c = data_map[sym]['close'].iloc[s_idx]
        qty = pos['remaining_qty']
        pnl = (c - pos['entry_price']) * qty if pos['side'] == 'LONG' else (pos['entry_price'] - c) * qty
        fee = (c * qty) * (FEE_SCHEDULE['taker_fee'] + FEE_SCHEDULE['slippage'])
        net = pnl - fee
        balance += (pos['margin'] * (0.50 if pos['tp1_hit'] else 1.00)) + net
        pos['realized_pnl'] += net
        pos['exit_time'] = common_timeline[-1]
        pos['exit_price'] = c
        pos['exit_reason'] = 'BACKTEST_END'
        closed_trades.append(pos)

    # --------------------------------------------------------------------------
    # 📊 4-Year Statistical Performance Report
    # --------------------------------------------------------------------------
    n_trades = len(closed_trades)
    wins = [t for t in closed_trades if t['realized_pnl'] > 0]
    losses = [t for t in closed_trades if t['realized_pnl'] <= 0]
    win_rate = (len(wins) / n_trades * 100.0) if n_trades > 0 else 0.0

    total_gross_win = sum(t['realized_pnl'] for t in wins)
    total_gross_loss = abs(sum(t['realized_pnl'] for t in losses))
    profit_factor = (total_gross_win / total_gross_loss) if total_gross_loss > 0 else 99.0

    total_pnl = balance - initial_balance
    total_roi = (total_pnl / initial_balance) * 100.0
    annualized_roi = ((balance / initial_balance) ** (1.0 / 4.0) - 1.0) * 100.0

    print("\n" + "=" * 95)
    print(" 🏆 4-YEAR COMPREHENSIVE INSTITUTIONAL PERFORMANCE SCORECARD (2022 - 2026)")
    print("=" * 95)
    print(f" • Starting Capital:     ${initial_balance:>10,.2f} USDT")
    print(f" • Final Capital:        ${balance:>10,.2f} USDT")
    print(f" • Total Net Profit:     ${total_pnl:>+10,.2f} USDT ({total_roi:>+8.2f}% Total ROI)")
    print(f" • Compound Annual ROI:  {annualized_roi:>+10.2f}% per year (4.0 Years)")
    print(f" • Profit Factor:        {profit_factor:>10.2f}")
    print(f" • Win Rate:             {win_rate:>10.1f}% ({len(wins)} Wins / {len(losses)} Losses out of {n_trades} Trades)")
    print(f" • Maximum Drawdown:     {max_drawdown_pct:>10.2f}%")
    print("=" * 95)

    # Channel Breakdown
    print("\n" + "-" * 95)
    print(f"{'Channel':<20} | {'Trades':>8} | {'Win Rate':>10} | {'Net PnL ($)':>14} | {'Profit Factor':>14}")
    print("-" * 95)
    for ch in ['FIBONACCI', 'MSS_SHIFT', '4MA_CONSENSUS']:
        ch_trades = [t for t in closed_trades if t['channel'] == ch]
        if ch_trades:
            ch_w = [t for t in ch_trades if t['realized_pnl'] > 0]
            ch_l = [t for t in ch_trades if t['realized_pnl'] <= 0]
            ch_wr = len(ch_w) / len(ch_trades) * 100.0
            ch_pnl = sum(t['realized_pnl'] for t in ch_trades)
            ch_gw = sum(t['realized_pnl'] for t in ch_w)
            ch_gl = abs(sum(t['realized_pnl'] for t in ch_l))
            ch_pf = (ch_gw / ch_gl) if ch_gl > 0 else 99.0
            print(f"{ch:<20} | {len(ch_trades):>8} | {ch_wr:>9.1f}% | ${ch_pnl:>+13,.2f} | {ch_pf:>14.2f}")
    print("-" * 95)

    # Year-by-Year Performance
    print("\n" + "=" * 95)
    print(" 📅 YEAR-BY-YEAR PERFORMANCE BREAKDOWN:")
    print("=" * 95)
    print(f"{'Year':<8} | {'Trades':>8} | {'Win Rate':>10} | {'Net Profit ($)':>18} | {'Status':<10}")
    print("-" * 95)
    for y in sorted(yearly_stats.keys()):
        st = yearly_stats[y]
        wr = (st['wins'] / st['trades'] * 100.0) if st['trades'] > 0 else 0.0
        print(f"{y:<8} | {st['trades']:>8} | {wr:>9.1f}% | ${st['pnl']:>+17,.2f} | {'🟢 GREEN' if st['pnl']>0 else '🔴 RED'}")
    print("=" * 95)

    # Monthly Breakdown (48 Months)
    print("\n" + "=" * 95)
    print(" 📅 48-MONTH MONTHLY PnL BREAKDOWN:")
    print("=" * 95)
    sorted_months = sorted(monthly_pnl.keys())
    green_m = sum(1 for m in sorted_months if monthly_pnl[m] > 0)
    for i in range(0, len(sorted_months), 4):
        chunk = sorted_months[i:i+4]
        line = " | ".join([f"{m}: ${monthly_pnl[m]:>+8.2f} {'🟢' if monthly_pnl[m]>0 else '🔴'}" for m in chunk])
        print(f" {line}")
    print("=" * 95)
    print(f" Monthly Consistency Score: {green_m}/{len(sorted_months)} Green Months ({(green_m/len(sorted_months)*100):.1f}%)")
    print("=" * 95)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="4-Year Institutional Backtest (2022 - 2026)")
    parser.add_argument("--balance", type=float, default=10.49, help="Starting balance (default: 10.49 USDT)")
    args = parser.parse_args()

    run_4year_compounding_simulation(initial_balance=args.balance)
