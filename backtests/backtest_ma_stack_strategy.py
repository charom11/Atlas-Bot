#!/usr/bin/env python3
"""
==========================================================================================
📊 QUANT BACKTEST: 5-MA STACK TREND STRATEGY (MA 9, 20, 50, 100, 200)
==========================================================================================
Strategy Specification:
- Moving Averages: MA 9, 20, 50, 100, 200 (Evaluates both EMA and SMA)
- Long Entry: Close > MA9 and Close > MA20 and Close > MA50 and Close > MA100 and Close > MA200 (on transition / breakout)
- Short Entry: Close < MA9 and Close < MA20 and Close < MA50 and Close < MA100 and Close < MA200 (on transition / breakdown)
- Stop Loss: Placed precisely midway between MA50 and MA100: (MA50 + MA100) / 2
- Risk R: |Entry - SL|
- Take Profit 1 (50% scale-out): 1:2 R:R target (Entry + 2 * R for Long, Entry - 2 * R for Short)
- Breakeven Shift: Move SL to Breakeven (+0.05% fee cover buffer) upon hitting TP1
- Runner (50% remaining): Dynamic Trailing Stop riding the MA20 / ATR trend wave

Universe & Data:
- 10 Perpetual Pairs: BTC, ETH, SOL, SUI, NEAR, AVAX, LINK, XRP, DOGE, ADA
- Period: July 1, 2025 to August 16, 2026 (39,459 bars x 10 symbols on 15m)
- Real Exchange Friction: VIP0+BNB (Maker 0.018%, Taker 0.045%, Slippage 0.015%, Funding 0.010%/8h)
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

def calc_sma(arr, span):
    s = pd.Series(arr)
    return s.rolling(span).mean().bfill().values

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

def run_ma_stack_backtest(ma_type='EMA', initial_balance=100.0, leverage=50, margin_pct=0.03, max_positions=5, start_date='2025-07-01'):
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

    min_len = min(len(df) for df in data.values())

    # Precalculate MAs for all symbols
    calc_fn = calc_ema if ma_type.upper() == 'EMA' else calc_sma
    ma_cache = {}
    for sym, df in data.items():
        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        ma9 = calc_fn(closes, 9)
        ma20 = calc_fn(closes, 20)
        ma50 = calc_fn(closes, 50)
        ma100 = calc_fn(closes, 100)
        ma200 = calc_fn(closes, 200)
        atr14 = calc_atr(highs, lows, closes, 14)
        ma_cache[sym] = {
            'ma9': ma9, 'ma20': ma20, 'ma50': ma50, 'ma100': ma100, 'ma200': ma200, 'atr14': atr14
        }

    balance = initial_balance
    peak_balance = balance
    max_drawdown = 0.0
    active_positions = {}
    trade_history = []
    symbol_stats = {sym: {'trades': 0, 'wins': 0, 'pnl': 0.0} for sym in data.keys()}
    monthly_pnl = {}
    last_trade_bar = {sym: -100 for sym in data.keys()}

    total_maker_fees = 0.0
    total_taker_fees = 0.0
    total_funding_fees = 0.0
    total_slippage = 0.0

    last_funding_bar = 0

    for bar_idx in range(200, min_len):
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

        # 1. Manage Active Positions (50% TP1 @ 1:2 R:R -> Breakeven SL -> 50% Trailing Runner)
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
                monthly_pnl[m_key] -= (t_fee + slip)
                monthly_pnl[m_key] += raw_pnl
                pos['realized_pnl'] += net_pnl
                pos['exit_time'] = cur_dt
                pos['exit_reason'] = 'TRAILED_RUNNER' if pos.get('trailing') else ('SL_BREAKEVEN' if pos['tp1_hit'] else 'INITIAL_SL')
                
                trade_history.append(pos)
                symbol_stats[sym]['trades'] += 1
                symbol_stats[sym]['pnl'] += pos['realized_pnl']
                if pos['realized_pnl'] > 0:
                    symbol_stats[sym]['wins'] += 1
                closed_syms.append(sym)
                continue

            # Stage 1: 50% TP1 Check @ 1:2 R:R
            if not pos['tp1_hit']:
                tp1_hit = (is_long and h >= pos['tp1']) or (is_short and l <= pos['tp1'])
                if tp1_hit:
                    pos['tp1_hit'] = True
                    close_qty = pos['initial_qty'] * 0.50
                    pos['rem_qty'] -= close_qty
                    tp_p = pos['tp1']
                    raw_pnl = close_qty * (tp_p - pos['entry_price']) if is_long else close_qty * (pos['entry_price'] - tp_p)
                    m_fee = close_qty * tp_p * FEE_SCHEDULE['maker_fee']
                    total_maker_fees += m_fee
                    net_pnl = raw_pnl - m_fee
                    balance += net_pnl
                    monthly_pnl[m_key] += net_pnl
                    pos['realized_pnl'] += net_pnl

                    # Move SL to Breakeven (+0.05% buffer to lock fee-free state)
                    pos['sl'] = pos['entry_price'] * 1.0005 if is_long else pos['entry_price'] * 0.9995
                    pos['trailing'] = True
                    pos['highest'] = h
                    pos['lowest'] = l

            # Stage 2: Dynamic Trailing Stop on the Final 50% Runner (riding MA20 / ATR)
            if pos.get('trailing'):
                cur_ma20 = ma_cache[sym]['ma20'][bar_idx]
                atr_v = ma_cache[sym]['atr14'][bar_idx]
                trail_dist = 1.0 * atr_v if atr_v > 0 else (c * 0.010)

                if is_long:
                    if h > pos['highest']:
                        pos['highest'] = h
                    # Trailing anchor: either Peak - ATR or MA20
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

        # 2. Check New Entries (5-MA Stack Transition)
        if len(active_positions) >= max_positions or balance <= 2.0:
            continue

        long_count = sum(1 for p in active_positions.values() if p['side'] == 'BUY')
        short_count = sum(1 for p in active_positions.values() if p['side'] == 'SELL')

        for sym in data.keys():
            if sym in active_positions or (bar_idx - last_trade_bar[sym]) < 12: # 3-hour cooldown
                continue

            c = data[sym]['close'].iloc[bar_idx]
            prev_c = data[sym]['close'].iloc[bar_idx - 1]
            m9 = ma_cache[sym]['ma9'][bar_idx]
            m20 = ma_cache[sym]['ma20'][bar_idx]
            m50 = ma_cache[sym]['ma50'][bar_idx]
            m100 = ma_cache[sym]['ma100'][bar_idx]
            m200 = ma_cache[sym]['ma200'][bar_idx]

            prev_m9 = ma_cache[sym]['ma9'][bar_idx - 1]
            prev_m20 = ma_cache[sym]['ma20'][bar_idx - 1]
            prev_m50 = ma_cache[sym]['ma50'][bar_idx - 1]
            prev_m100 = ma_cache[sym]['ma100'][bar_idx - 1]
            prev_m200 = ma_cache[sym]['ma200'][bar_idx - 1]

            # Conditions:
            # LONG: Current price > ALL MAs (9, 20, 50, 100, 200) AND transitioning (previous was not above all)
            is_above_all = (c > m9) and (c > m20) and (c > m50) and (c > m100) and (c > m200)
            was_above_all = (prev_c > prev_m9) and (prev_c > prev_m20) and (prev_c > prev_m50) and (prev_c > prev_m100) and (prev_c > prev_m200)
            long_trigger = is_above_all and (not was_above_all) and (long_count < 3)

            # SHORT: Current price < ALL MAs (9, 20, 50, 100, 200) AND transitioning (previous was not below all)
            is_below_all = (c < m9) and (c < m20) and (c < m50) and (c < m100) and (c < m200)
            was_below_all = (prev_c < prev_m9) and (prev_c < prev_m20) and (prev_c < prev_m50) and (prev_c < prev_m100) and (prev_c < prev_m200)
            short_trigger = is_below_all and (not was_below_all) and (short_count < 3)

            if long_trigger or short_trigger:
                action = 'BUY' if long_trigger else 'SELL'

                # Stop Loss: Midway between MA50 and MA100: (MA50 + MA100) / 2
                sl_mid = (m50 + m100) / 2.0
                
                # Sanity check: Ensure SL is on correct side of price with minimum buffer
                atr_v = ma_cache[sym]['atr14'][bar_idx]
                min_risk = 0.8 * atr_v if atr_v > 0 else (c * 0.005)

                if action == 'BUY':
                    sl_v = min(sl_mid, c - min_risk)
                    # Enforce max SL distance to prevent extreme outlier gaps
                    sl_v = max(sl_v, c - (3.5 * atr_v))
                    risk_r = c - sl_v
                    tp1_v = c + (2.0 * risk_r) # 1:2 R:R
                else:
                    sl_v = max(sl_mid, c + min_risk)
                    sl_v = min(sl_v, c + (3.5 * atr_v))
                    risk_r = sl_v - c
                    tp1_v = c - (2.0 * risk_r) # 1:2 R:R

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
                    total_maker_fees += e_fee
                    balance -= e_fee
                    monthly_pnl[m_key] -= e_fee

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

    # Close remaining open positions at latest price
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

    tp1_hits = sum(1 for t in trade_history if t.get('tp1_hit'))
    tp1_rate = (tp1_hits / tot_trades * 100.0) if tot_trades > 0 else 0.0

    long_trades = [t for t in trade_history if t['side'] == 'BUY']
    short_trades = [t for t in trade_history if t['side'] == 'SELL']
    long_wr = (sum(1 for t in long_trades if t['realized_pnl'] > 0) / len(long_trades) * 100.0) if long_trades else 0.0
    short_wr = (sum(1 for t in short_trades if t['realized_pnl'] > 0) / len(short_trades) * 100.0) if short_trades else 0.0

    return {
        'ma_type': ma_type,
        'initial_balance': initial_balance,
        'ending_balance': balance,
        'net_pnl': tot_pnl,
        'roi': roi,
        'trades': tot_trades,
        'win_rate': wr,
        'profit_factor': pf,
        'max_drawdown': max_drawdown,
        'tp1_rate': tp1_rate,
        'tp1_hits': tp1_hits,
        'long_trades': len(long_trades),
        'long_wr': long_wr,
        'short_trades': len(short_trades),
        'short_wr': short_wr,
        'fees_paid': total_maker_fees + total_taker_fees + total_funding_fees + total_slippage,
        'symbol_stats': symbol_stats,
        'monthly_pnl': monthly_pnl
    }

def print_ma_backtest_report():
    print("=" * 110)
    print(" 📊 QUANT BACKTEST: 5-MA STACK TREND STRATEGY (MA 9, 20, 50, 100, 200)")
    print("=" * 110)
    print(" • Rule 1 (Long Entry):    Price crosses ABOVE ALL MAs (9, 20, 50, 100, 200)")
    print(" • Rule 2 (Short Entry):   Price crosses BELOW ALL MAs (9, 20, 50, 100, 200)")
    print(" • Rule 3 (Stop Loss):     Midpoint between MA 50 and MA 100: (MA50 + MA100) / 2")
    print(" • Rule 4 (Take Profit):   Stage 1 (50% scale-out) @ 1:2 R:R -> Move SL to Breakeven (+0.05%)")
    print(" • Rule 5 (Trend Runner):  Stage 2 (50% runner) Dynamic Trailing Stop riding MA20 / ATR")
    print(" • Friction Schedule:      VIP0+BNB (Maker 0.018% | Taker 0.045% | Slip 0.015% | Funding 0.010%)")
    print("=" * 110)

    print("\n⚡ Running Simulation A: 5-EMA Stack (Exponential Moving Averages 9, 20, 50, 100, 200)...")
    res_ema = run_ma_stack_backtest(ma_type='EMA')

    print("⚡ Running Simulation B: 5-SMA Stack (Simple Moving Averages 9, 20, 50, 100, 200)...")
    res_sma = run_ma_stack_backtest(ma_type='SMA')

    print("\n" + "=" * 110)
    print(" 🏆 HEAD-TO-HEAD RESULTS: EMA STACK VS SMA STACK")
    print("=" * 110)
    print(f"{'Performance Metric':<32} | {'📈 5-EMA Stack (9/20/50/100/200)':<30} | {'📊 5-SMA Stack (9/20/50/100/200)':<30}")
    print("-" * 110)
    print(f"{'Total Executed Trades':<32} | {res_ema['trades']:>28} | {res_sma['trades']:>28}")
    print(f"{'Win Rate (%)':<32} | {res_ema['win_rate']:>27.1f}% | {res_sma['win_rate']:>27.1f}%")
    print(f"{'1:2 R:R (TP1) Hit Rate':<32} | {res_ema['tp1_rate']:>27.1f}% | {res_sma['tp1_rate']:>27.1f}%")
    print(f"{'Profit Factor (PF)':<32} | {res_ema['profit_factor']:>28.2f} | {res_sma['profit_factor']:>28.2f}")
    print(f"{'Long Trades (Count / Win Rate)':<32} | {res_ema['long_trades']:>12} trades ({res_ema['long_wr']:>4.1f}%) | {res_sma['long_trades']:>12} trades ({res_sma['long_wr']:>4.1f}%)")
    print(f"{'Short Trades (Count / Win Rate)':<32} | {res_ema['short_trades']:>12} trades ({res_ema['short_wr']:>4.1f}%) | {res_sma['short_trades']:>12} trades ({res_sma['short_wr']:>4.1f}%)")
    print(f"{'Ending Account Balance':<32} | ${res_ema['ending_balance']:>27.2f} | ${res_sma['ending_balance']:>27.2f}")
    print(f"{'Net Realized Profit':<32} | ${res_ema['net_pnl']:>+27.2f} | ${res_sma['net_pnl']:>+27.2f}")
    print(f"{'Total Return (ROI)':<32} | {res_ema['roi']:>+27.2f}% | {res_sma['roi']:>+27.2f}%")
    print(f"{'Max Portfolio Drawdown':<32} | {res_ema['max_drawdown']:>27.2f}% | {res_sma['max_drawdown']:>27.2f}%")
    print(f"{'Total Exchange Friction (Fees)':<32} | ${res_ema['fees_paid']:>27.2f} | ${res_sma['fees_paid']:>27.2f}")
    print("=" * 110)

    # Per-Asset Breakdown for EMA
    print("\n💎 PER-ASSET BREAKDOWN (5-EMA Stack):")
    print("-" * 110)
    print(f"{'Asset Symbol':<15} | {'Trades':>8} | {'Wins':>8} | {'Win Rate':>12} | {'Net PnL ($)':>16}")
    print("-" * 110)
    for sym, st in res_ema['symbol_stats'].items():
        sym_wr = (st['wins'] / st['trades'] * 100.0) if st['trades'] > 0 else 0.0
        print(f"#{sym:<14} | {st['trades']:>8} | {st['wins']:>8} | {sym_wr:>11.1f}% | ${st['pnl']:>+15.2f} USDT")
    print("=" * 110)

if __name__ == '__main__':
    print_ma_backtest_report()
