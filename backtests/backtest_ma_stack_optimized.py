#!/usr/bin/env python3
"""
==========================================================================================
📊 QUANT OPTIMIZATION: 5-MA STACK + ORDERED FAN + ADX ANTI-CHOP FILTER
==========================================================================================
Compares:
1. Basic 5-MA Cross (Price above/below all MAs)
2. Ordered 5-MA Rainbow Alignment (MA9 > MA20 > MA50 > MA100 > MA200 for Long | MA9 < MA20 < MA50 < MA100 < MA200 for Short)
3. Ordered 5-MA Rainbow + ADX >= 22 (Chop Avoidance)
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

from backtest_ma_stack_strategy import (
    SYMBOLS, CACHE_DIR, FEE_SCHEDULE, calc_ema, calc_atr
)
from backtest_counter_macro_quick_scalp import calc_adx

def run_variant(variant="ORDERED_ADX", initial_balance=100.0, leverage=50, margin_pct=0.03, max_positions=5):
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

    ma_cache = {}
    for sym, df in data.items():
        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        ma9 = calc_ema(closes, 9)
        ma20 = calc_ema(closes, 20)
        ma50 = calc_ema(closes, 50)
        ma100 = calc_ema(closes, 100)
        ma200 = calc_ema(closes, 200)
        atr14 = calc_atr(highs, lows, closes, 14)
        adx14 = calc_adx(highs, lows, closes, 14)
        ma_cache[sym] = {
            'ma9': ma9, 'ma20': ma20, 'ma50': ma50, 'ma100': ma100, 'ma200': ma200,
            'atr14': atr14, 'adx14': adx14
        }

    balance = initial_balance
    peak_balance = balance
    max_drawdown = 0.0
    active_positions = {}
    trade_history = []
    symbol_stats = {sym: {'trades': 0, 'wins': 0, 'pnl': 0.0} for sym in data.keys()}
    total_fees = 0.0
    last_trade_bar = {sym: -100 for sym in data.keys()}

    for bar_idx in range(200, min_len):
        cur_dt = data['BTCUSDT']['open_time'].iloc[bar_idx]

        # Manage positions
        closed_syms = []
        for sym, pos in list(active_positions.items()):
            h = data[sym]['high'].iloc[bar_idx]
            l = data[sym]['low'].iloc[bar_idx]
            c = data[sym]['close'].iloc[bar_idx]
            is_long = pos['side'] == 'BUY'
            is_short = pos['side'] == 'SELL'

            # Stop loss
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
                closed_syms.append(sym)
                continue

            # Stage 1: 50% TP1 @ 1:2 R:R
            if not pos['tp1_hit']:
                tp1_hit = (is_long and h >= pos['tp1']) or (is_short and l <= pos['tp1'])
                if tp1_hit:
                    pos['tp1_hit'] = True
                    q_close = pos['initial_qty'] * 0.50
                    pos['rem_qty'] -= q_close
                    tp_p = pos['tp1']
                    raw_pnl = q_close * (tp_p - pos['entry_price']) if is_long else q_close * (pos['entry_price'] - tp_p)
                    m_fee = q_close * tp_p * FEE_SCHEDULE['maker_fee']
                    total_fees += m_fee
                    net_pnl = raw_pnl - m_fee
                    balance += net_pnl
                    pos['realized_pnl'] += net_pnl
                    # Move to BE (+0.05%)
                    pos['sl'] = pos['entry_price'] * 1.0005 if is_long else pos['entry_price'] * 0.9995
                    pos['trailing'] = True
                    pos['highest'] = h
                    pos['lowest'] = l

            # Stage 2: 50% Runner (Trail riding MA20 / ATR)
            if pos.get('trailing'):
                cur_ma20 = ma_cache[sym]['ma20'][bar_idx]
                atr_v = ma_cache[sym]['atr14'][bar_idx]
                trail_dist = 1.0 * atr_v if atr_v > 0 else (c * 0.010)

                if is_long:
                    if h > pos['highest']:
                        pos['highest'] = h
                    calc_trail = max(pos['highest'] - trail_dist, cur_ma20)
                    if calc_trail > pos['sl'] and calc_trail > pos['entry_price']:
                        pos['sl'] = calc_trail
                elif is_short:
                    if l < pos['lowest']:
                        pos['lowest'] = l
                    calc_trail = min(pos['lowest'] + trail_dist, cur_ma20)
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

        # Entry logic
        if len(active_positions) >= max_positions or balance <= 2.0:
            continue

        long_count = sum(1 for p in active_positions.values() if p['side'] == 'BUY')
        short_count = sum(1 for p in active_positions.values() if p['side'] == 'SELL')

        for sym in data.keys():
            if sym in active_positions or (bar_idx - last_trade_bar[sym]) < 12:
                continue

            c = data[sym]['close'].iloc[bar_idx]
            prev_c = data[sym]['close'].iloc[bar_idx - 1]
            m9 = ma_cache[sym]['ma9'][bar_idx]
            m20 = ma_cache[sym]['ma20'][bar_idx]
            m50 = ma_cache[sym]['ma50'][bar_idx]
            m100 = ma_cache[sym]['ma100'][bar_idx]
            m200 = ma_cache[sym]['ma200'][bar_idx]

            adx_v = ma_cache[sym]['adx14'][bar_idx]

            if variant == "BASIC":
                long_cond = (c > m9) and (c > m20) and (c > m50) and (c > m100) and (c > m200)
                short_cond = (c < m9) and (c < m20) and (c < m50) and (c < m100) and (c < m200)
            elif variant == "ORDERED":
                long_cond = (c > m9 > m20 > m50 > m100 > m200)
                short_cond = (c < m9 < m20 < m50 < m100 < m200)
            elif variant == "ORDERED_ADX":
                long_cond = (c > m9 > m20 > m50 > m100 > m200) and (adx_v >= 22.0)
                short_cond = (c < m9 < m20 < m50 < m100 < m200) and (adx_v >= 22.0)

            long_trigger = long_cond and (long_count < 3)
            short_trigger = short_cond and (short_count < 3)

            if long_trigger or short_trigger:
                action = 'BUY' if long_trigger else 'SELL'
                sl_mid = (m50 + m100) / 2.0
                atr_v = ma_cache[sym]['atr14'][bar_idx]
                min_risk = 0.8 * atr_v if atr_v > 0 else (c * 0.005)

                if action == 'BUY':
                    sl_v = min(sl_mid, c - min_risk)
                    sl_v = max(sl_v, c - (3.5 * atr_v))
                    risk_r = c - sl_v
                    tp1_v = c + (2.0 * risk_r)
                else:
                    sl_v = max(sl_mid, c + min_risk)
                    sl_v = min(sl_v, c + (3.5 * atr_v))
                    risk_r = sl_v - c
                    tp1_v = c - (2.0 * risk_r)

                if risk_r <= 0:
                    continue

                margin = balance * margin_pct
                notional = margin * leverage
                if notional < 5.0:
                    notional = 5.0
                    margin = notional / leverage

                if balance >= margin:
                    qty = notional / c
                    e_fee = notional * FEE_SCHEDULE['maker_fee']
                    total_fees += e_fee
                    balance -= e_fee

                    active_positions[sym] = {
                        'symbol': sym,
                        'side': action,
                        'entry_time': cur_dt,
                        'entry_price': c,
                        'initial_qty': qty,
                        'rem_qty': qty,
                        'sl': sl_v,
                        'tp1': tp1_v,
                        'tp1_hit': False,
                        'trailing': False,
                        'risk_r': risk_r,
                        'highest': c,
                        'lowest': c,
                        'realized_pnl': -e_fee
                    }
                    last_trade_bar[sym] = bar_idx
                    if len(active_positions) >= max_positions:
                        break

    # Close remaining
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
        'variant': variant,
        'ending_balance': balance,
        'net_pnl': tot_pnl,
        'roi': roi,
        'trades': tot_trades,
        'win_rate': wr,
        'tp1_rate': tp1_rate,
        'profit_factor': pf,
        'max_drawdown': max_drawdown,
        'fees_paid': total_fees,
        'symbol_stats': symbol_stats
    }

def main():
    print("=" * 110)
    print(" 🚀 5-MA STACK ENHANCEMENT AUDIT (BASIC VS ORDERED RAINBOW VS ORDERED + ADX >= 22)")
    print("=" * 110)
    r1 = run_variant("BASIC")
    r2 = run_variant("ORDERED")
    r3 = run_variant("ORDERED_ADX")

    print(f"{'Configuration':<30} | {'Trades':>8} | {'Win Rate':>9} | {'TP1 Hit Rate':>13} | {'Profit Factor':>14} | {'Net PnL ($)':>14} | {'Fees Paid':>12}")
    print("-" * 110)
    print(f"{'1. Basic 5-MA Breakout':<30} | {r1['trades']:>8} | {r1['win_rate']:>8.1f}% | {r1['tp1_rate']:>12.1f}% | {r1['profit_factor']:>14.2f} | ${r1['net_pnl']:>+13.2f} | ${r1['fees_paid']:>11.2f}")
    print(f"{'2. Ordered 5-MA Rainbow':<30} | {r2['trades']:>8} | {r2['win_rate']:>8.1f}% | {r2['tp1_rate']:>12.1f}% | {r2['profit_factor']:>14.2f} | ${r2['net_pnl']:>+13.2f} | ${r2['fees_paid']:>11.2f}")
    print(f"{'3. Ordered 5-MA + ADX >= 22':<30} | {r3['trades']:>8} | {r3['win_rate']:>8.1f}% | {r3['tp1_rate']:>12.1f}% | {r3['profit_factor']:>14.2f} | ${r3['net_pnl']:>+13.2f} | ${r3['fees_paid']:>11.2f}")
    print("=" * 110)

if __name__ == '__main__':
    main()
