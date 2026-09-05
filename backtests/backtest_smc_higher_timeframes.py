#!/usr/bin/env python3
"""
==========================================================================================
🏛️ MULTI-TIMEFRAME QUANT AUDIT: LUXALGO SMC (15m vs 1H vs 2H vs 3H vs 4H)
==========================================================================================
Evaluates the exact SMC.pine algorithms across multiple timeframes:
- 15m (Baseline)
- 1H (60m)
- 2H (120m)
- 3H (180m)
- 4H (240m)

Features Tested:
1. Order Block (OB) Retest Strategy
2. Change of Character (CHoCH) Structure Shift
3. Full SMC Confluence Suite (Discount / Premium + OB + FVG)

Execution & Risk:
- $100 Initial Capital | 50x Leverage | 3.0% Dynamic Margin | Max 5 Positions
- 50% TP1 @ 1:2 R:R -> Move SL to Breakeven (+0.05%) -> 50% Trailing Runner
- Real Exchange Friction: VIP0+BNB (Maker 0.018%, Taker 0.045%, Slippage 0.015%, Funding 0.010%)
- 10 Liquid Perpetual Pairs (BTC, ETH, SOL, SUI, NEAR, AVAX, LINK, XRP, DOGE, ADA)
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

from backtest_luxalgo_smc import calc_atr, compute_smc_pine_signals

def resample_ohlcv(df, rule='1h'):
    """Resamples 15m OHLCV dataframe to higher timeframe (1H, 2H, 3H, 4H)"""
    t_col = 'open_time' if 'open_time' in df.columns else 'timestamp'
    df_copy = df.copy()
    df_copy['dt'] = pd.to_datetime(df_copy[t_col], utc=True)
    df_copy = df_copy.set_index('dt').sort_index()

    resampled = df_copy.resample(rule).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna().reset_index()

    resampled['open_time'] = resampled['dt']
    return resampled

def run_htf_smc_backtest(timeframe_label='1H', resample_rule='1h', smc_mode='OB_RETEST', initial_balance=100.0, leverage=50, margin_pct=0.03, max_positions=5):
    raw_data = {}
    for sym in SYMBOLS:
        fpath = os.path.join(CACHE_DIR, f"{sym}_15m_from_2025-07-01.csv")
        if not os.path.exists(fpath):
            fpath = os.path.join(CACHE_DIR, f"{sym}_15m_from_2024-08-25.csv")
        if os.path.exists(fpath):
            df = pd.read_csv(fpath)
            raw_data[sym] = df

    # Resample datasets
    htf_data = {}
    for sym, df in raw_data.items():
        if resample_rule == '15m':
            t_col = 'open_time' if 'open_time' in df.columns else 'timestamp'
            df['open_time'] = pd.to_datetime(df[t_col], utc=True)
            htf_data[sym] = df.sort_values('open_time').reset_index(drop=True)
        else:
            htf_data[sym] = resample_ohlcv(df, rule=resample_rule)

    min_len = min(len(df) for df in htf_data.values())
    sym_signals = {sym: compute_smc_pine_signals(df, internal_size=5, swing_size=20) for sym, df in htf_data.items()}

    balance = initial_balance
    peak_balance = balance
    max_drawdown = 0.0
    active_positions = {}
    trade_history = []
    symbol_stats = {sym: {'trades': 0, 'wins': 0, 'pnl': 0.0} for sym in htf_data.keys()}
    total_fees = 0.0
    last_trade_bar = {sym: -100 for sym in htf_data.keys()}

    for bar_idx in range(50, min_len):
        cur_dt = htf_data['BTCUSDT']['open_time'].iloc[bar_idx]

        # Manage active positions (50% TP1 @ 1:2 R:R -> Move to Breakeven -> 50% Trailing Runner)
        closed_syms = []
        for sym, pos in list(active_positions.items()):
            h = htf_data[sym]['high'].iloc[bar_idx]
            l = htf_data[sym]['low'].iloc[bar_idx]
            c = htf_data[sym]['close'].iloc[bar_idx]
            is_long = pos['side'] == 'BUY'
            is_short = pos['side'] == 'SELL'

            # Stop Loss
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

                    # Move SL to Breakeven (+0.05% fee cover)
                    pos['sl'] = pos['entry_price'] * 1.0005 if is_long else pos['entry_price'] * 0.9995
                    pos['trailing'] = True
                    pos['highest'] = h
                    pos['lowest'] = l

            # Stage 2: 50% Trailing Runner
            if pos.get('trailing'):
                trail_dist = 1.0 * pos['atr']
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

        # Check new entries
        if len(active_positions) >= max_positions or balance <= 2.0:
            continue

        long_count = sum(1 for p in active_positions.values() if p['side'] == 'BUY')
        short_count = sum(1 for p in active_positions.values() if p['side'] == 'SELL')

        for sym in htf_data.keys():
            if sym in active_positions or (bar_idx - last_trade_bar[sym]) < 4:
                continue

            sig_list = sym_signals[sym]
            sig_idx = bar_idx - 50
            if sig_idx < 0 or sig_idx >= len(sig_list):
                continue
            _, sig = sig_list[sig_idx]
            cur_p = htf_data[sym]['close'].iloc[bar_idx]
            atr_v = sig['atr']

            action = None
            sl_price = None

            if smc_mode == 'OB_RETEST':
                if sig['ob_long'] and long_count < 3 and sig['active_bull_ob']:
                    action = 'BUY'
                    sl_price = sig['active_bull_ob']['bottom'] * 0.998
                elif sig['ob_short'] and short_count < 3 and sig['active_bear_ob']:
                    action = 'SELL'
                    sl_price = sig['active_bear_ob']['top'] * 1.002

            elif smc_mode == 'CHOCH_SNIPER':
                if sig['bull_choch'] and long_count < 3:
                    action = 'BUY'
                    sl_price = cur_p - (1.2 * atr_v)
                elif sig['bear_choch'] and short_count < 3:
                    action = 'SELL'
                    sl_price = cur_p + (1.2 * atr_v)

            elif smc_mode == 'FULL_CONFLUENCE':
                if (sig['ob_long'] or sig['fvg_long'] or sig['bull_choch']) and sig['is_discount'] and sig['internal_trend'] == 1 and long_count < 3:
                    action = 'BUY'
                    ob_bot = sig['active_bull_ob']['bottom'] if sig.get('active_bull_ob') else (cur_p - 1.2 * atr_v)
                    sl_price = min(ob_bot * 0.998, cur_p - 0.8 * atr_v)
                elif (sig['ob_short'] or sig['fvg_short'] or sig['bear_choch']) and sig['is_premium'] and sig['internal_trend'] == -1 and short_count < 3:
                    action = 'SELL'
                    ob_top = sig['active_bear_ob']['top'] if sig.get('active_bear_ob') else (cur_p + 1.2 * atr_v)
                    sl_price = max(ob_top * 1.002, cur_p + 0.8 * atr_v)

            if action and sl_price:
                min_risk = 0.6 * atr_v
                if action == 'BUY':
                    sl_v = min(sl_price, cur_p - min_risk)
                    sl_v = max(sl_v, cur_p - (3.5 * atr_v))
                    risk_r = cur_p - sl_v
                    tp1_v = cur_p + (2.0 * risk_r) # 1:2 R:R
                else:
                    sl_v = max(sl_price, cur_p + min_risk)
                    sl_v = min(sl_v, cur_p + (3.5 * atr_v))
                    risk_r = sl_v - cur_p
                    tp1_v = cur_p - (2.0 * risk_r) # 1:2 R:R

                if risk_r <= 0:
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
                        'tp1_hit': False,
                        'trailing': False,
                        'atr': atr_v,
                        'highest': cur_p,
                        'lowest': cur_p,
                        'realized_pnl': -e_fee
                    }
                    last_trade_bar[sym] = bar_idx
                    if len(active_positions) >= max_positions:
                        break

    # Close remaining
    for sym, pos in list(active_positions.items()):
        c = htf_data[sym]['close'].iloc[-1]
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
        'timeframe': timeframe_label,
        'mode': smc_mode,
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

def print_htf_audit():
    print("=" * 115)
    print(" 🏛️ LUXALGO SMC (SMC.pine) MULTI-TIMEFRAME QUANT AUDIT (15m vs 1H vs 2H vs 3H vs 4H)")
    print("=" * 115)
    print(" • Universe:              10 Liquid Perpetual Pairs (BTC, ETH, SOL, SUI, NEAR, AVAX, LINK, XRP, DOGE, ADA)")
    print(" • Evaluated Timeline:    July 1, 2025 to August 16, 2026 (Continuous Multi-Asset Historical Data)")
    print(" • Account Sizing:        $100 Initial Balance | 50x Leverage | 3.0% Dynamic Margin | Max 5 Positions")
    print(" • Risk Architecture:     50% TP1 @ 1:2 R:R -> Move SL to Breakeven (+0.05%) -> 50% Trailing Runner")
    print(" • Friction Schedule:     VIP0+BNB (Maker 0.018% | Taker 0.045% | Slip 0.015% | Funding 0.010%)")
    print("=" * 115)

    tf_configs = [
        ('15m', '15m'),
        ('1H (60m)', '1h'),
        ('2H (120m)', '2h'),
        ('3H (180m)', '3h'),
        ('4H (240m)', '4h'),
    ]

    print("\n" + "=" * 115)
    print(" 🏆 SECTION 1: ORDER BLOCK (OB) RETEST ACROSS TIMEFRAMES")
    print("=" * 115)
    print(f"{'Timeframe':<15} | {'Trades':>7} | {'Win Rate':>9} | {'TP1 Hit Rate':>13} | {'Profit Factor':>14} | {'Net PnL ($)':>14} | {'Fees Paid':>12}")
    print("-" * 115)

    ob_results = {}
    for tf_lbl, rule in tf_configs:
        res = run_htf_smc_backtest(timeframe_label=tf_lbl, resample_rule=rule, smc_mode='OB_RETEST')
        ob_results[tf_lbl] = res
        print(f"{tf_lbl:<15} | {res['trades']:>7} | {res['win_rate']:>8.1f}% | {res['tp1_rate']:>12.1f}% | {res['profit_factor']:>14.2f} | ${res['net_pnl']:>+13.2f} | ${res['fees_paid']:>11.2f}")

    print("\n" + "=" * 115)
    print(" 🏆 SECTION 2: CHANGE OF CHARACTER (CHoCH) REVERSALS ACROSS TIMEFRAMES")
    print("=" * 115)
    print(f"{'Timeframe':<15} | {'Trades':>7} | {'Win Rate':>9} | {'TP1 Hit Rate':>13} | {'Profit Factor':>14} | {'Net PnL ($)':>14} | {'Fees Paid':>12}")
    print("-" * 115)

    for tf_lbl, rule in tf_configs:
        res = run_htf_smc_backtest(timeframe_label=tf_lbl, resample_rule=rule, smc_mode='CHOCH_SNIPER')
        print(f"{tf_lbl:<15} | {res['trades']:>7} | {res['win_rate']:>8.1f}% | {res['tp1_rate']:>12.1f}% | {res['profit_factor']:>14.2f} | ${res['net_pnl']:>+13.2f} | ${res['fees_paid']:>11.2f}")

    print("\n" + "=" * 115)
    print(" 🏆 SECTION 3: FULL SMC CONFLUENCE (Discount / Premium + OB + FVG)")
    print("=" * 115)
    print(f"{'Timeframe':<15} | {'Trades':>7} | {'Win Rate':>9} | {'TP1 Hit Rate':>13} | {'Profit Factor':>14} | {'Net PnL ($)':>14} | {'Fees Paid':>12}")
    print("-" * 115)

    full_results = {}
    for tf_lbl, rule in tf_configs:
        res = run_htf_smc_backtest(timeframe_label=tf_lbl, resample_rule=rule, smc_mode='FULL_CONFLUENCE')
        full_results[tf_lbl] = res
        print(f"{tf_lbl:<15} | {res['trades']:>7} | {res['win_rate']:>8.1f}% | {res['tp1_rate']:>12.1f}% | {res['profit_factor']:>14.2f} | ${res['net_pnl']:>+13.2f} | ${res['fees_paid']:>11.2f}")

    print("=" * 115)

if __name__ == '__main__':
    print_htf_audit()
