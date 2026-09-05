#!/usr/bin/env python3
"""
WEATHER-ENSEMBLE + OBJECTIVE FIBONACCI DUAL-ALPHA BACKTEST ENGINE
=================================================================
Combines:
1. 📐 Objective Fibonacci Retracement & Extension (0.500-0.618 Golden Pocket + Invalidation SL + Multi-Tier TP)
2. ⚡ Weather-Ensemble 31-Model Quantitative Consensus & 9-Pillar Voting Matrix
3. 👑 15m BTC Master Beta Trend Protection
4. 🔒 50x Leverage (3.0% margin per position, Max 5 concurrent slots, $5.00 min notional)
5. 💎 VIP0 + BNB Fee Schedule (0.018% Maker Limit Entry, 0.045% Taker SL) + 0.015% Slippage
6. 💰 Initial Wallet: $12.62 USDT (Live Binance Balance)
"""

import os
import sys
import math
import argparse
from datetime import datetime, timezone
import numpy as np
import pandas as pd

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Add parent directory to path
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from weather_ensemble_bot import (
    WeatherEnsembleBot,
    check_fibonacci_setup
)

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

class WeatherFibonacciEnsembleBacktest:
    def __init__(self, initial_balance=12.62, leverage=50, max_positions=5, margin_pct=0.03, min_weather_consensus=18, min_pillar_agreement=5, fee_tier='vip0_bnb'):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.leverage = leverage
        self.max_positions = max_positions
        self.margin_pct = margin_pct
        self.min_weather_consensus = min_weather_consensus
        self.min_pillar_agreement = min_pillar_agreement
        self.fee_tier = fee_tier
        
        self.bot = WeatherEnsembleBot(
            consensus_threshold=min_weather_consensus,
            live_trading=False,
            margin_pct=margin_pct,
            leverage=leverage,
            max_positions=max_positions
        )
        
        self.active_positions = {}
        self.trade_history = []
        self.monthly_pnl = {}
        
        # Fee Tier Settings
        if fee_tier == 'vip0_bnb':
            self.maker_fee = 0.00018  # 0.018% Maker (BNB 10% discount)
            self.taker_fee = 0.00045  # 0.045% Taker (BNB 10% discount)
            self.slippage = 0.00015   # 0.015% Slippage
        elif fee_tier == 'vip0_standard':
            self.maker_fee = 0.00020  # 0.020% Standard Maker
            self.taker_fee = 0.00050  # 0.050% Standard Taker
            self.slippage = 0.00020   # 0.020% Slippage
        elif fee_tier == 'worst_case_taker':
            self.maker_fee = 0.00050  # 0.050% Taker for everything (no limit orders)
            self.taker_fee = 0.00050  # 0.050% Taker on exit
            self.slippage = 0.00030   # 0.030% Heavy Slippage
            
        self.funding_rate_8h = 0.00010  # 0.010% average 8-hour funding rate (Binance historical baseline)
        
        # Detailed Fee Accounting Metrics
        self.total_maker_fees = 0.0
        self.total_taker_fees = 0.0
        self.total_funding_fees = 0.0
        self.total_slippage_cost = 0.0
        self.gross_profit_raw = 0.0
        self.gross_loss_raw = 0.0

    def run(self):
        raw_data = {}
        for sym in SYMBOLS:
            df = load_data(sym, "15m")
            if df is not None:
                raw_data[sym] = df
        
        if not raw_data:
            print("No cached data found!")
            return

        min_len = min(len(df) for df in raw_data.values())
        print(f"Loaded {len(raw_data)} assets from cache. Total bars per asset: {min_len:,} (15m intervals)")
        print(f"Fee Schedule Tier:     {self.fee_tier.upper()} (Maker: {self.maker_fee*100:.3f}% | Taker: {self.taker_fee*100:.3f}% | Slip: {self.slippage*100:.3f}% | 8h Funding: {self.funding_rate_8h*100:.3f}%)")
        print(f"Starting Wallet:       ${self.initial_balance:,.2f} USDT | Leverage: {self.leverage}x | Margin: {self.margin_pct*100:.1f}%\n")

        # Convert to numpy for fast execution
        np_data = {}
        for sym in SYMBOLS:
            df = raw_data[sym]
            np_data[sym] = {
                'high': df['high'].values,
                'low': df['low'].values,
                'close': df['close'].values,
                'volume': df['volume'].values if 'volume' in df.columns else np.ones(len(df)),
                'open_time': df['open_time'].values
            }

        last_trade_bar = {sym: -999 for sym in SYMBOLS}
        lookback = 100

        for bar_idx in range(lookback, min_len):
            current_time = pd.to_datetime(np_data['BTCUSDT']['open_time'][bar_idx])
            month_key = current_time.strftime('%Y-%m')
            if month_key not in self.monthly_pnl:
                self.monthly_pnl[month_key] = 0.0

            # 8-Hour Funding Rate Deduction on Open Positions (00:00, 08:00, 16:00 UTC)
            is_funding_bar = (current_time.hour in [0, 8, 16]) and (current_time.minute == 0)
            if is_funding_bar and self.active_positions:
                for sym, pos in self.active_positions.items():
                    bar_c = np_data[sym]['close'][bar_idx]
                    rem_notional = pos['rem_qty'] * bar_c
                    funding_cost = rem_notional * self.funding_rate_8h
                    self.total_funding_fees += funding_cost
                    self.balance -= funding_cost
                    self.monthly_pnl[month_key] -= funding_cost
                    pos['funding_paid'] = pos.get('funding_paid', 0.0) + funding_cost

            # 1. Manage Active Positions (TP1, TP2, TP3, SL, Breakeven)
            closed_syms = []
            for sym, pos in list(self.active_positions.items()):
                bar_h = np_data[sym]['high'][bar_idx]
                bar_l = np_data[sym]['low'][bar_idx]
                bar_c = np_data[sym]['close'][bar_idx]
                side = pos['side'].upper()
                is_long = side in ['BUY', 'LONG']
                is_short = side in ['SELL', 'SHORT']
                
                # Check Stop Loss first (worst-case execution)
                hit_sl = False
                sl_exit_price = pos['sl']
                if is_long and bar_l <= pos['sl']:
                    hit_sl = True
                    sl_exit_price = min(bar_c, pos['sl']) * (1.0 - self.slippage)
                elif is_short and bar_h >= pos['sl']:
                    hit_sl = True
                    sl_exit_price = max(bar_c, pos['sl']) * (1.0 + self.slippage)

                if hit_sl:
                    rem_qty = pos['rem_qty']
                    raw_pnl = rem_qty * (sl_exit_price - pos['entry_price']) if is_long else rem_qty * (pos['entry_price'] - sl_exit_price)
                    taker_fee = rem_qty * sl_exit_price * self.taker_fee
                    slip_cost = rem_qty * sl_exit_price * self.slippage
                    
                    self.total_taker_fees += taker_fee
                    self.total_slippage_cost += slip_cost
                    if raw_pnl > 0:
                        self.gross_profit_raw += raw_pnl
                    else:
                        self.gross_loss_raw += abs(raw_pnl)
                        
                    net_pnl = raw_pnl - taker_fee
                    self.balance += net_pnl
                    self.monthly_pnl[month_key] += net_pnl
                    
                    pos['realized_pnl'] += net_pnl
                    pos['exit_time'] = current_time
                    pos['exit_reason'] = 'SL_BE' if pos['tp1_hit'] else 'STOP_LOSS'
                    self.trade_history.append(pos)
                    closed_syms.append(sym)
                    continue

                # Check TP1 (0.000 Retest - 40% Scale Out + Move SL to Breakeven)
                if not pos['tp1_hit']:
                    tp1_hit = (is_long and bar_h >= pos['tp1']) or (is_short and bar_l <= pos['tp1'])
                    if tp1_hit:
                        pos['tp1_hit'] = True
                        close_qty = pos['initial_qty'] * 0.40
                        pos['rem_qty'] -= close_qty
                        
                        tp_p = pos['tp1']
                        raw_pnl = close_qty * (tp_p - pos['entry_price']) if is_long else close_qty * (pos['entry_price'] - tp_p)
                        maker_fee = close_qty * tp_p * self.maker_fee
                        
                        self.total_maker_fees += maker_fee
                        self.gross_profit_raw += raw_pnl
                        
                        net_pnl = raw_pnl - maker_fee
                        self.balance += net_pnl
                        self.monthly_pnl[month_key] += net_pnl
                        pos['realized_pnl'] += net_pnl
                        
                        # Move stop to breakeven
                        pos['sl'] = pos['entry_price']

                # Check TP2 (-0.618 Extension - 40% Scale Out)
                if pos['tp1_hit'] and not pos['tp2_hit']:
                    tp2_hit = (is_long and bar_h >= pos['tp2']) or (is_short and bar_l <= pos['tp2'])
                    if tp2_hit:
                        pos['tp2_hit'] = True
                        close_qty = pos['initial_qty'] * 0.40
                        pos['rem_qty'] -= close_qty
                        
                        tp_p = pos['tp2']
                        raw_pnl = close_qty * (tp_p - pos['entry_price']) if is_long else close_qty * (pos['entry_price'] - tp_p)
                        maker_fee = close_qty * tp_p * self.maker_fee
                        
                        self.total_maker_fees += maker_fee
                        self.gross_profit_raw += raw_pnl
                        
                        net_pnl = raw_pnl - maker_fee
                        self.balance += net_pnl
                        self.monthly_pnl[month_key] += net_pnl
                        pos['realized_pnl'] += net_pnl
                        
                        # Trail stop to TP1 level for remaining 20% runner
                        pos['sl'] = pos['tp1']

                # Check TP3 (-1.618 Runner - Remaining 20%)
                if pos['tp2_hit']:
                    tp3_hit = (is_long and bar_h >= pos['tp3']) or (is_short and bar_l <= pos['tp3'])
                    if tp3_hit:
                        close_qty = pos['rem_qty']
                        tp_p = pos['tp3']
                        raw_pnl = close_qty * (tp_p - pos['entry_price']) if is_long else close_qty * (pos['entry_price'] - tp_p)
                        maker_fee = close_qty * tp_p * self.maker_fee
                        
                        self.total_maker_fees += maker_fee
                        self.gross_profit_raw += raw_pnl
                        
                        net_pnl = raw_pnl - maker_fee
                        self.balance += net_pnl
                        self.monthly_pnl[month_key] += net_pnl
                        pos['realized_pnl'] += net_pnl
                        
                        pos['exit_time'] = current_time
                        pos['exit_reason'] = 'FULL_TP3_RUNNER'
                        self.trade_history.append(pos)
                        closed_syms.append(sym)
                        continue

            for sym in closed_syms:
                if sym in self.active_positions:
                    del self.active_positions[sym]

            # 2. Evaluate Dual Alpha Signals: Fibonacci Golden Pocket + Weather-Ensemble Consensus
            if len(self.active_positions) >= self.max_positions:
                continue

            # BTC Master Health Filter check
            btc_closes = np_data['BTCUSDT']['close'][bar_idx-25:bar_idx+1]
            btc_ret = (btc_closes[-1] - btc_closes[-2]) / btc_closes[-2]
            btc_ema20 = pd.Series(btc_closes).ewm(span=20, adjust=False).mean().iloc[-1]
            btc_dumping = (btc_closes[-1] < btc_ema20 and btc_ret < -0.0050)
            btc_pumping = (btc_closes[-1] > btc_ema20 and btc_ret > +0.0060)

            for sym in SYMBOLS:
                if sym in self.active_positions:
                    continue
                if (bar_idx - last_trade_bar[sym]) < 8:  # 2-hour trade spacing per asset
                    continue

                # Slice dataframe for both engines
                df_slice = raw_data[sym].iloc[bar_idx - lookback + 1 : bar_idx + 1]
                
                # 1. Evaluate Objective Fibonacci Setup
                fib_setup = check_fibonacci_setup(df_slice, sym)
                
                if fib_setup.get('is_setup') and fib_setup.get('rr', 0) >= 1.8:
                    side = fib_setup['side']
                    
                    # 2. Evaluate Weather-Ensemble 31 Models & 9 Quant Pillars
                    weather_signals = self.bot.evaluate_31_models(df_slice)
                    bull_models = weather_signals.count('BULLISH')
                    bear_models = weather_signals.count('BEARISH')
                    pillar_bull, pillar_bear, _ = self.bot.compute_pillar_consensus(weather_signals)

                    # Check Weather Agreement Confluence
                    if side == 'BUY':
                        if btc_dumping and sym != 'BTCUSDT':
                            continue
                        weather_aligned = (bull_models >= self.min_weather_consensus) or (pillar_bull >= self.min_pillar_agreement)
                    else:
                        if btc_pumping and sym != 'BTCUSDT':
                            continue
                        weather_aligned = (bear_models >= self.min_weather_consensus) or (pillar_bear >= self.min_pillar_agreement)

                    if weather_aligned:
                        entry_p = fib_setup['entry_price']
                        sl_p = fib_setup['sl']
                        tp1_p = fib_setup['tp1']
                        tp2_p = fib_setup['tp2']
                        tp3_p = fib_setup['tp3']
                        
                        # Sizing with Binance $5.00 min notional enforcement
                        margin = self.balance * self.margin_pct
                        notional = margin * self.leverage
                        if notional < 5.0:
                            notional = 5.0
                            margin = notional / self.leverage
                        
                        if self.balance >= margin:
                            qty = notional / entry_p
                            
                            # Entry Fee (Maker or Taker depending on tier)
                            entry_fee = notional * self.maker_fee
                            self.total_maker_fees += entry_fee
                            self.balance -= entry_fee
                            self.monthly_pnl[month_key] -= entry_fee

                            self.active_positions[sym] = {
                                'symbol': sym,
                                'side': side,
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
                                'realized_pnl': -entry_fee,
                                'channel': 'WEATHER_FIBONACCI_CONFLUENCE',
                                'consensus': bull_models if side == 'BUY' else bear_models,
                                'pillars': pillar_bull if side == 'BUY' else pillar_bear
                            }
                            last_trade_bar[sym] = bar_idx
                            if len(self.active_positions) >= self.max_positions:
                                break

        # Close remaining open positions at market close
        for sym, pos in list(self.active_positions.items()):
            bar_c = np_data[sym]['close'][-1]
            rem_qty = pos['rem_qty']
            raw_pnl = rem_qty * (bar_c - pos['entry_price']) if pos['side'] in ['BUY', 'LONG'] else rem_qty * (pos['entry_price'] - bar_c)
            taker_fee = rem_qty * bar_c * self.taker_fee
            self.total_taker_fees += taker_fee
            if raw_pnl > 0:
                self.gross_profit_raw += raw_pnl
            else:
                self.gross_loss_raw += abs(raw_pnl)
            net_pnl = raw_pnl - taker_fee
            self.balance += net_pnl
            pos['realized_pnl'] += net_pnl
            pos['exit_time'] = pd.to_datetime(np_data[sym]['open_time'][-1])
            pos['exit_reason'] = 'MARKET_END'
            self.trade_history.append(pos)

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

        hard_sls = len([t for t in self.trade_history if t['exit_reason'] == 'STOP_LOSS'])
        be_sls = len([t for t in self.trade_history if t['exit_reason'] == 'SL_BE'])
        tp2_hits = len([t for t in self.trade_history if t['tp2_hit'] and t['exit_reason'] != 'FULL_TP3_RUNNER'])
        tp3_hits = len([t for t in self.trade_history if t.get('exit_reason') == 'FULL_TP3_RUNNER'])
        total_all_friction = self.total_maker_fees + self.total_taker_fees + self.total_funding_fees + self.total_slippage_cost

        print("\n" + "="*75)
        print("⚡ WEATHER-ENSEMBLE + FIBONACCI: EXHAUSTIVE FEE & FRICTION AUDIT")
        print("="*75)
        print(f"Fee Schedule Tier:      {self.fee_tier.upper()}")
        print(f"Initial Balance:        ${self.initial_balance:,.2f} USDT")
        print(f"Final Net Balance:      ${self.balance:,.2f} USDT (After 100% Fees & Slippage)")
        print(f"Total Net Return:       {total_return_pct:+,.2f}%")
        print(f"Net Profit Factor:      {profit_factor:.2f}")
        print(f"Total Trades:           {total_trades}")
        print(f"Win Rate:               {win_rate:.2f}% ({len(wins)}W / {len(losses)}L)")
        print("-" * 75)
        print("💰 EXHAUSTIVE FEE & FRICTION ACCOUNTING BREAKDOWN:")
        print(f" • Gross Profit (Raw Market PnL):    ${self.gross_profit_raw:,.2f} USDT")
        print(f" • Gross Losses (Raw Market PnL):    ${self.gross_loss_raw:,.2f} USDT")
        print(f" • Total Maker Fees Paid:            ${self.total_maker_fees:,.2f} USDT ({self.maker_fee*100:.3f}% on Entry & TP limits)")
        print(f" • Total Taker Fees Paid:            ${self.total_taker_fees:,.2f} USDT ({self.taker_fee*100:.3f}% on SL & Close)")
        print(f" • Total 8-Hour Funding Fees Paid:   ${self.total_funding_fees:,.2f} USDT (0.010%/8h on open positions)")
        print(f" • Total Slippage Friction:          ${self.total_slippage_cost:,.2f} USDT ({self.slippage*100:.3f}% per market order)")
        print(f" • COMBINED TOTAL FRICTION DEDUCTED: ${total_all_friction:,.2f} USDT")
        print("-" * 75)
        print("📊 TRADE OUTCOME BREAKDOWN:")
        print(f" • Hard Stop Loss (Full -1R):        {hard_sls} ({hard_sls/total_trades*100:.1f}%)")
        print(f" • TP1 Hit -> SL Breakeven Exit:     {be_sls} ({be_sls/total_trades*100:.1f}%) -> Net Green (+1.06R)")
        print(f" • TP2 Hit (-0.618 Extension):       {tp2_hits} ({tp2_hits/total_trades*100:.1f}%) -> Big Win (+2.60R)")
        print(f" • TP3 Full Runner (-1.618 Ext):     {tp3_hits} ({tp3_hits/total_trades*100:.1f}%) -> Massive Trend Win (+4.53R)")
        print("-" * 75)
        print("📅 MONTHLY PnL BREAKDOWN (AFTER ALL FEES & FUNDING):")
        for m, pnl in sorted(self.monthly_pnl.items()):
            bar = "🟩" if pnl >= 0 else "🟥"
            print(f" {bar} {m}:  {pnl:+12.2f} USDT")
        print("="*75 + "\n")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Weather + Fibonacci Ensemble Backtest')
    parser.add_argument('--balance', type=float, default=12.62, help='Initial balance in USDT (default: 12.62)')
    parser.add_argument('--leverage', type=int, default=50, help='Leverage multiplier (default: 50)')
    parser.add_argument('--margin-pct', type=float, default=0.03, help='Margin pct per trade (default: 0.03 = 3.0%)')
    parser.add_argument('--max-positions', type=int, default=5, help='Max concurrent positions (default: 5)')
    parser.add_argument('--min-consensus', type=int, default=18, help='Min 31-model consensus (default: 18)')
    parser.add_argument('--min-pillars', type=int, default=5, help='Min pillar agreement (default: 5/9)')
    parser.add_argument('--fee-tier', type=str, default='vip0_bnb', choices=['vip0_bnb', 'vip0_standard', 'worst_case_taker'], help='Fee tier schedule (default: vip0_bnb)')
    args = parser.parse_args()

    engine = WeatherFibonacciEnsembleBacktest(
        initial_balance=args.balance,
        leverage=args.leverage,
        max_positions=args.max_positions,
        margin_pct=args.margin_pct,
        min_weather_consensus=args.min_consensus,
        min_pillar_agreement=args.min_pillars,
        fee_tier=args.fee_tier
    )
    engine.run()
