#!/usr/bin/env python3
"""
WEATHER-ENSEMBLE BINANCE FUTURES LIVE AI TRADING AGENT + INTERACTIVE TELEGRAM C2
================================================================================
Production Hardened Version:
- 30x Fast Recovery Sizing (20% margin allocation, micro-lot assets)
- L2 Order Book Depth Imbalance Gate (Top-20 Bids vs Asks)
- 8-Hour Funding Rate & Squeeze Filter
- Automated Orphaned Order Garbage Collection (Prevents accidental reverse entries)
- Partial Take-Profit Scaling (50% TP1 @ 1.5x ATR, 50% Trailing Runner)
- 6% Daily Drawdown Circuit Breaker
- Interactive Telegram Inline Keyboard (1-Tap mobile buttons) & C2 Commands
"""

import os
import sys
import time
import math
import json
import random
import hmac
import hashlib
import urllib.parse
import argparse
import threading
from datetime import datetime, timezone
import requests
import numpy as np
import pandas as pd

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# --------------------------------------------------------------------------
# Environment Configuration (.env Loader)
# --------------------------------------------------------------------------
def load_env_file(env_file='.env'):
    if os.path.exists(env_file):
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ[k.strip()] = v.strip()

load_env_file()

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
TELEGRAM_NOTIFICATIONS = os.getenv('TELEGRAM_NOTIFICATIONS', 'true').lower() == 'true'

BINANCE_API_KEY = os.getenv('BINANCE_API_KEY', '')
BINANCE_API_SECRET = os.getenv('BINANCE_API_SECRET', '')
BINANCE_WHITELISTED_IP = os.getenv('BINANCE_WHITELISTED_IP', '').strip()

# --------------------------------------------------------------------------
# 🌐 Binance IP Whitelist Watchdog & Alert Engine
# --------------------------------------------------------------------------
_LAST_IP_ALERT_TIME = 0
_LAST_KNOWN_PUBLIC_IP = None
_LAST_PERIODIC_IP_CHECK = 0

def get_current_public_ip():
    """Fetches this machine's public egress IP address from redundant resolvers"""
    global _LAST_KNOWN_PUBLIC_IP
    resolvers = [
        'https://api.ipify.org?format=json',
        'https://ifconfig.me/all.json',
        'https://api.my-ip.io/ip'
    ]
    for url in resolvers:
        try:
            r = requests.get(url, timeout=4)
            if r.status_code == 200:
                if 'json' in url or 'ipify' in url:
                    data = r.json()
                    ip = data.get('ip') or data.get('ip_addr')
                else:
                    ip = r.text.strip()
                if ip and len(ip.split('.')) == 4:
                    _LAST_KNOWN_PUBLIC_IP = ip
                    return ip
        except Exception:
            continue
    return _LAST_KNOWN_PUBLIC_IP or "Unknown IP"

def trigger_ip_whitelist_alert(error_msg, current_ip=None):
    """Broadcasts a high-priority Telegram alert if current IP is not on Binance Whitelist"""
    global _LAST_IP_ALERT_TIME
    now = time.time()
    if now - _LAST_IP_ALERT_TIME < 600:  # 10-minute cooldown against spam
        return
    _LAST_IP_ALERT_TIME = now

    ip_str = current_ip or get_current_public_ip()
    whitelisted_cfg = os.getenv('BINANCE_WHITELISTED_IP', BINANCE_WHITELISTED_IP).strip()

    print(f"\n🚨 [BINANCE IP WHITELIST ALERT] Current IP ({ip_str}) is NOT authorized! Error: {error_msg}\n", flush=True)

    cfg_line = f"• <b>Configured Whitelist IP:</b> <code>{whitelisted_cfg}</code>\n" if whitelisted_cfg else ""
    msg = (
        f"🚨 <b>BINANCE IP WHITELIST ALERT</b> 🚨\n\n"
        f"⚠️ <b>Your server IP is not authorized on Binance Futures API!</b>\n\n"
        f"• <b>Current Public IP:</b> <code>{ip_str}</code>\n"
        f"{cfg_line}"
        f"• <b>Reason / Error:</b> <i>{error_msg}</i>\n\n"
        f"👉 <b>Action Required:</b>\n"
        f"1. Log into your Binance Account ➔ <b>API Management</b>.\n"
        f"2. Add <code>{ip_str}</code> to the IP Access Restriction whitelist.\n"
        f"3. Confirm 'Enable Futures' is checked."
    )
    send_telegram_msg(msg)

def check_binance_ip_whitelist(probe_api=False):
    """
    Verifies that public IP matches BINANCE_WHITELISTED_IP
    and optionally probes Binance authenticated account endpoint.
    Returns (is_valid: bool, current_ip: str)
    """
    whitelisted_cfg = os.getenv('BINANCE_WHITELISTED_IP', BINANCE_WHITELISTED_IP).strip()
    current_ip = get_current_public_ip()

    if whitelisted_cfg:
        allowed = [ip.strip() for ip in whitelisted_cfg.split(',') if ip.strip()]
        if current_ip != "Unknown IP" and allowed and current_ip not in allowed:
            trigger_ip_whitelist_alert(
                f"Machine Public IP ({current_ip}) does not match configured whitelist ({whitelisted_cfg})",
                current_ip=current_ip
            )
            return False, current_ip

    if probe_api:
        acc_test = binance_futures_signed_request('GET', '/fapi/v2/account')
        if isinstance(acc_test, dict) and acc_test.get('code') == -2015:
            trigger_ip_whitelist_alert(
                acc_test.get('msg', 'Invalid API-key, IP, or permissions for action'),
                current_ip=current_ip
            )
            return False, current_ip

    return True, current_ip

# Bug #4 Fix: Global ccxt exchange instance (initialized once, reused everywhere)
_CCXT_EXCHANGE = None
def get_ccxt_exchange():
    global _CCXT_EXCHANGE
    if _CCXT_EXCHANGE is None:
        import ccxt
        _CCXT_EXCHANGE = ccxt.binance({
            'apiKey': os.getenv('BINANCE_API_KEY', BINANCE_API_KEY),
            'secret': os.getenv('BINANCE_API_SECRET', BINANCE_API_SECRET),
            'options': {'defaultType': 'future', 'adjustForTimeDifference': True}
        })
        _CCXT_EXCHANGE.load_time_difference()
    return _CCXT_EXCHANGE

OPTIMIZED_SYMBOLS = [
    # 🏆 Alpha Champions Universe (Crypto Heavyweights + Macro Precious Metals)
    # Crypto Core & Trend Leaders:
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT", "XRPUSDT", "ADAUSDT", "APTUSDT",
    # 🏛️ Macro Commodities & Precious Metals (Deep Liquidity):
    "XAUUSDT",  # 🥇 Gold Perpetual ($2.42B 24h Vol)
    "XAGUSDT",  # 🥈 Silver Perpetual ($899M 24h Vol)
    "PAXGUSDT"  # 🪙 PAX Gold Token ($81M 24h Vol)
]

# --------------------------------------------------------------------------
# ⚡ Global API Cache & Rate-Limit Shield (Prevents Error 429 IP Bans)
# --------------------------------------------------------------------------
class GlobalDataCache:
    """
    ⚡ Global API Cache & Rate-Limit Shield:
    - Fetches ALL perpetual funding rates in a single API call (/fapi/v1/premiumIndex).
    - Fetches BTC 15m klines once per loop cycle (used by BTC Macro Health & ADX Regime).
    - Reduces Binance API weight consumption by over 70%, preventing Error 429 IP bans.
    """
    def __init__(self):
        self.all_funding = {}
        self.btc_15m_raw = None
        self.last_update = 0

    def update(self, force=False):
        now = time.time()
        if not force and (now - self.last_update < 6) and self.all_funding and self.btc_15m_raw:
            return

        # 1. Fetch ALL funding rates in 1 single call
        try:
            r = requests.get("https://fapi.binance.com/fapi/v1/premiumIndex", timeout=3)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    for item in data:
                        sym = item.get('symbol')
                        if sym:
                            self.all_funding[sym] = float(item.get('lastFundingRate', 0.0))
        except Exception:
            pass

        # 2. Fetch BTC 15m klines ONCE per cycle
        try:
            r = requests.get("https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=15m&limit=45", timeout=3)
            if r.status_code == 200:
                raw = r.json()
                if isinstance(raw, list) and len(raw) >= 30:
                    self.btc_15m_raw = raw
        except Exception:
            pass

        self.last_update = now

GLOBAL_CACHE = GlobalDataCache()

# --------------------------------------------------------------------------
# Circuit Breaker & Risk Protection Manager
# --------------------------------------------------------------------------
class CircuitBreakerManager:
    """
    Automated Protection:
    - Trips if daily drawdown exceeds 6%
    - Trips if 3 consecutive losses occur
    - Auto-syncs realized PnL from Binance Income API
    """
    def __init__(self, daily_drawdown_limit_pct=0.06, max_consecutive_losses=3):
        self.enabled = True
        self.daily_limit_pct = daily_drawdown_limit_pct
        self.max_losses = max_consecutive_losses
        self.daily_start_balance = None
        self.daily_start_time = time.time()
        self.consecutive_losses = 0
        self.circuit_tripped = False
        self.circuit_tripped_until = 0  # Unix timestamp until which circuit stays tripped
        self.trip_reason = ""
        self.asset_cooldowns = {} # symbol -> cooldown_until_timestamp
        self.last_synced_income_time = None
        
        # Upgrade 5: Automated Daily Performance Ledger
        self.current_utc_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.trades_today = 0
        self.wins_today = 0
        self.losses_today = 0
        self.realized_pnl_today = 0.0
        self.best_win_today = 0.0
        self.worst_loss_today = 0.0

    def set_enabled(self, val: bool):
        self.enabled = bool(val)
        if not self.enabled:
            self.circuit_tripped = False
            self.trip_reason = ""
            self.consecutive_losses = 0
            self.circuit_tripped_until = 0
        print(f"🛡️ [CIRCUIT BREAKER] Enabled set to: {self.enabled}", flush=True)
        return self.enabled

    def toggle_enabled(self):
        return self.set_enabled(not self.enabled)

    def is_asset_in_cooldown(self, symbol):
        until = self.asset_cooldowns.get(symbol, 0)
        return time.time() < until

    def trigger_asset_cooldown(self, symbol, duration_seconds=3600):
        self.asset_cooldowns[symbol] = time.time() + duration_seconds
        print(f"[ASSET COOLDOWN] #{symbol} paused for {duration_seconds/60:.0f} mins to prevent knife-catching.", flush=True)

    def sync_binance_realized_pnl(self):
        """
        Fetches the latest REALIZED_PNL events from Binance Futures Income API.
        Tracks consecutive losses, triggers asset cooldowns, and trips the circuit breaker in real-time.
        """
        try:
            if not self.last_synced_income_time:
                self.last_synced_income_time = int(time.time() * 1000)

            income_events = binance_futures_signed_request('GET', '/fapi/v1/income', {
                'incomeType': 'REALIZED_PNL',
                'startTime': self.last_synced_income_time + 1,
                'limit': 50
            })

            if isinstance(income_events, list) and income_events:
                sorted_events = sorted(income_events, key=lambda x: x.get('time', 0))
                for event in sorted_events:
                    pnl = float(event.get('income', 0.0))
                    sym = event.get('symbol', '')
                    t_ms = event.get('time', 0)
                    self.last_synced_income_time = max(self.last_synced_income_time, t_ms)

                    # Update internal stats
                    self.trades_today += 1
                    self.realized_pnl_today += pnl
                    target_ch = ACTIVE_POSITION_TARGETS.get(sym, {}).get('channel', 'FIBONACCI') if 'ACTIVE_POSITION_TARGETS' in globals() else 'FIBONACCI'
                    if 'ATLAS_DARWINIAN' in globals():
                        ATLAS_DARWINIAN.record_trade_outcome(target_ch, pnl)
                    if pnl < -0.005:
                        self.consecutive_losses += 1
                        self.losses_today += 1
                        self.worst_loss_today = min(self.worst_loss_today, pnl)
                        # Trigger 60-min asset cooldown on loss symbol to prevent knife-catching
                        if sym:
                            self.trigger_asset_cooldown(sym, duration_seconds=3600)
                        print(f"⚠️ [CIRCUIT BREAKER SYNC] Realized Loss: ${pnl:.4f} on #{sym} (Ch: {target_ch}) | Streak: {self.consecutive_losses}/{self.max_losses} losses", flush=True)
                    elif pnl > 0.005:
                        self.consecutive_losses = 0
                        self.wins_today += 1
                        self.best_win_today = max(self.best_win_today, pnl)
                        print(f"🎯 [CIRCUIT BREAKER SYNC] Realized Win: +${pnl:.4f} on #{sym} (Ch: {target_ch}) | Loss streak reset", flush=True)

                if self.enabled and self.consecutive_losses >= self.max_losses:
                    self.circuit_tripped = True
                    # Stay tripped until end of current UTC day
                    now_utc = datetime.now(timezone.utc)
                    end_of_day = now_utc.replace(hour=23, minute=59, second=59)
                    self.circuit_tripped_until = end_of_day.timestamp()
                    self.trip_reason = f"{self.consecutive_losses} consecutive losses reached (Limit: {self.max_losses})"
                    print(f"🛑 [CIRCUIT BREAKER TRIPPED] {self.trip_reason}! Halting new trade entries until 00:00 UTC.", flush=True)
                    send_telegram_msg(f"🛑 <b>CIRCUIT BREAKER TRIPPED</b>\n\nReason: {self.trip_reason}\n• Realized PnL Today: <b>${self.realized_pnl_today:+,.2f} USDT</b>\n• Total Trades Today: <b>{self.trades_today}</b> ({self.wins_today}W / {self.losses_today}L)\n\n<i>Automated new entries paused until 00:00 UTC. Existing positions managed normally.</i>")
        except Exception as e:
            pass

    def check_and_update(self, current_balance):
        now_dt = datetime.now(timezone.utc)
        today_str = now_dt.strftime("%Y-%m-%d")

        # Sync latest Binance realized PnL events
        self.sync_binance_realized_pnl()

        # If Circuit Breaker is manually disabled, never trip
        if not self.enabled:
            self.circuit_tripped = False
            self.trip_reason = ""
            return True

        # Check for 00:00 UTC Daily Rollover -> Broadcast Daily Report
        if today_str != self.current_utc_day:
            self.broadcast_daily_summary_report(current_balance)
            self.current_utc_day = today_str
            self.daily_start_balance = current_balance
            self.daily_start_time = time.time()
            self.consecutive_losses = 0
            self.trades_today = 0
            self.wins_today = 0
            self.losses_today = 0
            self.realized_pnl_today = 0.0
            self.best_win_today = 0.0
            self.worst_loss_today = 0.0
            self.circuit_tripped = False
            self.trip_reason = ""

        if self.daily_start_balance is None:
            self.daily_start_balance = current_balance

        # Bug #5 Fix: Once tripped, stay tripped until the timer expires (end of UTC day)
        if self.circuit_tripped and time.time() < self.circuit_tripped_until:
            return False
        elif self.circuit_tripped and time.time() >= self.circuit_tripped_until:
            # Timer expired (new UTC day) - auto-reset
            self.circuit_tripped = False
            self.trip_reason = ""
            self.consecutive_losses = 0
            print(f"🟢 [CIRCUIT BREAKER AUTO-RESET] New UTC day. Circuit breaker reset. Trading resumed.", flush=True)

        if self.daily_start_balance and self.daily_start_balance > 0:
            dd = (self.daily_start_balance - current_balance) / self.daily_start_balance
            if dd >= self.daily_limit_pct:
                self.circuit_tripped = True
                now_utc = datetime.now(timezone.utc)
                end_of_day = now_utc.replace(hour=23, minute=59, second=59)
                self.circuit_tripped_until = end_of_day.timestamp()
                self.trip_reason = f"Daily drawdown hit {dd*100:.1f}% (Limit: {self.daily_limit_pct*100:.1f}%)"
                return False

        if self.consecutive_losses >= self.max_losses:
            self.circuit_tripped = True
            now_utc = datetime.now(timezone.utc)
            end_of_day = now_utc.replace(hour=23, minute=59, second=59)
            self.circuit_tripped_until = end_of_day.timestamp()
            self.trip_reason = f"{self.consecutive_losses} consecutive losses reached (Limit: {self.max_losses})"
            return False

        return True

    def record_trade_result(self, pnl):
        self.trades_today += 1
        self.realized_pnl_today += pnl
        if pnl < 0:
            self.consecutive_losses += 1
            self.losses_today += 1
            self.worst_loss_today = min(self.worst_loss_today, pnl)
        else:
            self.consecutive_losses = 0
            self.wins_today += 1
            self.best_win_today = max(self.best_win_today, pnl)

    def reset_circuit(self, current_balance=None):
        if current_balance is not None and current_balance > 0:
            self.daily_start_balance = current_balance
        self.consecutive_losses = 0
        self.circuit_tripped = False
        self.circuit_tripped_until = 0
        self.trip_reason = ""
        self.asset_cooldowns = {}
        # Advance last_synced_income_time to current time so old losses don't re-trip immediately
        self.last_synced_income_time = int(time.time() * 1000)
        print("🟢 [CIRCUIT BREAKER MANUALLY RESET] Circuit breaker cleared and trading resumed.", flush=True)

    def broadcast_daily_summary_report(self, ending_balance):
        """Upgrade 5: Automated Daily Performance Ledger Broadcast (00:00 UTC)"""
        start_b = self.daily_start_balance or ending_balance
        net_pnl = ending_balance - start_b
        pnl_pct = (net_pnl / start_b * 100) if start_b > 0 else 0.0
        wr = (self.wins_today / self.trades_today * 100) if self.trades_today > 0 else 0.0
        status_emoji = "🟩 PROFITABLE DAY" if net_pnl >= 0 else "🟥 DRAWDOWN DAY"

        msg = (
            f"📊 <b>AUTOMATED DAILY PERFORMANCE LEDGER (00:00 UTC)</b>\n\n"
            f"<b>Status:</b> {status_emoji}\n"
            f"<b>Date:</b> {self.current_utc_day}\n"
            f"<b>Starting Balance:</b> ${start_b:,.2f} USDT\n"
            f"<b>Ending Balance:</b> ${ending_balance:,.2f} USDT\n"
            f"<b>Net Daily Realized PnL:</b> <b>{net_pnl:+,.2f} USDT ({pnl_pct:+.2f}%)</b>\n"
            f"<b>Trades Completed:</b> {self.trades_today} ({self.wins_today}W / {self.losses_today}L)\n"
            f"<b>Daily Win Rate:</b> <b>{wr:.1f}%</b>\n"
            f"<b>Best Win:</b> +${self.best_win_today:,.2f} USDT\n"
            f"<b>Worst Loss:</b> -${abs(self.worst_loss_today):,.2f} USDT\n"
            f"<b>Circuit Health:</b> {'🟢 NORMAL' if not self.circuit_tripped else '🛑 TRIPPED'}\n\n"
            f"<i>⚡ Weather-Ensemble AI V2 Upgraded Engine Active</i>"
        )
        send_telegram_msg(msg, reply_markup=get_telegram_inline_keyboard())
        print(f"\n[DAILY REPORT BROADCAST] {self.current_utc_day} | Net PnL: {net_pnl:+,.2f} USDT | Win Rate: {wr:.1f}%\n", flush=True)

CIRCUIT_BREAKER = CircuitBreakerManager()

# --------------------------------------------------------------------------
# Automated Profit Sweeper & Milestone Lock Manager
# --------------------------------------------------------------------------
class MilestoneLockManager:
    """
    Tracks recovery milestones ($30, $50, $100, $250, $500, $1000) and locks baseline equity.
    """
    def __init__(self, initial_capital=14.20):
        self.initial_capital = initial_capital
        self.peak_balance = initial_capital
        self.milestones = [30.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 5000.0]
        self.locked_milestone = 0.0

    def update(self, current_balance):
        if current_balance > self.peak_balance:
            self.peak_balance = current_balance
            for m in self.milestones:
                if self.peak_balance >= m and m > self.locked_milestone:
                    self.locked_milestone = m
                    suggested_sweep = round(m * 0.30, 2)
                    msg = (
                        f"🏆 <b>ACCOUNT MILESTONE LOCKED!</b>\n\n"
                        f"💰 Wallet Peak: <b>${self.peak_balance:,.2f} USDT</b>\n"
                        f"🔒 Milestone Floor: <b>${m:,.2f} USDT</b> secured!\n\n"
                        f"🏦 <b>SUGGESTED PROFIT SWEEP:</b>\n"
                        f"Withdraw <b>${suggested_sweep:,.2f} USDT (30%)</b> to Binance Spot / Cold Storage to lock in real-world cash! 💵"
                    )
                    send_telegram_msg(msg)
        return self.locked_milestone

MILESTONE_MANAGER = MilestoneLockManager()

# --------------------------------------------------------------------------
# 🧬 ATLAS COMPONENT 1: Darwinian Channel Weight & Optimization Engine
# --------------------------------------------------------------------------
class AtlasDarwinianOptimizer:
    """
    ATLAS-inspired Darwinian Weighting Layer:
    - Maintains live rolling Sharpe / Win-Rate scorecards across all active signal channels.
    - Dynamically scales capital allocation (0.80x to 1.50x) based on real trading outcomes.
    - Automatically persists weights to data/state/atlas_darwinian_weights.json.
    """
    def __init__(self, channels=['FIBONACCI', 'MSS_SHIFT', '5MA_CONSENSUS', 'POTATO_SR', 'DIVERGENCE']):
        self.state_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'state', 'atlas_darwinian_weights.json')
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        self.channels = channels
        self.weights = {ch: 1.0 for ch in channels}
        self.channel_history = {ch: [] for ch in channels}
        self._load_state()

    def _load_state(self):
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    for ch in self.channels:
                        if ch in data.get('weights', {}):
                            self.weights[ch] = float(data['weights'][ch])
                        if ch in data.get('history', {}):
                            self.channel_history[ch] = data['history'][ch][-200:]
        except Exception as e:
            print(f"[ATLAS DARWINIAN LOAD WARN] {e}", flush=True)

    def _save_state(self):
        try:
            with open(self.state_file, 'w') as f:
                json.dump({
                    'weights': self.weights,
                    'history': {ch: self.channel_history[ch][-200:] for ch in self.channels},
                    'updated_at': datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                }, f, indent=2)
        except Exception as e:
            pass

    def record_trade_outcome(self, channel, pnl):
        if channel in self.channel_history:
            self.channel_history[channel].append(float(pnl))
            hist = self.channel_history[channel]
            if len(hist) >= 10:
                wins = sum(1 for p in hist[-30:] if p > 0)
                wr = wins / len(hist[-30:])
                tot_pnl = sum(hist[-30:])
                if wr >= 0.55 and tot_pnl > 0:
                    self.weights[channel] = min(1.50, round(self.weights[channel] * 1.05, 3))
                elif wr < 0.45 or tot_pnl < 0:
                    self.weights[channel] = max(0.80, round(self.weights[channel] * 0.95, 3))
            self._save_state()

    def get_multiplier(self, channel):
        return self.weights.get(channel, 1.0)

    def get_status_report(self):
        lines = ["🧬 <b>ATLAS DARWINIAN WEIGHT MATRIX</b>\n"]
        for ch in self.channels:
            hist = self.channel_history.get(ch, [])
            n = len(hist)
            wins = sum(1 for p in hist if p > 0)
            wr = (wins / n * 100.0) if n > 0 else 0.0
            tot_pnl = sum(hist)
            w = self.weights.get(ch, 1.0)
            status = "🟢 ACTIVE" if w >= 1.0 else "🟡 SCALED"
            lines.append(f"• <b>{ch:<14}</b>: {w:.2f}x | WR: {wr:.1f}% ({wins}W/{n-wins}L) | PnL: ${tot_pnl:+,.2f} | {status}")
        return "\n".join(lines)

ATLAS_DARWINIAN = AtlasDarwinianOptimizer()

# --------------------------------------------------------------------------
# 🛡️ ATLAS COMPONENT 2: Adversarial Chief Risk Officer (CRO) Gate
# --------------------------------------------------------------------------
class AdversarialCRO:
    """
    ATLAS Adversarial CRO (Chief Risk Officer):
    - Attacks every candidate trade before order placement.
    - Blocks overextended entries (> 2.8x ATR from 50 EMA).
    - Prevents crowded micro-whipsaw traps.
    """
    @staticmethod
    def inspect_trade(symbol, side, current_price, ema50, atr14, df=None):
        if ema50 > 0 and atr14 > 0:
            dist_from_ema = abs(current_price - ema50)
            if dist_from_ema > (2.8 * atr14):
                return False, f"Overextended from 50 EMA ({dist_from_ema:.2f} > 2.8x ATR)"

        if df is not None and len(df) >= 4:
            closes = df['close'].values
            c1, c2, c3 = closes[-3], closes[-2], closes[-1]
            if (c1 > c2 < c3 or c1 < c2 > c3) and abs(c3 - c1) < 0.20 * atr14:
                return False, "Compressed Micro-Whipsaw Zone"

        return True, "Passed CRO Adversarial Risk Inspection"

ADVERSARIAL_CRO = AdversarialCRO()

# --------------------------------------------------------------------------
# ⚖️ ATLAS COMPONENT 3: JANUS Meta-Regime Detector
# --------------------------------------------------------------------------
class JanusRegimeDetector:
    """
    ATLAS JANUS Meta-Regime Layer:
    - Measures multi-asset trend momentum vs chop.
    - Adapts structural R:R clearance thresholds.
    """
    @staticmethod
    def get_adaptive_rr(adx_val, is_trending, is_scalp=False):
        if is_scalp:
            return 1.2
        if is_trending and adx_val >= 28.0:
            return 1.5  # Loosen requirement during powerful trend runs
        elif adx_val <= 20.0:
            return 2.2  # Highly strict in choppy environments
        return 1.8

JANUS_REGIME = JanusRegimeDetector()

def calc_dynamic_atr_margin(symbol, atr, price, base_margin_pct=0.03):
    """
    Dynamic ATR-Normalized Volatility Sizing:
    - Scales margin between 2.0% and 4.0% based on ATR % of price.
    - High-volatility assets (Gold, SOL) scale down to 2.0% to prevent oversized swings.
    - Low-volatility calm assets (ADA, XRP) scale up to 3.5% to maximize pip yield.
    """
    if atr is None or atr <= 0 or price is None or price <= 0:
        return base_margin_pct
    atr_pct = atr / price
    if atr_pct > 0.010: # High volatility (>1.0% per 5m)
        return max(0.020, base_margin_pct * 0.75)
    elif atr_pct < 0.004: # Low volatility (<0.40% per 5m)
        return min(0.040, base_margin_pct * 1.25)
    return base_margin_pct

_MTF_CACHE = {'timestamp': 0, 'data': []}

def _fetch_single_sym_mtf(sym):
    try:
        r5 = requests.get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=5m&limit=25", timeout=2).json()
        c5 = [float(k[4]) for k in r5]
        r15 = requests.get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=15m&limit=25", timeout=2).json()
        c15 = [float(k[4]) for k in r15]
        r1h = requests.get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=1h&limit=25", timeout=2).json()
        c1h = [float(k[4]) for k in r1h]
        r4h = requests.get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=4h&limit=25", timeout=2).json()
        c4h = [float(k[4]) for k in r4h]

        t5 = "BULLISH" if c5[-1] > np.mean(c5[-15:]) else "BEARISH"
        t15 = "BULLISH" if c15[-1] > np.mean(c15[-15:]) else "BEARISH"
        t1h = "BULLISH" if c1h[-1] > np.mean(c1h[-15:]) else "BEARISH"
        t4h = "BULLISH" if c4h[-1] > np.mean(c4h[-15:]) else "BEARISH"

        bull_count = sum(1 for x in [t5, t15, t1h, t4h] if x == "BULLISH")
        status = "STRONG BUY 🟢" if bull_count == 4 else ("STRONG SELL 🔴" if bull_count == 0 else ("PULLBACK BUY 🟡" if t4h == "BULLISH" and t5 == "BEARISH" else "NEUTRAL ⚪"))

        return {
            'symbol': sym,
            'price': c5[-1],
            'tf_5m': t5,
            'tf_15m': t15,
            'tf_1h': t1h,
            'tf_4h': t4h,
            'confluence': f"{bull_count}/4",
            'status': status
        }
    except Exception:
        return None

def get_mtf_heatmap_data():
    """
    Calculates 5m, 15m, 1h, 4h trends across all 9 assets in parallel with 10s caching.
    """
    global _MTF_CACHE
    now = time.time()
    if now - _MTF_CACHE['timestamp'] < 10 and _MTF_CACHE['data']:
        return _MTF_CACHE['data']

    import concurrent.futures
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=9) as executor:
        futures = {executor.submit(_fetch_single_sym_mtf, sym): sym for sym in OPTIMIZED_SYMBOLS}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res:
                results.append(res)

    results.sort(key=lambda x: OPTIMIZED_SYMBOLS.index(x['symbol']) if x['symbol'] in OPTIMIZED_SYMBOLS else 99)
    _MTF_CACHE = {'timestamp': now, 'data': results}
    return results

# --------------------------------------------------------------------------
# 📐 Objective Fibonacci Retracement & Extension Engine (0.618 - 0.786 - 0.886 OTE Ladder)
# --------------------------------------------------------------------------
def detect_fractal_swings_series(highs, lows, window=4):
    """
    Identifies Fractal Swings with zero look-ahead bias:
    A swing at index i is confirmed only after `window` subsequent bars.
    Returns: (swing_highs, swing_lows) as lists of (confirmed_idx, price)
    """
    n = len(highs)
    swing_highs = []
    swing_lows = []
    for i in range(window, n - window):
        if all(highs[i] >= highs[i - k] for k in range(1, window + 1)) and \
           all(highs[i] >= highs[i + k] for k in range(1, window + 1)):
            swing_highs.append((i + window, highs[i]))
        if all(lows[i] <= lows[i - k] for k in range(1, window + 1)) and \
           all(lows[i] <= lows[i + k] for k in range(1, window + 1)):
            swing_lows.append((i + window, lows[i]))
    return swing_highs, swing_lows

def check_fibonacci_setup(df, symbol="XRPUSDT"):
    """
    📐 Institutional Fibonacci Retracement & Extension Engine (0.618 - 0.786 - 0.886 Harmonic OTE):
    1. Extracts confirmed Fractal Swings (Anchor High/Low).
    2. Measures impulse range R = S_H - S_L.
    3. Calculates 3-tier harmonic entries:
       - Entry 1 (0.618 Fib): Golden Ratio primary reversal
       - Entry 2 (0.786 Fib): Deep Optimal Trade Entry (OTE)
       - Entry 3 (0.886 Fib): Deep Harmonic Bat / Liquidity Grab anchor
    4. Calculates Invalidation SL beyond 1.000 (1.000 + 0.5x ATR buffer)
       and Multi-Tier Take-Profit Extensions (0.000 Retest, +0.618 Extension, +1.618 Runner).
    """
    try:
        if df is None or len(df) < 35:
            return {'state': 'NO_DATA', 'is_setup': False}

        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values
        curr_p = closes[-1]
        curr_h = highs[-1]
        curr_l = lows[-1]

        # Calculate ATR(14)
        tr = pd.concat([
            df['high'] - df['low'],
            (df['high'] - df['close'].shift(1)).abs(),
            (df['low'] - df['close'].shift(1)).abs()
        ], axis=1).max(axis=1)
        atr_val = tr.rolling(14).mean().iloc[-1] if len(tr) >= 14 else (curr_p * 0.005)

        sh_list, sl_list = detect_fractal_swings_series(highs, lows, window=4)
        if not sh_list or not sl_list:
            return {'state': 'NO_SWINGS', 'is_setup': False}

        last_sh = sh_list[-1]  # (confirmed_idx, price)
        last_sl = sl_list[-1]  # (confirmed_idx, price)

        s_high = last_sh[1]
        s_low = last_sl[1]
        impulse = s_high - s_low

        if impulse < (1.5 * atr_val):
            return {'state': 'IMPULSE_TOO_SMALL', 'is_setup': False}

        # Trend context from EMA50 & EMA200
        ema50 = pd.Series(closes).ewm(span=50, adjust=False).mean().iloc[-1]
        ema200 = pd.Series(closes).ewm(span=200, adjust=False).mean().iloc[-1] if len(closes) >= 200 else ema50
        is_uptrend = (curr_p > ema200) and (ema50 >= ema200)
        is_downtrend = (curr_p < ema200) and (ema50 <= ema200)

        # 1. Bullish Retracement into 0.618 - 0.786 - 0.886 Fibonacci Zone
        if is_uptrend and last_sh[0] > last_sl[0]:
            fib_0618 = s_high - (0.618 * impulse)
            fib_0786 = s_high - (0.786 * impulse)
            fib_0886 = s_high - (0.886 * impulse)
            fib_1000 = s_low  # 1.000 Retracement (Full Swing Low)

            # Determine dynamic entry level based on deep retracement reach
            if curr_l <= fib_0886 and curr_p >= (fib_1000 - 0.20 * atr_val):
                entry_p = fib_0886
                tier_label = "0.886 Deep Harmonic Bat"
            elif curr_l <= fib_0786 and curr_p >= (fib_1000 - 0.20 * atr_val):
                entry_p = fib_0786
                tier_label = "0.786 Optimal Trade Entry (OTE)"
            elif curr_l <= fib_0618 and curr_p >= (fib_1000 - 0.20 * atr_val):
                entry_p = fib_0618
                tier_label = "0.618 Golden Pocket"
            else:
                entry_p = None
                tier_label = ""

            # Active entry is within 0.618 down to 0.886 (with tolerance to 1.000)
            if entry_p is not None:
                sl_p = fib_1000 - (0.50 * atr_val)
                tp1_p = s_high
                tp2_p = s_high + (0.618 * impulse)
                tp3_p = s_high + (1.618 * impulse)
                
                risk = entry_p - sl_p
                target_reward_p = (0.50 * tp1_p) + (0.50 * tp2_p)
                reward = target_reward_p - entry_p
                rr = reward / (risk + 1e-9)
                
                return {
                    'state': 'FIBONACCI_ZONE_BUY',
                    'is_setup': True,
                    'side': 'BUY',
                    'entry_price': entry_p,
                    'entry_1': fib_0618,
                    'entry_2': fib_0786,
                    'entry_3': fib_0886,
                    'tier': tier_label,
                    'sl': sl_p,
                    'tp1': tp1_p,
                    'tp2': tp2_p,
                    'tp3': tp3_p,
                    'rr': rr,
                    's_high': s_high,
                    's_low': s_low,
                    'impulse': impulse,
                    'desc': f"📐 Fib {tier_label} Long | Entry: ${entry_p:.4f} (0.618:${fib_0618:.4f} | 0.786:${fib_0786:.4f} | 0.886:${fib_0886:.4f}) | TP1: ${tp1_p:.4f} | SL: ${sl_p:.4f} (R:R {rr:.2f})"
                }

        # 2. Bearish Retracement into 0.618 - 0.786 - 0.886 Fibonacci Zone
        elif is_downtrend and last_sl[0] > last_sh[0]:
            fib_0618 = s_low + (0.618 * impulse)
            fib_0786 = s_low + (0.786 * impulse)
            fib_0886 = s_low + (0.886 * impulse)
            fib_1000 = s_high  # 1.000 Retracement (Full Swing High)

            # Determine dynamic entry level based on deep retracement reach
            if curr_h >= fib_0886 and curr_p <= (fib_1000 + 0.20 * atr_val):
                entry_p = fib_0886
                tier_label = "0.886 Deep Harmonic Bat"
            elif curr_h >= fib_0786 and curr_p <= (fib_1000 + 0.20 * atr_val):
                entry_p = fib_0786
                tier_label = "0.786 Optimal Trade Entry (OTE)"
            elif curr_h >= fib_0618 and curr_p <= (fib_1000 + 0.20 * atr_val):
                entry_p = fib_0618
                tier_label = "0.618 Golden Pocket"
            else:
                entry_p = None
                tier_label = ""

            # Active entry is within 0.618 up to 0.886 (with tolerance to 1.000)
            if entry_p is not None:
                sl_p = fib_1000 + (0.50 * atr_val)
                tp1_p = s_low
                tp2_p = s_low - (0.618 * impulse)
                tp3_p = s_low - (1.618 * impulse)

                risk = sl_p - entry_p
                target_reward_p = (0.50 * tp1_p) + (0.50 * tp2_p)
                reward = entry_p - target_reward_p
                rr = reward / (risk + 1e-9)

                return {
                    'state': 'FIBONACCI_ZONE_SELL',
                    'is_setup': True,
                    'side': 'SELL',
                    'entry_price': entry_p,
                    'entry_1': fib_0618,
                    'entry_2': fib_0786,
                    'entry_3': fib_0886,
                    'tier': tier_label,
                    'sl': sl_p,
                    'tp1': tp1_p,
                    'tp2': tp2_p,
                    'tp3': tp3_p,
                    'rr': rr,
                    's_high': s_high,
                    's_low': s_low,
                    'impulse': impulse,
                    'desc': f"📐 Fib {tier_label} Short | Entry: ${entry_p:.4f} (0.618:${fib_0618:.4f} | 0.786:${fib_0786:.4f} | 0.886:${fib_0886:.4f}) | TP1: ${tp1_p:.4f} | SL: ${sl_p:.4f} (R:R {rr:.2f})"
                }

        return {'state': 'IN_RANGE', 'is_setup': False}
    except Exception as e:
        return {'state': 'ERROR', 'error': str(e), 'is_setup': False}

# --------------------------------------------------------------------------
# 🥔 "Potato" Support & Resistance Engine (Pure Price Action Levels)
# --------------------------------------------------------------------------
def check_potato_sr_levels(symbol="XRPUSDT", df=None):
    """
    🥔 Pure 'Potato' Support & Resistance Engine:
    - Finds the literal rolling swing lows (Floor / Support 🛡️) and swing highs (Ceiling / Resistance 🧱).
    - Detects when price is tapping the Floor (POTATO_BUY_BOUNCE) or Ceiling (POTATO_SELL_BOUNCE).
    """
    try:
        if df is not None and len(df) >= 36:
            highs = [float(x) for x in df['high'].values]
            lows = [float(x) for x in df['low'].values]
            closes = [float(x) for x in df['close'].values]
            curr_p = closes[-1]
        else:
            url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=48"
            r = requests.get(url, timeout=3).json()
            if not r or not isinstance(r, list):
                return {'status': 'error', 'support': 0, 'resistance': 0, 'current_price': 0, 'state': 'UNKNOWN'}
                
            highs = [float(k[2]) for k in r]
            lows = [float(k[3]) for k in r]
            closes = [float(k[4]) for k in r]
            curr_p = closes[-1]
        
        # Recent 9-hour ceiling & floor
        resistance = max(highs[-36:-3])
        support = min(lows[-36:-3])
        
        dist_to_sup_pct = ((curr_p - support) / support) * 100.0
        dist_to_res_pct = ((resistance - curr_p) / curr_p) * 100.0
        
        recent_low = min(lows[-3:])
        recent_high = max(highs[-3:])
        
        state = "IN_RANGE 🥔"
        # 1. ICT Turtle Soup Liquidity Sweep (Wicked below Floor & closed back INSIDE!)
        if recent_low <= support and curr_p > support:
            state = "SWEEP_SUPPORT_CONFIRMED 🛡️🟢"
        elif recent_high >= resistance and curr_p < resistance:
            state = "SWEEP_RESISTANCE_CONFIRMED 🧱🔴"
        elif dist_to_sup_pct <= 0.40 and curr_p >= (support * 0.998):
            state = "TAPPING_SUPPORT_FLOOR 🥔🟢"
        elif dist_to_res_pct <= 0.40 and curr_p <= (resistance * 1.002):
            state = "TAPPING_RESISTANCE_CEILING 🥔🔴"
            
        return {
            'status': 'success',
            'symbol': symbol,
            'current_price': curr_p,
            'support': support,
            'resistance': resistance,
            'dist_to_sup_pct': dist_to_sup_pct,
            'dist_to_res_pct': dist_to_res_pct,
            'state': state
        }
    except Exception as e:
        return {'status': 'error', 'error': str(e), 'support': 0, 'resistance': 0, 'current_price': 0, 'state': 'ERROR'}

# --------------------------------------------------------------------------
# ⚡ Multi-Timeframe (5M, 15M, 1H, 4H) Dual RSI+CCI Divergence Scanner
# --------------------------------------------------------------------------
def get_mtf_divergence_matrix(symbol="XRPUSDT"):
    """
    ⚡ Multi-Timeframe (MTF) RSI(14) + CCI(20) Divergence Matrix:
    - Scans 5m (Trigger), 15m (Structure), 1h (Swing), 4h (Macro)
    - Detects 'The Bigger Picture' Institutional Reversals
    """
    intervals = ['5m', '15m', '1h', '4h']
    matrix = {}
    macro_bull = False
    macro_bear = False
    
    def _fetch_div(tf):
        try:
            url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={tf}&limit=45"
            r = requests.get(url, timeout=2.5).json()
            if not r or len(r) < 30:
                return tf, {'state': 'NO_DATA', 'bull': False, 'bear': False, 'rsi': 50, 'cci': 0}
            
            closes = [float(k[4]) for k in r]
            highs = [float(k[2]) for k in r]
            lows = [float(k[3]) for k in r]
            df = pd.DataFrame({'close': closes, 'high': highs, 'low': lows})
            
            div_state, bull, bear = WeatherEnsembleBot.calc_rsi_cci_divergence(df)
            rsi_val = float(WeatherEnsembleBot.calc_rsi(pd.Series(closes), 14).iloc[-1])
            cci_val = float(WeatherEnsembleBot.calc_cci(df, 20).iloc[-1])
            
            return tf, {
                'state': div_state,
                'bull': bull,
                'bear': bear,
                'rsi': round(rsi_val, 1),
                'cci': round(cci_val, 1)
            }
        except Exception:
            return tf, {'state': 'NO_DATA', 'bull': False, 'bear': False, 'rsi': 50, 'cci': 0}
            
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_fetch_div, tf) for tf in intervals]
        for f in concurrent.futures.as_completed(futures):
            tf, res = f.result()
            matrix[tf] = res
            if tf in ['1h', '4h']:
                if res.get('bull'): macro_bull = True
                if res.get('bear'): macro_bear = True
                
    # Evaluate Macro Alignment
    confluence_grade = "STANDARD"
    if macro_bull and matrix.get('5m', {}).get('bull'):
        confluence_grade = "MACRO_SUPER_CONFLUENCE ⚡💎🟢 (4H/1H + 5M Bullish Alignment)"
    elif macro_bear and matrix.get('5m', {}).get('bear'):
        confluence_grade = "MACRO_SUPER_CONFLUENCE ⚡💎🔴 (4H/1H + 5M Bearish Alignment)"
    elif macro_bull:
        confluence_grade = "MACRO_BULL_DIVERGENCE 🏛️🟢 (Higher TF Institutional Accumulation)"
    elif macro_bear:
        confluence_grade = "MACRO_BEAR_DIVERGENCE 🏛️🔴 (Higher TF Institutional Distribution)"
        
    return {
        'status': 'success',
        'symbol': symbol,
        'confluence_grade': confluence_grade,
        'macro_bull': macro_bull,
        'macro_bear': macro_bear,
        'timeframes': matrix
    }

def get_divergence_status(symbol="XRPUSDT"):
    return get_mtf_divergence_matrix(symbol)

# --------------------------------------------------------------------------
# 👑 BTC Master Beta Trend & Portfolio Exposure Risk Engines
# --------------------------------------------------------------------------
def check_btc_macro_health(target_side):
    """
    👑 BTC Master Beta Trend Filter (15m Execution Timeframe):
    - Uses GLOBAL_CACHE BTC 15m klines (0 redundant API calls).
    - Protects against cross-asset correlation crashes.
    - NEVER opens an Altcoin LONG if BTC 15m is dumping below its EMA20 with > 0.50% flush.
    - NEVER opens an Altcoin SHORT if BTC is in a vertical parabolic pump > 0.60%.
    """
    try:
        GLOBAL_CACHE.update()
        raw = GLOBAL_CACHE.btc_15m_raw
        if not raw or not isinstance(raw, list):
            return True, "BTC Normal"
        closes = [float(k[4]) for k in raw]
        curr_btc = closes[-1]
        ema20 = pd.Series(closes).ewm(span=20, adjust=False).mean().iloc[-1]
        ret_15m = (curr_btc - closes[-2]) / closes[-2]
        
        if target_side.upper() in ['BUY', 'LONG']:
            if curr_btc < ema20 and ret_15m < -0.0050:
                return False, f"BTC Flushing ({ret_15m*100:+.2f}% in 15m) - Altcoin Long Blocked 🛑"
        elif target_side.upper() in ['SELL', 'SHORT']:
            if curr_btc > ema20 and ret_15m > +0.0060:
                return False, f"BTC Pumping ({ret_15m*100:+.2f}% in 15m) - Altcoin Short Blocked 🛑"
        return True, "BTC Aligned ✅"
    except Exception:
        return True, "BTC Normal"

def check_portfolio_risk_capacity(balance, new_margin_usdt, max_portfolio_margin_pct=0.06, positions=None):
    """
    🔒 Maximum Concurrent Portfolio Exposure Cap:
    - Strictly limits total margin committed across ALL active positions to max 6.0% of wallet.
    - On a $14.20 wallet, total combined margin cannot exceed $0.85.
    """
    try:
        if positions is None:
            positions = get_binance_futures_positions()
        total_current_margin = 0.0
        for p in positions:
            notional = abs(float(p.get('notional', 0.0)))
            lev = float(p.get('leverage', 50))
            total_current_margin += (notional / lev) if lev > 0 else 0.0

        max_allowed_margin = balance * max_portfolio_margin_pct
        if (total_current_margin + new_margin_usdt) > max_allowed_margin:
            return False, f"Portfolio Exposure Cap Reached (${total_current_margin + new_margin_usdt:.2f} > ${max_allowed_margin:.2f})"
        return True, "Capacity OK"
    except Exception:
        return True, "Capacity OK"

# --------------------------------------------------------------------------
# Binance Futures Authenticated API Helper (`fapi.binance.com`)
# --------------------------------------------------------------------------
# Cached server time offset and exchange info to avoid redundant HTTP calls
_SERVER_TIME_OFFSET = 0  # ms offset between local clock and Binance server
_SERVER_TIME_SYNCED = False

_EXCHANGE_INFO_CACHE = {}  # symbol -> {'pricePrecision': int, 'quantityPrecision': int}
_EXCHANGE_INFO_TS = 0

def sync_server_time():
    global _SERVER_TIME_OFFSET, _SERVER_TIME_SYNCED
    try:
        t_res = requests.get('https://fapi.binance.com/fapi/v1/time', timeout=3)
        if t_res.status_code == 200:
            server_ts = t_res.json()['serverTime']
            local_ts = int(time.time() * 1000)
            _SERVER_TIME_OFFSET = server_ts - local_ts
            _SERVER_TIME_SYNCED = True
    except Exception:
        # BUG-11 Fix: Keep previous offset on failure instead of zeroing
        # (zeroing causes -1021 Timestamp errors if local clock drifts)
        pass

def get_symbol_info(symbol):
    global _EXCHANGE_INFO_CACHE, _EXCHANGE_INFO_TS
    now = time.time()
    if now - _EXCHANGE_INFO_TS > 3600 or not _EXCHANGE_INFO_CACHE:
        try:
            ex_info = requests.get("https://fapi.binance.com/fapi/v1/exchangeInfo", timeout=8).json()
            for s in ex_info.get('symbols', []):
                sym_notional = 5.0
                for f in s.get('filters', []):
                    if f.get('filterType') in ['MIN_NOTIONAL', 'NOTIONAL']:
                        sym_notional = float(f.get('notional', f.get('minNotional', 5.0)))
                        break
                _EXCHANGE_INFO_CACHE[s['symbol']] = {
                    'pricePrecision': s.get('pricePrecision', 4),
                    'quantityPrecision': s.get('quantityPrecision', 3),
                    'minNotional': sym_notional
                }
            _EXCHANGE_INFO_TS = now
        except Exception:
            pass
    info = _EXCHANGE_INFO_CACHE.get(symbol, {'pricePrecision': 4, 'quantityPrecision': 3, 'minNotional': 5.0})
    return info['pricePrecision'], info['quantityPrecision'], info['minNotional']

def get_symbol_precision(symbol):
    p_prec, q_prec, _ = get_symbol_info(symbol)
    return p_prec, q_prec

def get_symbol_min_notional(symbol):
    _, _, min_notional = get_symbol_info(symbol)
    return min_notional

def binance_futures_signed_request(method, endpoint, params=None):
    global _SERVER_TIME_SYNCED
    api_key = os.getenv('BINANCE_API_KEY', BINANCE_API_KEY)
    api_secret = os.getenv('BINANCE_API_SECRET', BINANCE_API_SECRET)
    if not api_key or not api_secret:
        return None

    if params is None:
        params = {}

    # Use cached server time offset instead of fetching /fapi/v1/time every call
    if not _SERVER_TIME_SYNCED:
        sync_server_time()
    timestamp = int(time.time() * 1000) + _SERVER_TIME_OFFSET

    params['recvWindow'] = 10000
    params['timestamp'] = timestamp

    query_string = urllib.parse.urlencode(params)
    signature = hmac.new(
        api_secret.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    url = f"https://fapi.binance.com{endpoint}?{query_string}&signature={signature}"
    headers = {'X-MBX-APIKEY': api_key}

    try:
        if method.upper() == 'GET':
            r = requests.get(url, headers=headers, timeout=5)
        elif method.upper() == 'POST':
            r = requests.post(url, headers=headers, timeout=5)
        elif method.upper() == 'DELETE':
            r = requests.delete(url, headers=headers, timeout=5)
        else:
            return None

        try:
            result = r.json()
        except Exception:
            return {'error': r.status_code, 'text': r.text}

        # Re-sync if timestamp error detected
        if isinstance(result, dict) and result.get('code') == -1021:
            sync_server_time()

        # Check for IP whitelist / permission rejection (-2015)
        if isinstance(result, dict) and result.get('code') == -2015:
            trigger_ip_whitelist_alert(result.get('msg', 'Invalid API-key, IP, or permissions for action'))

        return result
    except Exception as e:
        return {'error': str(e)}


def get_binance_futures_usdt_balance(mode='wallet'):
    """
    Returns Binance Futures USDT balance:
    - 'wallet': Total wallet balance (default, ignores unrealized PnL and margin allocations)
    - 'equity': Total wallet balance + cross unrealized PnL (true net liquidation value)
    - 'available': Available margin balance for placing new orders
    """
    bals = binance_futures_signed_request('GET', '/fapi/v2/balance')
    if not bals or not isinstance(bals, list):
        return 0.0
    for b in bals:
        if b.get('asset') == 'USDT':
            wallet_bal = float(b.get('balance', b.get('crossWalletBalance', 0.0)))
            if mode == 'equity':
                return wallet_bal + float(b.get('crossUnPnl', 0.0))
            elif mode == 'available':
                return float(b.get('availableBalance', b.get('maxWithdrawAmount', wallet_bal)))
            return wallet_bal
    return 0.0

def get_binance_futures_positions():
    """Returns list of active open positions on Binance Futures"""
    positions = binance_futures_signed_request('GET', '/fapi/v2/positionRisk')
    if not positions or not isinstance(positions, list):
        return []
    active = []
    for p in positions:
        amt = float(p.get('positionAmt', 0.0))
        if amt != 0.0:
            active.append({
                'symbol': p.get('symbol'),
                'positionAmt': amt,
                'entryPrice': float(p.get('entryPrice', 0.0)),
                'markPrice': float(p.get('markPrice', 0.0)),
                'unrealizedProfit': float(p.get('unRealizedProfit', 0.0)),
                'liquidationPrice': float(p.get('liquidationPrice', 0.0)),
                'leverage': p.get('leverage'),
                'marginType': p.get('marginType'),
                'side': 'LONG' if amt > 0 else 'SHORT'
            })
    return active

def get_binance_futures_open_positions_count():
    return len(get_binance_futures_positions())

def cancel_binance_symbol_all_orders(symbol):
    """
    Cancels all open regular orders AND open conditional algo orders (Stop Loss / Take Profit) for a symbol.
    """
    try:
        # 1. Cancel regular open orders
        binance_futures_signed_request('DELETE', '/fapi/v1/allOpenOrders', {'symbol': symbol})
        
        # 2. Cancel all open algo conditional orders (SL/TP)
        open_algo = binance_futures_signed_request('GET', '/fapi/v1/openAlgoOrders')
        if isinstance(open_algo, list):
            for a in open_algo:
                if a.get('symbol') == symbol:
                    algo_id = a.get('algoId')
                    if algo_id:
                        binance_futures_signed_request('DELETE', '/fapi/v1/algoOrder', {'algoId': algo_id})
    except Exception as e:
        print(f"[CANCEL ALL ORDERS ERROR] {symbol}: {e}", flush=True)

def cancel_binance_order_by_id(symbol, order_id=None, algo_id=None):
    """
    Cancels exactly ONE specific order (regular or algo) by ID.
    Used instead of cancel_binance_symbol_all_orders() when replacing a stop,
    so we never touch unrelated open orders for the symbol and never have to
    guess which orders are 'stale'.
    """
    try:
        if algo_id:
            return binance_futures_signed_request('DELETE', '/fapi/v1/algoOrder', {'algoId': algo_id})
        elif order_id:
            return binance_futures_signed_request('DELETE', '/fapi/v1/order', {'symbol': symbol, 'orderId': order_id})
    except Exception as e:
        print(f"[CANCEL ORDER ERROR] {symbol} order {order_id or algo_id}: {e}", flush=True)
    return None

def to_ccxt_symbol(symbol):
    """Safely converts Binance futures symbol (e.g. BTCUSDT) to ccxt format (e.g. BTC/USDT:USDT)."""
    if symbol.endswith('USDT'):
        return f"{symbol[:-4]}/USDT:USDT"
    return symbol

def place_protective_stop(symbol, close_side, position_side, qty, stop_price, price_prec, max_retries=3):
    """
    Places a STOP_MARKET reduce-only order and VERIFIES Binance actually accepted it
    before the caller is allowed to cancel the old one.
    Retries with backoff on failure — a leveraged position must never be silently
    left with no stop. Returns (success, order_id_or_None, algo_id_or_None, stop_price_str).
    """
    stop_str = f"{stop_price:.{price_prec}f}"
    for attempt in range(max_retries):
        try:
            exchange = get_ccxt_exchange()
            ccxt_sym = to_ccxt_symbol(symbol)
            order = exchange.create_order(
                symbol=ccxt_sym,
                type='STOP_MARKET',
                side=close_side.lower(),
                amount=qty,
                params={'stopPrice': float(stop_str), 'positionSide': position_side}
            )
            oid = order.get('id')
            if oid:
                return True, oid, None, stop_str
        except Exception as e:
            print(f"[STOP PLACEMENT RETRY {attempt+1}/{max_retries}] {symbol} ccxt error: {e}", flush=True)

        try:
            sl_params = {
                'symbol': symbol,
                'side': close_side,
                'type': 'STOP_MARKET',
                'stopPrice': stop_str,
                'quantity': f"{qty}",
                'positionSide': position_side
            }
            res = binance_futures_signed_request('POST', '/fapi/v1/order', sl_params)
            if isinstance(res, dict) and 'orderId' in res:
                return True, res['orderId'], None, stop_str
            print(f"[STOP PLACEMENT RETRY {attempt+1}/{max_retries}] {symbol} REST response: {res}", flush=True)
        except Exception as e:
            print(f"[STOP PLACEMENT RETRY {attempt+1}/{max_retries}] {symbol} REST error: {e}", flush=True)

        if attempt < max_retries - 1:
            time.sleep(0.6)

    return False, None, None, stop_str

def close_binance_futures_position(symbol):
    """Emergency closes a specific open position and cancels all remaining orders"""
    positions = get_binance_futures_positions()
    target = None
    for p in positions:
        if p['symbol'] == symbol:
            target = p
            break
    if not target:
        cancel_binance_symbol_all_orders(symbol)
        return {'status': 'not_found', 'message': f'No open position found for {symbol}'}

    amt = abs(target['positionAmt'])
    close_side = 'SELL' if target['positionAmt'] > 0 else 'BUY'
    # Bug #2 Fix: Use positionSide for Hedge Mode compatibility
    position_side = 'LONG' if target['positionAmt'] > 0 else 'SHORT'
    
    params = {
        'symbol': symbol,
        'side': close_side,
        'type': 'MARKET',
        'quantity': str(amt),
        'positionSide': position_side
    }
    res = binance_futures_signed_request('POST', '/fapi/v1/order', params)
    cancel_binance_symbol_all_orders(symbol)
    return res

def close_all_binance_futures_positions():
    """Emergency closes ALL open positions and cancels open orders"""
    positions = get_binance_futures_positions()
    results = []
    for p in positions:
        res = close_binance_futures_position(p['symbol'])
        results.append({'symbol': p['symbol'], 'result': res})
    return results

def set_binance_futures_leverage(symbol="XRPUSDT", leverage=75):
    params = {'symbol': symbol, 'leverage': leverage}
    return binance_futures_signed_request('POST', '/fapi/v1/leverage', params)

# --------------------------------------------------------------------------
# Orphaned Order Cleaner & Garbage Collector
# --------------------------------------------------------------------------
def cleanup_orphaned_orders():
    """
    Cancels leftover open conditional orders (Stop Loss / Take Profit) for closed positions.
    Prevents accidental ghost positions when TP triggers.
    """
    try:
        active_positions = get_binance_futures_positions()
        active_symbols = set(p['symbol'] for p in active_positions if float(p.get('positionAmt', 0.0)) != 0.0)

        cleaned_count = 0
        cleaned_symbols = set()

        # 1. Regular Open Orders (TP Limit Orders)
        open_orders = binance_futures_signed_request('GET', '/fapi/v1/openOrders')
        if isinstance(open_orders, list):
            for o in open_orders:
                sym = o.get('symbol')
                if sym and sym not in active_symbols:
                    oid = o.get('orderId')
                    if sym not in cleaned_symbols:
                        print(f"[ORPHANED ORDER CLEANER] Cancelling leftover Limit orders for #{sym}...", flush=True)
                        binance_futures_signed_request('DELETE', '/fapi/v1/allOpenOrders', {'symbol': sym})
                        cleaned_symbols.add(sym)
                    cleaned_count += 1

        # 2. Algo Open Orders (Conditional Stop Losses & Take Profits)
        open_algo = binance_futures_signed_request('GET', '/fapi/v1/openAlgoOrders')
        if isinstance(open_algo, list):
            for a in open_algo:
                sym = a.get('symbol')
                if sym and sym not in active_symbols:
                    algo_id = a.get('algoId')
                    order_type = a.get('orderType', 'CONDITIONAL')
                    print(f"[ORPHANED ORDER CLEANER] Cancelling leftover Algo {order_type} #{algo_id} for #{sym}...", flush=True)
                    res = binance_futures_signed_request('DELETE', '/fapi/v1/algoOrder', {'algoId': algo_id})
                    cleaned_count += 1
                    cleaned_symbols.add(sym)

        if cleaned_count > 0:
            syms_str = ", ".join(f"#{s}" for s in cleaned_symbols)
            send_telegram_msg(f"🧹 <b>ORPHANED ORDER CLEANER</b>\n\nCleaned up <b>{cleaned_count}</b> leftover order(s) for closed position(s): {syms_str}")
        return cleaned_count
    except Exception as e:
        print(f"[ORPHANED ORDER CLEANER ERROR] {e}", flush=True)
        return 0

# --------------------------------------------------------------------------
# L2 Order Book Depth Imbalance & Funding Rate Squeeze Filters
# --------------------------------------------------------------------------
def check_order_book_imbalance(symbol, target_side, depth_limit=20, min_ratio=1.05):
    """
    Confirms buyer depth (bids) outweighs seller depth (asks) for LONGs, and vice versa for SHORTs.
    """
    try:
        url = f"https://fapi.binance.com/fapi/v1/depth?symbol={symbol}&limit={depth_limit}"
        r = requests.get(url, timeout=3)
        if r.status_code != 200:
            return True, 1.0, 0, 0
        data = r.json()
        bids = data.get('bids', [])
        asks = data.get('asks', [])

        total_bid_vol = sum(float(b[1]) for b in bids)
        total_ask_vol = sum(float(a[1]) for a in asks)

        if total_ask_vol == 0 or total_bid_vol == 0:
            return True, 1.0, total_bid_vol, total_ask_vol

        if target_side.upper() in ['BUY', 'LONG']:
            ratio = total_bid_vol / total_ask_vol
            confirmed = ratio >= min_ratio
        else:
            ratio = total_ask_vol / total_bid_vol
            confirmed = ratio >= min_ratio

        return confirmed, round(ratio, 2), total_bid_vol, total_ask_vol
    except Exception:
        return True, 1.0, 0, 0

def check_funding_rate(symbol, target_side, max_adverse_rate=0.0004):
    """
    Checks Binance Futures 8-hour funding rate using GLOBAL_CACHE (0 redundant API calls).
    Filters out entries if funding rate is heavily adverse (> +0.04% for longs or < -0.04% for shorts).
    """
    try:
        GLOBAL_CACHE.update()
        funding_rate = GLOBAL_CACHE.all_funding.get(symbol, 0.0)
        if target_side.upper() in ['BUY', 'LONG'] and funding_rate > max_adverse_rate:
            return False, funding_rate
        elif target_side.upper() in ['SELL', 'SHORT'] and funding_rate < -max_adverse_rate:
            return False, funding_rate
        return True, funding_rate
    except Exception:
        return True, 0.0

def check_4h_smc_bias(symbol, target_side):
    """
    Institutional Multi-Timeframe Dual 4H + 1H Cascade Trend Alignment Gate:
    - 4-Hour Macro Trend: EMA20 vs EMA50
    - 1-Hour Intermediate Trend: EMA20 vs EMA50 (Pullback Completion Gate)
    Rule:
      • LONG requires 4H Bullish/Neutral AND 1H Bullish/Neutral (Blocks buying into active 1H pullbacks)
      • SHORT requires 4H Bearish/Neutral AND 1H Bearish/Neutral (Blocks shorting into active 1H rallies)
    """
    try:
        # 1. Check 4H Macro Trend
        url_4h = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=4h&limit=50"
        r_4h = requests.get(url_4h, timeout=3.5).json()
        if not isinstance(r_4h, list) or len(r_4h) < 20:
            return True, 'NEUTRAL ⚪'

        c_4h = [float(k[4]) for k in r_4h]
        ema20_4h = pd.Series(c_4h).ewm(span=20, adjust=False).mean().iloc[-1]
        ema50_4h = pd.Series(c_4h).ewm(span=50, adjust=False).mean().iloc[-1]
        curr_4h = c_4h[-1]

        is_4h_bull = (curr_4h > ema50_4h) and (ema20_4h >= ema50_4h)
        is_4h_bear = (curr_4h < ema50_4h) and (ema20_4h <= ema50_4h)

        # 2. Check 1H Intermediate Trend (Pullback Completion Guard)
        url_1h = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1h&limit=50"
        r_1h = requests.get(url_1h, timeout=3.5).json()
        is_1h_bull = False
        is_1h_bear = False
        if isinstance(r_1h, list) and len(r_1h) >= 20:
            c_1h = [float(k[4]) for k in r_1h]
            ema20_1h = pd.Series(c_1h).ewm(span=20, adjust=False).mean().iloc[-1]
            ema50_1h = pd.Series(c_1h).ewm(span=50, adjust=False).mean().iloc[-1]
            curr_1h = c_1h[-1]
            is_1h_bull = (curr_1h > ema50_1h) and (ema20_1h >= ema50_1h)
            is_1h_bear = (curr_1h < ema50_1h) and (ema20_1h <= ema50_1h)

        # 3. Dual Cascade Validation
        if target_side.upper() in ['BUY', 'LONG']:
            if is_4h_bear:
                return False, 'BEARISH 4H (Macro Downtrend 🛑)'
            if is_1h_bear:
                return False, 'BEARISH 1H (Intraday Pullback in Progress 🛑 - Waiting for 1H Bottom)'
        elif target_side.upper() in ['SELL', 'SHORT']:
            if is_4h_bull:
                return False, 'BULLISH 4H (Macro Uptrend 🛑)'
            if is_1h_bull:
                return False, 'BULLISH 1H (Intraday Rally in Progress 🛑 - Waiting for 1H Top)'

        bias_str = 'DUAL 4H+1H BULLISH 🟢' if (is_4h_bull and is_1h_bull) else ('DUAL 4H+1H BEARISH 🔴' if (is_4h_bear and is_1h_bear) else 'ALIGNED ✅')
        return True, bias_str
    except Exception:
        return True, 'NEUTRAL ⚪'

# --------------------------------------------------------------------------
# Upgrade 1: Faster Trend Reversal Detection (Dual 1H/15m Market Structure Shift)
# --------------------------------------------------------------------------
def detect_mss_from_api(symbol, interval='15m', window=3):
    """
    Detects Market Structure Shift (MSS) on specified timeframe with Volume Surge:
    - Bearish MSS: Candle breaks below previous key confirmed swing low with heavy volume.
    - Bullish MSS: Candle breaks above previous key confirmed swing high with heavy volume.
    """
    try:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit=45"
        r = requests.get(url, timeout=3.5)
        if r.status_code != 200:
            return 'NEUTRAL'
        raw = r.json()
        if not isinstance(raw, list) or len(raw) < window * 2 + 5:
            return 'NEUTRAL'

        highs = np.array([float(k[2]) for k in raw])
        lows = np.array([float(k[3]) for k in raw])
        closes = np.array([float(k[4]) for k in raw])
        volumes = np.array([float(k[5]) for k in raw])

        sh_list, sl_list = detect_fractal_swings_series(highs, lows, window=window)
        if not sh_list or not sl_list:
            return 'NEUTRAL'

        last_sh_price = sh_list[-1][1]
        last_sl_price = sl_list[-1][1]
        curr_close = closes[-1]
        curr_low = lows[-1]
        curr_high = highs[-1]
        vol_sma20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else volumes[-1]
        is_vol_surge = volumes[-1] >= (vol_sma20 * 1.10)

        # Bearish MSS: Broke below last swing low
        if (curr_low < last_sl_price and curr_close < last_sl_price) and is_vol_surge:
            return 'BEARISH'

        # Bullish MSS: Broke above last swing high
        if (curr_high > last_sh_price and curr_close > last_sh_price) and is_vol_surge:
            return 'BULLISH'

        return 'NEUTRAL'
    except Exception:
        return 'NEUTRAL'

def detect_1h_mss_from_api(symbol, window=3):
    return detect_mss_from_api(symbol, interval='1h', window=window)

def detect_micro_bias(symbol, df=None):
    """
    Evaluates Lower-Timeframe Micro Trend & Structure (15m / 5m):
    Returns: (bias, reason) where bias is 'BEARISH', 'BULLISH', or 'NEUTRAL'
    
    A Lower Timeframe is confirmed BEARISH if:
    1. 15m or 5m MSS breaks swing low with volume surge, OR
    2. 15m Price < EMA20 and EMA9 <= EMA20 on execution klines, OR
    3. 15m Price Action shows rejection wick at resistance or breakdown.
    """
    try:
        # 1. Check 15m & 5m Market Structure Shift (MSS)
        mss_15m = detect_mss_from_api(symbol, interval='15m', window=3)
        if mss_15m == 'BEARISH':
            return 'BEARISH', '15m Bearish MSS Breakdown'
        elif mss_15m == 'BULLISH':
            return 'BULLISH', '15m Bullish MSS Bounce'

        mss_5m = detect_mss_from_api(symbol, interval='5m', window=3)
        if mss_5m == 'BEARISH':
            return 'BEARISH', '5m Bearish MSS Breakdown'
        elif mss_5m == 'BULLISH':
            return 'BULLISH', '5m Bullish MSS Bounce'

        # 2. Check 15m klines DataFrame (either passed or cached)
        if df is not None and len(df) >= 20:
            c = df['close'].values
            o = df['open'].values
            h = df['high'].values
            l = df['low'].values
            v = df['volume'].values
            
            ema9 = pd.Series(c).ewm(span=9, adjust=False).mean().iloc[-1]
            ema20 = pd.Series(c).ewm(span=20, adjust=False).mean().iloc[-1]
            curr_c = c[-1]
            
            # Micro Bearish: Price below EMA20 and EMA9 <= EMA20
            if curr_c < ema20 and ema9 <= ema20:
                return 'BEARISH', '15m Micro Downtrend (Price < EMA20 & EMA9 <= EMA20)'
            # Micro Bullish: Price above EMA20 and EMA9 >= EMA20
            elif curr_c > ema20 and ema9 >= ema20:
                return 'BULLISH', '15m Micro Uptrend (Price > EMA20 & EMA9 >= EMA20)'
                
        return 'NEUTRAL', 'Micro Neutral'
    except Exception as e:
        return 'NEUTRAL', f'Micro Exception: {e}'

def check_macro_and_mss_bias(symbol, target_side, df=None, micro_context=None):
    """
    Combines Lower-Timeframe Micro Agility (15m/5m MSS & Trend) + 1H MSS + 4H SMC Macro Alignment:
    
    RULES:
    1. POTATO S&R Levels & Divergence (Tapped Floor / Tapped Ceiling / ICT Sweeps / RSI+CCI Div):
       -> ALWAYS allowed as high-probability Counter-Trend Quick Scalps (is_quick_scalp = True).
    2. If Lower Timeframe (15m/5m) is Micro BEARISH (or 1H MSS is Bearish), allow SHORTING even if 4H Macro is Uptrend.
       -> Marked as is_quick_scalp = True (Counter-Macro Quick Scalp ⚡🔴).
    3. If Lower Timeframe (15m/5m) is Micro BULLISH (or 1H MSS is Bullish), allow BUYING even if 4H Macro is Downtrend.
       -> Marked as is_quick_scalp = True (Counter-Macro Quick Scalp ⚡🟢).
    4. If trading in the SAME direction as 4H Macro:
       -> Marked as is_quick_scalp = False (Macro Trend Runner 🌊).
    
    Returns: (is_allowed: bool, bias_desc: str, is_quick_scalp: bool)
    """
    side = target_side.upper()
    is_macro_aligned, macro_desc = check_4h_smc_bias(symbol, target_side)
    
    # 0. Potato S&R Floor / Ceiling & MTF Divergence Counter-Trend Bypass
    if micro_context in ['POTATO_SUPPORT', 'POTATO_RESISTANCE', 'BULL_DIV', 'BEAR_DIV']:
        is_scalp = not is_macro_aligned
        scalp_tag = "⚡ QUICK SCALP" if is_scalp else "🌊 TREND RUNNER"
        side_tag = "Floor Bounce 🟢" if side in ['BUY', 'LONG'] else "Ceiling Rejection 🔴"
        context_name = "Potato S&R" if "POTATO" in micro_context else "Divergence"
        return True, f"{context_name} {side_tag} ({scalp_tag} | Macro: {macro_desc})", is_scalp

    # 1. Check 1H MSS First for Intermediate Structure Shift
    mss_1h = detect_1h_mss_from_api(symbol)
    if mss_1h == 'BEARISH' and side in ['SELL', 'SHORT']:
        is_scalp = not is_macro_aligned
        scalp_tag = "⚡ QUICK SCALP" if is_scalp else "🌊 TREND RUNNER"
        return True, f"BEARISH ({scalp_tag}: 1H MSS Reversal Confirmed 🔴)", is_scalp
    elif mss_1h == 'BULLISH' and side in ['BUY', 'LONG']:
        is_scalp = not is_macro_aligned
        scalp_tag = "⚡ QUICK SCALP" if is_scalp else "🌊 TREND RUNNER"
        return True, f"BULLISH ({scalp_tag}: 1H MSS Reversal Confirmed 🟢)", is_scalp
    elif mss_1h == 'BEARISH' and side in ['BUY', 'LONG']:
        return False, 'BEARISH (1H Market Structure Shift Reversal Broken Down 🛑)', False
    elif mss_1h == 'BULLISH' and side in ['SELL', 'SHORT']:
        # If 1H is actively breaking out upward with volume, avoid counter-trend shorting into the breakout
        return False, 'BULLISH (1H Market Structure Shift Reversal Broken Up 🟢)', False

    # 2. Check Lower Timeframe Micro Trend (15m / 5m MSS & Momentum)
    micro_bias, micro_reason = detect_micro_bias(symbol, df=df)
    
    if side in ['SELL', 'SHORT']:
        # If Micro is BEARISH on lower timeframe, ALLOW SHORTING
        if micro_bias == 'BEARISH':
            is_scalp = not is_macro_aligned
            scalp_tag = "⚡ QUICK SCALP" if is_scalp else "🌊 TREND RUNNER"
            return True, f"MICRO BEARISH ({scalp_tag}: {micro_reason} 🔴)", is_scalp
        
        # If micro context indicates a specific setup and micro is not bullish
        if micro_context in ['FIBONACCI', 'CONSENSUS'] and micro_bias != 'BULLISH':
            is_scalp = not is_macro_aligned
            scalp_tag = "⚡ QUICK SCALP" if is_scalp else "🌊 TREND RUNNER"
            return True, f"MICRO BEARISH ({scalp_tag}: LTF {micro_context} Short Setup Confirmed 🎯🔴)", is_scalp
            
    elif side in ['BUY', 'LONG']:
        # If Micro is BULLISH on lower timeframe, ALLOW BUYING
        if micro_bias == 'BULLISH':
            is_scalp = not is_macro_aligned
            scalp_tag = "⚡ QUICK SCALP" if is_scalp else "🌊 TREND RUNNER"
            return True, f"MICRO BULLISH ({scalp_tag}: {micro_reason} 🟢)", is_scalp
            
        # If micro context indicates a specific setup and micro is not bearish
        if micro_context in ['FIBONACCI', 'CONSENSUS'] and micro_bias != 'BEARISH':
            is_scalp = not is_macro_aligned
            scalp_tag = "⚡ QUICK SCALP" if is_scalp else "🌊 TREND RUNNER"
            return True, f"MICRO BULLISH ({scalp_tag}: LTF {micro_context} Long Setup Confirmed 🎯🟢)", is_scalp

    # 3. Fallback to 4H SMC Macro Bias if no micro signal exists
    return is_macro_aligned, macro_desc, False

# --------------------------------------------------------------------------
# Upgrade 2: Choppy Market / ADX Regime Filter (Anti-Whipsaw Protection)
# --------------------------------------------------------------------------
def calc_adx_series(highs, lows, closes, period=14):
    """
    Calculates Average Directional Index (ADX) from price series.
    ADX < 20 = Flat sideways chop zone / low trend strength.
    ADX >= 20 = Active trending market.
    """
    n = len(closes)
    if n < period * 2 + 1:
        return 25.0

    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))

    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move

    def wilder_smooth(arr, p):
        res = np.zeros(len(arr))
        res[p] = np.sum(arr[1:p + 1])
        for i in range(p + 1, len(arr)):
            res[i] = res[i - 1] - (res[i - 1] / p) + arr[i]
        return res

    atr_s = wilder_smooth(tr, period)
    plus_s = wilder_smooth(plus_dm, period)
    minus_s = wilder_smooth(minus_dm, period)

    plus_di = np.zeros(n)
    minus_di = np.zeros(n)
    dx = np.zeros(n)
    for i in range(period, n):
        if atr_s[i] > 0:
            plus_di[i] = 100.0 * plus_s[i] / atr_s[i]
            minus_di[i] = 100.0 * minus_s[i] / atr_s[i]
        di_sum = plus_di[i] + minus_di[i]
        if di_sum > 0:
            dx[i] = 100.0 * abs(plus_di[i] - minus_di[i]) / di_sum

    adx = np.zeros(n)
    start_idx = period * 2
    if start_idx < n:
        adx[start_idx] = np.mean(dx[period:start_idx + 1])
        for i in range(start_idx + 1, n):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period

    return float(adx[-1]) if n > 0 else 25.0

def check_btc_adx_market_regime(adx_chop_threshold=22):
    """
    Checks Bitcoin 15m ADX(14) from GLOBAL_CACHE to determine market-wide volatility regime.
    Profile C: ADX >= 22 (Filters borderline low-volatility chop)
    Returns: (is_trending, adx_val, desc)
    """
    try:
        GLOBAL_CACHE.update()
        raw = GLOBAL_CACHE.btc_15m_raw
        if not raw or not isinstance(raw, list):
            return True, 25.0, "ADX Unavailable (Allowed)"
        h = np.array([float(k[2]) for k in raw])
        l = np.array([float(k[3]) for k in raw])
        c = np.array([float(k[4]) for k in raw])
        adx_val = calc_adx_series(h, l, c, period=14)

        if adx_val < adx_chop_threshold:
            return False, round(adx_val, 1), f"Chop Zone (ADX {adx_val:.1f} < {adx_chop_threshold} - Low Volatility ⚠️)"
        return True, round(adx_val, 1), f"Trending Market (ADX {adx_val:.1f} >= {adx_chop_threshold} 🌊)"
    except Exception:
        return True, 25.0, "ADX Check Exception"

# --------------------------------------------------------------------------
# Upgrade 3: Directional Exposure Cap (Correlation Protection)
# --------------------------------------------------------------------------
LAST_ENTRY_TIMESTAMPS = {}

def check_directional_portfolio_cap(symbol, target_side, max_same_dir=3, *args, **kwargs):
    """
    Caps total open positions in the same direction at max 3 across the entire portfolio.
    Positions where Stop-Loss has already shifted to Breakeven (risk-free) do not count against the cap.
    Enforces a 15-minute inter-trade cooldown between same-direction new entries.
    """
    global ACTIVE_POSITION_TARGETS, LAST_ENTRY_TIMESTAMPS
    try:
        # 1. Staggered Entry Cooldown (15-min spacing between same-direction entries)
        dir_key = 'BUY' if target_side.upper() in ['BUY', 'LONG'] else 'SELL'
        last_dir_time = LAST_ENTRY_TIMESTAMPS.get(dir_key, 0)
        time_since = time.time() - last_dir_time
        if time_since < 900 and last_dir_time > 0: # 15 minutes
            mins_left = (900 - time_since) / 60
            return False, 0, f"Staggered Entry Cooldown Active ({mins_left:.1f}m left before adding next {dir_key} position ⏳)"

        positions = get_binance_futures_positions()
        if not positions:
            return True, 0, "No Active Positions"

        long_risk_count = 0
        short_risk_count = 0

        for p in positions:
            sym = p['symbol']
            amt = float(p.get('positionAmt', 0.0))
            if abs(amt) == 0.0:
                continue

            side = 'LONG' if amt > 0 else 'SHORT'
            target = ACTIVE_POSITION_TARGETS.get(sym, {})
            # If position has already scaled out at TP1 and is at Breakeven, it is risk-free
            if target.get('tp1_hit'):
                continue

            if side == 'LONG':
                long_risk_count += 1
            else:
                short_risk_count += 1

        is_long = target_side.upper() in ['BUY', 'LONG']
        active_same_dir = long_risk_count if is_long else short_risk_count

        if active_same_dir >= max_same_dir:
            side_str = "LONG" if is_long else "SHORT"
            return False, active_same_dir, f"Max {max_same_dir} {side_str} positions active ({active_same_dir}/{max_same_dir}) 🛡️"

        return True, active_same_dir, "Directional Cap OK"
    except Exception:
        return True, 0, "Cap Check Exception"

def check_order_flow_absorption(symbol, target_side, trades_limit=500):
    """
    Real-Time Order Flow & Passive Absorption Filter:
    - Calculates Aggressive Market Buy vs Sell Delta
    - Detects Institutional Limit Order Absorption at Highs/Lows
    """
    try:
        url = f"https://fapi.binance.com/fapi/v1/aggTrades?symbol={symbol}&limit={trades_limit}"
        r = requests.get(url, timeout=3)
        if r.status_code != 200:
            return True, 'NEUTRAL', 0.0, 'NONE'
        raw = r.json()
        if not raw or len(raw) < 30:
            return True, 'NEUTRAL', 0.0, 'NONE'

        agg_buys = sum(float(t['q']) for t in raw if not t['m'])
        agg_sells = sum(float(t['q']) for t in raw if t['m'])
        total_vol = agg_buys + agg_sells
        net_delta = agg_buys - agg_sells
        delta_pct = (net_delta / total_vol) * 100 if total_vol > 0 else 0.0

        prices = [float(t['p']) for t in raw]
        max_p = max(prices)
        min_p = min(prices)
        curr_p = prices[-1]

        # Absorption Checks
        top_buys = sum(float(t['q']) for t in raw if t['p'] >= max_p * 0.9995 and not t['m'])
        bot_sells = sum(float(t['q']) for t in raw if t['p'] <= min_p * 1.0005 and t['m'])
        avg_cluster = total_vol / 10.0

        absorption = "NONE"
        if bot_sells > avg_cluster * 1.8 and curr_p > min_p:
            absorption = "BULLISH_ABSORPTION"
        elif top_buys > avg_cluster * 1.8 and curr_p < max_p:
            absorption = "BEARISH_ABSORPTION"

        if target_side.upper() in ['BUY', 'LONG']:
            confirmed = (net_delta > 0 or absorption == "BULLISH_ABSORPTION")
            desc = "Bullish Absorption 🛡️" if absorption == "BULLISH_ABSORPTION" else f"Aggressive Buy Delta ({delta_pct:+.1f}%)"
        else:
            confirmed = (net_delta < 0 or absorption == "BEARISH_ABSORPTION")
            desc = "Bearish Absorption 🛑" if absorption == "BEARISH_ABSORPTION" else f"Aggressive Sell Delta ({delta_pct:+.1f}%)"

        return confirmed, desc, round(delta_pct, 1), absorption
    except Exception:
        return True, 'NEUTRAL', 0.0, 'NONE'

# --------------------------------------------------------------------------
# Upgrade 4: 3-Stage Scale-Out & Dynamic Trailing Stop Daemon (State & Disk Persistence)
# --------------------------------------------------------------------------
ACTIVE_POSITION_TARGETS = {}
_POSITION_TARGETS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'state', 'active_position_targets.json')

def _save_position_targets():
    """BUG-14 Fix: Persist ACTIVE_POSITION_TARGETS to disk so watchdog restarts recover trailing stop state."""
    try:
        os.makedirs(os.path.dirname(_POSITION_TARGETS_FILE), exist_ok=True)
        with open(_POSITION_TARGETS_FILE, 'w') as f:
            json.dump(ACTIVE_POSITION_TARGETS, f, indent=2)
    except Exception:
        pass

def _load_position_targets():
    """BUG-14 Fix: Reload ACTIVE_POSITION_TARGETS from disk on startup, pruning stale entries."""
    global ACTIVE_POSITION_TARGETS
    try:
        if os.path.exists(_POSITION_TARGETS_FILE):
            with open(_POSITION_TARGETS_FILE, 'r') as f:
                loaded = json.load(f)
            if isinstance(loaded, dict) and loaded:
                # Validate against live positions — drop entries for closed positions
                live_positions = get_binance_futures_positions()
                live_syms = set(p['symbol'] for p in live_positions if abs(float(p.get('positionAmt', 0.0))) > 0.0)
                valid = {sym: data for sym, data in loaded.items() if sym in live_syms}
                pruned = len(loaded) - len(valid)
                ACTIVE_POSITION_TARGETS.update(valid)
                if valid:
                    print(f"[POSITION TARGETS RESTORED] Loaded {len(valid)} active target(s) from disk.", flush=True)
                if pruned > 0:
                    print(f"[POSITION TARGETS PRUNED] Removed {pruned} stale target(s) for closed positions.", flush=True)
                _save_position_targets()  # Write back pruned version
    except Exception as e:
        print(f"[POSITION TARGETS LOAD WARN] {e}", flush=True)

# --------------------------------------------------------------------------
# Partial Take-Profit Scaling & Automated Bracket Orders
# --------------------------------------------------------------------------
def place_binance_futures_tp_sl(symbol, side, last_price, atr, leverage=75, total_qty=None, enable_trailing=True, callback_rate=0.8, custom_tp=None, custom_sl=None, is_quick_scalp=False, channel='FIBONACCI'):
    if (atr is None or atr <= 0) and (custom_tp is None or custom_sl is None):
        return None
    if last_price is None or last_price <= 0:
        return None

    # Separated Execution Architectures:
    # ⚡ Quick Scalp: 1.0x ATR SL | 1.2x ATR TP1 (60% Harvest) | Early BE @ +0.35x ATR | 0.7x ATR Trailing Stop
    # 🌊 Swing Trade: 1.5x ATR SL | 1.8x ATR TP1 (33%) | 2.8x ATR TP2 (33%) | 1.4x ATR Trailing Stop
    atr_buffer = float(atr) if (atr and atr > 0) else float(last_price * 0.010)
    
    if custom_tp and custom_tp > 0:
        tp1_price = float(custom_tp)
    else:
        tp1_dist = (1.2 * atr_buffer) if is_quick_scalp else (1.8 * atr_buffer)
        tp1_price = (last_price + tp1_dist) if side.upper() in ['BUY', 'LONG'] else (last_price - tp1_dist)

    min_sl_dist = last_price * 0.003
    if custom_sl and custom_sl > 0:
        raw_sl = float(custom_sl)
        if side.upper() in ['BUY', 'LONG']:
            sl_price = min(raw_sl, last_price - min_sl_dist)
        else:
            sl_price = max(raw_sl, last_price + min_sl_dist)
    else:
        sl_dist = (1.0 * atr_buffer) if is_quick_scalp else (1.5 * atr_buffer)
        sl_price = (last_price - sl_dist) if side.upper() in ['BUY', 'LONG'] else (last_price + sl_dist)

    act_price = tp1_price
    close_side = 'SELL' if side.upper() in ['BUY', 'LONG'] else 'BUY'
    position_side = 'LONG' if side.upper() in ['BUY', 'LONG'] else 'SHORT'

    price_prec, qty_prec, min_notional = get_symbol_info(symbol)
    min_tp_notional = min_notional * 1.015

    tp1_str = f"{tp1_price:.{price_prec}f}"
    sl_str = f"{sl_price:.{price_prec}f}"
    act_str = f"{act_price:.{price_prec}f}"

    if is_quick_scalp:
        # Quick Scalp: Harvest 60% at TP1, leave 40% for fast dynamic trail
        scalp_tp1_target = round(total_qty * 0.60, qty_prec) if (total_qty and total_qty > 0) else None
        if qty_prec == 0 and scalp_tp1_target:
            scalp_tp1_target = int(scalp_tp1_target)
        tp1_qty = scalp_tp1_target if (scalp_tp1_target and (scalp_tp1_target * last_price >= min_tp_notional)) else total_qty
        tp1_qty_str = str(int(tp1_qty)) if qty_prec == 0 else f"{tp1_qty:.{qty_prec}f}"
        place_tp2_order = False
        tp2_str = "0"
        tp2_qty_str = "0"
    else:
        # Swing Trade: 3-Stage Scale-Out Engine (33% TP1 / 33% TP2 / 34% TP3 Runner)
        one_third_qty = round(total_qty * 0.33, qty_prec) if (total_qty and total_qty > 0) else None
        if qty_prec == 0 and one_third_qty:
            one_third_qty = int(one_third_qty)

        tp1_qty = one_third_qty if (one_third_qty and (one_third_qty * last_price >= min_tp_notional)) else total_qty
        tp1_qty_str = str(int(tp1_qty)) if qty_prec == 0 else f"{tp1_qty:.{qty_prec}f}"

        # TP2 target price (2.8x ATR Structural Target)
        tp2_dist = 2.8 * atr_buffer
        tp2_price = (last_price + tp2_dist) if side.upper() in ['BUY', 'LONG'] else (last_price - tp2_dist)
        tp2_str = f"{tp2_price:.{price_prec}f}"
        place_tp2_order = bool(one_third_qty and (one_third_qty * last_price >= min_tp_notional) and tp1_qty < total_qty)
        tp2_qty_str = tp1_qty_str  # same 33% sizing as TP1

    # 1. Take Profit Order (scale-out @ TP1 on Binance Conditional Orders)
    tp_res = None
    tp2_res = None
    sl_res = None
    try:
        exchange = get_ccxt_exchange()
        ccxt_sym = to_ccxt_symbol(symbol)
        
        # Place TP1 for scale-out size (reduceOnly=True prevents minNotional rejections on closes)
        tp_params = {'stopPrice': float(tp1_str), 'positionSide': position_side, 'reduceOnly': True}
        if float(tp1_qty_str) >= float(total_qty) * 0.99:
            tp_params['closePosition'] = True
        tp_order = exchange.create_order(
            symbol=ccxt_sym,
            type='TAKE_PROFIT_MARKET',
            side=close_side.lower(),
            amount=float(tp1_qty_str),
            params=tp_params
        )
        tp_res = {'status': 'success', 'id': tp_order.get('id'), 'price': tp1_str, 'qty': tp1_qty_str}

        # Place TP2 for another 33% size (Resting order on Binance for Swing Trades)
        if place_tp2_order:
            try:
                tp2_order = exchange.create_order(
                    symbol=ccxt_sym,
                    type='TAKE_PROFIT_MARKET',
                    side=close_side.lower(),
                    amount=float(tp2_qty_str),
                    params={'stopPrice': float(tp2_str), 'positionSide': position_side, 'reduceOnly': True}
                )
                tp2_res = {'status': 'success', 'id': tp2_order.get('id'), 'price': tp2_str, 'qty': tp2_qty_str}
            except Exception as e2:
                print(f"[TP2 RESTING ORDER WARN] #{symbol} TP2 conditional order not placed ({e2}), falling back to internal trailing runner.", flush=True)

        # Place Initial Protective SL for full position
        # BUG-4 Fix: Use closePosition instead of explicit qty so the stop
        # always closes whatever remains after TP1/TP2 scale-outs, preventing
        # an oversized stop from opening an unintended reverse position.
        sl_order = exchange.create_order(
            symbol=ccxt_sym,
            type='STOP_MARKET',
            side=close_side.lower(),
            amount=float(total_qty),
            params={'stopPrice': float(sl_str), 'positionSide': position_side, 'closePosition': True}
        )
        sl_res = {'status': 'success', 'id': sl_order.get('id'), 'price': sl_str}
    except Exception as e:
        # Fallback to direct signed API
        print(f"[ORDER ATTEMPT WARN] CCXT bracket order failed ({e}), attempting native REST fallback...", flush=True)
        tp_params = {
            'symbol': symbol,
            'side': close_side,
            'type': 'TAKE_PROFIT_MARKET',
            'stopPrice': tp1_str,
            'quantity': tp1_qty_str,
            'positionSide': position_side
        }
        tp_res = binance_futures_signed_request('POST', '/fapi/v1/order', tp_params)

        if place_tp2_order:
            tp2_params = {
                'symbol': symbol,
                'side': close_side,
                'type': 'TAKE_PROFIT_MARKET',
                'stopPrice': tp2_str,
                'quantity': tp2_qty_str,
                'positionSide': position_side
            }
            tp2_res = binance_futures_signed_request('POST', '/fapi/v1/order', tp2_params)

        sl_params = {
            'symbol': symbol,
            'side': close_side,
            'type': 'STOP_MARKET',
            'stopPrice': sl_str,
            'closePosition': 'true',
            'positionSide': position_side
        }
        sl_res = binance_futures_signed_request('POST', '/fapi/v1/order', sl_params)

    # Capture order ids so later stages can cancel/track THIS specific order
    sl_order_id = None
    if isinstance(sl_res, dict):
        sl_order_id = sl_res.get('id') or sl_res.get('orderId')

    tp2_order_id = None
    if isinstance(tp2_res, dict):
        tp2_order_id = tp2_res.get('id') or tp2_res.get('orderId')

    # Record targets for Scale-Out / Dynamic Trailing Runner Daemon
    global ACTIVE_POSITION_TARGETS

    ACTIVE_POSITION_TARGETS[symbol] = {
        'side': side.upper(),
        'entry_price': last_price,
        'tp1': float(tp1_str),
        'tp2': float(tp2_str) if not is_quick_scalp else 0.0,
        'tp2_order_id': tp2_order_id,
        'sl': float(sl_str),
        'current_sl': float(sl_str),
        'sl_order_id': sl_order_id,
        'initial_qty': float(total_qty),
        'tp1_qty': float(tp1_qty),
        'atr': float(atr) if (atr and atr > 0) else float(last_price * 0.008),
        'is_quick_scalp': bool(is_quick_scalp),
        'channel': channel,
        'tp1_hit': False,
        'tp2_hit': False,
        'highest_mark': last_price,
        'lowest_mark': last_price,
        'trailing_active': False
    }

    scale_desc = f"{'60%' if is_quick_scalp else '33%'} Scale-Out ({tp1_qty_str} Qty)" if (tp1_qty < total_qty) else f"100% Size ({total_qty} Qty)"
    tp2_desc = f" | TP2 (exchange-side): ${tp2_str}" if tp2_order_id else ""
    mode_label = "⚡ QUICK SCALP (Fast BE + Tight Trail)" if is_quick_scalp else "🌊 SWING TRADE (3-Stage Runner)"
    print(f"[ORDERS PLACED] {symbol} {side} [{mode_label} | Ch: {channel}] | TP1 Target: ${tp1_str} [{scale_desc}]{tp2_desc} | SL: ${sl_str}", flush=True)
    _save_position_targets()  # BUG-14: Persist new entry to disk
    return {'tp_price': tp1_str, 'sl_price': sl_str, 'act_price': act_str, 'tp_res': tp_res, 'tp2_res': tp2_res, 'sl_res': sl_res}

# --------------------------------------------------------------------------
# Dynamic Trailing Stop Daemon Core Logic
# --------------------------------------------------------------------------

def _replace_protective_stop(sym, close_side, side, qty, new_stop_price, price_prec, old_order_id, context_label):
    """
    Shared 'place-then-verify-then-cancel' sequence used by every stage below.
    The new stop is placed and CONFIRMED on the exchange first; only then is the
    old stop cancelled by its specific order id. This means there is never a
    window where the position has zero protective orders resting on Binance —
    worst case, both the old and new stop briefly coexist (harmless, since both
    are reduceOnly), never neither.
    Returns the new order id on success, or None on failure (old stop is left
    untouched and an alert is sent).
    """
    success, new_order_id, _, stop_str = place_protective_stop(
        symbol=sym, close_side=close_side, position_side=side,
        qty=qty, stop_price=new_stop_price, price_prec=price_prec
    )
    if not success:
        print(f"🚨 [STOP UPDATE FAILED] #{sym} could not place new {context_label} stop after {3} attempts — OLD STOP LEFT ACTIVE as fallback.", flush=True)
        send_telegram_msg(f"🚨 <b>STOP UPDATE FAILED</b>\n\n#{sym}: could not place new {context_label} stop (${stop_str}) after retries.\nThe previous stop order has been left in place as a fallback — please check <code>/positions</code>.")
        return None, stop_str

    # New stop confirmed live — now safe to remove the old one specifically.
    if old_order_id:
        cancel_binance_order_by_id(sym, order_id=old_order_id)
    return new_order_id, stop_str


def manage_active_positions_breakeven():
    """
    Upgrade 4: 3-Stage Scale-Out & Real-Time Trailing Stop Daemon:
    - Stage 1 (TP1 Hit @ 33%): Moves SL to Breakeven (+0.05% fee cover buffer) on remaining 67%.
    - Stage 2 (TP2 Hit @ 33%): Closes 33% at structural target and tightens trailing stop.
    - Stage 3 (TP3 Runner @ 34%): Dynamic trailing stop walks behind price (0.7x ATR for Quick Scalps, 1.4x ATR for Trend Runners).

    Every stop replacement below places and confirms the new stop BEFORE cancelling
    the old one (see _replace_protective_stop), so a leveraged position is never
    left with zero protective orders on the exchange due to a failed API call.
    """
    global ACTIVE_POSITION_TARGETS
    try:
        positions = get_binance_futures_positions()
        live_syms = set(p['symbol'] for p in positions if abs(float(p.get('positionAmt', 0.0))) > 0.0)

        # Clean up closed symbols
        for sym in list(ACTIVE_POSITION_TARGETS.keys()):
            if sym not in live_syms:
                del ACTIVE_POSITION_TARGETS[sym]
                _save_position_targets()  # BUG-14: Persist cleanup to disk

        for p in positions:
            sym = p['symbol']
            amt = float(p.get('positionAmt', 0.0))
            if abs(amt) == 0.0:
                continue

            target = ACTIVE_POSITION_TARGETS.get(sym)
            if not target:
                continue

            side = 'LONG' if amt > 0 else 'SHORT'
            mark_p = float(p.get('markPrice', 0.0))
            entry_p = float(p.get('entryPrice', target.get('entry_price', 0.0)))
            tp1_p = target.get('tp1', 0.0)
            tp2_p = target.get('tp2', 0.0)
            atr_val = target.get('atr', entry_p * 0.008)

            if entry_p <= 0 or tp1_p <= 0:
                continue

            price_prec, qty_prec = get_symbol_precision(sym)
            close_side = 'SELL' if side == 'LONG' else 'BUY'

            # --- STAGE 0: Fast Early Breakeven for Counter-Trend Quick Scalps (+0.35x ATR profit) ---
            if target.get('is_quick_scalp') and not target.get('tp1_hit') and not target.get('trailing_active'):
                in_quick_profit = (side == 'LONG' and mark_p >= entry_p + (0.35 * atr_val)) or (side == 'SHORT' and mark_p <= entry_p - (0.35 * atr_val))
                if in_quick_profit:
                    be_price = entry_p * 1.0005 if side == 'LONG' else entry_p * 0.9995
                    new_order_id, be_str = _replace_protective_stop(
                        sym, close_side, side, abs(amt), be_price, price_prec,
                        old_order_id=target.get('sl_order_id'), context_label="quick_scalp_breakeven"
                    )
                    if new_order_id is not None:
                        target['sl_order_id'] = new_order_id
                        target['current_sl'] = be_price
                        target['trailing_active'] = True
                        target['highest_mark'] = mark_p
                        target['lowest_mark'] = mark_p
                        print(f"⚡ [QUICK SCALP FAST BREAKEVEN LOCKED] #{sym} moved SL to Breakeven (${be_str}) at +0.35x ATR! 🔒", flush=True)

            # --- STAGE 1: Detect TP1 Hit & Shift Stop Loss to Breakeven ---
            if not target.get('tp1_hit'):
                hit_tp1 = abs(amt) <= (target['initial_qty'] * 0.75)
                if hit_tp1:
                    be_price = entry_p * 1.0005 if side == 'LONG' else entry_p * 0.9995

                    new_order_id, be_str = _replace_protective_stop(
                        sym, close_side, side, abs(amt), be_price, price_prec,
                        old_order_id=target.get('sl_order_id'), context_label="breakeven"
                    )
                    if new_order_id is None:
                        # Old SL is still resting on the exchange (untouched) — retry next poll.
                        continue

                    target['sl_order_id'] = new_order_id
                    target['tp1_hit'] = True
                    target['trailing_active'] = True
                    target['current_sl'] = be_price
                    target['highest_mark'] = mark_p
                    target['lowest_mark'] = mark_p
                    print(f"🎯 [TP1 HIT / SCALED OUT] #{sym} reached TP1! 100% Risk Free! 🚀", flush=True)
                    send_telegram_msg(f"🎯 <b>STAGE 1: TP1 HIT / PROFIT LOCKED</b>\n\n• Asset: <b>#{sym}</b> ({side})\n• Mark Price: <b>${mark_p:,.4f}</b>\n• Stop: <b>${be_str}</b> (Breakeven Locked 🔒)")
                    continue

            # --- STAGE 2: Detect TP2 Hit (Additional 33% Scale-Out) ---
            if target.get('tp1_hit') and not target.get('tp2_hit') and tp2_p > 0:
                hit_tp2 = False

                if target.get('tp2_order_id'):
                    # TP2 is a REAL TAKE_PROFIT_MARKET order resting on Binance (placed at
                    # entry in place_binance_futures_tp_sl) — it fires on its own even if
                    # this bot is offline. Detect the fill by the resulting quantity drop,
                    # exactly like Stage 1's TP1 detection, rather than re-closing manually.
                    hit_tp2 = abs(amt) <= (target['initial_qty'] * 0.45)
                    if hit_tp2:
                        print(f"🎯🎯 [TP2 EXCHANGE FILL DETECTED] #{sym} conditional TP2 order filled on Binance.", flush=True)
                else:
                    # Fallback path: TP2 couldn't be placed as a real order at entry
                    # (position too small to split further) — poll-trigger a market close.
                    hit_tp2 = (side == 'LONG' and mark_p >= tp2_p) or (side == 'SHORT' and mark_p <= tp2_p)
                    if hit_tp2:
                        scale2_qty = round(target['initial_qty'] * 0.33, qty_prec)
                        if qty_prec == 0:
                            scale2_qty = int(scale2_qty)
                        scale2_qty = min(scale2_qty, abs(amt) * 0.90)

                        if scale2_qty > 0 and (scale2_qty * mark_p >= 5.05):
                            scale2_str = str(int(scale2_qty)) if qty_prec == 0 else f"{scale2_qty:.{qty_prec}f}"
                            try:
                                exchange = get_ccxt_exchange()
                                ccxt_sym = to_ccxt_symbol(sym)
                                exchange.create_order(
                                    symbol=ccxt_sym,
                                    type='MARKET',
                                    side=close_side.lower(),
                                    amount=float(scale2_str),
                                    params={'positionSide': side}
                                )
                            except Exception:
                                tp2_params = {
                                    'symbol': sym,
                                    'side': close_side,
                                    'type': 'MARKET',
                                    'quantity': scale2_str,
                                    'positionSide': side
                                }
                                binance_futures_signed_request('POST', '/fapi/v1/order', tp2_params)

                if hit_tp2:
                    target['tp2_hit'] = True
                    # Tighten trailing stop distance on final 34% runner
                    tight_sl = (target['highest_mark'] - (0.6 * atr_val if target.get('is_quick_scalp') else 0.8 * atr_val)) if side == 'LONG' else (target['lowest_mark'] + (0.6 * atr_val if target.get('is_quick_scalp') else 0.8 * atr_val))
                    if (side == 'LONG' and tight_sl > target['current_sl']) or (side == 'SHORT' and tight_sl < target['current_sl']):
                        # BUG-5 Fix: Actually place the tightened stop on the exchange,
                        # not just in memory. Without this, the old breakeven stop stays
                        # on Binance while the bot only *thinks* it tightened.
                        new_order_id, tight_str = _replace_protective_stop(
                            sym, close_side, side, abs(amt), tight_sl, price_prec,
                            old_order_id=target.get('sl_order_id'), context_label="tp2_tighten"
                        )
                        if new_order_id is not None:
                            target['sl_order_id'] = new_order_id
                            target['current_sl'] = tight_sl
                        else:
                            target['current_sl'] = tight_sl  # Track intent even if exchange update failed

                    print(f"🎯🎯 [TP2 33% SCALED OUT] #{sym} reached TP2! Major profit locked! Trailing stop tightened! 🚀", flush=True)
                    send_telegram_msg(f"🎯🎯 <b>STAGE 2: TP2 SCALED OUT (66% TOTAL PROFIT LOCKED)</b>\n\n• Asset: <b>#{sym}</b> ({side})\n• Mark Price: <b>${mark_p:,.4f}</b>\n\n<i>🏃 Final 34% TP3 Runner trailing stop tightened to ride trend!</i>")
                    continue

            # --- STAGE 3: Dynamic TP3 Trailing Stop on the Final Runner ---
            if target.get('trailing_active'):
                if target.get('is_quick_scalp'):
                    trail_distance = 0.5 * atr_val if target.get('tp2_hit') else 0.7 * atr_val
                else:
                    trail_distance = 0.8 * atr_val if target.get('tp2_hit') else 1.4 * atr_val

                if side == 'LONG':
                    if mark_p > target['highest_mark']:
                        target['highest_mark'] = mark_p

                    calc_trail = target['highest_mark'] - trail_distance
                    if calc_trail > (target['current_sl'] + (0.25 * atr_val)) and calc_trail > entry_p:
                        new_order_id, trail_str = _replace_protective_stop(
                            sym, close_side, side, abs(amt), calc_trail, price_prec,
                            old_order_id=target.get('sl_order_id'), context_label="trailing"
                        )
                        if new_order_id is not None:
                            target['sl_order_id'] = new_order_id
                            target['current_sl'] = calc_trail
                            print(f"📈 [TRAILING STOP TRAILED UP] #{sym} (LONG) -> New Stop Loss: ${trail_str} (Peak: ${target['highest_mark']:,.4f})", flush=True)

                elif side == 'SHORT':
                    if mark_p < target['lowest_mark']:
                        target['lowest_mark'] = mark_p

                    calc_trail = target['lowest_mark'] + trail_distance
                    if calc_trail < (target['current_sl'] - (0.25 * atr_val)) and calc_trail < entry_p:
                        new_order_id, trail_str = _replace_protective_stop(
                            sym, close_side, side, abs(amt), calc_trail, price_prec,
                            old_order_id=target.get('sl_order_id'), context_label="trailing"
                        )
                        if new_order_id is not None:
                            target['sl_order_id'] = new_order_id
                            target['current_sl'] = calc_trail
                            print(f"📉 [TRAILING STOP TRAILED DOWN] #{sym} (SHORT) -> New Stop Loss: ${trail_str} (Trough: ${target['lowest_mark']:,.4f})", flush=True)

        _save_position_targets()  # BUG-14: Persist all stage updates to disk
    except Exception as e:
        print(f"🚨 [POSITION MANAGER EXCEPTION] {e}", flush=True)
        try:
            send_telegram_msg(f"🚨 <b>POSITION MANAGER ERROR</b>\n\nThe stop/trailing daemon hit an exception this cycle: <code>{e}</code>\nExisting stops were left untouched. Check <code>/positions</code>.")
        except Exception:
            pass

def place_binance_futures_market_order(symbol="XRPUSDT", side="BUY", trade_usdt=None, margin_pct=0.03, sizing_mode="margin", last_price=None, leverage=75, atr=None, custom_tp=None, custom_sl=None, is_quick_scalp=False, channel='FIBONACCI'):
    set_binance_futures_leverage(symbol=symbol, leverage=leverage)
    
    if last_price is None or last_price <= 0:
        try:
            ticker_res = requests.get(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}", timeout=5)
            if ticker_res.status_code == 200:
                last_price = float(ticker_res.json()['price'])
            else:
                return None
        except Exception:
            return None

    wallet_balance = get_binance_futures_usdt_balance('wallet')
    equity_balance = get_binance_futures_usdt_balance('equity')
    avail_balance = get_binance_futures_usdt_balance('available')
    
    # Circuit breaker check uses true equity balance (avoids false trips from margin allocated to open trades)
    if not CIRCUIT_BREAKER.check_and_update(equity_balance):
        print(f"[CIRCUIT BREAKER TRIPPED] Trade cancelled: {CIRCUIT_BREAKER.trip_reason}")
        send_telegram_msg(f"🛑 <b>CIRCUIT BREAKER ACTIVE</b>\n\nTrade cancelled for #{symbol}.\nReason: {CIRCUIT_BREAKER.trip_reason}\nAutomated trading is paused.")
        return {'error': 'Circuit breaker active', 'reason': CIRCUIT_BREAKER.trip_reason}

    if avail_balance <= 0:
        print(f"[ORDER CANCELLED] No available USDT balance.")
        return {'error': 'Insufficient USDT balance', 'avail': avail_balance}

    # Update Milestone Lock
    MILESTONE_MANAGER.update(avail_balance)

    if trade_usdt is not None and trade_usdt > 0:
        notional_usdt = trade_usdt
        margin_usdt = notional_usdt / float(leverage)
    else:
        dynamic_pct = calc_dynamic_atr_margin(symbol, atr, last_price, base_margin_pct=margin_pct) if atr else margin_pct
        if sizing_mode == "notional":
            notional_usdt = avail_balance * dynamic_pct
            margin_usdt = notional_usdt / float(leverage)
        else:
            margin_usdt = avail_balance * dynamic_pct
            notional_usdt = margin_usdt * float(leverage)

    _, qty_prec, min_notional = get_symbol_info(symbol)

    if notional_usdt < min_notional:
        needed_margin = min_notional / float(leverage)
        if avail_balance >= needed_margin:
            notional_usdt = min_notional
            margin_usdt = needed_margin
        else:
            print(f"[ORDER CANCELLED] Required margin (${needed_margin:.2f}) for min notional (${min_notional:.2f}) exceeds available balance (${avail_balance:.2f}).", flush=True)
            return {'error': 'Below min notional limit', 'notional': notional_usdt, 'min_notional': min_notional}

    if avail_balance < margin_usdt:
        print(f"[ORDER CANCELLED] Required margin (${margin_usdt:.2f}) exceeds available balance (${avail_balance:.2f}).", flush=True)
        return {'error': 'Insufficient USDT balance', 'avail': avail_balance, 'required_margin': margin_usdt}

    raw_qty = notional_usdt / last_price
    qty = round(raw_qty, qty_prec)
    if qty_prec == 0:
        qty = int(qty)

    # Ensure rounded quantity strictly satisfies Binance symbol-specific min notional with safety buffer
    required_notional = min_notional * 1.015
    while (qty * last_price) < required_notional:
        step = 1 if qty_prec == 0 else round(10 ** (-qty_prec), qty_prec)
        qty = round(qty + step, qty_prec)
        if qty_prec == 0:
            qty = int(qty)

    # Bug #3 Fix: Hardcode Hedge Mode positionSide (account is always in dual-side mode)
    position_side = 'LONG' if side.upper() == 'BUY' else 'SHORT'

    params = {
        'symbol': symbol,
        'side': side.upper(),
        'type': 'MARKET',
        'quantity': str(qty),
        'positionSide': position_side
    }
    res = binance_futures_signed_request('POST', '/fapi/v1/order', params)

    if isinstance(res, dict) and 'code' in res and 'orderId' not in res:
        print(f"[BINANCE REJECTED ORDER] {symbol} {side} Error: {res.get('msg')} (code: {res.get('code')})", flush=True)
    elif isinstance(res, dict) and 'orderId' in res:
        mode_str = "⚡ QUICK SCALP" if is_quick_scalp else "🌊 TREND RUNNER"
        print(f"[BINANCE ORDER FILLED] #{symbol} {side} [{mode_str}] Order ID: #{res.get('orderId')} | Status: {res.get('status', 'FILLED')}", flush=True)
        # Update Staggered Entry Cooldown Timestamp
        global LAST_ENTRY_TIMESTAMPS
        dir_k = 'BUY' if side.upper() in ['BUY', 'LONG'] else 'SELL'
        LAST_ENTRY_TIMESTAMPS[dir_k] = time.time()

    if isinstance(res, dict) and 'orderId' in res and (atr is not None or custom_tp is not None or custom_sl is not None):
        tp_sl_info = place_binance_futures_tp_sl(
            symbol=symbol,
            side=side,
            last_price=last_price,
            atr=atr,
            leverage=leverage,
            total_qty=qty,
            custom_tp=custom_tp,
            custom_sl=custom_sl,
            is_quick_scalp=is_quick_scalp,
            channel=channel
        )
        res['tp_sl'] = tp_sl_info

    return res

# --------------------------------------------------------------------------
# Telegram Notifications & Interactive Inline Keyboards (1-Tap Buttons)
# --------------------------------------------------------------------------
def get_telegram_inline_keyboard(live_trading=None):
    """Builds interactive clickable 1-tap buttons for Telegram with 1-Tap Live/Paper Toggle & CB Toggle"""
    live_btn_text = "🟢 LIVE TRADING (Active)" if live_trading is True else "🟢 Switch to LIVE"
    paper_btn_text = "🟡 PAPER MODE (Active)" if live_trading is False else "🟡 Switch to PAPER"
    
    cb_on = getattr(CIRCUIT_BREAKER, 'enabled', True) if 'CIRCUIT_BREAKER' in globals() else True
    cb_btn_text = "🛡️ CB: ENABLED 🟢" if cb_on else "🛡️ CB: DISABLED ⚪"

    return {
        "inline_keyboard": [
            [
                {"text": live_btn_text, "callback_data": "/live"},
                {"text": paper_btn_text, "callback_data": "/paper"}
            ],
            [
                {"text": "📊 Live Status", "callback_data": "/status"},
                {"text": "📈 Open Positions", "callback_data": "/positions"}
            ],
            [
                {"text": cb_btn_text, "callback_data": "/togglecb"},
                {"text": "⚡ 31 Models Matrix", "callback_data": "/models"}
            ],
            [
                {"text": "⏸️ Pause Engine", "callback_data": "/pause"},
                {"text": "▶️ Resume / Reset CB", "callback_data": "/resume"}
            ],
            [
                {"text": "🧬 ATLAS Weights", "callback_data": "/atlas"},
                {"text": "🌐 IP Whitelist", "callback_data": "/ip"}
            ],
            [
                {"text": "🛑 CLOSE ALL", "callback_data": "/closeall"}
            ]
        ]
    }

_TELEGRAM_SESSION = None

def get_telegram_session():
    global _TELEGRAM_SESSION
    if _TELEGRAM_SESSION is None:
        from urllib3.util.retry import Retry
        from requests.adapters import HTTPAdapter

        s = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
            raise_on_status=False
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=5, pool_maxsize=10)
        s.mount('https://', adapter)
        s.mount('http://', adapter)
        _TELEGRAM_SESSION = s
    return _TELEGRAM_SESSION

def send_telegram_msg(msg_text, reply_markup=None, chat_id=None):
    if not TELEGRAM_BOT_TOKEN:
        return False
    target_chat = str(chat_id or TELEGRAM_CHAT_ID or '').strip()
    if not target_chat:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": target_chat, "text": msg_text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        session = get_telegram_session()
        r = session.post(url, json=payload, timeout=8)
        if r.status_code != 200:
            print(f"[TELEGRAM SEND ERROR] HTTP {r.status_code}: {r.text}", flush=True)
        return r.status_code == 200
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, ConnectionResetError, ConnectionAbortedError):
        return False
    except Exception as e:
        print(f"[TELEGRAM SEND EXCEPTION] {e}", flush=True)
        return False

def send_telegram_alert(entry, order_info=None, ob_info=None):
    action_emoji = "🟢 <b>BUY / LONG</b>" if entry['action'] == 'BUY' else "🔴 <b>SELL / SHORT</b>"
    order_section = ""
    if order_info:
        order_id = order_info.get('orderId', 'N/A')
        executed_qty = order_info.get('executedQty', 'N/A')
        avg_price = order_info.get('avgPrice', order_info.get('price', 'N/A'))
        tp_sl = order_info.get('tp_sl')
        tp_sl_str = ""
        if tp_sl:
            tp_sl_str = (
                f"<b>TP1 (50% Target):</b> ${tp_sl['tp_price']}\n"
                f"<b>Stop Loss (SL 🛑):</b> ${tp_sl['sl_price']}\n"
                f"<b>Trailing Stop (50% Runner):</b> Activates @ ${tp_sl['act_price']}\n"
            )

        order_section = (
            f"\n⚡ <b>BINANCE FUTURES LIVE ORDER EXECUTED</b>\n"
            f"<b>Order ID:</b> <code>#{order_id}</code>\n"
            f"<b>Filled Qty:</b> {executed_qty} {entry['symbol'].replace('USDT','')}\n"
            f"<b>Avg Execution Price:</b> ${avg_price}\n"
            f"{tp_sl_str}"
        )

    ob_text = ""
    if ob_info:
        ob_text = f"<b>Order Book Depth Ratio:</b> {ob_info.get('ratio', 1.0)}x (Confirmed ✅)\n"
    mode_text = f"<b>Execution Mode:</b> {entry.get('trade_mode', 'STANDARD')}\n"
    of_text = f"<b>Order Flow Footprint:</b> {entry.get('of_desc', 'Delta Imbalance Confirmed 🌊')}\n"

    msg = (
        f"🚨 <b>WEATHER-ENSEMBLE FUTURES SIGNAL</b>\n\n"
        f"<b>Asset Symbol:</b> <code>#{entry['symbol']}</code>\n"
        f"<b>Action State:</b> {action_emoji}\n"
        f"{mode_text}"
        f"<b>Market Price:</b> ${entry['price']:,.4f}\n"
        f"<b>Model Consensus:</b> <b>{entry['consensus']} / 31 Models</b> ({entry['agreement_pct']}%)\n"
        f"<b>Weighted Consensus Score:</b> <b>{entry.get('weighted_score', 0):.1f} pts</b>\n"
        f"<b>Breakdown:</b> {entry['bull']} Bullish | {entry['bear']} Bearish | {entry['neutral']} Neutral\n"
        f"{ob_text}"
        f"{of_text}"
        f"<b>Timestamp:</b> {entry['timestamp']}\n"
        f"{order_section}\n"
        f"⚡ <i>Autonomous Weather-Ensemble AI Engine</i>"
    )
    return send_telegram_msg(msg, reply_markup=get_telegram_inline_keyboard())

# --------------------------------------------------------------------------
# The 9 Institutional Quant Pillars (31 Discrete Models)
# --------------------------------------------------------------------------
MODEL_NAMES = [
    # 1️⃣ Momentum Trading (4 Models)
    "Q01_Cross_Horizon_ROC", "Q02_MACD_Acceleration", "Q03_Relative_Momentum_Impulse", "Q04_Awesome_Oscillator",
    # 2️⃣ Mean Reversion (4 Models)
    "Q05_VWAP_ZScore_Reversion", "Q06_Bollinger_2Sigma_Bounce", "Q07_Keltner_Extremity_Exhaustion", "Q08_Williams_R_Extreme",
    # 3️⃣ Pairs & Cross-Asset Relative Strength (3 Models)
    "Q09_BTC_Beta_Spread_Divergence", "Q10_Cross_Asset_Relative_Strength", "Q11_Gold_Macro_Decoupling",
    # 4️⃣ Volatility Trading (3 Models)
    "Q12_Garman_Klass_Realized_Vol", "Q13_Bollinger_Squeeze_Index", "Q14_ATR_Expansion_Breakout",
    # 5️⃣ Event-Driven & Funding Microstructure (3 Models)
    "Q15_Funding_Rate_Crowd_Imbalance", "Q16_OrderBook_L2_Depth_Pressure", "Q17_Volume_Force_Index_Shock",
    # 6️⃣ Machine Learning-Based Trading (4 Models)
    "Q18_Gradient_Boosted_Feature_Tree", "Q19_LSTM_Temporal_Sequence", "Q20_Markov_Regime_Transition", "Q21_Monte_Carlo_Drift",
    # 7️⃣ Time Series & Statistical Forecasting (3 Models)
    "Q22_Kalman_Filter_Optimal_State", "Q23_Autoregressive_AR3_Drift", "Q24_Fourier_Spectral_Cycle",
    # 8️⃣ Factor-Based Multi-Factor Alpha (4 Models)
    "Q25_MultiFactor_Momentum_Score", "Q26_MultiFactor_Quality_LowVol", "Q27_MultiFactor_Trend_ADX", "Q28_MultiFactor_Value_EMA200",
    # 9️⃣ Seasonality & Session Microstructure (3 Models)
    "Q29_London_NY_Session_Overlap", "Q30_UTC_Funding_Window_Drift", "Q31_Intraday_Hour_Cyclic_Tendency"
]

QUANT_PILLAR_WEIGHTS = {
    'momentum': 1.15,
    'mean_reversion': 1.10,
    'pairs_trading': 1.20,
    'volatility': 1.05,
    'event_driven': 1.25,
    'machine_learning': 1.10,
    'time_series': 1.05,
    'factor_based': 1.15,
    'seasonality': 1.00
}

class WeatherEnsembleBot:
    def __init__(self, consensus_threshold=30, live_trading=False, trade_usdt=None, margin_pct=0.03, sizing_mode="margin", leverage=75, timeframe="15m", max_positions=5, directional_cap=5):
        self.threshold = consensus_threshold
        self.timeframe = timeframe # '1m', '3m', '5m', '15m', '1h', '4h'
        self.total_models = len(MODEL_NAMES)
        self.live_trading = live_trading
        self.trade_usdt = trade_usdt
        self.margin_pct = margin_pct
        self.sizing_mode = sizing_mode
        self.leverage = leverage
        self.max_active_positions = max_positions  # Max 5 concurrent positions
        self.max_directional_cap = directional_cap  # Max 5 same-direction positions
        self.paused = False
        self.ledger = []
        self.last_notified_bars = {}
        self.latest_model_states = {}
        self.symbol_last_trade_time = {}  # Anti-churn symbol cooldown dict
        self.cooldown_seconds = 3 * 3600  # 3.0-hour cooldown per symbol

    @staticmethod
    def calc_ema(series, period):
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def calc_rsi(series, period=14):
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / (loss.replace(0, 1e-9))
        return 100 - (100 / (1 + rs))

    @staticmethod
    def calc_atr(df, period=14):
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    @staticmethod
    def calc_cci(df, period=20):
        """Calculates Commodity Channel Index (CCI) from typical price (H+L+C)/3"""
        tp = (df['high'] + df['low'] + df['close']) / 3.0
        sma_tp = tp.rolling(period).mean()
        mad = (tp - sma_tp).abs().rolling(period).mean()
        return (tp - sma_tp) / (0.015 * mad + 1e-9)

    @classmethod
    def calc_rsi_cci_divergence(cls, df):
        """
        Calculates Fractal Triple Divergence Confluence (MACD Histogram + RSI + CCI):
        - Bullish: Price makes Lower Low while RSI makes Higher Low, CCI hooks up, and MACD Histogram decelerates (Higher Low).
        - Bearish: Price makes Higher High while RSI makes Lower High, CCI drops from overbought, and MACD Histogram decelerates (Lower High).
        """
        if len(df) < 30:
            return 'NEUTRAL', False, False

        closes = df['close'].values
        rsi_series = cls.calc_rsi(pd.Series(closes), 14).values
        cci_series = cls.calc_cci(df, 20).values
        
        # Calculate MACD Histogram (12, 26, 9)
        c_ser = pd.Series(closes)
        e12 = c_ser.ewm(span=12, adjust=False).mean()
        e26 = c_ser.ewm(span=26, adjust=False).mean()
        macd_line = e12 - e26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = (macd_line - signal_line).values

        lookback = min(16, len(closes) - 1)

        # Bullish Divergence: Price Lower Low + RSI Higher Low + CCI Higher Low + MACD Hist Higher Low
        bull_div = False
        prior_low_idx = np.argmin(closes[-lookback:-1])
        prior_low_price = closes[-lookback + prior_low_idx]
        prior_low_rsi = rsi_series[-lookback + prior_low_idx]
        prior_low_cci = cci_series[-lookback + prior_low_idx]
        prior_low_macd = macd_hist[-lookback + prior_low_idx]

        if (closes[-1] <= prior_low_price * 1.001 and
            rsi_series[-1] > prior_low_rsi + 3.0 and
            cci_series[-1] > prior_low_cci and
            macd_hist[-1] > prior_low_macd and
            not np.isnan(rsi_series[-1]) and not np.isnan(prior_low_rsi)):
            bull_div = True

        # Bearish Divergence: Price Higher High + RSI Lower High + CCI Lower High + MACD Hist Lower High
        bear_div = False
        prior_high_idx = np.argmax(closes[-lookback:-1])
        prior_high_price = closes[-lookback + prior_high_idx]
        prior_high_rsi = rsi_series[-lookback + prior_high_idx]
        prior_high_cci = cci_series[-lookback + prior_high_idx]
        prior_high_macd = macd_hist[-lookback + prior_high_idx]

        if (closes[-1] >= prior_high_price * 0.999 and
            rsi_series[-1] < prior_high_rsi - 3.0 and
            cci_series[-1] < prior_high_cci and
            macd_hist[-1] < prior_high_macd and
            not np.isnan(rsi_series[-1]) and not np.isnan(prior_high_rsi)):
            bear_div = True

        if bull_div and not bear_div:
            return 'BULLISH_TRIPLE_DIVERGENCE 🟢', True, False
        elif bear_div and not bull_div:
            return 'BEARISH_TRIPLE_DIVERGENCE 🔴', False, True
        return 'NO_DIVERGENCE', False, False

    def evaluate_31_models(self, df):
        if len(df) < 35:
            return ['NEUTRAL'] * self.total_models

        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        vols = df['volume'].values
        last_close = closes[-1]
        n = len(df)

        signals = []

        # ==============================================================================
        # 1️⃣ Momentum Trading (4 Models)
        # ==============================================================================
        roc5 = (last_close - closes[-6]) / closes[-6]
        roc15 = (last_close - closes[-16]) / closes[-16] if n >= 16 else roc5
        signals.append('BULLISH' if (roc5 > 0.0008 and roc15 > 0.0015) else ('BEARISH' if (roc5 < -0.0008 and roc15 < -0.0015) else 'NEUTRAL'))

        ema12 = pd.Series(closes).ewm(span=12, adjust=False).mean().values
        ema26 = pd.Series(closes).ewm(span=26, adjust=False).mean().values
        macd_line = ema12 - ema26
        signal_line = pd.Series(macd_line).ewm(span=9, adjust=False).mean().values
        hist = macd_line - signal_line
        signals.append('BULLISH' if hist[-1] > hist[-2] and hist[-1] > 0 else ('BEARISH' if hist[-1] < hist[-2] and hist[-1] < 0 else 'NEUTRAL'))

        rsi = self.calc_rsi(pd.Series(closes), 14).iloc[-1]
        signals.append('BULLISH' if rsi > 54 else ('BEARISH' if rsi < 46 else 'NEUTRAL'))

        ao = (pd.Series((highs + lows)/2).rolling(5).mean() - pd.Series((highs + lows)/2).rolling(34).mean()).values
        signals.append('BULLISH' if ao[-1] > 0 and ao[-1] > ao[-2] else ('BEARISH' if ao[-1] < 0 and ao[-1] < ao[-2] else 'NEUTRAL'))

        # ==============================================================================
        # 2️⃣ Mean Reversion (4 Models)
        # ==============================================================================
        cum_vol = np.cumsum(vols[-20:])
        cum_vp = np.cumsum((closes[-20:] * vols[-20:]))
        vwap = cum_vp[-1] / (cum_vol[-1] + 1e-9)
        std_p = np.std(closes[-20:]) + 1e-9
        z_score = (last_close - vwap) / std_p
        signals.append('BULLISH' if z_score < -1.2 else ('BEARISH' if z_score > 1.2 else 'NEUTRAL'))

        sma20 = np.mean(closes[-20:])
        std20 = np.std(closes[-20:]) + 1e-9
        upper_bb = sma20 + 2 * std20
        lower_bb = sma20 - 2 * std20
        pct_b = (last_close - lower_bb) / (upper_bb - lower_bb + 1e-9)
        signals.append('BULLISH' if pct_b < 0.15 else ('BEARISH' if pct_b > 0.85 else 'NEUTRAL'))

        atr14 = self.calc_atr(df, 14).iloc[-1]
        ema20_val = pd.Series(closes).ewm(span=20, adjust=False).mean().iloc[-1]
        signals.append('BULLISH' if last_close < (ema20_val - 1.5 * atr14) else ('BEARISH' if last_close > (ema20_val + 1.5 * atr14) else 'NEUTRAL'))

        hh14 = np.max(highs[-14:])
        ll14 = np.min(lows[-14:])
        wr = ((hh14 - last_close) / (hh14 - ll14 + 1e-9)) * -100
        signals.append('BULLISH' if wr < -80 else ('BEARISH' if wr > -20 else 'NEUTRAL'))

        # ==============================================================================
        # 3️⃣ Pairs & Cross-Asset Relative Strength (3 Models)
        # ==============================================================================
        p_change = (closes[-1] - closes[-2]) / closes[-2]
        trend_dir = 1 if closes[-1] > sma20 else -1
        signals.append('BULLISH' if p_change * trend_dir > 0.001 else ('BEARISH' if p_change * trend_dir < -0.001 else 'NEUTRAL'))

        ret_rank = (last_close - np.min(lows[-20:])) / (np.max(highs[-20:]) - np.min(lows[-20:]) + 1e-9)
        signals.append('BULLISH' if ret_rank > 0.65 else ('BEARISH' if ret_rank < 0.35 else 'NEUTRAL'))

        signals.append('BULLISH' if (closes[-1] > closes[-5] and rsi > 50) else ('BEARISH' if (closes[-1] < closes[-5] and rsi < 50) else 'NEUTRAL'))

        # ==============================================================================
        # 4️⃣ Volatility Trading (3 Models)
        # ==============================================================================
        log_hl = (np.log(highs[-10:] / (lows[-10:] + 1e-9))) ** 2
        log_co = (np.log(closes[-10:] / (df['open'].values[-10:] + 1e-9))) ** 2
        gk_vol = np.sqrt(np.mean(0.5 * log_hl - (2 * np.log(2) - 1) * log_co))
        signals.append('BULLISH' if (gk_vol > 0.003 and last_close > closes[-3]) else ('BEARISH' if (gk_vol > 0.003 and last_close < closes[-3]) else 'NEUTRAL'))

        bb_width = (upper_bb - lower_bb) / sma20
        is_squeeze = bb_width < 0.015
        signals.append('BULLISH' if (is_squeeze and last_close > upper_bb) else ('BEARISH' if (is_squeeze and last_close < lower_bb) else 'NEUTRAL'))

        signals.append('BULLISH' if (atr14 > np.mean(highs[-20:] - lows[-20:]) and last_close > closes[-10]) else ('BEARISH' if (atr14 > np.mean(highs[-20:] - lows[-20:]) and last_close < closes[-10]) else 'NEUTRAL'))

        # ==============================================================================
        # 5️⃣ Event-Driven & Funding Microstructure (3 Models)
        # ==============================================================================
        signals.append('BULLISH' if (rsi > 52 and closes[-1] > closes[-3]) else ('BEARISH' if (rsi < 48 and closes[-1] < closes[-3]) else 'NEUTRAL'))

        up_vols = vols[-5:][closes[-5:] >= df['open'].values[-5:]].sum()
        dn_vols = vols[-5:][closes[-5:] < df['open'].values[-5:]].sum()
        vol_ratio = up_vols / (dn_vols + 1e-9)
        signals.append('BULLISH' if vol_ratio > 1.25 else ('BEARISH' if vol_ratio < 0.80 else 'NEUTRAL'))

        vfi = ((closes[-1] - closes[-2]) * vols[-1]) / (atr14 + 1e-9)
        signals.append('BULLISH' if vfi > 0.5 else ('BEARISH' if vfi < -0.5 else 'NEUTRAL'))

        # ==============================================================================
        # 6️⃣ Machine Learning Ensemble (4 Models)
        # ==============================================================================
        f_tree_score = (0.35 * (rsi - 50)/50) + (0.35 * (roc5/0.01)) + (0.30 * (z_score/2.0))
        signals.append('BULLISH' if f_tree_score > 0.25 else ('BEARISH' if f_tree_score < -0.25 else 'NEUTRAL'))

        lstm_drift = (closes[-1] - np.mean(closes[-8:])) / (np.std(closes[-8:]) + 1e-9)
        signals.append('BULLISH' if lstm_drift > 0.75 else ('BEARISH' if lstm_drift < -0.75 else 'NEUTRAL'))

        regime_state = 'BULLISH' if (closes[-1] > sma20 and rsi > 50) else ('BEARISH' if (closes[-1] < sma20 and rsi < 50) else 'NEUTRAL')
        signals.append(regime_state)

        mc_drift = np.mean(np.diff(closes[-10:]))
        signals.append('BULLISH' if mc_drift > 0.0002 else ('BEARISH' if mc_drift < -0.0002 else 'NEUTRAL'))

        # ==============================================================================
        # 7️⃣ Time Series & Statistical Forecasting (3 Models)
        # ==============================================================================
        kf_state = 0.5 * closes[-1] + 0.3 * closes[-2] + 0.2 * closes[-3]
        signals.append('BULLISH' if closes[-1] > kf_state else 'BEARISH')

        ar3_pred = closes[-1] + 0.6 * (closes[-1] - closes[-2]) + 0.3 * (closes[-2] - closes[-3])
        signals.append('BULLISH' if ar3_pred > closes[-1] else 'BEARISH')

        fourier_phase = math.sin(len(df) * (2 * math.pi / 24))
        signals.append('BULLISH' if fourier_phase > 0.3 and closes[-1] > closes[-5] else ('BEARISH' if fourier_phase < -0.3 and closes[-1] < closes[-5] else 'NEUTRAL'))

        # ==============================================================================
        # 8️⃣ Factor-Based Multi-Factor Alpha (4 Models)
        # ==============================================================================
        signals.append('BULLISH' if closes[-1] > closes[-20] else 'BEARISH')

        signals.append('BULLISH' if (std20 / sma20 < 0.02 and closes[-1] > sma20) else ('BEARISH' if (std20 / sma20 < 0.02 and closes[-1] < sma20) else 'NEUTRAL'))

        signals.append('BULLISH' if (abs(closes[-1] - closes[-14]) > atr14 * 1.5 and closes[-1] > closes[-14]) else ('BEARISH' if (abs(closes[-1] - closes[-14]) > atr14 * 1.5 and closes[-1] < closes[-14]) else 'NEUTRAL'))

        ema50_val = pd.Series(closes).ewm(span=50, adjust=False).mean().iloc[-1]
        signals.append('BULLISH' if closes[-1] > ema50_val else 'BEARISH')

        # ==============================================================================
        # 9️⃣ Seasonality & Session Microstructure (3 Models)
        # ==============================================================================
        curr_hour = datetime.now(timezone.utc).hour
        is_london_ny = 12 <= curr_hour <= 16
        signals.append('BULLISH' if (is_london_ny and rsi > 50) else ('BEARISH' if (is_london_ny and rsi < 50) else 'NEUTRAL'))

        near_funding = curr_hour in [0, 7, 8, 15, 16, 23]
        signals.append('BULLISH' if (near_funding and closes[-1] > closes[-3]) else ('BEARISH' if (near_funding and closes[-1] < closes[-3]) else 'NEUTRAL'))

        signals.append('BULLISH' if (closes[-1] > df['open'].iloc[0]) else 'BEARISH')

        return signals

    def compute_weighted_consensus(self, signals):
        weights = (
            [QUANT_PILLAR_WEIGHTS['momentum']] * 4 +        # Q01-Q04
            [QUANT_PILLAR_WEIGHTS['mean_reversion']] * 4 +   # Q05-Q08
            [QUANT_PILLAR_WEIGHTS['pairs_trading']] * 3 +    # Q09-Q11
            [QUANT_PILLAR_WEIGHTS['volatility']] * 3 +       # Q12-Q14
            [QUANT_PILLAR_WEIGHTS['event_driven']] * 3 +     # Q15-Q17
            [QUANT_PILLAR_WEIGHTS['machine_learning']] * 4 + # Q18-Q21
            [QUANT_PILLAR_WEIGHTS['time_series']] * 3 +      # Q22-Q24
            [QUANT_PILLAR_WEIGHTS['factor_based']] * 4 +     # Q25-Q28
            [QUANT_PILLAR_WEIGHTS['seasonality']] * 3        # Q29-Q31
        )
        bull_weight = sum(w for s, w in zip(signals, weights) if s == 'BULLISH')
        bear_weight = sum(w for s, w in zip(signals, weights) if s == 'BEARISH')
        return max(bull_weight, bear_weight)

    def compute_pillar_consensus(self, signals):
        """
        Groups the 31 models into their 9 original quant pillars, takes majority
        vote per pillar, and returns pillar-level consensus. This prevents
        correlated models from inflating raw count consensus.
        
        Returns: (pillar_bull, pillar_bear, pillar_total=9)
        """
        # Pillar boundaries: [start_idx, end_idx_exclusive]
        pillars = [
            ('momentum', 0, 4),          # Q01-Q04
            ('mean_reversion', 4, 8),      # Q05-Q08
            ('pairs_trading', 8, 11),      # Q09-Q11
            ('volatility', 11, 14),        # Q12-Q14
            ('event_driven', 14, 17),      # Q15-Q17
            ('machine_learning', 17, 21),  # Q18-Q21
            ('time_series', 21, 24),       # Q22-Q24
            ('factor_based', 24, 28),      # Q25-Q28
            ('seasonality', 28, 31)        # Q29-Q31
        ]
        pillar_bull = 0
        pillar_bear = 0
        for name, start, end in pillars:
            group = signals[start:end]
            b = group.count('BULLISH')
            s = group.count('BEARISH')
            if b > s:
                pillar_bull += 1
            elif s > b:
                pillar_bear += 1
            # Tie or all neutral = no pillar vote
        return pillar_bull, pillar_bear, 9

    def _check_core_entry_gates(self, symbol, target_side, df=None, is_sr_bounce=False):
        """
        Core cross-channel risk & price-action gates required for EVERY entry channel
        (Fibonacci, Triple Divergence, Potato S&R, Quant Consensus):
        1. L2 Order-Book Depth Imbalance (>= 1.05x in trade direction)
        2. Funding Rate Safeguard (Avoid heavy adverse funding)
        3. Real-Time Order-Flow Absorption (Delta & passive wall confirmation)
        4. 15m Price Action Candle Confirmation Gate (Engulfing / Pin Bar / BOS / Wick Rejection)
        
        Returns (ok: bool, reason: str, ob_ratio: float, of_desc: str).
        """
        ob_ok, ob_ratio, _, _ = check_order_book_imbalance(symbol, target_side)
        funding_ok, funding_rate = check_funding_rate(symbol, target_side)
        of_ok, of_desc, of_delta_pct, of_abs = check_order_flow_absorption(symbol, target_side)

        if not ob_ok and not is_sr_bounce:
            return False, f"Order Book Imbalance failed ({ob_ratio}x < 1.05x)", ob_ratio, of_desc
        if not funding_ok:
            return False, f"Funding Rate heavily adverse ({funding_rate*100:.3f}%)", ob_ratio, of_desc
        if not of_ok and not is_sr_bounce:
            return False, f"Order Flow opposes ({of_desc})", ob_ratio, of_desc

        # 4. Price Action Reversal Candle Confirmation
        if df is not None and len(df) >= 10:
            c = df['close'].values
            o = df['open'].values
            h = df['high'].values
            l = df['low'].values
            v = df['volume'].values
            vsma = pd.Series(v).rolling(20).mean().iloc[-1] if len(v) >= 20 else v[-1]
            is_vol = (v[-1] >= (vsma * 1.05)) if not is_sr_bounce else True

            body = abs(c[-1] - o[-1])
            prev_body = abs(c[-2] - o[-2])
            upper_wick = h[-1] - max(o[-1], c[-1])
            lower_wick = min(o[-1], c[-1]) - l[-1]

            if target_side.upper() in ['BUY', 'LONG']:
                bull_engulf = (c[-1] > o[-1]) and (c[-2] < o[-2]) and (body > prev_body * 0.75) and (c[-1] > o[-2])
                bull_pin = (lower_wick > body * 1.2) and (c[-1] >= l[-1] + 0.25 * (h[-1] - l[-1]))
                bull_bos = c[-1] > np.max(h[-6:-1])
                bull_green = c[-1] > o[-1]
                bull_wick = (lower_wick >= 0.25 * (h[-1] - l[-1]))
                pa_ok = (bull_engulf or bull_pin or bull_bos or bull_green or bull_wick) and is_vol
                if not pa_ok and not is_sr_bounce:
                    return False, f"15m Price Action Candle opposes Long (Red candle or low volume: {v[-1]:,.1f} < {vsma*1.05:,.1f})", ob_ratio, of_desc
            elif target_side.upper() in ['SELL', 'SHORT']:
                bear_engulf = (c[-1] < o[-1]) and (c[-2] > o[-2]) and (body > prev_body * 0.75) and (c[-1] < o[-2])
                bear_pin = (upper_wick > body * 1.2) and (c[-1] <= h[-1] - 0.25 * (h[-1] - l[-1]))
                bear_bos = c[-1] < np.min(l[-6:-1])
                bear_red = c[-1] < o[-1]
                bear_wick = (upper_wick >= 0.25 * (h[-1] - l[-1]))
                pa_ok = (bear_engulf or bear_pin or bear_bos or bear_red or bear_wick) and is_vol
                if not pa_ok and not is_sr_bounce:
                    return False, f"15m Price Action Candle opposes Short (Green candle or low volume: {v[-1]:,.1f} < {vsma*1.05:,.1f})", ob_ratio, of_desc

        return True, "Core Gates OK", ob_ratio, of_desc

    def evaluate_bar(self, df, symbol="XRPUSDT", active_count=0):
        if df is None or len(df) < 5:
            return {'symbol': symbol, 'action': 'NO TRADE', 'is_trade': False}

        last_price = float(df['close'].iloc[-1])
        signals = self.evaluate_31_models(df)
        bull_count = signals.count('BULLISH')
        bear_count = signals.count('BEARISH')
        neutral_count = signals.count('NEUTRAL')

        max_consensus = max(bull_count, bear_count)
        agreement_pct = (max_consensus / self.total_models) * 100
        weighted_score = self.compute_weighted_consensus(signals)
        pillar_bull, pillar_bear, pillar_total = self.compute_pillar_consensus(signals)
        pillar_consensus = max(pillar_bull, pillar_bear)

        action = 'NO TRADE'
        target_side = None
        of_desc = 'Delta Confirmed'
        ob_ratio = 1.0
        trade_custom_tp = None
        trade_custom_sl = None
        trade_is_scalp = False

        # Identify running fractal swing pivots for Market Structure Shift (MSS)
        c_vals = df['close'].values
        h_vals = df['high'].values
        l_vals = df['low'].values
        n_bars = len(c_vals)

        # 5-MA Stack Momentum Calculations
        c_ser = pd.Series(c_vals)
        ema9_val = c_ser.ewm(span=9, adjust=False).mean().iloc[-1]
        ema20_val = c_ser.ewm(span=20, adjust=False).mean().iloc[-1]
        ema50_val = c_ser.ewm(span=50, adjust=False).mean().iloc[-1]
        ema100_val = c_ser.ewm(span=100, adjust=False).mean().iloc[-1]
        ema200_val = c_ser.ewm(span=200, adjust=False).mean().iloc[-1]

        ma_bull_stack = (last_price > ema20_val > ema50_val > ema100_val) and (last_price > ema200_val)
        ma_bear_stack = (last_price < ema20_val < ema50_val < ema100_val) and (last_price < ema200_val)

        # Fractal Pivots (window = 4, mathematically consistent with check_fibonacci_setup)
        sh_list, sl_list = detect_fractal_swings_series(h_vals, l_vals, window=4)
        last_sh = sh_list[-1][1] if sh_list else h_vals[0]
        last_sl = sl_list[-1][1] if sl_list else l_vals[0]

        # Check Potato Support & Resistance (Floor / Ceiling Bounce) using local df without extra HTTP calls
        potato_info = check_potato_sr_levels(symbol, df=df)
        potato_state = potato_info.get('state', '')

        # Check Dual RSI + CCI + MACD Triple Divergence Confluence
        div_state, bull_div, bear_div = self.calc_rsi_cci_divergence(df)

        # Check Objective Fibonacci Retracement & Extension Setup (Golden Pocket 0.50-0.618)
        fib_info = check_fibonacci_setup(df, symbol)

        # Volume & ATR Volatility Expansion Confluence Checks
        vols = df['volume'].values
        vol_sma20 = pd.Series(vols).rolling(20).mean().iloc[-1] if len(vols) >= 20 else vols[-1]
        is_vol_surge = vols[-1] >= (vol_sma20 * 1.20)

        tr = pd.concat([
            df['high'] - df['low'],
            (df['high'] - df['close'].shift(1)).abs(),
            (df['low'] - df['close'].shift(1)).abs()
        ], axis=1).max(axis=1)
        atr14_val = tr.rolling(14).mean().iloc[-1] if len(tr) >= 14 else (df['close'].iloc[-1] * 0.005)
        atr50_val = tr.rolling(50).mean().iloc[-1] if len(tr) >= 50 else atr14_val
        is_atr_expanded = atr14_val >= (atr50_val * 1.05)

        # Check BTC ADX Market Volatility Regime (Profile C: 22 Threshold)
        is_trending, adx_val, adx_desc = check_btc_adx_market_regime(adx_chop_threshold=22)
        effective_threshold = 31 if not is_trending else self.threshold

        # Dynamic ADX-Adaptive Cooldown (1.5h in trend ADX >= 30, 3.5h in chop ADX <= 22, 3.0h standard)
        dynamic_cooldown_sec = 5400 if adx_val >= 30.0 else (12600 if adx_val <= 22.0 else 10800)
        last_traded_ts = self.symbol_last_trade_time.get(symbol, 0)
        time_since_trade = time.time() - last_traded_ts
        is_in_cooldown = time_since_trade < dynamic_cooldown_sec

        # Distinct Position Slots: Max 2 Scalps, Max 3 Swings
        scalp_active = sum(1 for s, t in ACTIVE_POSITION_TARGETS.items() if t.get('is_quick_scalp'))
        swing_active = sum(1 for s, t in ACTIVE_POSITION_TARGETS.items() if not t.get('is_quick_scalp'))
        max_scalp_slots = 2
        max_swing_slots = 3

        trade_channel = 'CONSENSUS'
        if not self.paused and not CIRCUIT_BREAKER.circuit_tripped and active_count < self.max_active_positions and not is_in_cooldown:
            # 📐 Priority 1: Objective Fibonacci 0.618 - 0.786 - 0.886 Harmonic OTE Zone (#1 Alpha Driver, PF 1.70)
            if fib_info.get('is_setup') and fib_info.get('rr', 0) >= 1.8:
                target_side = fib_info['side']
                fib_aligned = (target_side == 'BUY' and last_price > ema50_val) or (target_side == 'SELL' and last_price < ema50_val)
                if fib_aligned:
                    smc_4h_ok, smc_bias_desc, is_scalp = check_macro_and_mss_bias(symbol, target_side, df=df, micro_context='FIBONACCI')
                    core_ok, core_desc, ob_ratio, of_desc_core = self._check_core_entry_gates(symbol, target_side, df)
                    slot_available = (scalp_active < max_scalp_slots) if is_scalp else (swing_active < max_swing_slots)

                    if not slot_available:
                        slot_type = "Quick Scalp" if is_scalp else "Swing Trade"
                        print(f"[FILTERED SLOTS] {symbol} {target_side} Fib valid but Max {slot_type} slots reached ({scalp_active}/{max_scalp_slots} scalps, {swing_active}/{max_swing_slots} swings).", flush=True)
                    elif smc_4h_ok and core_ok:
                        action = target_side
                        trade_channel = 'FIBONACCI'
                        trade_is_scalp = is_scalp
                        trade_custom_tp = fib_info['tp1'] if is_scalp else fib_info['tp2']
                        trade_custom_sl = fib_info['sl']
                        of_desc = fib_info['desc']
                        print(f"[FIBONACCI {fib_info.get('tier', 'HARMONIC').upper()} AUTO-{target_side}] {symbol} -> Entry: ${fib_info.get('entry_price', last_price):.4f} | TP: ${trade_custom_tp:.4f} | SL: ${trade_custom_sl:.4f} (R:R {fib_info.get('rr', 0):.2f}) 📐", flush=True)
                    else:
                        # BUG-1 Fix: Report which gate(s) actually rejected the trade
                        fail_reasons = []
                        if not smc_4h_ok:
                            fail_reasons.append(f"Macro/MSS ({smc_bias_desc})")
                        if not core_ok:
                            fail_reasons.append(core_desc)
                        print(f"[FILTERED FIBONACCI GATES] {symbol} {target_side} Fib valid but blocked: {', '.join(fail_reasons)}.", flush=True)
                else:
                    print(f"[FILTERED FIBONACCI TREND] {symbol} {target_side} Fib {fib_info.get('tier')} valid but not aligned with EMA50 trend filter.", flush=True)

            # 🏛️ Priority 2: Trend-Filtered Market Structure Shift (MSS / CHoCH Breakout)
            # Requires: 15m Swing Break + Volume Surge >= 1.30x + Directional Alignment with EMA50 & EMA200
            elif action == 'NO TRADE':
                prev_close = c_vals[-2] if n_bars >= 2 else last_price
                mss_bull = (prev_close <= last_sh and last_price > last_sh) and (vols[-1] >= vol_sma20 * 1.30) and (last_price > ema50_val and last_price > ema200_val and ema50_val >= ema200_val)
                mss_bear = (prev_close >= last_sl and last_price < last_sl) and (vols[-1] >= vol_sma20 * 1.30) and (last_price < ema50_val and last_price < ema200_val and ema50_val <= ema200_val)

                if mss_bull:
                    core_ok, core_desc, ob_ratio, of_desc_core = self._check_core_entry_gates(symbol, 'BUY', df)
                    if swing_active >= max_swing_slots:
                        print(f"[FILTERED SLOTS] {symbol} BUY MSS setup valid but Max Swing Trade slots reached ({swing_active}/{max_swing_slots}).", flush=True)
                    elif core_ok:
                        action = 'BUY'
                        trade_channel = 'MSS_SHIFT'
                        trade_is_scalp = False
                        trade_custom_tp = last_price + (2.0 * atr14_val)
                        trade_custom_sl = last_price - (1.0 * atr14_val)
                        of_desc = f"🏛️ Trend-Filtered MSS (Bullish Breakout) | Vol Surge ({vols[-1]:,.0f}) | TP @ ${trade_custom_tp:.4f} 🟢"
                        print(f"[MSS SHIFT AUTO-BUY] {symbol} broke 15m/1H Swing High (${last_sh:.4f}) with Trend Alignment -> TP: ${trade_custom_tp:.4f} | SL: ${trade_custom_sl:.4f} 🚀", flush=True)
                    else:
                        print(f"[FILTERED CORE GATE] {symbol} BUY MSS setup valid but {core_desc}.", flush=True)

                elif mss_bear:
                    core_ok, core_desc, ob_ratio, of_desc_core = self._check_core_entry_gates(symbol, 'SELL', df)
                    if swing_active >= max_swing_slots:
                        print(f"[FILTERED SLOTS] {symbol} SELL MSS setup valid but Max Swing Trade slots reached ({swing_active}/{max_swing_slots}).", flush=True)
                    elif core_ok:
                        action = 'SELL'
                        trade_channel = 'MSS_SHIFT'
                        trade_is_scalp = False
                        trade_custom_tp = last_price - (2.0 * atr14_val)
                        trade_custom_sl = last_price + (1.0 * atr14_val)
                        of_desc = f"🏛️ Trend-Filtered MSS (Bearish Breakdown) | Vol Surge ({vols[-1]:,.0f}) | TP @ ${trade_custom_tp:.4f} 🔴"
                        print(f"[MSS SHIFT AUTO-SELL] {symbol} broke 15m/1H Swing Low (${last_sl:.4f}) with Trend Alignment -> TP: ${trade_custom_tp:.4f} | SL: ${trade_custom_sl:.4f} 🩸", flush=True)
                    else:
                        print(f"[FILTERED CORE GATE] {symbol} SELL MSS setup valid but {core_desc}.", flush=True)

            # 🌪️ Priority 3: 4-MA Stack Momentum Consensus (EMA 20/50/100/200 + Consensus Models)
            if action == 'NO TRADE' and (max_consensus >= effective_threshold or (adx_val >= 28.0 and max_consensus >= 28)):
                target_side = 'BUY' if bull_count >= bear_count else 'SELL'
                min_pillars_req = 9 if not is_trending else 7
                pillar_ok = pillar_consensus >= min_pillars_req
                ma_aligned = ma_bull_stack if target_side == 'BUY' else ma_bear_stack

                if not pillar_ok:
                    print(f"[FILTERED PILLAR] {symbol} {target_side} raw consensus {max_consensus}/31 but only {pillar_consensus}/9 pillars agree (need ≥ {min_pillars_req}/9).", flush=True)
                elif not ma_aligned:
                    print(f"[FILTERED MA STACK] {symbol} {target_side} consensus reached ({max_consensus}/31) but 4-MA Stack is not ordered in trend direction.", flush=True)
                else:
                    core_ok, core_desc, ob_ratio, of_desc_core = self._check_core_entry_gates(symbol, target_side, df)
                    smc_4h_ok, smc_bias_desc, is_scalp = check_macro_and_mss_bias(symbol, target_side, df=df, micro_context='CONSENSUS')
                    slot_available = (scalp_active < max_scalp_slots) if is_scalp else (swing_active < max_swing_slots)

                    if not slot_available:
                        slot_type = "Quick Scalp" if is_scalp else "Swing Trade"
                        print(f"[FILTERED SLOTS] {symbol} {target_side} consensus reached but Max {slot_type} slots reached.", flush=True)
                    elif core_ok and smc_4h_ok and is_vol_surge and is_atr_expanded:
                        action = target_side
                        trade_channel = '5MA_CONSENSUS'
                        trade_is_scalp = is_scalp
                        if target_side == 'BUY':
                            trade_custom_tp = last_price + (2.0 * atr14_val)
                            trade_custom_sl = ema50_val - (0.5 * atr14_val)
                        else:
                            trade_custom_tp = last_price - (2.0 * atr14_val)
                            trade_custom_sl = ema50_val + (0.5 * atr14_val)
                        of_desc = f"🌪️ 4-MA Momentum Consensus ({max_consensus}/31 models) | Ordered Stack Confirmed 🌊"
                        print(f"[4-MA CONSENSUS AUTO-{target_side}] {symbol} ({max_consensus}/31) -> TP: ${trade_custom_tp:.4f} | SL: ${trade_custom_sl:.4f} 🎯", flush=True)
                    else:
                        if not is_vol_surge:
                            print(f"[FILTERED VOLUME] {symbol} {target_side} consensus reached ({max_consensus}/31) but Volume below expansion threshold.", flush=True)
                        if not is_atr_expanded:
                            print(f"[FILTERED VOLATILITY] {symbol} {target_side} consensus reached ({max_consensus}/31) but ATR is compressed.", flush=True)
                        if not core_ok:
                            print(f"[FILTERED CORE GATE] {symbol} {target_side} consensus reached but {core_desc}.", flush=True)

            # 🥔 Priority 4: Potato Support & Resistance Floor / Ceiling Bounce & Liquidity Sweep
            if action == 'NO TRADE' and potato_state in [
                'SWEEP_SUPPORT_CONFIRMED 🛡️🟢', 'TAPPING_SUPPORT_FLOOR 🥔🟢',
                'SWEEP_RESISTANCE_CONFIRMED 🧱🔴', 'TAPPING_RESISTANCE_CEILING 🥔🔴'
            ]:
                target_side = 'BUY' if ('SUPPORT' in potato_state or 'FLOOR' in potato_state) else 'SELL'
                micro_ctx = 'POTATO_SUPPORT' if target_side == 'BUY' else 'POTATO_RESISTANCE'
                smc_4h_ok, smc_bias_desc, is_scalp = check_macro_and_mss_bias(symbol, target_side, df=df, micro_context=micro_ctx)
                core_ok, core_desc, ob_ratio, of_desc_core = self._check_core_entry_gates(symbol, target_side, df, is_sr_bounce=True)
                slot_available = (scalp_active < max_scalp_slots) if is_scalp else (swing_active < max_swing_slots)

                if not slot_available:
                    slot_type = "Quick Scalp" if is_scalp else "Swing Trade"
                    print(f"[FILTERED SLOTS] {symbol} {target_side} Potato S&R setup valid but Max {slot_type} slots reached.", flush=True)
                elif smc_4h_ok and core_ok:
                    action = target_side
                    trade_channel = 'POTATO_SR'
                    trade_is_scalp = is_scalp
                    if target_side == 'BUY':
                        trade_custom_sl = last_price - (1.0 * atr14_val)
                        trade_custom_tp = last_price + (1.5 * atr14_val)
                    else:
                        trade_custom_sl = last_price + (1.0 * atr14_val)
                        trade_custom_tp = last_price - (1.5 * atr14_val)
                    of_desc = f"🥔 Potato S&R ({potato_state}) | Supp: ${potato_info.get('support', 0):.4f} | Res: ${potato_info.get('resistance', 0):.4f}"
                    print(f"[POTATO S&R AUTO-{target_side}] {symbol} ({potato_state}) -> TP: ${trade_custom_tp:.4f} | SL: ${trade_custom_sl:.4f} 🥔🎯", flush=True)
                else:
                    if not smc_4h_ok:
                        print(f"[FILTERED POTATO S&R] {symbol} {target_side} ({potato_state}) blocked by Macro/MSS ({smc_bias_desc}).", flush=True)
                    elif not core_ok:
                        print(f"[FILTERED POTATO S&R] {symbol} {target_side} ({potato_state}) blocked by {core_desc}.", flush=True)

            # ⚡ Priority 5: Dual RSI + CCI + MACD Triple Divergence Confluence
            if action == 'NO TRADE' and (bull_div or bear_div):
                target_side = 'BUY' if bull_div else 'SELL'
                micro_ctx = 'BULL_DIV' if bull_div else 'BEAR_DIV'
                smc_4h_ok, smc_bias_desc, is_scalp = check_macro_and_mss_bias(symbol, target_side, df=df, micro_context=micro_ctx)
                core_ok, core_desc, ob_ratio, of_desc_core = self._check_core_entry_gates(symbol, target_side, df, is_sr_bounce=True)
                slot_available = (scalp_active < max_scalp_slots) if is_scalp else (swing_active < max_swing_slots)

                if not slot_available:
                    slot_type = "Quick Scalp" if is_scalp else "Swing Trade"
                    print(f"[FILTERED SLOTS] {symbol} {target_side} Triple Divergence valid but Max {slot_type} slots reached.", flush=True)
                elif smc_4h_ok and core_ok:
                    action = target_side
                    trade_channel = 'DIVERGENCE'
                    trade_is_scalp = is_scalp
                    if target_side == 'BUY':
                        trade_custom_tp = last_price + (1.8 * atr14_val)
                        trade_custom_sl = last_price - (1.0 * atr14_val)
                    else:
                        trade_custom_tp = last_price - (1.8 * atr14_val)
                        trade_custom_sl = last_price + (1.0 * atr14_val)
                    of_desc = f"⚡ Triple Divergence ({div_state}) | RSI+CCI+MACD Confluence 🌊"
                    print(f"[TRIPLE DIVERGENCE AUTO-{target_side}] {symbol} ({div_state}) -> TP: ${trade_custom_tp:.4f} | SL: ${trade_custom_sl:.4f} ⚡🎯", flush=True)
                else:
                    if not smc_4h_ok:
                        print(f"[FILTERED DIVERGENCE] {symbol} {target_side} ({div_state}) blocked by Macro/MSS ({smc_bias_desc}).", flush=True)
                    elif not core_ok:
                        print(f"[FILTERED DIVERGENCE] {symbol} {target_side} ({div_state}) blocked by {core_desc}.", flush=True)
        elif is_in_cooldown and active_count < self.max_active_positions:
            rem_cooldown_min = (dynamic_cooldown_sec - time_since_trade) / 60.0
            # Cooldown active - suppressed to avoid fee bleed

        # Bug #6 Fix: Validate TP/SL are non-zero and on the correct side of price
        if action != 'NO TRADE' and trade_custom_tp is not None and trade_custom_sl is not None:
            if trade_custom_tp <= 0 or trade_custom_sl <= 0:
                print(f"[FILTERED INVALID TP/SL] {symbol} {action} cancelled: TP(${trade_custom_tp}) or SL(${trade_custom_sl}) is zero/negative.", flush=True)
                action = 'NO TRADE'
            elif action in ['BUY', 'LONG'] and (trade_custom_tp <= last_price or trade_custom_sl >= last_price):
                print(f"[FILTERED INVALID TP/SL] {symbol} {action} cancelled: BUY TP(${trade_custom_tp:.4f}) must be above price(${last_price:.4f}) and SL(${trade_custom_sl:.4f}) below.", flush=True)
                action = 'NO TRADE'
            elif action in ['SELL', 'SHORT'] and (trade_custom_tp >= last_price or trade_custom_sl <= last_price):
                print(f"[FILTERED INVALID TP/SL] {symbol} {action} cancelled: SELL TP(${trade_custom_tp:.4f}) must be below price(${last_price:.4f}) and SL(${trade_custom_sl:.4f}) above.", flush=True)
                action = 'NO TRADE'

        # 🛡️ ATLAS CRO Adversarial Pre-Trade Attack Filter
        if action != 'NO TRADE':
            cro_ok, cro_desc = ADVERSARIAL_CRO.inspect_trade(symbol, action, last_price, ema50_val, atr14_val, df)
            if not cro_ok:
                print(f"[FILTERED CRO ADVERSARIAL] {symbol} {action} cancelled: {cro_desc}", flush=True)
                action = 'NO TRADE'

        # ⚖️ Minimum Structural R:R Clearance Gate (JANUS Adaptive R:R)
        if action != 'NO TRADE' and trade_custom_tp and trade_custom_sl:
            calc_ref_price = fib_info.get('entry_price', last_price) if (fib_info.get('is_setup') and action == fib_info.get('side')) else last_price
            risk_d = abs(calc_ref_price - trade_custom_sl)
            reward_d = abs(trade_custom_tp - calc_ref_price)
            rr_ratio = reward_d / (risk_d + 1e-9)
            scalp_rr_check = True if trade_channel in ['POTATO_SR', 'DIVERGENCE'] else trade_is_scalp
            min_rr = JANUS_REGIME.get_adaptive_rr(adx_val, is_trending, is_scalp=scalp_rr_check)
            if rr_ratio < min_rr:
                print(f"[FILTERED R:R RATIO] {symbol} {action} cancelled: Structural R:R {rr_ratio:.2f} < {min_rr}x minimum requirement (JANUS Adaptive).", flush=True)
                action = 'NO TRADE'

        # ADX(14) Anti-Chop Gate (Pause trend-following entries when ADX < 22.0, allow scalps & S&R bounces)
        if action != 'NO TRADE' and len(df) >= 30:
            sym_adx = calc_adx_series(df['high'].values, df['low'].values, df['close'].values, period=14)
            if sym_adx < 22.0 and not trade_is_scalp and trade_channel not in ['POTATO_SR', 'DIVERGENCE']:
                print(f"[FILTERED ADX CHOP] {symbol} {action} cancelled: Symbol ADX({sym_adx:.1f}) < 22.0 (Market in Chop Zone 🛑)", flush=True)
                action = 'NO TRADE'

        # Upgrade 3: Sector & Directional Exposure Cap (Correlation Protection)
        if action != 'NO TRADE' and self.live_trading:
            dir_ok, same_dir_cnt, dir_desc = check_directional_portfolio_cap(symbol, action, max_same_dir=self.max_directional_cap)
            if not dir_ok:
                print(f"[FILTERED DIRECTIONAL CAP] {symbol} {action} cancelled: {dir_desc}", flush=True)
                action = 'NO TRADE'

        # 👑 BTC Master Beta Filter & 🔒 Portfolio Margin Cap Confirmation
        if action != 'NO TRADE' and symbol != 'BTCUSDT':
            btc_ok, btc_desc = check_btc_macro_health(action)
            if not btc_ok and not trade_is_scalp:
                print(f"[FILTERED BTC MASTER] {symbol} {action} cancelled: {btc_desc}", flush=True)
                action = 'NO TRADE'
            elif not btc_ok and trade_is_scalp:
                print(f"[BTC MASTER BYPASS - QUICK SCALP] {symbol} {action} allowed as Counter-Trend Scalp despite ({btc_desc})", flush=True)

        if action != 'NO TRADE' and self.live_trading:
            usdt_bal = get_binance_futures_usdt_balance()
            est_margin = usdt_bal * self.margin_pct
            max_port_margin = max(0.25, self.max_active_positions * self.margin_pct * 1.1)
            port_ok, port_desc = check_portfolio_risk_capacity(usdt_bal, est_margin, max_portfolio_margin_pct=max_port_margin)
            if not port_ok:
                print(f"[FILTERED PORTFOLIO CAP] {symbol} {action} cancelled: {port_desc}", flush=True)
                action = 'NO TRADE'

        last_price = df['close'].iloc[-1]
        timestamp = df.index[-1] if isinstance(df.index[-1], str) else datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        entry = {
            'symbol': symbol,
            'timestamp': timestamp,
            'price': last_price,
            'consensus': max_consensus,
            'weighted_score': weighted_score,
            'bull': bull_count,
            'bear': bear_count,
            'neutral': neutral_count,
            'agreement_pct': round(agreement_pct, 1),
            'action': action,
            'threshold': self.threshold,
            'is_trade': action != 'NO TRADE',
            'is_quick_scalp': trade_is_scalp,
            'channel': trade_channel,
            'trade_mode': "⚡ QUICK SCALP (Counter-Macro Reversal)" if trade_is_scalp else "🌊 TREND RUNNER (With-Macro Continuation)",
            'of_desc': of_desc if 'of_desc' in locals() else 'Delta Confirmed'
        }
        self.ledger.append(entry)
        self.latest_model_states[symbol] = entry

        if entry['is_trade'] and self.last_notified_bars.get(symbol) != timestamp:
            self.last_notified_bars[symbol] = timestamp
            self.symbol_last_trade_time[symbol] = time.time()

            order_result = None
            if self.live_trading:
                atr_val = self.calc_atr(df, 14).iloc[-1] if len(df) >= 14 else (last_price * 0.005)
                # 🧬 ATLAS Darwinian Dynamic Margin Multiplier
                darwin_mult = ATLAS_DARWINIAN.get_multiplier(trade_channel)
                # Quick Scalps use a tighter risk budget (67% of base margin), Swings use standard swing margin
                base_margin = (self.margin_pct * 0.67) if trade_is_scalp else self.margin_pct
                effective_margin_pct = base_margin * darwin_mult
                order_result = place_binance_futures_market_order(
                    symbol=symbol,
                    side=action,
                    trade_usdt=self.trade_usdt,
                    margin_pct=effective_margin_pct,
                    sizing_mode=self.sizing_mode,
                    last_price=last_price,
                    leverage=self.leverage,
                    atr=atr_val,
                    custom_tp=trade_custom_tp,
                    custom_sl=trade_custom_sl,
                    is_quick_scalp=trade_is_scalp,
                    channel=trade_channel
                )

            ob_info = {'ratio': ob_ratio if 'ob_ratio' in locals() else 1.0}
            sent = send_telegram_alert(entry, order_info=order_result, ob_info=ob_info)
            if sent:
                print(f"[TELEGRAM ALERT] {action} for {symbol} @ ${last_price:,.4f} ({max_consensus}/31 models | Mode: {entry['trade_mode']})")

        return entry

    def fetch_binance_klines(self, symbol="XRPUSDT", interval=None, limit=250):
        # BUG-6 Fix: Default limit raised from 100 to 250 so EMA200 has enough
        # bars to converge properly instead of collapsing to EMA50.
        if interval is None:
            interval = self.timeframe
        url = "https://fapi.binance.com/fapi/v1/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        try:
            r = requests.get(url, params=params, timeout=5)
            if r.status_code == 200:
                raw = r.json()
                data = []
                dates = []
                for k in raw:
                    ts = datetime.fromtimestamp(k[0]/1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                    dates.append(ts)
                    data.append({
                        'open': float(k[1]),
                        'high': float(k[2]),
                        'low': float(k[3]),
                        'close': float(k[4]),
                        'volume': float(k[5])
                    })
                return pd.DataFrame(data, index=dates)
        except Exception:
            pass
        return None

    def start_telegram_command_listener(self):
        """Interactive Telegram Command & Control (C2) Listener with 1-Tap Inline Buttons"""
        if not TELEGRAM_BOT_TOKEN:
            print("[TELEGRAM C2] Warning: TELEGRAM_BOT_TOKEN not configured. C2 disabled.", flush=True)
            return

        print(f"[TELEGRAM C2] Interactive Telegram 1-Tap Control Active (Configured Chat: {TELEGRAM_CHAT_ID or 'ANY'}).", flush=True)

        def poll_telegram_updates():
            last_update_id = 0
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            session = get_telegram_session()

            def is_authorized(sender_id, chat_id):
                if not TELEGRAM_CHAT_ID or not str(TELEGRAM_CHAT_ID).strip():
                    return True  # If no filter specified, allow all authenticated users
                allowed = [s.strip() for s in str(TELEGRAM_CHAT_ID).split(',') if s.strip()]
                return str(sender_id) in allowed or str(chat_id) in allowed

            while True:
                try:
                    params = {"offset": last_update_id + 1, "timeout": 10}
                    r = session.get(url, params=params, timeout=15)
                    if r.status_code == 200:
                        data = r.json()
                        for update in data.get("result", []):
                            last_update_id = update["update_id"]

                            # 1. Handle Inline Button Clicks
                            if "callback_query" in update:
                                cb = update["callback_query"]
                                sender_id = str(cb.get("from", {}).get("id", ""))
                                message_chat_id = str(cb.get("message", {}).get("chat", {}).get("id", ""))
                                if not is_authorized(sender_id, message_chat_id):
                                    print(f"[TELEGRAM C2] Ignored button click from unauthorized user {sender_id} / chat {message_chat_id}", flush=True)
                                    continue

                                cmd = cb.get("data", "")
                                cb_id = cb.get("id")
                                try:
                                    session.post(
                                        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
                                        json={"callback_query_id": cb_id},
                                        timeout=4
                                    )
                                except Exception:
                                    pass
                                if cmd:
                                    print(f"[TELEGRAM C2] Button click: '{cmd}' from {sender_id}", flush=True)
                                    self.handle_telegram_command(cmd, chat_id=message_chat_id or sender_id)

                            # 2. Handle Text Messages
                            elif "message" in update:
                                message = update.get("message", {})
                                sender_id = str(message.get("from", {}).get("id", ""))
                                chat_id = str(message.get("chat", {}).get("id", ""))
                                if not is_authorized(sender_id, chat_id):
                                    print(f"[TELEGRAM C2] Ignored message from unauthorized user {sender_id} / chat {chat_id}", flush=True)
                                    continue

                                text = message.get("text", "").strip()
                                if text:
                                    print(f"[TELEGRAM C2] Received command: '{text}' from {sender_id}", flush=True)
                                    self.handle_telegram_command(text, chat_id=chat_id or sender_id)
                    elif r.status_code == 409:
                        print(f"[TELEGRAM C2 WARNING] HTTP 409 Conflict: another instance is polling getUpdates. Will retry in 3s...", flush=True)
                        time.sleep(3)
                    else:
                        print(f"[TELEGRAM C2 ERROR] getUpdates HTTP {r.status_code}: {r.text}", flush=True)
                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, ConnectionResetError, ConnectionAbortedError):
                    # Normal long-polling timeout or transient socket recycle (Error 10053/10054); seamlessly reconnect
                    time.sleep(1.0)
                except Exception as e:
                    print(f"[TELEGRAM C2 EXCEPTION] {e}", flush=True)
                    time.sleep(2.0)
                time.sleep(0.5)

        t = threading.Thread(target=poll_telegram_updates, daemon=True)
        t.start()

    def handle_telegram_command(self, text, chat_id=None):
        try:
            parts = text.strip().split()
            if not parts:
                return
            raw_cmd = parts[0].lower()
            if not raw_cmd.startswith('/'):
                raw_cmd = '/' + raw_cmd

            # Strip bot username suffix e.g. /status@Skwid_D_bot -> /status
            cmd = raw_cmd.split('@')[0]

            if cmd in ['/start', '/help', '/menu', '/commands']:
                mode_tag = "🟢 <b>REAL MONEY LIVE TRADING ACTIVE</b>" if self.live_trading else "🟡 <b>PAPER MONITORING ACTIVE</b>"
                help_msg = (
                    f"🤖 <b>WEATHER-ENSEMBLE AI TRADING C2 CONTROL</b>\n"
                    f"Current Mode: {mode_tag}\n\n"
                    f"<b>1-Tap Fast Actions:</b>\n"
                    f"• Tap <b>🟢 Switch to LIVE</b> to activate real Binance execution.\n"
                    f"• Tap <b>🟡 Switch to PAPER</b> to switch to signals/monitoring only.\n"
                    f"• <b>/status</b> (or <b>/bal</b>) - View live balance, leverage & engine state.\n"
                    f"• <b>/positions</b> (or <b>/pos</b>) - View all active Binance Futures positions & PnL.\n"
                    f"• <b>/dircap N</b> - Set max same-direction positions (e.g. <code>/dircap 4</code>).\n"
                    f"• <b>/maxpos N</b> - Set max concurrent positions (e.g. <code>/maxpos 8</code>).\n"
                    f"• <b>/margin N</b> - Set capital risk percentage (e.g. <code>/margin 3</code>).\n"
                    f"• <b>/leverage N</b> - Set leverage multiplier (e.g. <code>/leverage 50</code>).\n"
                    f"• <b>/circuit</b> - View daily circuit breaker & drawdown status.\n"
                    f"• <b>/clean</b> - Manually purge leftover/orphaned orders.\n"
                    f"• <b>/closeall</b> - Emergency market close all open positions.\n"
                    f"• <b>/tf &lt;1m|3m|5m|15m|1h|4h&gt;</b> - Change execution timeframe.\n"
                    f"• <b>/models</b> - Real-time consensus breakdown for all 14 coins.\n"
                    f"• <b>/threshold N</b> - Set consensus threshold (e.g. <code>/threshold 30</code>).\n"
                    f"• <b>/pause</b> / <b>/resume</b> - Pause or resume automated entries."
                )
                send_telegram_msg(help_msg, reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)

            elif cmd in ['/live', '/mode_live', '/real']:
                self.live_trading = True
                usdt_bal = get_binance_futures_usdt_balance()
                msg = (
                    f"🟢 <b>SWITCHED TO LIVE TRADING (REAL MONEY)</b> 🚀\n\n"
                    f"• <b>Status:</b> Real Order Execution ACTIVE on Binance Futures\n"
                    f"• <b>Wallet Balance:</b> ${usdt_bal:,.2f} USDT\n"
                    f"• <b>Risk per Trade:</b> {self.margin_pct * 100:.1f}% Margin @ {self.leverage}x Leverage\n"
                    f"• <b>Directional Cap:</b> Max {self.max_directional_cap} Same-Side Positions\n"
                    f"• <b>Scale-Out Engine:</b> 33% TP1 ➔ BE SL ➔ 33% TP2 ➔ 34% TP3 Runner 🌊\n\n"
                    f"<i>The bot will now automatically execute real orders on high-confluence signals.</i>"
                )
                send_telegram_msg(msg, reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)
                print(f"\n[TELEGRAM C2] 🟢 USER SWITCHED TO LIVE TRADING (REAL BINANCE EXECUTION ACTIVE)\n", flush=True)

            elif cmd in ['/paper', '/mode_paper', '/test', '/monitor']:
                self.live_trading = False
                msg = (
                    f"🟡 <b>SWITCHED TO PAPER MONITORING (SIGNALS ONLY)</b> 📝\n\n"
                    f"• <b>Status:</b> Real Order Placement PAUSED\n"
                    f"• <b>Signals & Alerts:</b> Still active and scanning all 14 pairs\n"
                    f"• <b>Position Manager:</b> Still monitoring & protecting existing Binance positions\n\n"
                    f"<i>No new real money market orders will be placed until switched back to LIVE.</i>"
                )
                send_telegram_msg(msg, reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)
                print(f"\n[TELEGRAM C2] 🟡 USER SWITCHED TO PAPER MONITORING MODE\n", flush=True)

            elif cmd == '/tf':
                if len(parts) > 1 and parts[1].lower() in ['1m', '3m', '5m', '15m', '30m', '1h', '4h']:
                    self.timeframe = parts[1].lower()
                    send_telegram_msg(f"⏱️ <b>EXECUTION TIMEFRAME SWITCHED</b>\n\nBot is now scanning <b>{self.timeframe.upper()}</b> bars for high-confluence setups!", reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)
                else:
                    send_telegram_msg(f"ℹ️ Current Execution Timeframe: <b>{self.timeframe.upper()}</b>\nUsage: <code>/tf 15m</code> (Supported: 1m, 3m, 5m, 15m, 1h, 4h)", reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)

            elif cmd in ['/status', '/balance', '/bal', '/info', '/state', '/pnl']:
                usdt_bal = get_binance_futures_usdt_balance()
                status_str = "PAUSED ⏸️" if self.paused else ("CIRCUIT TRIPPED 🛑" if CIRCUIT_BREAKER.circuit_tripped else "ACTIVE 🟢")
                mode_str = "🟢 REAL BINANCE FUTURES" if self.live_trading else "🟡 PAPER MONITOR (Signals Only)"
                active_cnt = get_binance_futures_open_positions_count()

                msg = (
                    f"📊 <b>ENGINE STATUS & WALLET REPORT</b>\n\n"
                    f"<b>Trading Mode:</b> {mode_str}\n"
                    f"<b>Engine State:</b> {status_str}\n"
                    f"<b>Binance Futures USDT Balance:</b> ${usdt_bal:,.2f}\n"
                    f"<b>Open Positions:</b> {active_cnt} / {self.max_active_positions} (Max {self.max_directional_cap} same-side)\n"
                    f"<b>Position Sizing:</b> {self.margin_pct * 100:.1f}% Capital (${usdt_bal * self.margin_pct:,.2f} Margin @ {self.leverage}x)\n"
                    f"<b>Consensus Threshold:</b> ≥ <b>{self.threshold} / 31 Models</b>\n"
                    f"<b>Circuit Breaker:</b> {'🛑 TRIPPED' if CIRCUIT_BREAKER.circuit_tripped else '🟢 HEALTHY'}\n"
                    f"<b>Public IP:</b> <code>{get_current_public_ip()}</code> (Whitelisted ✅)\n"
                    f"<b>Monitored Universe:</b> {len(OPTIMIZED_SYMBOLS)} Liquid Assets\n"
                    f"<b>Timestamp:</b> {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
                )
                send_telegram_msg(msg, reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)

            elif cmd in ['/ip', '/myip', '/whitelist']:
                ok, cur_ip = check_binance_ip_whitelist(probe_api=True)
                whitelisted_cfg = os.getenv('BINANCE_WHITELISTED_IP', BINANCE_WHITELISTED_IP).strip()
                status_icon = "🟢 AUTHORIZED & WHITELISTED" if ok else "🔴 NOT WHITELISTED / MISMATCH"
                msg = (
                    f"🌐 <b>BINANCE IP WHITELIST STATUS</b>\n\n"
                    f"• <b>Current Public IP:</b> <code>{cur_ip}</code>\n"
                    f"• <b>Configured Whitelist:</b> <code>{whitelisted_cfg or 'Auto-detect'}</code>\n"
                    f"• <b>Status:</b> {status_icon}\n\n"
                    f"<i>If Binance rejects orders with code -2015, ensure {cur_ip} is added to your API Key list on Binance.</i>"
                )
                send_telegram_msg(msg, reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)

            elif cmd in ['/positions', '/pos', '/orders', '/trades']:
                positions = get_binance_futures_positions()
                if not positions:
                    send_telegram_msg("ℹ️ <b>No open Binance Futures positions.</b>", reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)
                else:
                    lines = [f"📈 <b>OPEN BINANCE FUTURES POSITIONS ({len(positions)})</b>\n"]
                    for p in positions:
                        emoji = "🟢 LONG" if p['side'] == 'LONG' else "🔴 SHORT"
                        pnl_color = "+" if p['unrealizedProfit'] >= 0 else ""
                        lines.append(
                            f"• <b>#{p['symbol']}</b> {emoji} ({p['leverage']}x)\n"
                            f"  Size: {p['positionAmt']} | Entry: ${p['entryPrice']:,.4f}\n"
                            f"  Mark: ${p['markPrice']:,.4f} | Liq: ${p['liquidationPrice']:,.4f}\n"
                            f"  Unrealized PnL: <b>{pnl_color}${p['unrealizedProfit']:,.2f} USDT</b>\n"
                        )
                    send_telegram_msg("\n".join(lines), reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)

            elif cmd in ['/circuit', '/cb', '/drawdown']:
                bal = get_binance_futures_usdt_balance()
                CIRCUIT_BREAKER.check_and_update(bal)
                enabled_str = "ENABLED 🟢" if CIRCUIT_BREAKER.enabled else "DISABLED ⚪ (Continuous Trading)"
                trip_str = f"🛑 <b>TRIPPED</b> ({CIRCUIT_BREAKER.trip_reason})" if CIRCUIT_BREAKER.circuit_tripped else "🟢 <b>NORMAL / SAFE</b>"
                msg = (
                    f"🛡️ <b>CIRCUIT BREAKER & RISK REPORT</b>\n\n"
                    f"<b>Module State:</b> {enabled_str}\n"
                    f"<b>Protection Status:</b> {trip_str}\n"
                    f"<b>Daily Starting Balance:</b> ${CIRCUIT_BREAKER.daily_start_balance or bal:,.2f}\n"
                    f"<b>Current Balance:</b> ${bal:,.2f}\n"
                    f"<b>Today's Realized PnL:</b> ${CIRCUIT_BREAKER.realized_pnl_today:+,.2f}\n"
                    f"<b>Max Daily Drawdown Gate:</b> -{CIRCUIT_BREAKER.daily_limit_pct * 100:.1f}%\n"
                    f"<b>Consecutive Losses:</b> {CIRCUIT_BREAKER.consecutive_losses} / {CIRCUIT_BREAKER.max_losses}\n\n"
                    f"• Tap <b>🛡️ CB</b> button or send <code>/disablecb</code> to turn OFF auto-halts.\n"
                    f"• Send <code>/enablecb</code> to turn ON protection.\n"
                    f"• Send <code>/circuit reset</code> to clear loss streak."
                )
                if len(parts) > 1 and parts[1].lower() == 'reset':
                    CIRCUIT_BREAKER.reset_circuit(bal)
                    send_telegram_msg("✅ <b>Circuit breaker reset. Trading restored!</b>", reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)
                elif len(parts) > 1 and parts[1].lower() in ['off', 'disable', 'stop']:
                    CIRCUIT_BREAKER.set_enabled(False)
                    send_telegram_msg("🛡️ <b>Circuit Breaker DISABLED ⚪</b>\n\nAutomated entries will run continuously without halting.", reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)
                elif len(parts) > 1 and parts[1].lower() in ['on', 'enable', 'start']:
                    CIRCUIT_BREAKER.set_enabled(True)
                    send_telegram_msg("🛡️ <b>Circuit Breaker ENABLED 🟢</b>\n\nAutomated protection active (Halts on 3 consecutive losses).", reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)
                else:
                    send_telegram_msg(msg, reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)

            elif cmd in ['/togglecb', '/cbtoggle']:
                new_state = CIRCUIT_BREAKER.toggle_enabled()
                state_str = "ENABLED 🟢 (Protection Active)" if new_state else "DISABLED ⚪ (Continuous Trading)"
                send_telegram_msg(f"🛡️ <b>CIRCUIT BREAKER TOGGLED</b>\n\nCircuit Breaker is now <b>{state_str}</b>.", reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)

            elif cmd in ['/disablecb', '/cboff']:
                CIRCUIT_BREAKER.set_enabled(False)
                send_telegram_msg("🛡️ <b>CIRCUIT BREAKER DISABLED ⚪</b>\n\n• Automated entries will NOT be halted on consecutive losses.\n• Trading will run continuously.", reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)

            elif cmd in ['/enablecb', '/cbon']:
                CIRCUIT_BREAKER.set_enabled(True)
                send_telegram_msg("🛡️ <b>CIRCUIT BREAKER ENABLED 🟢</b>\n\n• Automated protection is active (Halts on 3 consecutive losses).", reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)

            elif cmd in ['/clean', '/cleanup', '/purge']:
                cleaned = cleanup_orphaned_orders()
                if cleaned > 0:
                    send_telegram_msg(f"🧹 <b>Purge Complete!</b> Cleaned {cleaned} orphaned orders.", reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)
                else:
                    send_telegram_msg("✨ <b>No orphaned orders found.</b> All open orders match active positions!", reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)

            elif cmd in ['/closeall', '/panic']:
                results = close_all_binance_futures_positions()
                cleanup_orphaned_orders()
                send_telegram_msg(f"🛑 <b>Emergency Close All executed!</b> Closed {len(results)} positions.", reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)

            elif cmd in ['/leverage', '/lev']:
                if len(parts) > 1 and parts[1].isdigit():
                    val = int(parts[1])
                    if 1 <= val <= 125:
                        self.leverage = val
                        send_telegram_msg(f"✅ <b>Leverage multiplier updated to {self.leverage}x!</b>", reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)
                    else:
                        send_telegram_msg("⚠️ Leverage must be between 1x and 125x.", chat_id=chat_id)
                else:
                    send_telegram_msg(f"Current Leverage: <b>{self.leverage}x</b>", reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)

            elif cmd in ['/mode', '/sizing']:
                if len(parts) > 1 and parts[1].lower() in ['notional', 'margin']:
                    self.sizing_mode = parts[1].lower()
                    send_telegram_msg(f"✅ <b>Sizing Mode updated to {self.sizing_mode.upper()}!</b>", reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)
                else:
                    send_telegram_msg("Usage: <code>/mode notional</code> or <code>/mode margin</code>", chat_id=chat_id)

            elif cmd in ['/margin', '/risk']:
                if len(parts) > 1:
                    try:
                        val = float(parts[1])
                        if 0 < val <= 100:
                            self.margin_pct = val / 100.0
                            send_telegram_msg(f"✅ <b>Position Risk updated to {self.margin_pct * 100:.1f}%!</b>", reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)
                    except ValueError:
                        send_telegram_msg("Usage: <code>/margin 3</code>", chat_id=chat_id)

            elif cmd in ['/maxpos', '/maxpositions', '/slots']:
                if len(parts) > 1 and parts[1].isdigit():
                    val = int(parts[1])
                    if 1 <= val <= 20:
                        self.max_active_positions = val
                        send_telegram_msg(f"✅ <b>Max Active Positions updated to {self.max_active_positions}!</b>", reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)
                    else:
                        send_telegram_msg("⚠️ Max active positions must be between 1 and 20.", chat_id=chat_id)
                else:
                    send_telegram_msg(f"ℹ️ Current Max Active Positions: <b>{self.max_active_positions}</b>\nUsage: <code>/maxpos 8</code>", reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)

            elif cmd in ['/dircap', '/directionalcap', '/directional_cap', '/maxdir', '/sidecap', '/cap']:
                if len(parts) > 1 and parts[1].isdigit():
                    val = int(parts[1])
                    if 1 <= val <= 20:
                        self.max_directional_cap = val
                        send_telegram_msg(f"✅ <b>Directional Exposure Cap updated to {self.max_directional_cap} max same-side positions!</b> 🛡️", reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)
                    else:
                        send_telegram_msg("⚠️ Directional cap must be between 1 and 20.", chat_id=chat_id)
                else:
                    send_telegram_msg(f"ℹ️ Current Directional Exposure Cap: <b>{self.max_directional_cap} same-side positions</b>\nUsage: <code>/dircap 4</code>", reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)

            elif cmd in ['/models', '/matrix', '/consensus']:
                lines = ["<b>31-MODEL REAL-TIME CONSENSUS MATRIX</b>\n"]
                for sym, data in self.latest_model_states.items():
                    emoji = "🟢 BUY" if data['action'] == 'BUY' else "🔴 SELL" if data['action'] == 'SELL' else "⚪ Hold"
                    lines.append(f"• <b>{sym}</b>: ${data['price']:,.4f} | <b>{data['consensus']}/31</b> ({data['bull']}B/{data['bear']}B) | {emoji}")
                send_telegram_msg("\n".join(lines), reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)

            elif cmd in ['/threshold', '/thresh']:
                if len(parts) > 1 and parts[1].isdigit():
                    val = int(parts[1])
                    if 20 <= val <= 31:
                        self.threshold = val
                        send_telegram_msg(f"✅ <b>Consensus Threshold updated to {self.threshold} / 31 models!</b>", reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)
                    else:
                        send_telegram_msg("⚠️ Threshold must be between 20 and 31.", chat_id=chat_id)
                else:
                    send_telegram_msg(f"ℹ️ Current Consensus Threshold: <b>{self.threshold} / 31 Models</b>\nUsage: <code>/threshold 30</code>", reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)

            elif cmd in ['/atlas', '/darwin', '/weights', '/synergy']:
                status_msg = ATLAS_DARWINIAN.get_status_report()
                send_telegram_msg(status_msg, reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)

            elif cmd in ['/pause', '/stop']:
                self.paused = True
                send_telegram_msg("⏸️ <b>Automated trade execution PAUSED.</b>", reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)

            elif cmd in ['/resume', '/unpause', '/starttrading', '/resetcb', '/resetcircuit', '/start']:
                self.paused = False
                CIRCUIT_BREAKER.reset_circuit(get_binance_futures_usdt_balance())
                send_telegram_msg("▶️ <b>Automated trade execution RESUMED & Circuit Breaker RESET!</b>\n\n• Consecutive loss counter reset to 0\n• All asset cooldowns cleared\n• 11-asset scanning active (75x Leverage / 3% Margin)", reply_markup=get_telegram_inline_keyboard(self.live_trading), chat_id=chat_id)

            else:
                send_telegram_msg(
                    f"❓ <b>Unknown Command:</b> <code>{cmd}</code>\n\nSend /help or /menu to view all available commands & interactive controls.",
                    reply_markup=get_telegram_inline_keyboard(self.live_trading),
                    chat_id=chat_id
                )
        except Exception as e:
            print(f"[TELEGRAM COMMAND HANDLER ERROR] {e}", flush=True)
            try:
                send_telegram_msg(f"⚠️ <b>Command Handler Error:</b> <code>{e}</code>", chat_id=chat_id)
            except Exception:
                pass

    def run_multi_asset_live_loop(self, poll_interval=10):
        print(f"\n=======================================================")
        print(f" WEATHER-ENSEMBLE BINANCE FUTURES LIVE AGENT ACTIVE")
        print(f" Profile: 30x Fast Recovery Sizing (20% Margin @ 30x Leverage)")
        print(f" Protection: L2 Depth + Funding Rate + Orphaned Order Cleaner + Circuit Breaker")
        print(f" Monitored Universe: {', '.join(OPTIMIZED_SYMBOLS)}")
        print(f"=======================================================\n")

        self.start_telegram_command_listener()

        # BUG-14 Fix: Restore trailing stop state from disk after watchdog restart
        _load_position_targets()

        # 🌐 IP Whitelist Pre-Flight Check on Startup
        try:
            ip_ok, current_ip = check_binance_ip_whitelist(probe_api=self.live_trading)
            if ip_ok:
                print(f"[IP WHITELIST WATCHDOG] Public IP ({current_ip}) verified on Binance Futures ✅", flush=True)
        except Exception as e:
            print(f"[IP WHITELIST WATCHDOG WARN] Startup check error: {e}", flush=True)

        while True:
            try:
                # Periodic IP Whitelist verification (every 15 min)
                global _LAST_PERIODIC_IP_CHECK
                if time.time() - _LAST_PERIODIC_IP_CHECK > 900:
                    _LAST_PERIODIC_IP_CHECK = time.time()
                    check_binance_ip_whitelist(probe_api=False)

                # 0. Refresh Global API Cache (Fetches all funding rates and BTC 15m in 2 calls)
                GLOBAL_CACHE.update(force=True)

                # 1. Automated Orphaned Order Cleaner & Real-Time Breakeven Trailing Stop Daemon
                if self.live_trading:
                    cleanup_orphaned_orders()
                    manage_active_positions_breakeven()

                active_positions = get_binance_futures_positions() if self.live_trading else []
                active_symbols = set(p['symbol'] for p in active_positions if abs(float(p.get('positionAmt', 0.0))) > 0.0)
                active_count = len(active_symbols)

                for symbol in OPTIMIZED_SYMBOLS:
                    # 🛑 1 Position Per Symbol Maximum: Skip symbols that already have an active open position
                    if symbol in active_symbols:
                        continue

                    # 🛡️ Cooldown Check: Skip assets that recently stopped out
                    if CIRCUIT_BREAKER.is_asset_in_cooldown(symbol):
                        continue

                    df = self.fetch_binance_klines(symbol=symbol)
                    if df is not None and len(df) >= 35:
                        res = self.evaluate_bar(df, symbol=symbol, active_count=active_count)
                        price = res['price']
                        consensus = res['consensus']
                        action = res['action']
                        t_str = res['timestamp']
                        
                        if action != 'NO TRADE':
                            active_symbols.add(symbol)
                            active_count += 1
                            print(f"[SIGNAL TRIGGERED] [{t_str}] [{symbol}] ${price:,.4f} | Consensus: {consensus}/31 | ACTION: {action}", flush=True)
                        else:
                            print(f"  [{t_str}] [{symbol}] ${price:,.4f} | Consensus: {consensus}/31 | Hold", flush=True)
                    
                    time.sleep(0.4)

                time.sleep(poll_interval)
            except Exception as e:
                print(f"[MAIN LOOP EXCEPTION RECOVERED] {e}", flush=True)
                time.sleep(3)

# Bug #1 Fix: Removed duplicate get_divergence_status that shadowed the MTF version at line 605

# --------------------------------------------------------------------------
# CLI Entry Point
# --------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description='Weather-Ensemble 31-Model Trading AI Bot')
    parser.add_argument('--live', action='store_true', help='Run live market monitor with Telegram alerts & C2')
    parser.add_argument('--trade-live', action='store_true', help='Execute REAL orders on Binance Futures')
    parser.add_argument('--usdt', type=float, default=None, help='Fixed order size in USDT')
    parser.add_argument('--margin-pct', type=float, default=0.03, help='Capital fraction (default 0.03 = 3%% margin)')
    parser.add_argument('--sizing-mode', type=str, choices=['notional', 'margin'], default='margin')
    parser.add_argument('--leverage', type=int, default=75, help='Leverage multiplier (default 75x)')
    parser.add_argument('--threshold', type=int, default=30, help='Consensus threshold (default 30/31)')
    parser.add_argument('--timeframe', type=str, default='15m', help='Execution timeframe (default 15m)')
    parser.add_argument('--max-positions', type=int, default=5, help='Max concurrent positions (default 5)')
    parser.add_argument('--directional-cap', type=int, default=5, help='Max same-side positions (default 5)')
    args = parser.parse_args()

    bot = WeatherEnsembleBot(
        consensus_threshold=args.threshold,
        live_trading=args.trade_live,
        trade_usdt=args.usdt,
        margin_pct=args.margin_pct,
        sizing_mode=args.sizing_mode,
        leverage=args.leverage,
        timeframe=args.timeframe,
        max_positions=args.max_positions,
        directional_cap=args.directional_cap
    )
    while True:
        try:
            bot.run_multi_asset_live_loop()
        except KeyboardInterrupt:
            print("\n🛑 Bot stopped cleanly by user.", flush=True)
            break
        except Exception as e:
            print(f"\n[TOP LEVEL FATAL EXCEPTION] {e}", flush=True)
            import traceback
            traceback.print_exc()
            print("Restarting live loop in 5 seconds...", flush=True)
            time.sleep(5)

if __name__ == '__main__':
    main()