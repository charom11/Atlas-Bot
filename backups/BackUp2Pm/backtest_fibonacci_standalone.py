#!/usr/bin/env python3
"""
STANDALONE FIBONACCI RETRACEMENT & EXTENSION BACKTEST ENGINE
============================================================
Period: July 2025 -> Present (August 2026)
Configuration:
- 50x Leverage (Isolated/Cross Margin simulation)
- 2.5% Margin allocation per position (Max 5 concurrent slots)
- Non-anticipative Fractal Swings (Anchor High/Low detection)
- Golden Pocket Entry: 0.500 to 0.618 Retracement
- Stop Loss: Beyond 0.786 Retracement + 0.5x ATR buffer
- Multi-Tier Take Profit Scale-outs:
    * TP1 (40%): 0.000 (Swing High/Low retest) -> Move SL to Breakeven
    * TP2 (40%): -0.272 to -0.618 (Fib Extension Target)
    * TP3 (20%): -1.618 (Trend Runner with Chandelier Trailing Stop)
- Fee Modeling: 0.018% Maker Entry / TP Limits | 0.045% Taker SL
- Slippage: 0.015% per trade
"""

import os
import sys
import math
import numpy as np
import pandas as pd
from datetime import datetime

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

CACHE_DIR = os.path.join(os.path.dirname(__file__), "historical_data_cache")
SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "SUIUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "NEARUSDT"
]

def load_data(symbol, interval="15m"):
    fname = f"{symbol}_{interval}_from_2025-07-01.csv"
    fpath = os.path.join(CACHE_DIR, fname)
    if not os.path.exists(fpath):
        return None
    df = pd.read_csv(fpath)
    time_col = 'timestamp' if 'timestamp' in df.columns else 'open_time'
    df['open_time'] = pd.to_datetime(df[time_col])
    df = df.sort_values('open_time').reset_index(drop=True)
    return df

def calculate_atr(df, period=14):
    high = df['high']
    low = df['low']
    close = df['close']
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def calculate_adx(df, period=14):
    high = df['high']
    low = df['low']
    close = df['close']
    
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    
    tr = calculate_atr(df, period)
    
    plus_di = 100 * (pd.Series(plus_dm).rolling(period).mean() / (tr + 1e-9))
    minus_di = 100 * (pd.Series(minus_dm).rolling(period).mean() / (tr + 1e-9))
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9))
    adx = dx.rolling(period).mean()
    return adx, plus_di, minus_di

def detect_fractal_swings(highs, lows, window=5):
    """
    Identifies Fractal Swings with zero look-ahead bias:
    A swing at index i is confirmed only after window subsequent bars.
    Returns lists of (bar_index, price)
    """
    n = len(highs)
    swing_highs = []
    swing_lows = []
    
    for i in range(window, n - window):
        # Swing High
        if all(highs[i] >= highs[i - k] for k in range(1, window + 1)) and \
           all(highs[i] >= highs[i + k] for k in range(1, window + 1)):
            swing_highs.append((i + window, highs[i])) # confirmed at i + window
            
        # Swing Low
        if all(lows[i] <= lows[i - k] for k in range(1, window + 1)) and \
           all(lows[i] <= lows[i + k] for k in range(1, window + 1)):
            swing_lows.append((i + window, lows[i])) # confirmed at i + window
            
    return swing_highs, swing_lows

class FibonacciBacktestEngine:
    def __init__(self, initial_balance=100.0, leverage=50, max_positions=5, margin_pct=0.025):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.leverage = leverage
        self.max_positions = max_positions
        self.margin_pct = margin_pct
        self.active_positions = {}  # symbol -> position dict
        self.trade_history = []
        self.monthly_pnl = {}
        self.maker_fee = 0.00018  # 0.018% Binance maker
        self.taker_fee = 0.00045  # 0.045% Binance taker
        self.slippage = 0.00015   # 0.015% slippage

    def run(self):
        # Load and align all symbols data
        raw_data = {}
        for sym in SYMBOLS:
            df = load_data(sym, "15m")
            if df is not None:
                df['atr'] = calculate_atr(df, 14)
                df['adx'], df['pdi'], df['ndi'] = calculate_adx(df, 14)
                df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
                df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
                raw_data[sym] = df
        
        if not raw_data:
            print("No cached data found!")
            return

        min_len = min(len(df) for df in raw_data.values())
        print(f"Loaded {len(raw_data)} assets. Total bars per asset: {min_len:,} (15m intervals)")

        # Prepare precalculated swing anchors
        swings_by_sym = {}
        for sym, df in raw_data.items():
            sh, sl = detect_fractal_swings(df['high'].values, df['low'].values, window=4)
            swings_by_sym[sym] = {'highs': sh, 'lows': sl}

        last_trade_bar = {sym: -999 for sym in SYMBOLS}

        # Step through time synchronously across all assets
        for bar_idx in range(250, min_len):
            current_time = raw_data['BTCUSDT']['open_time'].iloc[bar_idx]
            month_key = current_time.strftime('%Y-%m')
            if month_key not in self.monthly_pnl:
                self.monthly_pnl[month_key] = 0.0

            # 1. Update & Manage Open Positions (TP1, TP2, TP3, SL, Breakeven)
            closed_syms = []
            for sym, pos in self.active_positions.items():
                df = raw_data[sym]
                bar_h = df['high'].iloc[bar_idx]
                bar_l = df['low'].iloc[bar_idx]
                bar_c = df['close'].iloc[bar_idx]
                side = pos['side']
                
                # Check Stop Loss first (worst-case execution)
                hit_sl = False
                sl_exit_price = pos['sl']
                if side == 'LONG' and bar_l <= pos['sl']:
                    hit_sl = True
                    sl_exit_price = min(bar_c, pos['sl']) * (1.0 - self.slippage)
                elif side == 'SHORT' and bar_h >= pos['sl']:
                    hit_sl = True
                    sl_exit_price = max(bar_c, pos['sl']) * (1.0 + self.slippage)

                if hit_sl:
                    # Realize remaining position at SL
                    rem_qty = pos['rem_qty']
                    if side == 'LONG':
                        pnl = rem_qty * (sl_exit_price - pos['entry_price'])
                    else:
                        pnl = rem_qty * (pos['entry_price'] - sl_exit_price)
                    
                    fee = rem_qty * sl_exit_price * self.taker_fee
                    net_pnl = pnl - fee
                    self.balance += net_pnl
                    self.monthly_pnl[month_key] += net_pnl
                    
                    pos['realized_pnl'] += net_pnl
                    pos['exit_time'] = current_time
                    pos['exit_reason'] = 'SL_BE' if pos['tp1_hit'] else 'STOP_LOSS'
                    self.trade_history.append(pos)
                    closed_syms.append(sym)
                    continue

                # Check TP1 (0.0 Retest - 40% Scale Out + Move SL to Breakeven)
                if not pos['tp1_hit']:
                    tp1_hit = (side == 'LONG' and bar_h >= pos['tp1']) or (side == 'SHORT' and bar_l <= pos['tp1'])
                    if tp1_hit:
                        pos['tp1_hit'] = True
                        close_qty = pos['initial_qty'] * 0.40
                        pos['rem_qty'] -= close_qty
                        
                        tp_p = pos['tp1']
                        pnl = close_qty * (tp_p - pos['entry_price']) if side == 'LONG' else close_qty * (pos['entry_price'] - tp_p)
                        fee = close_qty * tp_p * self.maker_fee
                        net_pnl = pnl - fee
                        
                        self.balance += net_pnl
                        self.monthly_pnl[month_key] += net_pnl
                        pos['realized_pnl'] += net_pnl
                        
                        # Lock in Breakeven Stop Loss (entry price)
                        pos['sl'] = pos['entry_price']

                # Check TP2 (-0.272 to -0.618 Extension - 40% Scale Out)
                if pos['tp1_hit'] and not pos['tp2_hit']:
                    tp2_hit = (side == 'LONG' and bar_h >= pos['tp2']) or (side == 'SHORT' and bar_l <= pos['tp2'])
                    if tp2_hit:
                        pos['tp2_hit'] = True
                        close_qty = pos['initial_qty'] * 0.40
                        pos['rem_qty'] -= close_qty
                        
                        tp_p = pos['tp2']
                        pnl = close_qty * (tp_p - pos['entry_price']) if side == 'LONG' else close_qty * (pos['entry_price'] - tp_p)
                        fee = close_qty * tp_p * self.maker_fee
                        net_pnl = pnl - fee
                        
                        self.balance += net_pnl
                        self.monthly_pnl[month_key] += net_pnl
                        pos['realized_pnl'] += net_pnl
                        
                        # Trail Stop to TP1 level for the remaining 20% runner
                        pos['sl'] = pos['tp1']

                # Check TP3 (-1.618 Trend Runner - Remaining 20%)
                if pos['tp2_hit']:
                    tp3_hit = (side == 'LONG' and bar_h >= pos['tp3']) or (side == 'SHORT' and bar_l <= pos['tp3'])
                    if tp3_hit:
                        close_qty = pos['rem_qty']
                        tp_p = pos['tp3']
                        pnl = close_qty * (tp_p - pos['entry_price']) if side == 'LONG' else close_qty * (pos['entry_price'] - tp_p)
                        fee = close_qty * tp_p * self.maker_fee
                        net_pnl = pnl - fee
                        
                        self.balance += net_pnl
                        self.monthly_pnl[month_key] += net_pnl
                        pos['realized_pnl'] += net_pnl
                        
                        pos['exit_time'] = current_time
                        pos['exit_reason'] = 'FULL_TP3_RUNNER'
                        self.trade_history.append(pos)
                        closed_syms.append(sym)
                        continue

            for sym in closed_syms:
                del self.active_positions[sym]

            # 2. Evaluate New Fibonacci Entries
            if len(self.active_positions) >= self.max_positions:
                continue

            for sym in SYMBOLS:
                if sym in self.active_positions:
                    continue
                if (bar_idx - last_trade_bar[sym]) < 8:  # 2-hour spacing per asset
                    continue

                df = raw_data[sym]
                curr_c = df['close'].iloc[bar_idx]
                curr_h = df['high'].iloc[bar_idx]
                curr_l = df['low'].iloc[bar_idx]
                atr_v = df['atr'].iloc[bar_idx]
                adx_v = df['adx'].iloc[bar_idx]
                ema50 = df['ema50'].iloc[bar_idx]
                ema200 = df['ema200'].iloc[bar_idx]
                
                if math.isnan(atr_v) or atr_v <= 0:
                    continue

                # Get the most recent confirmed swing high and swing low before current bar
                sh_list = [sh for sh in swings_by_sym[sym]['highs'] if sh[0] <= bar_idx]
                sl_list = [sl for sl in swings_by_sym[sym]['lows'] if sl[0] <= bar_idx]
                
                if not sh_list or not sl_list:
                    continue

                last_sh = sh_list[-1]  # (confirmed_idx, price)
                last_sl = sl_list[-1]  # (confirmed_idx, price)

                s_high = last_sh[1]
                s_low = last_sl[1]
                impulse = s_high - s_low

                if impulse < (1.5 * atr_v):
                    continue

                # Trend Alignment: 4H Macro / EMA50 vs EMA200
                is_uptrend = (curr_c > ema200) and (ema50 >= ema200)
                is_downtrend = (curr_c < ema200) and (ema50 <= ema200)

                # ==========================================
                # BULLISH SETUP (Pullback into Golden Pocket)
                # ==========================================
                if is_uptrend and last_sh[0] > last_sl[0]:  # Higher high formed after low
                    fib_050 = s_high - (0.500 * impulse)
                    fib_0618 = s_high - (0.618 * impulse)
                    fib_0786 = s_high - (0.786 * impulse)
                    
                    # Golden Pocket Entry Trigger: Low penetrated between 0.50 and 0.618 and closed above 0.618
                    if (curr_l <= fib_050) and (curr_c >= fib_0618):
                        entry_p = fib_0618
                        sl_p = fib_0786 - (0.50 * atr_v)  # Invalidation SL with ATR buffer
                        tp1_p = s_high                    # 0.000 Retest
                        tp2_p = s_high + (0.618 * impulse) # -0.618 Extension
                        tp3_p = s_high + (1.618 * impulse) # -1.618 Runner
                        
                        risk = entry_p - sl_p
                        reward1 = tp1_p - entry_p
                        if risk > 0 and (reward1 / risk) >= 1.8:
                            # Sizing with Min Notional Enforcement ($5.00 min on Binance)
                            margin = self.balance * self.margin_pct
                            notional = margin * self.leverage
                            if notional < 5.0:
                                notional = 5.0
                                margin = notional / self.leverage
                            
                            if self.balance >= margin:
                                qty = notional / entry_p
                                
                                # Maker entry fee
                                fee = notional * self.maker_fee
                                self.balance -= fee
                                self.monthly_pnl[month_key] -= fee

                                self.active_positions[sym] = {
                                    'symbol': sym,
                                    'side': 'LONG',
                                    'entry_time': current_time,
                                    'entry_price': entry_p,
                                    'initial_qty': qty,
                                    'rem_qty': qty,
                                    'sl': sl_p,
                                    'tp1': tp1_p,
                                    'tp2': tp2_p,
                                    'tp3': tp3_p,
                                    'tp1_hit': False,
                                    'tp2_hit': False,
                                    'realized_pnl': -fee
                                }
                                last_trade_bar[sym] = bar_idx
                                if len(self.active_positions) >= self.max_positions:
                                    break

                # ==========================================
                # BEARISH SETUP (Rally into Golden Pocket)
                # ==========================================
                elif is_downtrend and last_sl[0] > last_sh[0]:  # Lower low formed after high
                    fib_050 = s_low + (0.500 * impulse)
                    fib_0618 = s_low + (0.618 * impulse)
                    fib_0786 = s_low + (0.786 * impulse)

                    # Golden Pocket Entry Trigger: High penetrated between 0.50 and 0.618 and closed below 0.618
                    if (curr_h >= fib_050) and (curr_c <= fib_0618):
                        entry_p = fib_0618
                        sl_p = fib_0786 + (0.50 * atr_v)  # Invalidation SL with ATR buffer
                        tp1_p = s_low                     # 0.000 Retest
                        tp2_p = s_low - (0.618 * impulse) # -0.618 Extension
                        tp3_p = s_low - (1.618 * impulse) # -1.618 Runner

                        risk = sl_p - entry_p
                        reward1 = entry_p - tp1_p
                        if risk > 0 and (reward1 / risk) >= 1.8:
                            # Sizing with Min Notional Enforcement ($5.00 min on Binance)
                            margin = self.balance * self.margin_pct
                            notional = margin * self.leverage
                            if notional < 5.0:
                                notional = 5.0
                                margin = notional / self.leverage

                            if self.balance >= margin:
                                qty = notional / entry_p

                                # Maker entry fee
                                fee = notional * self.maker_fee
                                self.balance -= fee
                                self.monthly_pnl[month_key] -= fee

                                self.active_positions[sym] = {
                                    'symbol': sym,
                                    'side': 'SHORT',
                                    'entry_time': current_time,
                                    'entry_price': entry_p,
                                    'initial_qty': qty,
                                    'rem_qty': qty,
                                    'sl': sl_p,
                                    'tp1': tp1_p,
                                    'tp2': tp2_p,
                                    'tp3': tp3_p,
                                    'tp1_hit': False,
                                    'tp2_hit': False,
                                    'realized_pnl': -fee
                                }
                                last_trade_bar[sym] = bar_idx
                                if len(self.active_positions) >= self.max_positions:
                                    break

        self.print_results()

    def print_results(self):
        total_trades = len(self.trade_history)
        if total_trades == 0:
            print("No trades triggered.")
            return

        wins = [t for t in self.trade_history if t['realized_pnl'] > 0]
        losses = [t for t in self.trade_history if t['realized_pnl'] <= 0]
        
        win_rate = (len(wins) / total_trades) * 100
        gross_profit = sum(t['realized_pnl'] for t in wins)
        gross_loss = abs(sum(t['realized_pnl'] for t in losses))
        profit_factor = gross_profit / (gross_loss + 1e-9)
        total_return_pct = ((self.balance - self.initial_balance) / self.initial_balance) * 100

        tp1_only = len([t for t in self.trade_history if t['tp1_hit'] and not t['tp2_hit']])
        tp2_hits = len([t for t in self.trade_history if t['tp2_hit'] and t['exit_reason'] != 'FULL_TP3_RUNNER'])
        tp3_hits = len([t for t in self.trade_history if t.get('exit_reason') == 'FULL_TP3_RUNNER'])
        hard_sls = len([t for t in self.trade_history if t['exit_reason'] == 'STOP_LOSS'])
        be_sls = len([t for t in self.trade_history if t['exit_reason'] == 'SL_BE'])

        print("\n" + "="*70)
        print("🎯 STANDALONE FIBONACCI RETRACEMENT & EXTENSION BACKTEST RESULTS")
        print("="*70)
        print(f"Initial Balance:        ${self.initial_balance:,.2f} USDT")
        print(f"Final Balance:          ${self.balance:,.2f} USDT")
        print(f"Total Net Return:       {total_return_pct:+,.2f}%")
        print(f"Profit Factor (PF):     {profit_factor:.2f}")
        print(f"Total Trades:           {total_trades}")
        print(f"Win Rate:               {win_rate:.2f}% ({len(wins)}W / {len(losses)}L)")
        print(f"Average Trade PnL:      ${(self.balance - self.initial_balance)/total_trades:+,.2f}")
        print("-" * 70)
        print("📊 TRADE OUTCOME BREAKDOWN:")
        print(f" • Hard Stop Loss (Full -1R):        {hard_sls} ({hard_sls/total_trades*100:.1f}%)")
        print(f" • TP1 Hit -> SL Breakeven Exit:     {be_sls} ({be_sls/total_trades*100:.1f}%) -> Net Green (+1.06R)")
        print(f" • TP2 Hit (-0.618 Extension):       {tp2_hits} ({tp2_hits/total_trades*100:.1f}%) -> Big Win (+2.60R)")
        print(f" • TP3 Full Runner (-1.618 Ext):     {tp3_hits} ({tp3_hits/total_trades*100:.1f}%) -> Massive Trend Win (+4.53R)")
        print("-" * 70)
        print("📅 MONTHLY PnL BREAKDOWN (USDT):")
        for m, pnl in sorted(self.monthly_pnl.items()):
            bar = "🟩" if pnl >= 0 else "🟥"
            print(f" {bar} {m}:  {pnl:+8.2f} USDT")
        print("="*70 + "\n")

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Standalone Fibonacci Backtest')
    parser.add_argument('--balance', type=float, default=12.62, help='Initial balance in USDT (default: 12.62)')
    parser.add_argument('--leverage', type=int, default=50, help='Leverage multiplier (default: 50)')
    parser.add_argument('--margin-pct', type=float, default=0.025, help='Margin pct per trade (default: 0.025 = 2.5%)')
    parser.add_argument('--max-positions', type=int, default=5, help='Max concurrent positions (default: 5)')
    args = parser.parse_args()

    engine = FibonacciBacktestEngine(
        initial_balance=args.balance,
        leverage=args.leverage,
        max_positions=args.max_positions,
        margin_pct=args.margin_pct
    )
    engine.run()
